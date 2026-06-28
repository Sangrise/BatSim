from .base import BatteryModel
from .rint import RintModel
from .thevenin import TheveninModel
from .n_rc import NRCModel
from .spm import SPMModel

MODEL_REGISTRY: dict[str, type[BatteryModel]] = {
    "Rint": RintModel,
    "Thevenin": TheveninModel,
    "n-RC": NRCModel,
    "SPM": SPMModel,
}


def make_model(kind: str, **kwargs) -> BatteryModel:
    cls = MODEL_REGISTRY.get(kind, RintModel)
    return cls(**kwargs)
