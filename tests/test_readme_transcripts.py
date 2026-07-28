"""Every transcript in the README, executed and diffed against the card.

A README is a promise that the thing shown is the thing that happens. That
promise decays silently: a JSON key gets renamed, a message reworded, a number
recomputed, and the card keeps claiming the old one. Nothing in a normal test
suite notices, because the suite tests the code and the card is prose.

This file closed two real defects on its first run:

* the ``--json`` snippet indexed ``law["name"]``. The key is ``law["law"]``, so
  the example a reader copies raised ``KeyError`` -- a documented command that
  cannot work at all;
* the transcripts had to be re-verified against the current conclusion wording
  after a network failing only reciprocity stopped being called unrealizable.

The guard runs the CLI as a subprocess, exactly as a reader would.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
README = HERE / "README.md"
EXAMPLES = HERE / "examples"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI the way the card shows it, from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "sparam_lint.cli", *args],
        cwd=HERE, capture_output=True, text=True, encoding="utf-8",
        # PYTHONIOENCODING is pinned because the card shows the UTF-8 output.
        # On a narrow console the tool degrades the ohm sign to " ohm" on
        # purpose -- that path is covered by tests/test_console_encoding.py,
        # and comparing it against a card written in UTF-8 would be comparing
        # two different, both-correct renderings.
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(HERE / "src"),
             "HOME": str(HERE), "COLUMNS": "200", "PYTHONIOENCODING": "utf-8"},
    )


def _quoted_block_after(marker: str) -> list[str]:
    """The output lines of the fenced block whose command line is `marker`."""
    body = _readme()
    m = re.search(r"```[a-z]*\n\$ " + re.escape(marker) + r"\n(.*?)```", body, re.S)
    assert m, f"no transcript block for `$ {marker}` in the README"
    return [ln.rstrip() for ln in m.group(1).splitlines()]


def _flat(text: str) -> str:
    """Collapse runs of whitespace to single spaces.

    The card hand-wraps the longest law messages across two lines with a
    hanging indent; the tool prints them on one. That is a typesetting choice
    and not a claim about output, so the comparison is on content with
    whitespace normalised -- but every *word*, number and unit must match.
    """
    return " ".join(text.split())


@pytest.mark.parametrize("case", ["passive_line", "active_gain"])
def test_the_single_file_transcripts_match(case: str) -> None:
    r = _cli(f"examples/{case}.s2p")
    live = _flat(r.stdout)
    for line in _quoted_block_after(f"sparam-lint examples/{case}.s2p"):
        if not line.strip() or line.startswith("$ ") or line.strip().isdigit():
            continue  # the `$ echo $?` / `1` pair is covered by the exit-code test
        assert _flat(line) in live, (
            f"README quotes a line the code no longer prints:\n  {line!r}"
        )


def test_the_documented_exit_code_is_the_real_one() -> None:
    """`$ echo $?` -> `1` on the failing example."""
    assert _cli("examples/active_gain.s2p").returncode == 1
    assert _cli("examples/passive_line.s2p").returncode == 0


def test_the_json_snippet_on_the_card_runs_and_prints_what_the_card_says() -> None:
    """The defect this file was written for: the snippet used a key that does
    not exist, so anyone copying it got a KeyError."""
    r = _cli("--json", "examples/active_gain.s2p", "examples/passive_line.s2p")
    json.loads(r.stdout)  # it must be valid JSON before anything is piped it

    snippet = re.search(
        r"```[a-z]*\n\$ sparam-lint --json examples/\*\.s2p \| python3 -c '\n(.*?)'\n(.*?)```",
        _readme(), re.S,
    )
    assert snippet, "the README's --json example is no longer in the shape this guards"
    code, expected = snippet.group(1), snippet.group(2)

    # Run it exactly as the card does: `python3 -c '<code>'` with the report on
    # stdin. Executing it in-process would let the snippet's own `import sys`
    # shadow any stub and would not prove the pipeline works.
    piped = subprocess.run([sys.executable, "-c", code], input=r.stdout,
                           capture_output=True, text=True, encoding="utf-8")
    assert piped.returncode == 0, (
        "the README's --json snippet does not run:\n" + piped.stderr
    )
    got = [ln for ln in piped.stdout.splitlines() if ln.strip()]
    want = [ln for ln in expected.splitlines() if ln.strip()]
    assert got == want, f"snippet prints {got}, card says {want}"


def test_the_self_test_transcript_matches() -> None:
    r = _cli("--self-test")
    assert r.returncode == 0, r.stdout + r.stderr
    for line in _quoted_block_after("sparam-lint --self-test"):
        if line.strip():
            assert line.rstrip() in r.stdout, f"card line not printed: {line!r}"


def test_the_quiet_summary_line_matches() -> None:
    files = sorted(str(p.relative_to(HERE)) for p in EXAMPLES.glob("*.s2p"))
    r = _cli("--quiet", *files)
    tail = r.stdout.strip().splitlines()[-1].rstrip()
    assert tail in _readme(), f"card's summary line is stale; live is {tail!r}"


def test_every_documented_json_key_exists_in_the_output() -> None:
    """A blunt backstop for the whole class.

    Any ``x["key"]`` the README indexes into a law object must be a key the
    tool emits. This is what would have caught ``law["name"]`` even if the
    snippet had never been run.
    """
    r = _cli("--json", "examples/active_gain.s2p")
    laws = json.loads(r.stdout)["laws"]
    emitted = set(laws[0])
    indexed = set(re.findall(r'law\["([a-z_]+)"\]', _readme()))
    assert indexed, "no law-key indexing found in the README; did its shape change?"
    assert indexed <= emitted, (
        f"README indexes law key(s) the tool never emits: {sorted(indexed - emitted)}; "
        f"emitted keys are {sorted(emitted)}"
    )
