"""
Configurazione degli endpoint di rete per i nodi della coreografia BSPL PurchaseWithDelivery.

In questa implementazione prototipale, gli indirizzi dei nodi ibridi MCP sono configurati
staticamente (out-of-band) su localhost con porte dedicate su trasporto Streamable HTTP:
- Buyer:   http://127.0.0.1:8001/mcp
- Seller:  http://127.0.0.1:8002/mcp
- Shipper: http://127.0.0.1:8003/mcp
"""

BUYER_HOST = "127.0.0.1"
BUYER_PORT = 8001
BUYER_URL = f"http://{BUYER_HOST}:{BUYER_PORT}/mcp"

SELLER_HOST = "127.0.0.1"
SELLER_PORT = 8002
SELLER_URL = f"http://{SELLER_HOST}:{SELLER_PORT}/mcp"

SHIPPER_HOST = "127.0.0.1"
SHIPPER_PORT = 8003
SHIPPER_URL = f"http://{SHIPPER_HOST}:{SHIPPER_PORT}/mcp"
