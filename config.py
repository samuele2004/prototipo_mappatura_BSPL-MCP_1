"""
Configurazione degli endpoint di rete per i ruoli della coreografia BSPL Purchase.

In questa implementazione di esempio, gli indirizzi dei Server MCP di ciascun ruolo
sono configurati staticamente (hardcoded) per simulare la scoperta dei nodi (Role Binding).
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
