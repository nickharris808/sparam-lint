"""Test suite for sparam-lint.

The load-bearing tests are the negative-control ones: they assert that each law
*rejects* a deliberate violation. A suite that only checks the happy path
cannot distinguish a working checker from one that always says PASS.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sparam_lint import (  # noqa: E402
    TouchstoneError,
    check_energy_conservation,
    check_group_delay_nonneg,
    check_passivity,
    check_positive_real_z0,
    check_reciprocity,
    make_passive_line,
    read_touchstone,
    run_battery,
    run_negative_control,
)
from sparam_lint.cli import main as cli_main  # noqa: E402
from sparam_lint.control import VIOLATORS  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


# ---------------------------------------------------------------- positive path

def test_passive_line_passes_all_five_laws():
    s, freq = make_passive_line()
    results = run_battery(s, freq, 50.0)
    assert len(results) == 5
    failed = [r.name for r in results if not r.passed]
    assert not failed, f"passive line should satisfy every law, failed: {failed}"


def test_passive_line_sigma_max_below_one():
    s, freq = make_passive_line()
    r = check_passivity(s, freq)
    assert r.passed
    assert r.worst_value <= 1.0


# ------------------------------------------------------- negative control (key)

@pytest.mark.parametrize("law", sorted(VIOLATORS))
def test_each_law_rejects_its_own_violator(law):
    """The load-bearing test: break one law, that law must catch it."""
    s, freq = make_passive_line()
    make_bad, check = VIOLATORS[law]
    s_bad, f_bad = make_bad(s, freq)
    res = check(s_bad, f_bad)
    assert not res.passed, f"{law} failed to reject a deliberate violation"


def test_negative_control_reports_discriminating():
    report = run_negative_control()
    assert report["positive_control_all_pass"] is True
    assert report["negative_control_all_rejected"] is True
    assert report["battery_discriminates"] is True


def test_reciprocity_violator_does_not_trip_passivity():
    """A fault should isolate its own law where physics permits."""
    s, freq = make_passive_line()
    s_bad, _ = VIOLATORS["reciprocity"][0](s, freq)
    assert not check_reciprocity(s_bad, freq).passed
    assert check_passivity(s_bad, freq).passed


def test_group_delay_uses_unwrapped_phase():
    """A long delay wraps phase many times; without unwrap this reports
    spurious negative group delay."""
    s, freq = make_passive_line(n_freq=128, f_start=1e9, f_stop=100e9,
                                delay_s=200e-12)
    assert check_group_delay_nonneg(s, freq).passed


def test_group_delay_skips_short_grids():
    s, freq = make_passive_line(n_freq=2)
    r = check_group_delay_nonneg(s, freq)
    assert r.passed and r.detail.get("skipped") is True


def test_energy_check_catches_row_power():
    s, freq = make_passive_line()
    s_bad, _ = VIOLATORS["energy_conservation"][0](s, freq)
    assert not check_energy_conservation(s_bad, freq).passed


def test_positive_real_catches_negative_resistance():
    s, freq = make_passive_line()
    s_bad, _ = VIOLATORS["positive_real_z0"][0](s, freq)
    assert not check_positive_real_z0(s_bad, freq, 50.0).passed


# ------------------------------------------------------------------- touchstone

def test_roundtrip_example_files_exist_and_parse():
    for name in ("passive_line.s2p", "active_gain.s2p"):
        net = read_touchstone(EXAMPLES / name)
        assert net.n_ports == 2
        assert net.n_freq == 64
        assert net.z0 == 50.0
        assert np.all(np.diff(net.freq_hz) > 0)


def test_two_port_column_major_order_is_honoured(tmp_path):
    """Touchstone 2-port is S11 S21 S12 S22. A row-major reader silently
    transposes, which would make an asymmetric network look reciprocal."""
    p = tmp_path / "asym.s2p"
    p.write_text(
        "# HZ S RI R 50\n"
        # S11=0.1  S21=0.7  S12=0.2  S22=0.3
        "1e9 0.1 0 0.7 0 0.2 0 0.3 0\n"
    )
    net = read_touchstone(p)
    assert net.s[0, 0, 0] == pytest.approx(0.1)
    assert net.s[0, 1, 0] == pytest.approx(0.7), "S21 must land at [1,0]"
    assert net.s[0, 0, 1] == pytest.approx(0.2), "S12 must land at [0,1]"
    assert net.s[0, 1, 1] == pytest.approx(0.3)


def test_three_port_is_row_major(tmp_path):
    """N>=3 is row-major (S11 S12 S13 S21 ...), unlike the 2-port special case.
    Getting this backwards would transpose every multi-port file."""
    p = tmp_path / "t.s3p"
    vals = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    p.write_text("# HZ S RI R 50\n1e9 " + " ".join(f"{v} 0" for v in vals) + "\n")
    net = read_touchstone(p)
    assert net.n_ports == 3
    assert np.allclose(np.real(net.s[0]), np.array(vals).reshape(3, 3))


def test_four_port_battery_runs(tmp_path):
    """The laws must work at N>2, not just on the bundled 2-port examples."""
    rng = np.random.default_rng(0)
    n_f, n_p = 8, 4
    freq = np.linspace(1e9, 10e9, n_f)
    lines = ["# HZ S RI R 50"]
    for f in freq:
        a = rng.normal(size=(n_p, n_p)) * 0.1
        s = (a + a.T) / 2.0          # symmetric -> reciprocal
        s = s / max(np.linalg.svd(s, compute_uv=False)[0] * 1.2, 1.0)  # passive
        flat = " ".join(f"{v:.10g} 0" for v in s.reshape(-1))
        lines.append(f"{f:.10g} {flat}")
    p = tmp_path / "q.s4p"
    p.write_text("\n".join(lines) + "\n")

    net = read_touchstone(p)
    assert net.n_ports == 4
    results = run_battery(net.s, net.freq_hz, net.z0)
    assert len(results) == 5
    by = {r.name: r for r in results}
    assert by["passivity"].passed
    assert by["reciprocity"].passed


def test_nan_is_refused_not_propagated(tmp_path):
    p = tmp_path / "nan.s2p"
    p.write_text("# HZ S RI R 50\n1e9 nan 0 0.5 0 0.5 0 0.1 0\n")
    with pytest.raises(TouchstoneError, match="non-finite"):
        read_touchstone(p)


def test_non_monotonic_frequency_refused(tmp_path):
    p = tmp_path / "back.s2p"
    p.write_text("# HZ S RI R 50\n"
                 "2e9 0.1 0 0.5 0 0.5 0 0.1 0\n"
                 "1e9 0.1 0 0.5 0 0.5 0 0.1 0\n")
    with pytest.raises(TouchstoneError, match="increasing"):
        read_touchstone(p)


def test_truncated_row_refused(tmp_path):
    p = tmp_path / "short.s2p"
    p.write_text("# HZ S RI R 50\n1e9 0.1 0 0.5 0\n")
    with pytest.raises(TouchstoneError, match="multiple"):
        read_touchstone(p)


def test_magnitude_angle_format(tmp_path):
    p = tmp_path / "ma.s2p"
    p.write_text("# GHZ S MA R 50\n1 0.5 90 0.5 0 0.5 0 0.5 0\n")
    net = read_touchstone(p)
    assert net.freq_hz[0] == pytest.approx(1e9)
    assert net.s[0, 0, 0].imag == pytest.approx(0.5, abs=1e-12)


def test_db_format(tmp_path):
    p = tmp_path / "db.s2p"
    p.write_text("# HZ S DB R 50\n1e9 -6.0206 0 0.5 0 0.5 0 0.5 0\n")
    net = read_touchstone(p)
    assert abs(net.s[0, 0, 0]) == pytest.approx(0.5, rel=1e-4)


def test_missing_file_refused():
    with pytest.raises(TouchstoneError, match="no such file"):
        read_touchstone("/definitely/not/here.s2p")


# -------------------------------------------------------------------------- cli

def test_cli_exit_zero_on_passive(capsys):
    rc = cli_main([str(EXAMPLES / "passive_line.s2p"), "--no-colour"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "all 5 laws passed" in out


def test_cli_exit_one_on_active(capsys):
    rc = cli_main([str(EXAMPLES / "active_gain.s2p"), "--no-colour"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out and "passivity" in out


def test_cli_json_is_valid_and_complete(capsys):
    rc = cli_main([str(EXAMPLES / "active_gain.s2p"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False
    assert len(payload["laws"]) == 5
    assert {law["law"] for law in payload["laws"]} == {
        "passivity", "reciprocity", "energy_conservation",
        "positive_real_z0", "group_delay_nonneg",
    }


def test_cli_exit_two_on_unparseable(tmp_path, capsys):
    bad = tmp_path / "bad.s2p"
    bad.write_text("# HZ S RI R 50\n1e9 nan 0 0.5 0 0.5 0 0.1 0\n")
    rc = cli_main([str(bad), "--json"])
    assert rc == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_cli_self_test_exit_zero(capsys):
    rc = cli_main(["--self-test", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert report["battery_discriminates"] is True


def test_installed_entrypoint_runs():
    """The console script must work, not just the module."""
    r = subprocess.run(
        [sys.executable, "-m", "sparam_lint.cli", "--self-test", "--json"],
        capture_output=True, text=True,
        env={**os.environ,
             # Inherit the OS environment and override only PYTHONPATH.
             # A scrubbed env is not portable: on Windows, Python needs
             # SYSTEMROOT to seed its hash randomisation and aborts
             # without it.
             "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["battery_discriminates"] is True


# ----------------------------------------------------------- packaging boundary

def test_package_imports_nothing_private():
    """This package must never import from a private source tree."""
    root = Path(__file__).resolve().parents[1] / "src"
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for forbidden in ("import genesis", "from genesis", "provisionals"):
            assert forbidden not in text, f"{py.name} references private tree: {forbidden}"


# ------------------------------------------- every shipped install must work

_REPO = Path(__file__).resolve().parents[1]


def test_no_install_command_points_at_a_path_a_stranger_will_not_have():
    """READMEs get copy-pasted, so a local path in one is a broken command.

    `pip install ./sparam-lint` works in the development tree and fails for
    everyone else with "File './sparam-lint' does not exist". Every install
    line here has to resolve for someone who cloned only this repository.
    """
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    offenders = []
    for i, line in enumerate(readme.splitlines(), 1):
        if "pip install" not in line:
            continue
        for tok in line.split():
            tok = tok.strip("`\"',")
            if tok.startswith(("./", "../")) and not (_REPO / tok).exists():
                offenders.append("line %d: %s" % (i, tok))
    assert not offenders, (
        "install commands reference paths absent from a fresh clone: "
        + "; ".join(offenders)
    )


def test_pypi_install_lines_are_labelled_as_not_yet_available():
    """The package name 404s on PyPI today. Saying so is the whole fix."""
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    if "pip install sparam-lint" in readme:
        assert "Not yet on PyPI" in readme, (
            "README shows `pip install sparam-lint` without saying the name "
            "is not published yet"
        )


# ------------------------------------------ the documentation must stay true

def test_readme_cli_reference_lists_every_real_flag_and_no_invented_one():
    """A reference that drifts from argparse is worse than no reference."""
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    table = readme.split("## CLI reference", 1)[1].split("## Library use", 1)[0]

    import sparam_lint.cli as cli
    src = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
    flags = set(re.findall(r'p\.add_argument\("(--[a-z-]+)"', src))
    assert flags, "no flags found -- this guard has stopped looking"
    for flag in flags:
        assert flag in table, f"{flag} exists but the CLI reference omits it"
    for documented in set(re.findall(r"`(--[a-z-]+)`", table)):
        assert documented in flags, f"CLI reference documents {documented}, which does not exist"


def test_readme_documents_the_real_exit_codes():
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    table = readme.split("**Exit codes**", 1)[1].split("`2` outranks", 1)[0]
    for code in ("`0`", "`1`", "`2`", "`3`"):
        assert code in table, f"exit code {code} is undocumented"


def test_readme_api_table_names_only_real_attributes():
    """Every attribute the Library-use table promises must exist."""
    from sparam_lint import read_touchstone, run_battery, run_negative_control
    net = read_touchstone(EXAMPLES / "passive_line.s2p")
    for attr in ("freq_hz", "s", "z0", "n_ports", "n_freq", "path"):
        assert hasattr(net, attr), f"README promises Network.{attr}"
    law = run_battery(net.s, net.freq_hz, net.z0)[0]
    for attr in ("name", "passed", "message", "detail", "as_dict"):
        assert hasattr(law, attr), f"README promises LawResult.{attr}"
    # The README says the dict key is `law`, not `name`. It said `name` once.
    assert "law" in law.as_dict() and "name" not in law.as_dict()
    for key in ("worst_value", "worst_freq_hz"):
        assert key in law.as_dict(), f"README promises as_dict()[{key!r}]"
    nc = run_negative_control()
    for key in ("battery_discriminates", "negative_control", "positive_control",
                "negative_control_all_rejected", "positive_control_all_pass"):
        assert key in nc, f"README promises run_negative_control()[{key!r}]"


def test_readme_passivity_tolerance_matches_the_code():
    from sparam_lint.laws import PASSIVITY_TOL
    readme = (_REPO / "README.md").read_text(encoding="utf-8")
    # 1e-09 and 1e-9 are the same number written two ways; accept either
    # spelling, reject a different number.
    spellings = {f"1 + {PASSIVITY_TOL:g}", f"1 + {PASSIVITY_TOL:.0e}".replace("e-09", "e-9")}
    assert any(sp in readme for sp in spellings), (
        f"README quotes a passivity tolerance that is not {PASSIVITY_TOL:g}"
    )


def test_worked_example_transcript_is_real_output():
    """The tutorial pastes two transcripts. Both must be what the code prints."""
    readme = (_REPO / "README.md").read_text(encoding="utf-8")

    for cmd, argv in [
        ("$ sparam-lint --self-test\n", ["--self-test"]),
        # Pass POSIX-style paths: the README documents a shell glob, and the
        # tool echoes back whatever it was given. On Windows relative_to()
        # would yield backslashes and the comparison would fail on a separator
        # rather than on anything about the physics.
        ("$ sparam-lint --quiet examples/*.s2p\n", ["--quiet"] + sorted(
            p.relative_to(_REPO).as_posix() for p in (_REPO / "examples").glob("*.s2p"))),
    ]:
        documented = readme.split(cmd, 1)[1].split("```", 1)[0].strip()
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            cli_main(argv)
        finally:
            sys.stdout = old
        assert buf.getvalue().strip() == documented, (
            f"transcript for `{cmd.strip()}` no longer matches the code"
        )


def test_report_echoes_the_path_as_given_not_reserialized():
    """A report should quote the argument, not a re-rendered version of it.

    Path() round-trips through the OS separator, so on Windows a user who typed
    `examples/x.s2p` was shown `examples\\x.s2p` -- and the JSON `file` field
    was likewise not the string they passed.
    """
    given = "./examples/passive_line.s2p"
    buf = io.StringIO()
    old, sys.stdout = sys.stdout, buf
    try:
        cli_main([given, "--json"])
    finally:
        sys.stdout = old
    assert json.loads(buf.getvalue())["file"] == given
