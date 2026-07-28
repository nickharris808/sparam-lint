"""Negative control: prove the battery still discriminates.

A physics checker that reports 100% compliance is indistinguishable from one
that has quietly stopped working. This module constructs networks that
deliberately violate each law and asserts the corresponding check rejects
them, so a clean report from :mod:`sparam_lint` is evidence rather than
assertion.

Each violator is built to break **exactly one** law where possible, because a
fault that trips several checks does not tell you which check is alive.
"""

from __future__ import annotations

import numpy as np

from .laws import (
    check_energy_conservation,
    check_group_delay_nonneg,
    check_passivity,
    check_positive_real_z0,
    check_reciprocity,
)

__all__ = ["make_passive_line", "run_negative_control", "VIOLATORS"]


def make_passive_line(
    n_freq: int = 64,
    f_start: float = 1e9,
    f_stop: float = 40e9,
    loss_db: float = 0.5,
    delay_s: float = 20e-12,
) -> tuple[np.ndarray, np.ndarray]:
    """A genuinely passive, reciprocal, causal 2-port: a lossy delay line.

    Returns (s, freq). This is the positive control -- every law must PASS.
    """
    freq = np.linspace(f_start, f_stop, n_freq)
    amp = 10.0 ** (-abs(loss_db) / 20.0)
    phase = -2.0 * np.pi * freq * delay_s
    s21 = amp * np.exp(1j * phase)
    s11 = np.full_like(s21, 0.05 + 0j)
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 1] = s11
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    return s, freq


def _violate_passivity(s, freq):
    bad = s.copy()
    bad[:, 0, 1] *= 3.0
    bad[:, 1, 0] *= 3.0
    return bad, freq


def _violate_reciprocity(s, freq):
    bad = s.copy()
    bad[:, 0, 1] = bad[:, 1, 0] * np.exp(1j * 0.7)
    return bad, freq


def _violate_energy(s, freq):
    """Row power > 1 while keeping sigma_max modest is not possible for a 2x2,
    so this violator trips energy first and is checked on that law alone."""
    bad = s.copy()
    bad[:, 0, 0] = 0.9 + 0j
    bad[:, 0, 1] = 0.9 + 0j
    return bad, freq


def _violate_positive_real(s, freq):
    bad = s.copy()
    bad[:, 0, 0] = -1.6 + 0j  # |S11| > 1 -> Re(Z_in) < 0
    bad[:, 1, 1] = -1.6 + 0j
    return bad, freq


def _violate_group_delay(s, freq):
    """Advance rather than delay: phase increases with frequency."""
    bad = s.copy()
    phase = +2.0 * np.pi * freq * 20e-12
    amp = np.abs(bad[:, 0, 1])
    bad[:, 0, 1] = amp * np.exp(1j * phase)
    bad[:, 1, 0] = bad[:, 0, 1]
    return bad, freq


VIOLATORS = {
    "passivity": (_violate_passivity, lambda s, f: check_passivity(s, f)),
    "reciprocity": (_violate_reciprocity, lambda s, f: check_reciprocity(s, f)),
    "energy_conservation": (_violate_energy, lambda s, f: check_energy_conservation(s, f)),
    "positive_real_z0": (_violate_positive_real, lambda s, f: check_positive_real_z0(s, f, 50.0)),
    "group_delay_nonneg": (_violate_group_delay, lambda s, f: check_group_delay_nonneg(s, f)),
}


def run_negative_control() -> dict:
    """Build a violator per law, confirm the law rejects it.

    Returns a dict with per-law outcomes and an overall verdict. If any law
    fails to reject its violator, that law has stopped discriminating and the
    battery's clean verdicts should not be trusted.
    """
    s_good, freq = make_passive_line()

    positive = {}
    from .laws import run_battery

    for r in run_battery(s_good, freq, 50.0):
        positive[r.name] = r.passed

    negative = {}
    for law, (make_bad, check) in VIOLATORS.items():
        s_bad, f_bad = make_bad(s_good, freq)
        res = check(s_bad, f_bad)
        negative[law] = {
            "rejected": (not res.passed),
            "worst_value": res.worst_value,
        }

    all_pos = all(positive.values())
    all_neg = all(v["rejected"] for v in negative.values())
    return {
        "positive_control_all_pass": all_pos,
        "positive_control": positive,
        "negative_control_all_rejected": all_neg,
        "negative_control": negative,
        "battery_discriminates": bool(all_pos and all_neg),
    }
