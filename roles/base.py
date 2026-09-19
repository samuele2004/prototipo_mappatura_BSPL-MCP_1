"""
Classe base per un nodo di ruolo nella coreografia BSPL su MCP.

Incapsula:
- Il ciclo di vita del Server MCP su trasporto Streamable HTTP (uvicorn).
- La gestione dello stato locale relazionale secondo il modello LoST (Local State Transfer):
  relazioni separate R(m) per ciascuno schema di messaggio m.
- Le regole formali di viabilità per l'emissione dei messaggi:
  * verifica e recupero dei parametri [in] dallo stato locale;
  * verifica che nessun parametro [out] sia già vincolato;
  * verifica che nessun parametro [nil] sia già vincolato.
- I controlli di consistenza semantica (immutabilità BSPL) e idempotenza (duplicati) in ricezione.
- La sincronizzazione asincrona reattiva per il coordinamento degli scenari.
- L'estrazione della storia locale del ruolo per l'History Vector distribuito.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import uvicorn
from mcp.server import MCPServer

logger = logging.getLogger("BaseRoleNode")


class BSPLProtocolError(Exception):
    """Classe base per le eccezioni relative ai vincoli BSPL."""
    pass


class BSPLViabilityError(BSPLProtocolError):
    """Sollevata quando l'emissione di un messaggio viola le regole di viabilità BSPL."""
    pass


class BSPLConsistencyError(BSPLProtocolError):
    """Sollevata quando un messaggio in ricezione entra in conflitto con lo stato locale (immutabilità)."""
    pass


class BSPLExecutionError(BSPLProtocolError):
    """Sollevata quando una chiamata a un Tool MCP remoto restituisce un errore."""
    pass


class BaseRoleNode:
    """
    Nodo ibrido generico per la coreografia BSPL su MCP.
    Integra un Server MCP per ricevere messaggi (esposti come Tool) e
    gestisce lo stato locale relazionale secondo il modello LoST.
    """

    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self.server = MCPServer(f"{name}Server")
        self.uvicorn_server: Optional[uvicorn.Server] = None

        # Relazioni locali LoST: schema_name -> { transaction_ID: { param_name: param_value } }
        self.relations: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Mappa per sincronizzazione eventi: (message_name, transaction_ID) -> asyncio.Event
        self._message_events: Dict[Tuple[str, str], asyncio.Event] = {}

        # Registrazione dei Tool MCP specifici del ruolo
        self._register_tools()

    def _register_tools(self):
        """Metodo da sovrascrivere nelle sottoclassi per registrare i Tool MCP."""
        pass

    # ----------------------------------------------------------------------
    # Gestione dello Stato Locale Relazionale (LoST) e Verifiche BSPL
    # ----------------------------------------------------------------------

    def has_known_parameter(self, param: str, ID: str) -> bool:
        """
        Verifica se il parametro indicato è già vincolato in una qualsiasi delle
        relazioni locali del ruolo per la transazione identificata da ID.
        """
        for table in self.relations.values():
            if ID in table and param in table[ID]:
                return True
        return False

    def get_known_parameter(self, param: str, ID: str) -> Any:
        """
        Restituisce il valore del parametro se già vincolato in una qualsiasi delle
        relazioni locali del ruolo per l'ID indicato, altrimenti None.
        """
        for table in self.relations.values():
            if ID in table and param in table[ID]:
                return table[ID][param]
        return None

    def check_viability(
        self,
        ID: str,
        in_params: List[str],
        out_params: List[str],
        nil_params: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Verifica le condizioni formali di viabilità LoST/BSPL per l'emissione di un messaggio:
        1. Tutti i parametri in_params devono risultare già vincolati nelle relazioni locali per ID.
        2. Nessun parametro out_params deve risultare già vincolato per la chiave ID (assioma di immutabilità).
        3. Nessun parametro nil_params deve risultare già vincolato per la chiave ID.

        Ritorna il dizionario dei parametri [in] risolti dallo stato locale: { param_name: param_value }.
        """
        resolved_in_params: Dict[str, Any] = {}

        # 1. Verifica e recupero parametri [in] dallo stato locale
        for param in in_params:
            if not self.has_known_parameter(param, ID):
                raise BSPLViabilityError(
                    f"[{self.name}] Emissione non viabile: parametro [in] '{param}' non ancora noto per ID='{ID}'"
                )
            resolved_in_params[param] = self.get_known_parameter(param, ID)

        # 2. Verifica che nessun parametro [out] sia già vincolato
        for param in out_params:
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                raise BSPLViabilityError(
                    f"[{self.name}] Emissione non viabile: parametro [out] '{param}' già vincolato "
                    f"(valore={known!r}) per ID='{ID}'"
                )

        # 3. Verifica che nessun parametro [nil] sia già vincolato
        for param in nil_params or []:
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                raise BSPLViabilityError(
                    f"[{self.name}] Emissione non viabile: parametro [nil] '{param}' già vincolato "
                    f"(valore={known!r}) per ID='{ID}'"
                )

        return resolved_in_params

    def check_consistency(self, ID: str, params: Dict[str, Any]):
        """
        Verifica la consistenza semantica in ricezione (assioma di immutabilità BSPL):
        Per ciascun parametro ricevuto, se è già noto nello stato locale del ruolo per quell'ID,
        il valore in arrivo DEVE coincidere esattamente con quello registrato.
        """
        for param, val in params.items():
            if self.has_known_parameter(param, ID):
                known = self.get_known_parameter(param, ID)
                if known != val:
                    raise BSPLConsistencyError(
                        f"[{self.name}] Violazione consistenza BSPL: parametro '{param}' ricevuto con valore {val!r} "
                        f"incompatibile con il valore già registrato {known!r} per ID='{ID}'"
                    )

    def is_duplicate(self, schema: str, ID: str, params: Dict[str, Any]) -> bool:
        """
        Verifica se la tupla del messaggio è un duplicato idempotente già registrato in R(schema).
        """
        table = self.relations.get(schema, {})
        return ID in table and table[ID] == params

    def insert_relation(self, schema: str, ID: str, params: Dict[str, Any]):
        """
        Inserisce la tupla convalidata all'interno della relazione locale R(schema).
        """
        if schema not in self.relations:
            self.relations[schema] = {}
        self.relations[schema][ID] = dict(params)

    def remove_relation(self, schema: str, ID: str):
        """
        Rimuove una tupla da R(schema) in caso di errore durante la trasmissione (rollback locale).
        """
        if schema in self.relations and ID in self.relations[schema]:
            del self.relations[schema][ID]

    def get_history(self, ID: str) -> Dict[str, Dict[str, Any]]:
        """
        Restituisce la storia locale H_x (le tuple delle relazioni locali popolate)
        per una data transazione ID, corrispondente alla componente del ruolo
        all'interno dell'History Vector H = [H_x1, ..., H_xn] (Cap. 1, Sez. 1.3.2).
        """
        return {
            schema: dict(table[ID])
            for schema, table in self.relations.items()
            if ID in table
        }

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
