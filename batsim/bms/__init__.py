"""BMS package — protection, balancing, SOC estimation, controllers.

Cell-balancing algorithms live in :mod:`batsim.bms.cell_balancer` and are
auto-registered both in the local balancer registry and in the global
BMS plugin registry (``BMS_BLOCKS``) so they appear in ``batsim list-bms``.
"""
from . import cell_balancer  # noqa: F401  (registers built-in balancers)
from .cell_balancer import (
    list_balancers,
    make_balancer,
    register_balancer,
    PassiveBalancerV1,
    CellBalancerBase,
)

__all__ = [
    "list_balancers",
    "make_balancer",
    "register_balancer",
    "PassiveBalancerV1",
    "CellBalancerBase",
]
