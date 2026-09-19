# Prototipo: Mappatura BSPL su MCP (Modello a Nodi Ibridi)

Questo repository contiene il prototipo di riferimento per la mappatura del protocollo BSPL **`PurchaseWithDelivery`** sull'infrastruttura **Model Context Protocol (MCP)**, utilizzando l'SDK ufficiale per Python (`mcp>=2.0.0`) su trasporto **Streamable HTTP**.

Il prototipo realizza il **terzo modello di mappatura (Nodi Ibridi)** definito nel Capitolo 3 della tesi di laurea:
- Ciascun partecipante è un nodo ibrido che integra sia un Server MCP (per ricevere comunicazioni) sia un Client/Host MCP (per inviare comunicazioni).
- La comunicazione avviene unicamente tramite la primitiva dei **Tool MCP**, superando le limitazioni di risorse e notifiche.
- Lo stato locale è organizzato secondo i principi del modello **LoST (Local State Transfer)**, con tabelle relazionali distinte $R(m)$ per ciascuno schema di messaggio.
- I vincoli di viabilità in emissione e consistenza semantica (immutabilità BSPL) e idempotenza in ricezione sono applicati localmente da ciascun nodo.

---

## 1. Il Protocollo BSPL di Riferimento

```bspl
PurchaseWithDelivery {
    role Buyer, Seller, Shipper
    parameter out ID key, out item, out price, out outcome

    Buyer -> Seller: rfq[out ID, out item]
    Seller -> Buyer: quote[in ID, in item, out price]
    Buyer -> Seller: accept[in ID, in item, in price, out address, out response]
    Buyer -> Seller: reject[in ID, in item, in price, out outcome, out response]

    Seller -> Shipper: ship[in ID, in item, in address]
    Shipper -> Buyer: deliver[in ID, in item, in address, out outcome]
}
```

---

## 2. Architettura del Prototipo

```
                   +---------------------+
                   |      BuyerNode      |
                   | Server :8001 | Host |
                   +---------------------+
                         /          ^
               rfq,     /            \  deliver
        accept, reject /              \
                      v                \
             +---------------------+   +---------------------+
             |     SellerNode      |   |     ShipperNode     |
             | Server :8002 | Host |---> Server :8003 | Host |
             +---------------------+   +---------------------+
                                ship
```

1. **Relazioni Locali LoST ($R(m)$)**:
   - **Buyer**: $R(rfq), R(quote), R(accept), R(reject), R(deliver)$
   - **Seller**: $R(rfq), R(quote), R(accept), R(reject), R(ship)$
   - **Shipper**: $R(ship), R(deliver)$
2. **Controlli di Viabilità LoST (Emissione)**:
   - Parametri `[in]`: devono essere già vincolati localmente e vengono automaticamente risolti dalle relazioni locali del nodo. Il chiamante passa a `send_*` unicamente la chiave `ID` e i parametri `[out]` generati.
   - Parametri `[out]`: non devono essere già vincolati per quell'ID. La mutua esclusione tra `accept` e `reject` è garantita dalla non-riassegnabilità del parametro `response`.
   - Parametri `[nil]`: se dichiarati nello schema, viene verificato che non siano vincolati nello stato locale per quell'ID.
3. **Controlli di Consistenza e Idempotenza (Ricezione Tool)**:
   - Consistenza: se un parametro ricevuto è già noto nello stato locale, il valore deve essere identico. In caso di discrepanza viene sollevata una `BSPLConsistencyError` che l'SDK MCP restituisce come risposta con `is_error=True`.
   - Idempotenza: messaggi duplicati identici vengono riconosciuti e accettati senza duplicare tuple né scatenare eventi ridondanti.
4. **Trasporto Streamable HTTP**:
   - Endpoint HTTP dedicati con porta configurabile (`Buyer: 8001`, `Seller: 8002`, `Shipper: 8003`).

---

## 3. Tabella dei Messaggi, Tool e Metodi Send

| Messaggio BSPL | Mittente | Ricevente | Tool MCP (Ricevente) | Metodo Send (Mittente) | Input Chiamante (`send_*`) | Parametri Risolti da Stato Locale (`[in]`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Buyer -> Seller: rfq` | Buyer | Seller | `rfq` | `buyer.send_rfq(ID, item)` | `ID: [out key]`, `item: [out]` | *(nessuno)* |
| `Seller -> Buyer: quote` | Seller | Buyer | `quote` | `seller.send_quote(ID, price)` | `price: [out]` | `ID: [in key]`, `item: [in]` |
| `Buyer -> Seller: accept` | Buyer | Seller | `accept` | `buyer.send_accept(ID, address, response)` | `address: [out]`, `response: [out]` | `ID: [in key]`, `item: [in]`, `price: [in]` |
| `Buyer -> Seller: reject` | Buyer | Seller | `reject` | `buyer.send_reject(ID, outcome, response)` | `outcome: [out]`, `response: [out]` | `ID: [in key]`, `item: [in]`, `price: [in]` |
| `Seller -> Shipper: ship` | Seller | Shipper | `ship` | `seller.send_ship(ID)` | *(nessuno)* | `ID: [in key]`, `item: [in]`, `address: [in]` |
| `Shipper -> Buyer: deliver` | Shipper | Buyer | `deliver` | `shipper.send_deliver(ID, outcome)` | `outcome: [out]` | `ID: [in key]`, `item: [in]`, `address: [in]` |

---

## 4. Struttura del Repository

```
.
├── config.py                 # Endpoint e porte dei nodi ibridi (8001, 8002, 8003)
├── main.py                   # Simulazione del protocollo e ispezione relazioni LoST
├── pytest.ini                # Configurazione per pytest-asyncio
├── requirements.txt          # Dipendenze Python (mcp>=2.0.0, uvicorn, pytest)
├── roles/
│   ├── __init__.py           # Export dei nodi e delle eccezioni BSPL
│   ├── base.py               # BaseRoleNode (Server MCP, relazioni LoST, viabilità, consistenza)
│   ├── buyer.py              # Ruolo Buyer
│   ├── seller.py             # Ruolo Seller
│   └── shipper.py            # Ruolo Shipper
├── tests/
│   ├── __init__.py
│   └── test_choreography.py  # Test suite (Happy path, Reject, Concorrenza, Viabilità, Consistenza, Duplicati)
└── README.md
```

---

## 5. Istruzioni per l'Esecuzione

### 1. Attivazione dell'ambiente virtuale
```bash
source .venv/bin/activate
```

### 2. Esecuzione della simulazione completa
```bash
python main.py
```

### 3. Esecuzione della suite di test
```bash
pytest -v
```
