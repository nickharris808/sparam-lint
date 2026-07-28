"""The CLI must survive a console that cannot encode its glyphs.

Found by running the README transcripts as subprocesses during final
verification, which is the only way this surfaces: pytest's captured stdout is
UTF-8, so every in-process test passed while the shipped command died on a
default Windows console.

What actually happened there is the failure mode this whole portfolio argues
against. The physics ran, the verdict was computed, and then ``print`` raised
``UnicodeEncodeError`` on the ohm sign -- so the process exited non-zero with
no output. A caller reading only the exit code sees "1" and concludes a law
failed. A crash that is indistinguishable from a verdict is worse than a
crash that announces itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
EXAMPLES = HERE / "examples"

# cp1252 is the Windows default and has no U+03A9; ascii is the harsher case.
NARROW = ["cp1252", "ascii"]


def _run(args: list[str], encoding: str | None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(HERE / "src"))
    if encoding is None:
        env.pop("PYTHONIOENCODING", None)
    else:
        env["PYTHONIOENCODING"] = encoding
    # `text=True` alone decodes with the PARENT's locale encoding, which on a
    # Windows runner is cp1252 -- so a child writing UTF-8 came back as mojibake
    # and the test failed for a reason that had nothing to do with the tool.
    # Decode with exactly what the child was told to write.
    return subprocess.run([sys.executable, "-m", "sparam_lint.cli", *args],
                          cwd=HERE, capture_output=True, text=True, env=env,
                          encoding=encoding or "utf-8")


@pytest.mark.parametrize("encoding", NARROW)
def test_a_clean_file_still_exits_0_on_a_narrow_console(encoding: str) -> None:
    r = _run(["examples/passive_line.s2p"], encoding)
    assert "UnicodeEncodeError" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    assert "all 5 laws passed" in r.stdout


@pytest.mark.parametrize("encoding", NARROW)
def test_a_failing_file_still_exits_1_on_a_narrow_console(encoding: str) -> None:
    r = _run(["examples/active_gain.s2p"], encoding)
    assert "UnicodeEncodeError" not in r.stderr, r.stderr
    assert r.returncode == 1
    assert "laws FAILED" in r.stdout


@pytest.mark.parametrize("encoding", NARROW)
def test_the_output_is_encodable_by_the_console_it_was_written_for(
    encoding: str,
) -> None:
    """Not just "did not crash" -- every byte must actually be representable."""
    r = _run(["--quiet", *sorted(str(p.relative_to(HERE)) for p in EXAMPLES.glob("*.s2p"))],
             encoding)
    assert r.returncode in (0, 1)
    r.stdout.encode(encoding)  # raises if we emitted something unrepresentable


def test_the_numbers_are_identical_whatever_the_console_can_encode() -> None:
    """Degrading a glyph must not change a single measured value."""
    import json

    wide = json.loads(_run(["--json", "examples/active_gain.s2p"], "utf-8").stdout)
    narrow = json.loads(_run(["--json", "examples/active_gain.s2p"], "cp1252").stdout)
    assert wide == narrow


def test_the_ohm_glyph_is_the_real_one_when_the_console_can_take_it() -> None:
    r = _run(["examples/passive_line.s2p"], "utf-8")
    assert "z0=50Ω" in r.stdout, "the UTF-8 path should still print the ohm sign"
