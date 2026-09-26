"""
Package contenente i nodi di ruolo, l'adattatore e le eccezioni BSPL per la coreografia PurchaseWithDelivery.
"""

from roles.exceptions import (
    BSPLProtocolError,
    BSPLViabilityError,
    BSPLConsistencyError,
    BSPLExecutionError,
)
from roles.adapter import BSPLAdapter
from roles.base import BaseRoleNode
from roles.buyer import BuyerNode
from roles.seller import SellerNode
from roles.shipper import ShipperNode

__all__ = [
    "BaseRoleNode",
    "BuyerNode",
    "SellerNode",
    "ShipperNode",
    "BSPLAdapter",
    "BSPLProtocolError",
    "BSPLViabilityError",
    "BSPLConsistencyError",
    "BSPLExecutionError",
]
