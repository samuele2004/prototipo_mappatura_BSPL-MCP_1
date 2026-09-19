"""
Implementazione del ruolo 'Buyer' per il protocollo BSPL PurchaseWithDelivery.

Definizione del ruolo nel protocollo:
- Relazioni Locali LoST:
  * R(rfq):     [ID, item]
  * R(quote):   [ID, item, price]
  * R(accept):  [ID, item, price, address, response]
  * R(reject):  [ID, item, price, outcome, response]
  * R(deliver): [ID, item, address, outcome]
- RICEZIONE (Tool MCP esposti):
  * quote(ID, item, price) [Seller -> Buyer: quote]
  * deliver(ID, item, address, outcome) [Shipper -> Buyer: deliver]
- EMISSIONE (Metodi pubblici per l'invio messaggi via Client MCP):
  * send_rfq(ID, item) [Buyer -> Seller: rfq]
  * send_accept(ID, address, response) [Buyer -> Seller: accept]
  * send_reject(ID, outcome, response) [Buyer -> Seller: reject]
"""

import asyncio
import logging
from typing import Annotated, Any, Dict
from pydantic import Field
from mcp import Client
from config import BUYER_HOST, BUYER_PORT, SELLER_URL
from roles.base import BaseRoleNode, BSPLExecutionError

logger = logging.getLogger("Buyer")


class BuyerNode(BaseRoleNode):
    """
    Nodo ibrido per il ruolo Buyer.
    Gestisce le relazioni locali R(rfq), R(quote), R(accept), R(reject), R(deliver),
    i tool di ricezione e i metodi di emissione con verifiche formali LoST.
    """

    def __init__(self, host: str = BUYER_HOST, port: int = BUYER_PORT):
        super().__init__(name="Buyer", host=host, port=port)

    # ----------------------------------------------------------------------
    # Proprietà di accesso rapido alle relazioni locali
    # ----------------------------------------------------------------------

    @property
    def r_rfq(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("rfq", {})

    @property
    def r_quote(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("quote", {})

    @property
    def r_accept(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("accept", {})

    @property
    def r_reject(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("reject", {})

    @property
    def r_deliver(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("deliver", {})

    # ----------------------------------------------------------------------
    # Tool MCP Esposti (Ricezione messaggi BSPL)
    # ----------------------------------------------------------------------

    def _register_tools(self):
        """Registra i Tool esposti dal Server MCP del Buyer per ricevere messaggi BSPL."""

        @self.server.tool()
        async def quote(
            ID: Annotated[str, Field(description="[BSPL: in key] Identificativo univoco della transazione")],
            item: Annotated[str, Field(description="[BSPL: in] Articolo richiesto")],
            price: Annotated[float, Field(description="[BSPL: out] Prezzo quotato dal Seller")],
        ) -> str:
            """
            Messaggio BSPL: Seller -> Buyer: quote [in ID, in item, out price]
            Riceve e registra la quotazione inviata dal Seller.
            """
            logger.info(f"[Buyer] Ricevuto Tool 'quote': ID={ID!r}, item={item!r}, price={price}")
            params = {"ID": ID, "item": item, "price": price}

            # 1. Verifica di consistenza semantica (immutabilità BSPL)
            self.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.is_duplicate("quote", ID, params):
                logger.info(f"[Buyer] Messaggio 'quote' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"Quote già registrata per ID={ID}."

            # 3. Inserimento nella relazione locale R(quote)
            self.insert_relation("quote", ID, params)

            # 4. Notifica evento per sincronizzazione reattiva
            self._notify_message_received("quote", ID)

            return f"Quote ricevuta per ID={ID} con prezzo {price}."

        @self.server.tool()
        async def deliver(
            ID: Annotated[str, Field(description="[BSPL: in key] Identificativo univoco della transazione")],
            item: Annotated[str, Field(description="[BSPL: in] Articolo consegnato")],
            address: Annotated[str, Field(description="[BSPL: in] Indirizzo di consegna")],
            outcome: Annotated[str, Field(description="[BSPL: out] Esito finale della consegna")],
        ) -> str:
            """
            Messaggio BSPL: Shipper -> Buyer: deliver [in ID, in item, in address, out outcome]
            Riceve e registra la notifica di avvenuta consegna dallo Shipper.
            """
            logger.info(f"[Buyer] Ricevuto Tool 'deliver': ID={ID!r}, item={item!r}, address={address!r}, outcome={outcome!r}")
            params = {"ID": ID, "item": item, "address": address, "outcome": outcome}

            # 1. Verifica di consistenza semantica (immutabilità BSPL)
            self.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.is_duplicate("deliver", ID, params):
                logger.info(f"[Buyer] Messaggio 'deliver' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"Consegna già registrata per ID={ID}."

            # 3. Inserimento nella relazione locale R(deliver)
            self.insert_relation("deliver", ID, params)

            # 4. Notifica evento di consegna
            self._notify_message_received("deliver", ID)

            return f"Consegna per ID={ID} registrata con successo."

    # ----------------------------------------------------------------------
    # Metodi Pubblici di Invio (Emissione messaggi BSPL tramite Client MCP)
    # ----------------------------------------------------------------------

    async def send_rfq(self, ID: str, item: str):
        """
        Messaggio BSPL: Buyer -> Seller: rfq [out ID, out item]
        Invia una Request For Quote (RFQ) al Seller generando ID e item.
        """
        # 1. Verifica di viabilità LoST: ID e item sono parametri out (non devono essere già noti)
        self.check_viability(ID, out_params=["ID", "item"])

        params = {"ID": ID, "item": item}

        # 2. Inserimento locale nella relazione R(rfq)
        self.insert_relation("rfq", ID, params)

        logger.info(f"[Buyer -> Seller] Invocazione Tool 'rfq': ID={ID!r}, item={item!r}")
        try:
            async with Client(SELLER_URL) as client:
                result = await client.call_tool("rfq", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Buyer] Errore dal server Seller su 'rfq': {error_msg}")
                    self.remove_relation("rfq", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'rfq': {error_msg}")
                logger.info(f"[Buyer] Risposta per 'rfq': {result.content}")
        except Exception:
            self.remove_relation("rfq", ID)
            raise

    async def send_accept(
        self,
        ID: str,
        address: str,
        response: str = "accepted"
    ):
        """
        Messaggio BSPL: Buyer -> Seller: accept [in ID, in item, in price, out address, out response]
        Invia l'accettazione dell'offerta al Seller generando address e response.
        I parametri [in] (ID, item, price) vengono verificati e risolti dallo stato locale.
        """
        # 1. Verifica di viabilità LoST sui nomi dei parametri
        in_values = self.check_viability(
            ID,
            in_params=["ID", "item", "price"],
            out_params=["address", "response"],
        )

        params = {**in_values, "address": address, "response": response}

        # 2. Inserimento locale nella relazione R(accept)
        self.insert_relation("accept", ID, params)

        await asyncio.sleep(0.05)
        logger.info(f"[Buyer -> Seller] Invocazione Tool 'accept': ID={ID!r}, address={address!r}, response={response!r}")
        try:
            async with Client(SELLER_URL) as client:
                result = await client.call_tool("accept", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Buyer] Errore dal server Seller su 'accept': {error_msg}")
                    self.remove_relation("accept", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'accept': {error_msg}")
                logger.info(f"[Buyer] Risposta per 'accept': {result.content}")
        except Exception:
            self.remove_relation("accept", ID)
            raise

    async def send_reject(
        self,
        ID: str,
        outcome: str = "rejected",
        response: str = "rejected"
    ):
        """
        Messaggio BSPL: Buyer -> Seller: reject [in ID, in item, in price, out outcome, out response]
        Invia il rifiuto dell'offerta al Seller generando outcome e response.
        I parametri [in] (ID, item, price) vengono verificati e risolti dallo stato locale.
        """
        # 1. Verifica di viabilità LoST sui nomi dei parametri
        in_values = self.check_viability(
            ID,
            in_params=["ID", "item", "price"],
            out_params=["outcome", "response"],
        )

        params = {**in_values, "outcome": outcome, "response": response}

        # 2. Inserimento locale nella relazione R(reject)
        self.insert_relation("reject", ID, params)

        await asyncio.sleep(0.05)
        logger.info(f"[Buyer -> Seller] Invocazione Tool 'reject': ID={ID!r}, outcome={outcome!r}, response={response!r}")
        try:
            async with Client(SELLER_URL) as client:
                result = await client.call_tool("reject", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Buyer] Errore dal server Seller su 'reject': {error_msg}")
                    self.remove_relation("reject", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'reject': {error_msg}")
                logger.info(f"[Buyer] Risposta per 'reject': {result.content}")
        except Exception:
            self.remove_relation("reject", ID)
            raise
