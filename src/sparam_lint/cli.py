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
    p.add_argument("paths", nargs="*", metavar="FILE",
                   help="Touchstone .sNp file(s); a shell glob works")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--self-test", action="store_true",
                   help="run the negative control and exit (proves the checker discriminates)")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="with several files, print only the ones with violations")
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

    if not args.paths:
        p.error("a Touchstone file is required (or use --self-test)")

    use_colour = not args.no_colour and sys.stdout.isatty()
    reports, worst = [], 0

    for path in args.paths:
        try:
            net = read_touchstone(Path(path))
        except TouchstoneError as exc:
            # Exit 2 outranks exit 1: "I could not check this" is a worse
            # answer than "I checked it and it failed", so it wins the code.
            worst = 2
            reports.append({"file": str(path), "error": str(exc), "passed": False})
            if not args.json:
                print(f"error: {exc}", file=sys.stderr)
            continue

        results = run_battery(net.s, net.freq_hz, net.z0)
        failed = any(not r.passed for r in results)
        if failed and worst < 1:
            worst = 1
        # Quote the argument as given. Path() round-trips through the OS
        # separator, so `examples/x.s2p` would come back as `examples\x.s2p`
        # on Windows -- a report should echo what the user typed.
        as_given = str(path)
        reports.append({
            "file": as_given,
            "n_ports": net.n_ports,
            "n_freq": net.n_freq,
            "z0_ohm": net.z0,
            "passed": not failed,
            "laws": [r.as_dict() for r in results],
        })
        if not args.json and not (args.quiet and not failed):
            if len(args.paths) > 1:
                print(_c(f"── {as_given}", BOLD, use_colour))
            print(_human(results, net, use_colour))
            if len(args.paths) > 1:
                print()

    if args.json:
        # One file keeps the flat object it has always emitted, so existing
        # parsers do not break; several files get an envelope. The presence of
        # "files" is how a consumer tells them apart.
        if len(args.paths) == 1:
            print(json.dumps(reports[0], indent=2))
        else:
            checked = [r for r in reports if "error" not in r]
            print(json.dumps({
                "files": reports,
                "summary": {
                    "n_files": len(reports),
                    "n_checked": len(checked),
                    "n_unreadable": len(reports) - len(checked),
                    "n_with_violations": sum(1 for r in checked if not r["passed"]),
                    "passed": worst == 0,
                },
            }, indent=2))
    elif len(args.paths) > 1:
        checked = [r for r in reports if "error" not in r]
        bad = sum(1 for r in checked if not r["passed"])
        unread = len(reports) - len(checked)
        parts = [f"{len(reports)} file(s)", f"{bad} with violations"]
        if unread:
            parts.append(f"{unread} unreadable")
        line = "  " + ", ".join(parts)
        print(_c(line, (RED + BOLD) if worst else (GREEN + BOLD), use_colour))

    return worst


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
