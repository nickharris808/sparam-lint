"""Command-line interface.

Exit codes are the contract -- this is meant to live in CI:

    0  all laws passed
    1  at least one law failed
    2  the file could not be parsed / usage error
    3  the negative control failed (the checker itself is not discriminating)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .control import run_negative_control
from .laws import run_battery
from .touchstone import TouchstoneError, read_touchstone

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)


def _c(text: str, colour: str, use: bool) -> str:
    return f"{colour}{text}{RESET}" if use else text


def _human(results, net, use_colour: bool) -> str:
    lines = [
        f"{_c('sparam-lint', BOLD, use_colour)} {net.n_ports}-port  "
        f"{net.n_freq} points  "
        f"{net.freq_hz[0]/1e9:.4g}-{net.freq_hz[-1]/1e9:.4g} GHz  z0={net.z0:g}Ω",
        "",
    ]
    for r in results:
        skipped = r.detail.get("skipped")
        if skipped:
            tag = _c("SKIP", YELLOW, use_colour)
        elif r.passed:
            tag = _c("PASS", GREEN, use_colour)
        else:
            tag = _c("FAIL", RED, use_colour)
        lines.append(f"  [{tag}] {r.name:<22} {r.message}")
    n_fail = sum(1 for r in results if not r.passed)
    lines.append("")
    if n_fail:
        lines.append(_c(f"  {n_fail} of {len(results)} laws FAILED", RED + BOLD, use_colour))
        lines.append(_c("  This network is not physically realizable as a passive device.",
                        DIM, use_colour))
    else:
        lines.append(_c(f"  all {len(results)} laws passed", GREEN + BOLD, use_colour))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sparam-lint",
        description="Check whether an S-parameter model is physically possible.",
    )
    p.add_argument("path", nargs="?", help="Touchstone .sNp file")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--self-test", action="store_true",
                   help="run the negative control and exit (proves the checker discriminates)")
    p.add_argument("--no-colour", action="store_true", help="disable ANSI colour")
    p.add_argument("--version", action="version", version=f"sparam-lint {__version__}")
    args = p.parse_args(argv)

    if args.self_test:
        report = run_negative_control()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            ok = report["battery_discriminates"]
            use = not args.no_colour and sys.stdout.isatty()
            print(_c("negative control", BOLD, use))
            for law, v in report["negative_control"].items():
                tag = _c("REJECTED", GREEN, use) if v["rejected"] else _c("MISSED", RED, use)
                print(f"  [{tag}] {law}")
            print()
            print(_c(f"  battery discriminates: {ok}", GREEN if ok else RED, use))
        return 0 if report["battery_discriminates"] else 3

    if not args.path:
        p.error("a Touchstone file is required (or use --self-test)")

    try:
        net = read_touchstone(Path(args.path))
    except TouchstoneError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "passed": False}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    results = run_battery(net.s, net.freq_hz, net.z0)
    failed = any(not r.passed for r in results)

    if args.json:
        print(json.dumps({
            "file": net.path,
            "n_ports": net.n_ports,
            "n_freq": net.n_freq,
            "z0_ohm": net.z0,
            "passed": not failed,
            "laws": [r.as_dict() for r in results],
        }, indent=2))
    else:
        print(_human(results, net, not args.no_colour and sys.stdout.isatty()))

    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
