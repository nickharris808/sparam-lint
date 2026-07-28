"""The five physical laws every passive linear network must obey.

Each law returns a :class:`LawResult` carrying a boolean verdict, the worst
observed value, the frequency at which it occurred, and a human sentence.

A note on why this library exists at all. Checking passivity is easy; checking
that your *checker* still works is the part people skip. A battery that has
silently stopped discriminating -- a tolerance widened until nothing fails, a
reshape that transposed the matrix, a phase unwrap that aliased -- reports
100% compliance forever and looks exactly like a healthy one. So this module
ships with :mod:`sparam_lint.control`, which builds deliberately non-compliant
networks and requires each law to reject them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "LawResult",
    "check_passivity",
    "check_reciprocity",
    "check_energy_conservation",
    "check_positive_real_z0",
    "check_group_delay_nonneg",
    "ALL_LAWS",
    "run_battery",
]

# Tolerances are floating-point slack, not physics slack. They exist so that a
# genuinely passive network computed in fp64 is not failed for a 1e-15 excess.
PASSIVITY_TOL = 1e-9
RECIPROCITY_TOL = 1e-6


@dataclass
class LawResult:
    name: str
    passed: bool
    worst_value: float | None
    worst_freq_hz: float | None
    message: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "law": self.name,
            "passed": self.passed,
            "worst_value": self.worst_value,
            "worst_freq_hz": self.worst_freq_hz,
            "message": self.message,
            **({"detail": self.detail} if self.detail else {}),
        }


def _worst(values: np.ndarray, freq: np.ndarray) -> tuple[float, float]:
    idx = int(np.argmax(values))
    return float(values[idx]), float(freq[idx])


def check_passivity(s: np.ndarray, freq: np.ndarray, tol: float = PASSIVITY_TOL) -> LawResult:
    """sigma_max(S(f)) <= 1: a passive network cannot create energy."""
    sig = np.array([np.linalg.svd(sf, compute_uv=False)[0] for sf in s])
    worst, wf = _worst(sig, freq)
    ok = bool(np.all(np.isfinite(sig))) and worst <= 1.0 + tol
    if ok:
        msg = f"largest singular value {worst:.9f} <= 1"
    else:
        msg = (
            f"largest singular value {worst:.6f} > 1 at {wf/1e9:.4f} GHz -- "
            "this network produces more power than is put into it"
        )
    return LawResult("passivity", ok, worst, wf, msg)


def check_reciprocity(s: np.ndarray, freq: np.ndarray, tol: float = RECIPROCITY_TOL) -> LawResult:
    """S = S^T for a network of reciprocal media (no ferrites, no active parts)."""
    num = np.array([np.linalg.norm(sf - sf.T, "fro") for sf in s])
    den = np.array([max(np.linalg.norm(sf, "fro"), 1e-300) for sf in s])
    rel = num / den
    worst, wf = _worst(rel, freq)
    ok = bool(np.all(np.isfinite(rel))) and worst <= tol
    msg = (
        f"normalized asymmetry {worst:.3e} <= {tol:g}"
        if ok
        else f"normalized asymmetry {worst:.3e} > {tol:g} at {wf/1e9:.4f} GHz -- "
        "S is not symmetric; if the medium is reciprocal this indicates a "
        "port-ordering or transpose error"
    )
    return LawResult("reciprocity", ok, worst, wf, msg)


def check_energy_conservation(
    s: np.ndarray, freq: np.ndarray, tol: float = PASSIVITY_TOL
) -> LawResult:
    """Row-wise: sum_j |S_ij|^2 <= 1 for every incident port i.

    Distinct from the spectral-norm test -- this bounds the power leaving when
    a single port is driven, and catches per-port violations that a global
    singular value can average away.
    """
    rows = np.sum(np.abs(s) ** 2, axis=2)  # (F, N)
    per_f = rows.max(axis=1)
    worst, wf = _worst(per_f, freq)
    ok = bool(np.all(np.isfinite(rows))) and worst <= 1.0 + tol
    msg = (
        f"worst row power {worst:.9f} <= 1"
        if ok
        else f"worst row power {worst:.6f} > 1 at {wf/1e9:.4f} GHz -- "
        "driving one port yields more power out than in"
    )
    return LawResult("energy_conservation", ok, worst, wf, msg)


def check_positive_real_z0(
    s: np.ndarray, freq: np.ndarray, z0: float, tol: float = 1e-9
) -> LawResult:
    """Re(Z) > 0 for the one-port input impedance seen at each port.

    Z_in,i = z0 * (1 + S_ii) / (1 - S_ii). A passive termination cannot present
    negative resistance.
    """
    sii = np.einsum("fii->fi", s)  # (F, N)
    denom = 1.0 - sii
    safe = np.abs(denom) > 1e-12
    z = np.full(sii.shape, np.nan, dtype=complex)
    z[safe] = z0 * (1.0 + sii[safe]) / denom[safe]
    re = np.real(z)
    finite = np.isfinite(re)
    if not finite.any():
        return LawResult(
            "positive_real_z0", False, None, None,
            "input impedance undefined at every port (S_ii == 1)",
        )
    masked = np.where(finite, re, np.inf)
    per_f = masked.min(axis=1)
    idx = int(np.argmin(per_f))
    worst, wf = float(per_f[idx]), float(freq[idx])
    ok = worst > -tol
    msg = (
        f"minimum Re(Z_in) {worst:.6g} ohm > 0"
        if ok
        else f"minimum Re(Z_in) {worst:.6g} ohm < 0 at {wf/1e9:.4f} GHz -- "
        "negative resistance at a port"
    )
    n_skipped = int(np.count_nonzero(~finite))
    return LawResult(
        "positive_real_z0", ok, worst, wf, msg,
        detail={"skipped_singular_points": n_skipped} if n_skipped else {},
    )


def check_group_delay_nonneg(
    s: np.ndarray, freq: np.ndarray, tol: float = 1e-12
) -> LawResult:
    """Group delay -d(phase)/d(omega) >= 0 on the through path: causality.

    The phase is unwrapped before differencing. An un-unwrapped difference
    aliases at every 2*pi crossing and produces spurious negative delays -- a
    defect this project found in its own checker via the negative control.
    """
    if len(freq) < 3:
        return LawResult(
            "group_delay_nonneg", True, None, None,
            f"skipped: {len(freq)} frequency points, need >= 3", detail={"skipped": True},
        )
    n = s.shape[1]
    i, j = (0, 1) if n >= 2 else (0, 0)
    phase = np.unwrap(np.angle(s[:, i, j]))
    omega = 2.0 * np.pi * freq
    tau = -np.gradient(phase, omega)
    worst = float(np.min(tau))
    wf = float(freq[int(np.argmin(tau))])
    ok = bool(np.all(np.isfinite(tau))) and worst >= -tol
    msg = (
        f"minimum group delay {worst:.6e} s >= 0"
        if ok
        else f"minimum group delay {worst:.6e} s < 0 at {wf/1e9:.4f} GHz -- "
        "output precedes input on the through path"
    )
    return LawResult("group_delay_nonneg", ok, worst, wf, msg,
                     detail={"path": f"S{i+1}{j+1}"})


ALL_LAWS = (
    "passivity",
    "reciprocity",
    "energy_conservation",
    "positive_real_z0",
    "group_delay_nonneg",
)


def run_battery(s: np.ndarray, freq: np.ndarray, z0: float = 50.0) -> list[LawResult]:
    """Run all five laws and return their results in a stable order."""
    return [
        check_passivity(s, freq),
        check_reciprocity(s, freq),
        check_energy_conservation(s, freq),
        check_positive_real_z0(s, freq, z0),
        check_group_delay_nonneg(s, freq),
    ]
