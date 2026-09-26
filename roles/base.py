"""
Classe base per un nodo di ruolo nella coreografia BSPL su MCP.

Incapsula:
- Il ciclo di vita del Server MCP su trasporto Streamable HTTP (uvicorn).
- L'integrazione con l'adattatore LoST locale (BSPLAdapter).
- La sincronizzazione asincrona reattiva per il coordinamento degli scenari.
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple
import uvicorn
from mcp.server import MCPServer

from roles.adapter import BSPLAdapter

logger = logging.getLogger("BaseRoleNode")


class BaseRoleNode:
    """
    Nodo ibrido generico per la coreografia BSPL su MCP.
    Integra un Server MCP per ricevere messaggi (esposti come Tool) e
    un adattatore LoST (BSPLAdapter) per lo stato relazionale e le verifiche BSPL.
    """

    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self.server = MCPServer(f"{name}Server")
        self.uvicorn_server: Optional[uvicorn.Server] = None

        # Adattatore LoST locale per la gestione dello stato relazionale e dei vincoli causali
        self.adapter = BSPLAdapter(role_name=name)

        # Mappa per sincronizzazione eventi: (message_name, transaction_ID) -> asyncio.Event
        self._message_events: Dict[Tuple[str, str], asyncio.Event] = {}

        # Registrazione dei Tool MCP specifici del ruolo
        self._register_tools()

    def _register_tools(self):
        """Metodo da sovrascrivere nelle sottoclassi per registrare i Tool MCP."""
        pass

    # ----------------------------------------------------------------------
    # Sincronizzazione a Eventi
    # ----------------------------------------------------------------------

    def _notify_message_received(self, message_name: str, transaction_id: str):
        """Notifica che uno specifico messaggio BSPL è stato ricevuto e convalidato dal Tool del nodo."""
        key = (message_name, transaction_id)
        if key not in self._message_events:
            self._message_events[key] = asyncio.Event()
        self._message_events[key].set()

    async def wait_for_message(self, message_name: str, transaction_id: str, timeout: float = 10.0) -> bool:
        """
        Attende in modo asincrono che il nodo riceva un messaggio BSPL per la transazione indicata.
        Ritorna True se l'evento è avvenuto entro il timeout, altrimenti solleva TimeoutError.
        """
        key = (message_name, transaction_id)
        if key not in self._message_events:
            self._message_events[key] = asyncio.Event()
        try:
            await asyncio.wait_for(self._message_events[key].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Nodo '{self.name}' non ha ricevuto il messaggio '{message_name}' "
                f"per ID='{transaction_id}' entro {timeout}s"
            )

    # ----------------------------------------------------------------------
    # Ciclo di Vita del Server HTTP (Streamable HTTP)
    # ----------------------------------------------------------------------

    async def wait_ready(self, timeout: float = 5.0):
        """Attende che il server HTTP sia in ascolto e pronto a ricevere richieste."""
        start = asyncio.get_event_loop().time()
        while not getattr(self.uvicorn_server, "started", False):
            if asyncio.get_event_loop().time() - start > timeout:
                raise TimeoutError(f"Il server {self.name} non è pronto entro {timeout}s")
            await asyncio.sleep(0.05)

    async def run(self):
        """Avvia il Server MCP su trasporto Streamable HTTP."""
        app = self.server.streamable_http_app()
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning")
        self.uvicorn_server = uvicorn.Server(config)
        try:
            await self.uvicorn_server.serve()
        except asyncio.CancelledError:
            pass

    def stop(self):
        """Arresta in modo ordinato il server HTTP."""
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
