"""Register built-in BMS blocks with the plugin registry."""
from __future__ import annotations

from batsim_core.plugins.registry import register_bms_block
from batsim_core.bms.soc_estimator import CoulombCounter
from batsim_core.bms.protection import Protector
from batsim_core.bms.balancer import PassiveBalancer
from batsim_core.bms.ekf_soc import EKFSocEstimator
from batsim_core.bms.controller import CCCVController


register_bms_block("CoulombCounter")(CoulombCounter)
register_bms_block("Protector")(Protector)
register_bms_block("PassiveBalancer")(PassiveBalancer)
register_bms_block("EKF")(EKFSocEstimator)
register_bms_block("CCCV")(CCCVController)

