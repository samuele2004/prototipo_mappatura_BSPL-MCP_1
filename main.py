"""
Script Principale: Simulazione della Coreografia BSPL 'PurchaseWithDelivery' su MCP v2.

Questo script simula l'interazione tra i tre ruoli (Buyer, Seller, Shipper) secondo
il modello di mappatura a nodi ibridi (Modello 3 della tesi):
1. Avvia i Server MCP dei tre nodi su trasporto Streamable HTTP (:8001, :8002, :8003).
2. Coordina i passaggi della transazione invocando i metodi di invio pubblici dei ruoli
   e sincronizzandosi sui messaggi ricevuti:
   * Step 1: Buyer   --[rfq]-->     Seller
   * Step 2: Seller  --[quote]-->   Buyer
   * Step 3: Buyer   --[accept]-->  Seller
   * Step 4: Seller  --[ship]-->    Shipper
   * Step 5: Shipper --[deliver]--> Buyer
3. Ispeziona e stampa lo stato finale delle relazioni locali LoST R(m) di ciascun nodo.
4. Convalida la consistenza dell'history vector distribuito e arresta i nodi.
"""

import asyncio
import json
import logging
from roles import BuyerNode, SellerNode, ShipperNode

# Configurazione del logging console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Simulation")


async def run_choreography_scenario():
    logger.info("=" * 75)
    logger.info("   SIMULAZIONE PROTOCOLLO BSPL 'PurchaseWithDelivery' (NODI IBRIDI MCP v2)")
    logger.info("=" * 75)

    # 1. Istanziazione dei nodi dei ruoli
    buyer = BuyerNode()
    seller = SellerNode()
    shipper = ShipperNode()

    # 2. Avvio dei Server MCP in background
    t_buyer = asyncio.create_task(buyer.run())
    t_seller = asyncio.create_task(seller.run())
    t_shipper = asyncio.create_task(shipper.run())

    try:
        # Attesa disponibilità di tutti i Server HTTP
        logger.info("Avvio dei nodi ibridi MCP (Buyer :8001, Seller :8002, Shipper :8003)...")
        await asyncio.gather(buyer.wait_ready(), seller.wait_ready(), shipper.wait_ready())
        logger.info("Tutti i nodi sono attivi e pronti alla comunicazione su Streamable HTTP.\n")

        # Dati specifici dell'istanza di acquisto
        tx_id = "ORDER-2026-001"
        item_name = "MacBook Pro 16 M3 Max"
        offered_price = 1200.0
        delivery_address = "Via Roma 10, 20121 Milano, Italia"

        # ------------------------------------------------------------------
        # FASE 1: Buyer invia RFQ al Seller
        # BSPL: Buyer -> Seller: rfq [out ID key, out item]
        # ------------------------------------------------------------------
        logger.info("-" * 75)
        logger.info(f"[FASE 1] Buyer emette RFQ: ID='{tx_id}', item='{item_name}'")
        logger.info("-" * 75)
        await buyer.send_rfq(ID=tx_id, item=item_name)

        # ------------------------------------------------------------------
        # FASE 2: Seller riceve RFQ e invia Quote al Buyer
        # BSPL: Seller -> Buyer: quote [in ID key, in item, out price]
        # ------------------------------------------------------------------
        await seller.wait_for_message("rfq", tx_id)
        logger.info("-" * 75)
        logger.info(f"[FASE 2] Seller ha ricevuto RFQ ed emette Quote: price={offered_price} EUR")
        logger.info("-" * 75)
        await seller.send_quote(ID=tx_id, item=item_name, price=offered_price)

        # ------------------------------------------------------------------
        # FASE 3: Buyer riceve Quote, accetta e invia Accept al Seller
        # BSPL: Buyer -> Seller: accept [in ID, in item, in price, out address, out response]
        # ------------------------------------------------------------------
        await buyer.wait_for_message("quote", tx_id)
        logger.info("-" * 75)
        logger.info(f"[FASE 3] Buyer accetta l'offerta ed emette Accept verso Seller")
        logger.info("-" * 75)
        await buyer.send_accept(
            ID=tx_id,
            item=item_name,
            price=offered_price,
            address=delivery_address,
            response="accepted",
        )

        # ------------------------------------------------------------------
        # FASE 4: Seller riceve Accept e invia Ship allo Shipper
        # BSPL: Seller -> Shipper: ship [in ID, in item, in address]
        # ------------------------------------------------------------------
        await seller.wait_for_message("accept", tx_id)
        logger.info("-" * 75)
        logger.info("[FASE 4] Seller riceve Accept ed emette ordine di spedizione Ship allo Shipper")
        logger.info("-" * 75)
        await seller.send_ship(ID=tx_id, item=item_name, address=delivery_address)

        # ------------------------------------------------------------------
        # FASE 5: Shipper riceve Ship e invia Deliver al Buyer
        # BSPL: Shipper -> Buyer: deliver [in ID, in item, in address, out outcome]
        # ------------------------------------------------------------------
        await shipper.wait_for_message("ship", tx_id)
        logger.info("-" * 75)
        logger.info("[FASE 5] Shipper prende in carico la merce ed emette Deliver verso Buyer")
        logger.info("-" * 75)
        await shipper.send_deliver(
            ID=tx_id,
            item=item_name,
            address=delivery_address,
            outcome="delivered",
        )

        # Attesa ricezione notifica di consegna sul Buyer
        await buyer.wait_for_message("deliver", tx_id)
        logger.info("-" * 75)
        logger.info("COREOGRAFIA COMPLETATA CON SUCCESSO!")
        logger.info("-" * 75)

        # ------------------------------------------------------------------
        # Ispezione dello stato locale relazionale LoST R(m) di ciascun ruolo
        # ------------------------------------------------------------------
        print("\n" + "=" * 75)
        print("  STATO DELLE RELAZIONI LOCALI LoST (R(m) per ciascun Ruolo)")
        print("=" * 75)

        print("\n[BUYER RELATIONS]:")
        for rel_name, table in buyer.relations.items():
            print(f"  R({rel_name}): {json.dumps(table.get(tx_id, {}), ensure_ascii=False)}")

        print("\n[SELLER RELATIONS]:")
        for rel_name, table in seller.relations.items():
            print(f"  R({rel_name}): {json.dumps(table.get(tx_id, {}), ensure_ascii=False)}")

        print("\n[SHIPPER RELATIONS]:")
        for rel_name, table in shipper.relations.items():
            print(f"  R({rel_name}): {json.dumps(table.get(tx_id, {}), ensure_ascii=False)}")
        print("=" * 75 + "\n")

        # ------------------------------------------------------------------
        # Asserzioni di conformità e consistenza dell'History Vector
        # ------------------------------------------------------------------
        # 1. Verifica Buyer
        assert buyer.r_rfq[tx_id]["item"] == item_name
        assert buyer.r_quote[tx_id]["price"] == offered_price
        assert buyer.r_accept[tx_id]["response"] == "accepted"
        assert buyer.r_deliver[tx_id]["outcome"] == "delivered"

        # 2. Verifica Seller
        assert seller.r_rfq[tx_id]["item"] == item_name
        assert seller.r_quote[tx_id]["price"] == offered_price
        assert seller.r_accept[tx_id]["address"] == delivery_address
        assert seller.r_ship[tx_id]["address"] == delivery_address

        # 3. Verifica Shipper
        assert shipper.r_ship[tx_id]["address"] == delivery_address
        assert shipper.r_deliver[tx_id]["outcome"] == "delivered"

        logger.info("Tutte le asserzioni sull'History Vector distribuito sono verificate.")

    finally:
        logger.info("Arresto dei nodi MCP...")
        buyer.stop()
        seller.stop()
        shipper.stop()
        await asyncio.gather(t_buyer, t_seller, t_shipper, return_exceptions=True)
        logger.info("Simulazione terminata regolarmente.")


if __name__ == "__main__":
    asyncio.run(run_choreography_scenario())
