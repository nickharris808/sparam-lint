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
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["Network", "read_touchstone", "TouchstoneError"]

_FREQ_MULT = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}



def _glyphs() -> tuple[str, str]:
    """The ohm sign and the rule, degraded when stdout cannot encode them.

    A Windows console defaults to cp1252, which has no U+03A9. Printing it
    there raised ``UnicodeEncodeError`` *after* the physics had already run, so
    the process died with exit 1 and no output -- indistinguishable, to a caller
    reading only the exit code, from "a law failed". A crash that looks like a
    verdict is precisely the failure this checker exists to prevent, so the
    glyphs degrade to ASCII rather than the run dying.
    """
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "\u03a9\u2500\u2500".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return " ohm", "--"
    return "\u03a9", "\u2500\u2500"


OHM, RULE = _glyphs()


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
            f"{self.freq_hz[0]/1e9:.4g}-{self.freq_hz[-1]/1e9:.4g} GHz, z0={self.z0}{OHM})"
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
    """Scalar conversion. Kept as the reference the array form is tested against."""
    if fmt == "ri":
        return complex(a, b)
    if fmt == "ma":
        return cmath.rect(a, math.radians(b))
    if fmt == "db":
        return cmath.rect(10.0 ** (a / 20.0), math.radians(b))
    raise TouchstoneError(f"unknown format {fmt!r}")  # pragma: no cover


def _to_complex_array(a: np.ndarray, b: np.ndarray, fmt: str) -> np.ndarray:
    """Vectorized :func:`_to_complex` over whole arrays.

    A 16-port sweep has one entry per port pair per frequency -- 256,256 of
    them for 1001 points -- and calling the scalar form once each dominated
    parsing. These are the same three formulae applied elementwise.

    Not bit-identical to the scalar form for MA/DB, because ``exp(1j*theta)``
    and ``cmath.rect`` order their floating-point operations differently; they
    agree to ~1e-16 relative, which ``test_vectorized_conversion_matches_the_
    scalar_form`` pins.
    """
    if fmt == "ri":
        return a + 1j * b
    if fmt in ("ma", "db"):
        mag = a if fmt == "ma" else 10.0 ** (a / 20.0)
        return mag * np.exp(1j * np.radians(b))
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
        near = sorted(p.name for p in path.parent.glob(path.stem + ".*")) \
            if path.parent.exists() else []
        hint = f" -- did you mean {near[0]}?" if near else ""
        raise TouchstoneError(f"no such file: {path}{hint}")
    if not path.is_file():
        # A directory named model.s2p, a device node, a broken symlink target.
        # Opening it raises IsADirectoryError or OSError, neither of which is a
        # TouchstoneError, so the traceback escapes and kills a whole batch run
        # instead of marking one path unreadable.
        kind = "a directory" if path.is_dir() else "not a regular file"
        raise TouchstoneError(f"{path} is {kind}, not a Touchstone file")

    m = re.search(r"\.s(\d+)p$", path.name, re.IGNORECASE)
    n_ports = int(m.group(1)) if m else 0

    freq_mult, param, fmt, z0 = 1e9, "s", "ma", 50.0
    saw_option = False
    first_row_width: int | None = None
    tokens: list[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as fh:
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
            toks = line.replace(",", " ").split()
            if first_row_width is None:
                first_row_width = len(toks)
            tokens.extend(toks)

    # Convert the whole sweep in one call rather than once per token: a
    # 32-port x 2001-point file is 4.1M tokens, and `float()` per token was
    # 98% of parse time once the complex conversion was vectorized. numpy does
    # the same conversion in C. The slow, precise error path only runs when the
    # fast one has already told us something is wrong.
    try:
        numbers = np.asarray(tokens, dtype=float)
    except ValueError as exc:
        for tok in tokens:
            try:
                float(tok)
            except ValueError:
                raise TouchstoneError(
                    f"non-numeric token {tok!r} in {path.name}"
                ) from exc
        raise TouchstoneError(f"{path.name}: could not read the data ({exc})") from exc

    if numbers.size == 0:
        raise TouchstoneError(
            f"{path.name}: no data rows -- the file has an option line or comments "
            "but no numbers. Check it is not truncated or an empty export."
        )
    if param != "s":
        raise TouchstoneError(
            f"{path.name}: only S-parameter files supported, got {param.upper()}. "
            f"The option line declares '{param.upper()}'; re-export as S-parameters, "
            "or convert with scikit-rf before checking."
        )

    if n_ports == 0:
        raise TouchstoneError(
            f"cannot infer port count from filename {path.name!r} -- Touchstone "
            "encodes it in the extension. Rename to .s2p for a 2-port, .s4p for "
            "a 4-port, and so on."
        )

    stride = 1 + 2 * n_ports * n_ports
    if numbers.size % stride:
        # Almost always a file whose extension disagrees with its contents --
        # a 4-port export saved as .s2p. Say which extension would fit, since
        # that is the fix rather than a fact about arithmetic.
        # The width of the first data line is the strongest evidence: one row
        # is 1 frequency + 2 numbers per S entry, so it pins the port count
        # outright. Fall back to divisibility only when rows are wrapped.
        fits = [n for n in range(1, 33)
                if 1 + 2 * n * n == first_row_width and n != n_ports] or \
               [n for n in range(1, 33)
                if numbers.size % (1 + 2 * n * n) == 0 and n != n_ports]
        hint = (f" The rows are the right width for a {fits[0]}-port file -- is "
                f"this really a .s{n_ports}p, or should it be .s{fits[0]}p?"
                ) if fits else ""
        raise TouchstoneError(
            f"{path.name}: {numbers.size} numbers is not a multiple of "
            f"{stride} (1 freq + {n_ports*n_ports} complex entries)."
            + hint
        )

    rows = numbers.reshape(-1, stride)
    if not np.all(np.isfinite(rows)):
        bad = int(np.count_nonzero(~np.isfinite(rows)))
        raise TouchstoneError(
            f"{path.name}: {bad} non-finite value(s) (NaN/Inf). Refusing to parse -- "
            "a physics verdict computed on NaN is not a verdict."
        )

    freq = rows[:, 0] * freq_mult
    if np.any(np.diff(freq) <= 0):
        i = int(np.argmax(np.diff(freq) <= 0))
        what = "repeats" if freq[i + 1] == freq[i] else "goes backwards"
        raise TouchstoneError(
            f"{path.name}: frequencies are not strictly increasing -- row {i + 2} "
            f"{what} ({freq[i]/1e9:g} GHz then {freq[i+1]/1e9:g} GHz). Sort the "
            "rows by frequency and remove duplicates; group delay is a derivative "
            "and cannot be computed across an unordered sweep."
        )

    pairs = rows[:, 1:].reshape(len(rows), n_ports * n_ports, 2)
    flat = _to_complex_array(pairs[:, :, 0], pairs[:, :, 1], fmt)

    if n_ports == 2:
        # Touchstone 2-port order is S11 S21 S12 S22, i.e. column-major, while
        # 3-port and above are row-major. Reshaping to (F, 2, 2) and
        # transposing the last two axes is the same permutation the per-row
        # _reorder_2port did, applied to the whole sweep at once.
        s = flat.reshape(len(rows), 2, 2).transpose(0, 2, 1)
    else:
        s = flat.reshape(len(rows), n_ports, n_ports)

    return Network(freq_hz=freq, s=np.ascontiguousarray(s), z0=z0, path=str(path))
