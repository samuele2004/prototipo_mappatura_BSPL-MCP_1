"""
Definizione delle eccezioni per i vincoli del protocollo BSPL nell'architettura a nodi ibridi.

Tutte le eccezioni derivano da ToolError dell'SDK di MCP per consentire al Server MCP
di restituire automaticamente al client chiamante una risposta JSON-RPC con isError=True
e il messaggio di errore descrittivo nel payload.
"""

from mcp.server.mcpserver.exceptions import ToolError


class BSPLProtocolError(ToolError):
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
