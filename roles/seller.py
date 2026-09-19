"""
Implementazione del ruolo 'Seller' per il protocollo BSPL PurchaseWithDelivery.

Definizione del ruolo nel protocollo:
- Relazioni Locali LoST:
  * R(rfq):    [ID, item]
  * R(quote):  [ID, item, price]
  * R(accept): [ID, item, price, address, response]
  * R(reject): [ID, item, price, outcome, response]
  * R(ship):   [ID, item, address]
- RICEZIONE (Tool MCP esposti):
  * rfq(ID, item) [Buyer -> Seller: rfq]
  * accept(ID, item, price, address, response) [Buyer -> Seller: accept]
  * reject(ID, item, price, outcome, response) [Buyer -> Seller: reject]
- EMISSIONE (Metodi pubblici per l'invio messaggi via Client MCP):
  * send_quote(ID, item, price) [Seller -> Buyer: quote]
  * send_ship(ID, item, address) [Seller -> Shipper: ship]
"""

import asyncio
import logging
from typing import Annotated, Any, Dict
from pydantic import Field
from mcp import Client
from config import SELLER_HOST, SELLER_PORT, BUYER_URL, SHIPPER_URL
from roles.base import BaseRoleNode, BSPLExecutionError

logger = logging.getLogger("Seller")


class SellerNode(BaseRoleNode):
    """
    Nodo ibrido per il ruolo Seller.
    Gestisce le relazioni locali R(rfq), R(quote), R(accept), R(reject), R(ship),
    i tool di ricezione e i metodi di emissione con verifiche formali LoST.
    """

    def __init__(self, host: str = SELLER_HOST, port: int = SELLER_PORT):
        super().__init__(name="Seller", host=host, port=port)

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
    def r_ship(self) -> Dict[str, Dict[str, Any]]:
        return self.relations.setdefault("ship", {})

    # ----------------------------------------------------------------------
    # Tool MCP Esposti (Ricezione messaggi BSPL)
    # ----------------------------------------------------------------------

    def _register_tools(self):
        """Registra i Tool esposti dal Server MCP del Seller per ricevere messaggi BSPL."""

        @self.server.tool()
        async def rfq(
            ID: Annotated[str, Field(description="[BSPL: out key] Identificativo univoco della transazione generato dal Buyer")],
            item: Annotated[str, Field(description="[BSPL: out] Articolo richiesto dal Buyer")],
        ) -> str:
            """
            Messaggio BSPL: Buyer -> Seller: rfq [out ID, out item]
            Riceve e registra la richiesta di preventivo dal Buyer.
            """
            logger.info(f"[Seller] Ricevuto Tool 'rfq': ID={ID!r}, item={item!r}")
            params = {"ID": ID, "item": item}

            # 1. Verifica di consistenza semantica (immutabilità BSPL)
            self.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.is_duplicate("rfq", ID, params):
                logger.info(f"[Seller] Messaggio 'rfq' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"RFQ già registrata per ID={ID}."

            # 3. Inserimento nella relazione locale R(rfq)
            self.insert_relation("rfq", ID, params)

            # 4. Notifica evento arrivo RFQ
            self._notify_message_received("rfq", ID)

            return f"RFQ registrata per ID={ID}."

        @self.server.tool()
        async def accept(
            ID: Annotated[str, Field(description="[BSPL: in key] Identificativo univoco della transazione")],
            item: Annotated[str, Field(description="[BSPL: in] Articolo negoziato")],
            price: Annotated[float, Field(description="[BSPL: in] Prezzo pattuito")],
            address: Annotated[str, Field(description="[BSPL: out] Indirizzo di consegna specificato dal Buyer")],
            response: Annotated[str, Field(description="[BSPL: out] Risposta di accettazione ('accepted')")],
        ) -> str:
            """
            Messaggio BSPL: Buyer -> Seller: accept [in ID, in item, in price, out address, out response]
            Riceve e registra l'accettazione dell'offerta da parte del Buyer.
            """
            logger.info(
                f"[Seller] Ricevuto Tool 'accept': ID={ID!r}, item={item!r}, price={price}, "
                f"address={address!r}, response={response!r}"
            )
            params = {
                "ID": ID,
                "item": item,
                "price": price,
                "address": address,
                "response": response,
            }

            # 1. Verifica di consistenza semantica (immutabilità BSPL su item, price, response)
            self.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.is_duplicate("accept", ID, params):
                logger.info(f"[Seller] Messaggio 'accept' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"Accettazione già registrata per ID={ID}."

            # 3. Inserimento nella relazione locale R(accept)
            self.insert_relation("accept", ID, params)

            # 4. Notifica evento accettazione
            self._notify_message_received("accept", ID)

            return f"Accettazione registrata per ID={ID}."

        @self.server.tool()
        async def reject(
            ID: Annotated[str, Field(description="[BSPL: in key] Identificativo univoco della transazione")],
            item: Annotated[str, Field(description="[BSPL: in] Articolo negoziato")],
            price: Annotated[float, Field(description="[BSPL: in] Prezzo rifiutato")],
            outcome: Annotated[str, Field(description="[BSPL: out] Esito negativo ('rejected')")],
            response: Annotated[str, Field(description="[BSPL: out] Risposta di rifiuto ('rejected')")],
        ) -> str:
            """
            Messaggio BSPL: Buyer -> Seller: reject [in ID, in item, in price, out outcome, out response]
            Riceve e registra il rifiuto dell'offerta da parte del Buyer.
            """
            logger.info(
                f"[Seller] Ricevuto Tool 'reject': ID={ID!r}, item={item!r}, price={price}, "
                f"outcome={outcome!r}, response={response!r}"
            )
            params = {
                "ID": ID,
                "item": item,
                "price": price,
                "outcome": outcome,
                "response": response,
            }

            # 1. Verifica di consistenza semantica (immutabilità BSPL)
            self.check_consistency(ID, params)

            # 2. Controllo duplicati (idempotenza)
            if self.is_duplicate("reject", ID, params):
                logger.info(f"[Seller] Messaggio 'reject' già registrato per ID={ID!r} (duplicato idempotente)")
                return f"Rifiuto già registrato per ID={ID}."

            # 3. Inserimento nella relazione locale R(reject)
            self.insert_relation("reject", ID, params)

            # 4. Notifica evento rifiuto
            self._notify_message_received("reject", ID)

            return f"Rifiuto registrato per ID={ID}."

    # ----------------------------------------------------------------------
    # Metodi Pubblici di Invio (Emissione messaggi BSPL tramite Client MCP)
    # ----------------------------------------------------------------------

    async def send_quote(self, ID: str, item: str, price: float):
        """
        Messaggio BSPL: Seller -> Buyer: quote [in ID, in item, out price]
        Invia la quotazione di prezzo al Buyer.
        """
        in_params = {"ID": ID, "item": item}
        out_params = ["price"]
        params = {**in_params, "price": price}

        # 1. Verifica di viabilità BSPL: ID e item devono essere già noti; price non deve essere noto
        self.check_viability(ID, in_params=in_params, out_params=out_params, schema="quote")

        # 2. Inserimento locale nella relazione R(quote)
        self.insert_relation("quote", ID, params)

        await asyncio.sleep(0.05)
        logger.info(f"[Seller -> Buyer] Invocazione Tool 'quote': ID={ID!r}, price={price}")
        try:
            async with Client(BUYER_URL) as client:
                result = await client.call_tool("quote", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Seller] Errore dal server Buyer su 'quote': {error_msg}")
                    self.remove_relation("quote", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'quote': {error_msg}")
                logger.info(f"[Seller] Risposta per 'quote': {result.content}")
        except Exception:
            self.remove_relation("quote", ID)
            raise

    async def send_ship(self, ID: str, item: str, address: str):
        """
        Messaggio BSPL: Seller -> Shipper: ship [in ID, in item, in address]
        Invia l'ordine di spedizione allo Shipper.
        """
        in_params = {"ID": ID, "item": item, "address": address}
        out_params: list[str] = []
        params = dict(in_params)

        # 1. Verifica di viabilità BSPL: tutti i parametri sono [in] e devono essere già noti (da rfq e accept)
        self.check_viability(ID, in_params=in_params, out_params=out_params, schema="ship")

        # 2. Inserimento locale nella relazione R(ship)
        self.insert_relation("ship", ID, params)

        await asyncio.sleep(0.05)
        logger.info(f"[Seller -> Shipper] Invocazione Tool 'ship': ID={ID!r}, address={address!r}")
        try:
            async with Client(SHIPPER_URL) as client:
                result = await client.call_tool("ship", params)
                if result.is_error:
                    error_msg = str(result.content)
                    logger.error(f"❌ [Seller] Errore dal server Shipper su 'ship': {error_msg}")
                    self.remove_relation("ship", ID)
                    raise BSPLExecutionError(f"Errore remoto su 'ship': {error_msg}")
                logger.info(f"[Seller] Risposta per 'ship': {result.content}")
        except Exception:
            self.remove_relation("ship", ID)
            raise
