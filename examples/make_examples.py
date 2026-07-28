"""Generate the worked-example Touchstone files shipped with sparam-lint.

Run:  python examples/make_examples.py
Writes passive_line.s2p (all laws pass) and active_gain.s2p (passivity and
energy fail -- a model that produces power from nothing).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sparam_lint.control import make_passive_line  # noqa: E402

HERE = Path(__file__).resolve().parent


def write_s2p(path: Path, freq: np.ndarray, s: np.ndarray, z0: float = 50.0,
              comment: str = "") -> None:
    lines = []
    if comment:
        for c in comment.strip().splitlines():
            lines.append(f"! {c}")
    lines.append("# HZ S RI R %g" % z0)
    for fi, f in enumerate(freq):
        m = s[fi]
        # Touchstone 2-port order: S11 S21 S12 S22
        vals = [m[0, 0], m[1, 0], m[0, 1], m[1, 1]]
        row = " ".join(f"{v.real:.12g} {v.imag:.12g}" for v in vals)
        lines.append(f"{f:.12g} {row}")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    s, freq = make_passive_line(n_freq=64, f_start=1e9, f_stop=40e9,
                                loss_db=0.5, delay_s=20e-12)
    write_s2p(HERE / "passive_line.s2p", freq, s,
              comment="Lossy 20 ps delay line, 0.5 dB insertion loss.\n"
                      "Physically realizable: all five laws pass.")

    bad = s.copy()
    bad[:, 0, 1] *= 3.0
    bad[:, 1, 0] *= 3.0
    write_s2p(HERE / "active_gain.s2p", freq, bad,
              comment="Same line with 3x through-path gain bolted on.\n"
                      "Not passive: sigma_max > 1. This is what a bad vendor\n"
                      "model or a mis-de-embedded measurement looks like.")

    print(f"wrote {HERE/'passive_line.s2p'}")
    print(f"wrote {HERE/'active_gain.s2p'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
