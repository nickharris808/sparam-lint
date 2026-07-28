"""Touchstone (.sNp) reader.

Implements the Touchstone 1.x file format as used by essentially every RF tool.
Deliberately dependency-light: numpy only.

The one real trap in this format, and the reason most hand-rolled parsers are
subtly wrong: **two-port files store data in the order S11 S21 S12 S22**, i.e.
column-major, while three-port and above are row-major (S11 S12 S13 S21 ...).
A parser that assumes row-major everywhere silently transposes every 2-port
file it reads, which turns a reciprocity check into a no-op. We handle it.
"""

from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["Network", "read_touchstone", "TouchstoneError"]

_FREQ_MULT = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}


class TouchstoneError(ValueError):
    """Raised when a file cannot be parsed as valid Touchstone."""


@dataclass
class Network:
    """An N-port network sampled over frequency.

    Attributes
    ----------
    freq_hz : (F,) float array, strictly increasing
    s       : (F, N, N) complex array
    z0      : reference impedance in ohms
    path    : source file, for messages
    """

    freq_hz: np.ndarray
    s: np.ndarray
    z0: float
    path: str = "<memory>"

    @property
    def n_ports(self) -> int:
        return int(self.s.shape[1])

    @property
    def n_freq(self) -> int:
        return int(self.s.shape[0])

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"Network({self.n_ports}-port, {self.n_freq} freq, "
            f"{self.freq_hz[0]/1e9:.4g}-{self.freq_hz[-1]/1e9:.4g} GHz, z0={self.z0}Ω)"
        )


def _parse_option_line(line: str) -> tuple[float, str, str, float]:
    """Parse '# GHZ S RI R 50' -> (freq_mult, param, fmt, z0)."""
    toks = line[1:].split()
    freq_mult, param, fmt, z0 = 1e9, "s", "ma", 50.0
    i = 0
    while i < len(toks):
        t = toks[i].lower()
        if t in _FREQ_MULT:
            freq_mult = _FREQ_MULT[t]
        elif t in ("s", "y", "z", "h", "g"):
            param = t
        elif t in ("ri", "ma", "db"):
            fmt = t
        elif t == "r":
            if i + 1 < len(toks):
                try:
                    z0 = float(toks[i + 1])
                except ValueError as exc:
                    raise TouchstoneError(f"bad reference impedance: {toks[i+1]!r}") from exc
                i += 1
        i += 1
    return freq_mult, param, fmt, z0


def _to_complex(a: float, b: float, fmt: str) -> complex:
    if fmt == "ri":
        return complex(a, b)
    if fmt == "ma":
        return cmath.rect(a, math.radians(b))
    if fmt == "db":
        return cmath.rect(10.0 ** (a / 20.0), math.radians(b))
    raise TouchstoneError(f"unknown format {fmt!r}")  # pragma: no cover


def _reorder_2port(flat: np.ndarray) -> np.ndarray:
    """Touchstone 2-port order is S11 S21 S12 S22 -> return proper 2x2."""
    s11, s21, s12, s22 = flat
    return np.array([[s11, s12], [s21, s22]], dtype=complex)


def read_touchstone(path: str | Path) -> Network:
    """Read a Touchstone .sNp file into a :class:`Network`.

    Raises :class:`TouchstoneError` on anything malformed. Notably it does not
    silently accept non-finite entries -- a file containing NaN or Inf is
    rejected rather than propagated into a physics check that would then
    report a meaningless verdict.
    """
    path = Path(path)
    if not path.exists():
        raise TouchstoneError(f"no such file: {path}")

    m = re.search(r"\.s(\d+)p$", path.name, re.IGNORECASE)
    n_ports = int(m.group(1)) if m else 0

    freq_mult, param, fmt, z0 = 1e9, "s", "ma", 50.0
    saw_option = False
    numbers: list[float] = []

    with path.open("r", errors="replace") as fh:
        for raw in fh:
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            if line.startswith("#"):
                if saw_option:
                    continue  # later option lines are v2 keywords; ignore
                freq_mult, param, fmt, z0 = _parse_option_line(line)
                saw_option = True
                continue
            if line[0].isalpha():
                continue  # v2 keyword block
            for tok in line.replace(",", " ").split():
                try:
                    numbers.append(float(tok))
                except ValueError as exc:
                    raise TouchstoneError(f"non-numeric token {tok!r} in {path.name}") from exc

    if not numbers:
        raise TouchstoneError(f"{path.name}: no data rows")
    if param != "s":
        raise TouchstoneError(f"{path.name}: only S-parameter files supported, got {param.upper()}")

    if n_ports == 0:
        raise TouchstoneError(f"cannot infer port count from filename {path.name!r}")

    stride = 1 + 2 * n_ports * n_ports
    if len(numbers) % stride:
        raise TouchstoneError(
            f"{path.name}: {len(numbers)} numbers is not a multiple of "
            f"{stride} (1 freq + {n_ports*n_ports} complex entries)"
        )

    rows = np.asarray(numbers, dtype=float).reshape(-1, stride)
    if not np.all(np.isfinite(rows)):
        bad = int(np.count_nonzero(~np.isfinite(rows)))
        raise TouchstoneError(
            f"{path.name}: {bad} non-finite value(s) (NaN/Inf). Refusing to parse -- "
            "a physics verdict computed on NaN is not a verdict."
        )

    freq = rows[:, 0] * freq_mult
    if np.any(np.diff(freq) <= 0):
        raise TouchstoneError(f"{path.name}: frequencies are not strictly increasing")

    pairs = rows[:, 1:].reshape(len(rows), n_ports * n_ports, 2)
    s = np.empty((len(rows), n_ports, n_ports), dtype=complex)
    for fi in range(len(rows)):
        flat = np.array(
            [_to_complex(a, b, fmt) for a, b in pairs[fi]], dtype=complex
        )
        if n_ports == 2:
            s[fi] = _reorder_2port(flat)
        else:
            s[fi] = flat.reshape(n_ports, n_ports)

    return Network(freq_hz=freq, s=s, z0=z0, path=str(path))
