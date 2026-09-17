from .base import CongestionControl
from .bbr import BBR
from .cubic import Cubic
from .reno import Reno

ALGORITHMS = {"reno": Reno, "cubic": Cubic, "bbr": BBR}

__all__ = ["CongestionControl", "Reno", "Cubic", "BBR", "ALGORITHMS"]
