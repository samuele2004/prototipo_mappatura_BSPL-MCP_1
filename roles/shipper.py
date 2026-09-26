"""
Implementazione del ruolo 'Shipper' per il protocollo BSPL PurchaseWithDelivery.

Definizione del ruolo nel protocollo:
- Relazioni Locali LoST gestite da self.adapter:
  * R(ship):    [ID, item, address]
  * R(deliver): [ID, item, address, outcome]
- RICEZIONE (Tool MCP esposti):
  * ship(ID, item, address) [Seller -> Shipper: ship]
- EMISSIONE (Metodi pubblici per l'invio messaggi via Client MCP):
  * send_deliver(ID, outcome) [Shipper -> Buyer: deliver]
"""

import asyncio
import logging
from typing import Annotated, Any, Dict
from pydantic import Field
from mcp import Client
from config import SHIPPER_HOST, SHIPPER_PORT, BUYER_URL
from roles.base import BaseRoleNode
from roles.exceptions import BSPLExecutionError

logger = logging.getLogger("Shipper")


class ShipperNode(BaseRoleNode):
    """
    Nodo ibrido per il ruolo Shipper.
    Gestisce le relazioni locali R(ship) e R(deliver),
    il tool di ricezione 'ship' e il metodo di emissione 'send_deliver' con verifiche formali LoST tramite self.adapter.
    """

    def __init__(self, host: str = SHIPPER_HOST, port: int = SHIPPER_PORT):
        super().__init__(name="Shipper", host=host, port=port)

    # ----------------------------------------------------------------------
    # Proprietà di accesso rapido alle relazioni locali dell'adattatore
    # ----------------------------------------------------------------------

    @property
    def r_ship(self) -> Dict[str, Dict[str, Any]]:
        return self.adapter.relations.setdefault("ship", {})

    @property
    def r_deliver(self) -> Dict[str, Dict[str, Any]]:
        return self.adapter.relations.setdefault("deliver", {})

    # ----------------------------------------------------------------------
    # Tool MCP Esposti (Ricezione messaggi BSPL)
    # ----------------------------------------------------------------------

    def _register_tools(self):
        """Registra i Tool esposti dal Server MCP dello Shipper per ricevere messaggi BSPL."""

        @self.server.tool()
        async def ship(
            ID: Annotated[str, Field(description="[BSPL: in key] Identificativo univoco della transazione")],
            item: Annotated[str, Field(description="[BSPL: in] Articolo da spedire")],
            address: Annotated[str, Field(description="[BSPL: in] Indirizzo di consegna")],
        ) -> str:
            """
            Messaggio BSPL: Seller -> Shipper: ship [in ID, in item, in address]
            Riceve e registra la presa in carico della spedizione.
            """
            logger.info(f"[Shipper] Ricevuto Tool 'ship': ID={ID!r}, item={item!r}, address={address!r}")
            params = {"ID": ID, "item": item, "address": address}

            # 1. Verifica di consistenza semantica (immutabilità BSPL)
            self.adapter.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.adapter.is_duplicate("ship", ID, params):
                logger.info(f"[Shipper] Messaggio 'ship' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"Spedizione già registrata per ID={ID}."

            # 3. Inserimento nella relazione locale R(ship)
            self.adapter.insert_relation("ship", ID, params)

            # 4. Notifica evento arrivo ordine di spedizione
            self._notify_message_received("ship", ID)

            return f"Richiesta di spedizione presa in carico per ID={ID}."

    # ----------------------------------------------------------------------
    # Metodi Pubblici di Invio (Emissione messaggi BSPL tramite Client MCP)
    # ----------------------------------------------------------------------

    async def send_deliver(
        self,
        ID: str,
        outcome: str = "delivered"
    ):
        """
        Messaggio BSPL: Shipper -> Buyer: deliver [in ID, in item, in address, out outcome]
        Invia la notifica di avvenuta consegna al Buyer generando outcome.
        I parametri [in] (ID, item, address) vengono verificati e risolti dallo stato locale.
        """
        # 1. Verifica di viabilità LoST sui nomi dei parametri
        in_values = self.adapter.check_viability(
            ID,
            in_params=["ID", "item", "address"],
            out_params=["outcome"],
        )

        params = {**in_values, "outcome": outcome}

        # 2. Inserimento locale nella relazione R(deliver)
        self.adapter.insert_relation("deliver", ID, params)

        await asyncio.sleep(0.05)
        logger.info(f"[Shipper -> Buyer] Invocazione Tool 'deliver': ID={ID!r}, outcome={outcome!r}")
        try:
            async with Client(BUYER_URL) as client:
                result = await client.call_tool("deliver", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Shipper] Errore dal server Buyer su 'deliver': {error_msg}")
                    self.adapter.remove_relation("deliver", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'deliver': {error_msg}")
                logger.info(f"[Shipper] Risposta per 'deliver': {result.content}")
        except Exception:
            self.adapter.remove_relation("deliver", ID)
            raise
