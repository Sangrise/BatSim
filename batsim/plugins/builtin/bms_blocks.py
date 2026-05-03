"""Register built-in BMS blocks with the plugin registry."""
from __future__ import annotations

from batsim.plugins.registry import register_bms_block
from batsim.bms.soc_estimator import CoulombCounter
from batsim.bms.protection import Protector
from batsim.bms.balancer import PassiveBalancer
from batsim.bms.ekf_soc import EKFSocEstimator
from batsim.bms.controller import CCCVController


register_bms_block("CoulombCounter")(CoulombCounter)
register_bms_block("Protector")(Protector)
register_bms_block("PassiveBalancer")(PassiveBalancer)
register_bms_block("EKF")(EKFSocEstimator)
register_bms_block("CCCV")(CCCVController)
