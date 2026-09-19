"""
Package contenente i nodi di ruolo e le eccezioni BSPL per la coreografia PurchaseWithDelivery.
"""

from roles.base import (
    BaseRoleNode,
    BSPLProtocolError,
    BSPLViabilityError,
    BSPLConsistencyError,
    BSPLExecutionError,
)
from roles.buyer import BuyerNode
from roles.seller import SellerNode
from roles.shipper import ShipperNode

__all__ = [
    "BaseRoleNode",
    "BuyerNode",
    "SellerNode",
    "ShipperNode",
    "BSPLProtocolError",
    "BSPLViabilityError",
    "BSPLConsistencyError",
    "BSPLExecutionError",
]
