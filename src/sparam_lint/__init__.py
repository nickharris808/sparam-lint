"""sparam-lint -- is your S-parameter model physically possible?

Five laws every passive linear network must obey, plus a negative control that
proves the checks still discriminate.
"""
__version__ = "0.1.0"

from .laws import (  # noqa: F401
    LawResult, run_battery, check_passivity, check_reciprocity,
    check_energy_conservation, check_positive_real_z0, check_group_delay_nonneg,
)
from .touchstone import Network, TouchstoneError, read_touchstone  # noqa: F401
from .control import make_passive_line, run_negative_control  # noqa: F401

__all__ = [
    "__version__", "LawResult", "run_battery", "check_passivity",
    "check_reciprocity", "check_energy_conservation", "check_positive_real_z0",
    "check_group_delay_nonneg", "Network", "TouchstoneError",
    "read_touchstone", "make_passive_line", "run_negative_control",
]
