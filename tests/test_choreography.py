"""
Test suite per la coreografia BSPL PurchaseWithDelivery su nodi ibridi MCP v2.

Include test per:
1. Scenario completo con esito positivo (Accept -> Ship -> Deliver)
2. Scenario alternativo con rifiuto (Reject) e non coinvolgimento dello Shipper
3. Concorrenza e isolamento dello stato tra transazioni multiple indipendenti
4. Validazione degli schemi sintattici tramite JSON Schema / Pydantic di MCP
5. Enforcement delle regole di viabilità LoST in emissione (in, out, nil)
6. Enforcement della consistenza semantica e immutabilità in ricezione (is_error=True)
7. Gestione dell'idempotenza su messaggi duplicati
"""

import asyncio
import pytest
import pytest_asyncio
from config import BUYER_URL, SELLER_URL, SHIPPER_URL
from mcp import Client
from roles import (
    BuyerNode,
    SellerNode,
    ShipperNode,
    BSPLViabilityError,
)


@pytest_asyncio.fixture
async def running_environment():
    """Fixture che avvia in background i nodi ibridi Buyer, Seller e Shipper."""
    buyer = BuyerNode()
    seller = SellerNode()
    shipper = ShipperNode()

    t_buyer = asyncio.create_task(buyer.run())
    t_seller = asyncio.create_task(seller.run())
    t_shipper = asyncio.create_task(shipper.run())

    await asyncio.gather(
        buyer.wait_ready(),
        seller.wait_ready(),
        shipper.wait_ready()
    )

    yield buyer, seller, shipper

    buyer.stop()
    seller.stop()
    shipper.stop()
    await asyncio.gather(t_buyer, t_seller, t_shipper, return_exceptions=True)


@pytest.mark.asyncio
async def test_purchase_happy_path(running_environment):
    """Verifica il percorso felice con accettazione e consegna."""
    buyer, seller, shipper = running_environment
    tx_id = "TEST-ORDER-ACCEPT-01"
    item = "MacBook Pro M3 Max"
    price = 1500.0
    address = "Via Roma 10, 20121 Milano, Italia"

    # 1. Buyer -> Seller: rfq (out ID, out item)
    await buyer.send_rfq(ID=tx_id, item=item)

    # 2. Seller -> Buyer: quote (in ID, in item, out price)
    await seller.wait_for_message("rfq", tx_id)
    await seller.send_quote(ID=tx_id, price=price)

    # 3. Buyer -> Seller: accept (in ID, in item, in price, out address, out response)
    await buyer.wait_for_message("quote", tx_id)
    await buyer.send_accept(ID=tx_id, address=address, response="accepted")

    # 4. Seller -> Shipper: ship (in ID, in item, in address)
    await seller.wait_for_message("accept", tx_id)
    await seller.send_ship(ID=tx_id)

    # 5. Shipper -> Buyer: deliver (in ID, in item, in address, out outcome)
    await shipper.wait_for_message("ship", tx_id)
    await shipper.send_deliver(ID=tx_id, outcome="delivered")

    # 6. Attesa ricezione consegna su Buyer
    await buyer.wait_for_message("deliver", tx_id)

    # Verifica stato finale relazioni LoST Buyer
    assert buyer.r_rfq[tx_id] == {"ID": tx_id, "item": item}
    assert buyer.r_quote[tx_id] == {"ID": tx_id, "item": item, "price": price}
    assert buyer.r_accept[tx_id]["response"] == "accepted"
    assert buyer.r_deliver[tx_id]["outcome"] == "delivered"

    # Verifica stato finale relazioni LoST Seller
    assert seller.r_rfq[tx_id] == {"ID": tx_id, "item": item}
    assert seller.r_quote[tx_id] == {"ID": tx_id, "item": item, "price": price}
    assert seller.r_accept[tx_id]["address"] == address
    assert seller.r_ship[tx_id]["address"] == address

    # Verifica stato finale relazioni LoST Shipper
    assert shipper.r_ship[tx_id] == {"ID": tx_id, "item": item, "address": address}
    assert shipper.r_deliver[tx_id]["outcome"] == "delivered"

    # Verifica History Vector distribuito H = [H_Buyer, H_Seller, H_Shipper]
    assert set(buyer.adapter.get_history(tx_id).keys()) == {"rfq", "quote", "accept", "deliver"}
    assert set(seller.adapter.get_history(tx_id).keys()) == {"rfq", "quote", "accept", "ship"}
    assert set(shipper.adapter.get_history(tx_id).keys()) == {"ship", "deliver"}


@pytest.mark.asyncio
async def test_purchase_reject_path(running_environment):
    """Verifica il percorso alternativo con rifiuto del preventivo da parte del Buyer."""
    buyer, seller, shipper = running_environment
    tx_id = "TEST-ORDER-REJECT-01"
    item = "Overpriced Item"
    price = 5000.0

    # 1. Buyer -> Seller: rfq
    await buyer.send_rfq(ID=tx_id, item=item)

    # 2. Seller -> Buyer: quote
    await seller.wait_for_message("rfq", tx_id)
    await seller.send_quote(ID=tx_id, price=price)

    # 3. Buyer decide di rifiutare ed invia 'reject' al Seller
    await buyer.wait_for_message("quote", tx_id)
    await buyer.send_reject(ID=tx_id, outcome="rejected", response="rejected")

    # 4. Seller attende il rifiuto
    await seller.wait_for_message("reject", tx_id)

    # Verifica stato Buyer
    assert buyer.r_reject[tx_id]["response"] == "rejected"
    assert buyer.r_reject[tx_id]["outcome"] == "rejected"

    # Verifica stato Seller
    assert seller.r_reject[tx_id]["response"] == "rejected"
    assert seller.r_reject[tx_id]["outcome"] == "rejected"

    # Verifica che lo Shipper NON abbia alcuna relazione registrata per questa transazione
    assert tx_id not in shipper.r_ship, "Lo Shipper non doveva ricevere alcun ordine di spedizione"


@pytest.mark.asyncio
async def test_concurrent_transactions_isolation(running_environment):
    """Verifica l'esecuzione concorrente di più transazioni indipendenti correlate per ID."""
    buyer, seller, shipper = running_environment

    orders = [
        ("CONC-001", "Item A", 100.0, "Address A"),
        ("CONC-002", "Item B", 200.0, "Address B"),
        ("CONC-003", "Item C", 300.0, "Address C"),
    ]

    async def execute_transaction(tx_id, item, price, address):
        await buyer.send_rfq(ID=tx_id, item=item)
        await seller.wait_for_message("rfq", tx_id)
        await seller.send_quote(ID=tx_id, price=price)
        await buyer.wait_for_message("quote", tx_id)
        await buyer.send_accept(ID=tx_id, address=address, response="accepted")
        await seller.wait_for_message("accept", tx_id)
        await seller.send_ship(ID=tx_id)
        await shipper.wait_for_message("ship", tx_id)
        await shipper.send_deliver(ID=tx_id, outcome="delivered")
        await buyer.wait_for_message("deliver", tx_id)

    # Esecuzione in parallelo delle 3 transazioni
    await asyncio.gather(*(execute_transaction(*order) for order in orders))

    # Verifica dell'isolamento dei dati nelle tabelle relazionali
    for tx_id, item, expected_price, address in orders:
        assert buyer.r_rfq[tx_id]["item"] == item
        assert buyer.r_quote[tx_id]["price"] == expected_price
        assert buyer.r_deliver[tx_id]["outcome"] == "delivered"

        assert seller.r_quote[tx_id]["price"] == expected_price
        assert seller.r_ship[tx_id]["address"] == address

        assert shipper.r_deliver[tx_id]["outcome"] == "delivered"


@pytest.mark.asyncio
async def test_tool_schema_validation(running_environment):
    """Verifica che il server MCP validi la presenza e il tipo dei parametri obbligatori."""
    buyer, seller, shipper = running_environment

    # Chiamata a 'rfq' con parametri mancanti sul Seller (manca 'item')
    async with Client(SELLER_URL) as client:
        result = await client.call_tool("rfq", {"ID": "INVALID-SCHEMA-01"})
        assert result.is_error is True, "Il server MCP avrebbe dovuto rifiutare la chiamata con schema invalido"
        assert "item" in str(result.content).lower()


@pytest.mark.asyncio
async def test_viability_emission_check(running_environment):
    """Verifica l'enforcement delle regole di viabilità BSPL in fase di emissione (in, out, nil)."""
    buyer, seller, shipper = running_environment
    tx_id = "TEST-VIABILITY-01"
    item = "Test Phone"

    # 1. Tentativo illegale: Seller prova ad inviare Quote senza aver prima ricevuto RFQ
    # (manca il parametro in 'item' nello stato locale del Seller)
    with pytest.raises(BSPLViabilityError) as exc_info:
        await seller.send_quote(ID=tx_id, price=300.0)
    assert "non ancora noto" in str(exc_info.value)
    assert any(param in str(exc_info.value) for param in ["ID", "item"])

    # Ora eseguiamo regolarmente RFQ e Quote
    await buyer.send_rfq(ID=tx_id, item=item)
    await seller.wait_for_message("rfq", tx_id)
    await seller.send_quote(ID=tx_id, price=300.0)
    await buyer.wait_for_message("quote", tx_id)

    # Buyer invia Accept (vincolando response="accepted")
    await buyer.send_accept(ID=tx_id, address="Via Test 1", response="accepted")

    # 2. Tentativo illegale: Buyer prova a inviare Reject dopo aver già accettato (mutua esclusione su response)
    with pytest.raises(BSPLViabilityError) as exc_info2:
        await buyer.send_reject(ID=tx_id, outcome="rejected", response="rejected")
    assert "già vincolato" in str(exc_info2.value)
    assert "response" in str(exc_info2.value)

    # 3. Verifica controllo parametri [nil]: se un parametro nil è vincolato, l'emissione deve fallire
    with pytest.raises(BSPLViabilityError) as exc_info3:
        # simuliamo un controllo di viabilità con nil_params=["item"] (dove item è già noto)
        buyer.adapter.check_viability(ID=tx_id, nil_params=["item"])
    assert "parametro [nil]" in str(exc_info3.value)


@pytest.mark.asyncio
async def test_consistency_reception_check(running_environment):
    """Verifica che il server MCP segnali errore se un messaggio ricevuto viola la consistenza BSPL."""
    buyer, seller, shipper = running_environment
    tx_id = "TEST-CONSISTENCY-01"
    item = "Smart Watch"
    price = 250.0

    # Prepariamo la transazione fino alla quotazione di 250.0
    await buyer.send_rfq(ID=tx_id, item=item)
    await seller.wait_for_message("rfq", tx_id)
    await seller.send_quote(ID=tx_id, price=price)
    await buyer.wait_for_message("quote", tx_id)

    # Chiamata remota diretta non conforme: accept con prezzo alterato a 100.0 invece di 250.0
    async with Client(SELLER_URL) as client:
        result = await client.call_tool("accept", {
            "ID": tx_id,
            "item": item,
            "price": 100.0,  # Prezzo discordante rispetto alla quotazione registrata
            "address": "Via Disaccordo 5",
            "response": "accepted"
        })
        assert result.is_error is True, "Il Tool accept sul Seller avrebbe dovuto restituire is_error=True"
        assert "consistenza" in str(result.content).lower() or "incompatibile" in str(result.content).lower()


@pytest.mark.asyncio
async def test_idempotent_duplicate_handling(running_environment):
    """Verifica che la ricezione di messaggi duplicati identici sia idempotente e non generi errori."""
    buyer, seller, shipper = running_environment
    tx_id = "TEST-DUP-01"
    item = "Duplicated Item"

    # Buyer invia la prima RFQ
    await buyer.send_rfq(ID=tx_id, item=item)
    await seller.wait_for_message("rfq", tx_id)
    assert tx_id in seller.r_rfq

    # Invio di una seconda RFQ identica direttamente al server del Seller (simulazione ritrasmissione di rete)
    async with Client(SELLER_URL) as client:
        result = await client.call_tool("rfq", {"ID": tx_id, "item": item})
        assert result.is_error is False
        assert "già registrata" in str(result.content).lower() or "duplicato" in str(result.content).lower()

    # Lo stato in R(rfq) rimane consistente e non alterato
    assert seller.r_rfq[tx_id] == {"ID": tx_id, "item": item}
