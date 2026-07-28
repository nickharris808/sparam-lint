# sparam-lint

![CI](https://github.com/nickharris808/sparam-lint/actions/workflows/ci.yml/badge.svg) ![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue) ![Licence](https://img.shields.io/badge/licence-Apache--2.0-green) ![Tests](https://img.shields.io/badge/tests-61%20passing-brightgreen)

📖 **[Documentation site](https://nickharris808.github.io/physics-lint/)** — the portfolio narrative, the concepts, a full walkthrough, and what all of this proves (and does not).

**Is your S-parameter model physically possible?**

Every RF and signal-integrity engineer has a folder of `.s2p` files from vendors,
simulators and measurements. Some of them describe networks that cannot exist —
they produce power from nothing, respond before they are excited, or present
negative resistance. Those files go into simulators, and the simulators believe
them.

`sparam-lint` checks five laws that every passive linear network must obey, in
about a second, from the command line.

```bash
# from source (works today)
pip install git+https://github.com/nickharris808/sparam-lint.git

sparam-lint my_model.s2p
```

> **Not yet on PyPI.** `pip install sparam-lint` is the intended install once published; until then use the source install above.

## 30-second quickstart

```bash
$ sparam-lint examples/passive_line.s2p
sparam-lint 2-port  64 points  1-40 GHz  z0=50Ω

  [PASS] passivity              largest singular value 0.994053225 <= 1
  [PASS] reciprocity            normalized asymmetry 0.000e+00 <= 1e-06
  [PASS] energy_conservation    worst row power 0.893750938 <= 1
  [PASS] positive_real_z0       minimum Re(Z_in) 55.2632 ohm > 0
  [PASS] group_delay_nonneg     minimum group delay 2.000000e-11 s >= 0

  all 5 laws passed
```

Now the same line with 3× gain bolted onto the through path:

```bash
$ sparam-lint examples/active_gain.s2p
  [FAIL] passivity              largest singular value 2.882175 > 1 at 25.1429 GHz --
                                this network produces more power than is put into it
  [FAIL] energy_conservation    worst row power 8.023758 > 1 at 18.9524 GHz --
                                driving one port yields more power out than in

  2 of 5 laws FAILED
  This network is not physically realizable as a passive device.

$ echo $?
1
```

## The five laws

| Law | Statement | Catches |
|---|---|---|
| **Passivity** | σ_max(S) ≤ 1 | Models that create energy |
| **Reciprocity** | S = Sᵀ | Transpose bugs, port-ordering errors, unintended non-reciprocity |
| **Energy conservation** | Σⱼ \|S_ij\|² ≤ 1 per driven port | Per-port violations a global norm averages away |
| **Positive-real Z₀** | Re(Z_in) > 0 | Negative resistance at a port |
| **Group delay ≥ 0** | −dφ/dω ≥ 0 | Non-causal models (output before input) |

## The part that makes it trustworthy

A physics checker that reports 100% compliance is **indistinguishable from one
that has quietly stopped working** — a tolerance widened until nothing fails, a
reshape that transposed the matrix, a phase unwrap that aliased.

So `sparam-lint` ships a **negative control**: it constructs networks that
deliberately violate each law and requires the corresponding check to reject
them. A clean report is therefore evidence, not assertion.

```bash
$ sparam-lint --self-test
negative control
  [REJECTED] passivity
  [REJECTED] reciprocity
  [REJECTED] energy_conservation
  [REJECTED] positive_real_z0
  [REJECTED] group_delay_nonneg

  battery discriminates: True
```

If any law fails to reject its own violator, the self-test exits **3** and you
should not trust that day's clean verdicts.

## Use in CI

Exit codes are the contract:

| Code | Meaning |
|---|---|
| `0` | all laws passed |
| `1` | at least one law failed |
| `2` | file could not be parsed |
| `3` | negative control failed — the checker itself is not discriminating |

```yaml
- run: pip install git+https://github.com/nickharris808/sparam-lint.git@main
- run: sparam-lint --self-test          # prove the checker works
- run: sparam-lint models/*.s2p --json  # then check the models
```

Paste that into your own workflow as-is — it installs from this repository, so
it needs nothing on a package index. Swap the first line for
`pip install sparam-lint` once the name is published.

Running `--self-test` *before* the models is the recommended order: a clean
report from a checker you have not verified is worth nothing.

## Use as a pre-commit hook

Three lines in `.pre-commit-config.yaml` and a non-physical model never reaches
the branch:

```yaml
repos:
  - repo: https://github.com/nickharris808/sparam-lint
    rev: main
    hooks:
      - id: sparam-lint            # checks the staged .sNp files
      - id: sparam-lint-self-test  # proves the checker still discriminates
```

The second hook has `always_run: true` on purpose. It costs about a second and
it runs even when no model changed, because a checker that has quietly stopped
discriminating looks exactly like a healthy one — and the commit where you would
most want to know is the one where nothing looks wrong.

## A worked example: triaging a folder of vendor models

You have been handed a directory of `.s2p` files and no provenance. Start by
proving the checker still works, then check everything at once, then look only
at what failed.

```bash
$ sparam-lint --self-test
negative control
  [REJECTED] passivity
  [REJECTED] reciprocity
  [REJECTED] energy_conservation
  [REJECTED] positive_real_z0
  [REJECTED] group_delay_nonneg

  battery discriminates: True
```

Five networks built to violate one law each, and each was rejected. Now the
models — one command, one exit code:

```bash
$ sparam-lint --quiet examples/*.s2p
── examples/active_gain.s2p
sparam-lint 2-port  64 points  1-40 GHz  z0=50Ω

  [FAIL] passivity              largest singular value 2.882175 > 1 at 25.1429 GHz -- this network produces more power than is put into it
  [PASS] reciprocity            normalized asymmetry 0.000e+00 <= 1e-06
  [FAIL] energy_conservation    worst row power 8.023758 > 1 at 18.9524 GHz -- driving one port yields more power out than in
  [PASS] positive_real_z0       minimum Re(Z_in) 55.2632 ohm > 0
  [PASS] group_delay_nonneg     minimum group delay 2.000000e-11 s >= 0

  2 of 5 laws FAILED
  This network is not physically realizable as a passive device.

  2 file(s), 1 with violations
```

`--quiet` printed only the file with violations; the clean one is accounted for
in the summary line. The exit code is `1`, so a CI step fails here without any
parsing of the output.

To act on it programmatically, take the JSON. Several files produce an envelope
with a `summary`; one file produces the flat object on its own:

```bash
$ sparam-lint --json examples/*.s2p | python3 -c '
import json,sys
d = json.load(sys.stdin)
for f in d["files"]:
    bad = [law["law"] for law in f.get("laws", []) if not law["passed"]]
    print(f["file"], "->", ", ".join(bad) or "clean")
'
examples/active_gain.s2p -> passivity, energy_conservation
examples/passive_line.s2p -> clean
```

**Now the judgement call.** Suppose one of those failures is
`reciprocity` on a ferrite isolator. That is a real, buyable component whose
medium is non-reciprocal, so `S ≠ Sᵀ` is correct behaviour — the check is a true
positive for the law and a false alarm for the device. The tool will not decide
that for you, and it should not: the right move is to record that
non-reciprocity is expected for that file, not to switch the law off for
everything. Turning the law off to quiet one isolator also goes blind to the
transposed-reshape bug it exists to catch.

## CLI reference

```
sparam-lint [FILE ...] [--json] [--quiet] [--self-test] [--no-colour] [--version]
```

| Argument | Meaning |
|---|---|
| `FILE ...` | One or more Touchstone files. A shell glob works: `models/*.s2p`. |
| `--json` | Machine-readable output. See the shapes below. |
| `--quiet`, `-q` | With several files, print only those with violations. The summary line still counts every file. |
| `--self-test` | Run the negative control and exit. Ignores `FILE`. |
| `--no-colour` | Disable ANSI colour. Colour is off automatically when stdout is not a TTY. |
| `--version` | Print the version. |

**Exit codes** — the contract, and the reason this survives in CI:

| Code | Meaning |
|---|---|
| `0` | every law passed on every file |
| `1` | at least one law failed |
| `2` | at least one file could not be parsed |
| `3` | the negative control failed — the checker itself is not discriminating |

`2` outranks `1` deliberately. "I could not check this" is a worse answer than
"I checked it and it failed", so it wins the exit code.

**JSON shapes.** One file emits the flat object, unchanged since the first
release so existing parsers keep working:

```json
{"file": "...", "n_ports": 2, "n_freq": 64, "z0_ohm": 50.0,
 "passed": true, "laws": [{"name": "passivity", "passed": true, ...}]}
```

Several files emit an envelope. The presence of `files` is how a consumer tells
them apart:

```json
{"files": [ ...one flat object per file... ],
 "summary": {"n_files": 2, "n_checked": 2, "n_unreadable": 0,
             "n_with_violations": 1, "passed": false}}
```

A file that could not be parsed appears in `files` as
`{"file": ..., "error": "...", "passed": false}` — it is never silently dropped.

## Library use

```python
from sparam_lint import read_touchstone, run_battery

net = read_touchstone("my_model.s2p")
for law in run_battery(net.s, net.freq_hz, net.z0):
    print(law.name, law.passed, law.message)
```

| Object | What it is |
|---|---|
| `read_touchstone(path) -> Network` | Parses `.sNp`. Raises `TouchstoneError` on anything malformed — it never returns a partly-read network. |
| `Network` | `.freq_hz` (F,), `.s` (F, N, N) complex, `.z0`, `.n_ports`, `.n_freq`, `.path` |
| `run_battery(s, freq_hz, z0) -> list[LawResult]` | The five laws over the whole band. |
| `LawResult` | `.name`, `.passed`, `.message`, `.detail` (dict), `.as_dict()` |
| `run_negative_control() -> dict` | Builds a violator per law and asserts each is rejected. `["battery_discriminates"]` is the verdict. |
| `TouchstoneError` | Subclass of `ValueError`. |

`as_dict()` carries the numbers behind the verdict — `worst_value` and
`worst_freq_hz`, plus `law`, `passed` and `message` — so you can threshold on
them yourself rather than parsing prose. Note the key is `law`, not `name`.

`.detail` is for the exceptions rather than the numbers: today only the
group-delay law populates it, with `{"skipped": True}` when the sweep has fewer
than three frequency points and a derivative cannot be taken. A skipped law is
reported as `SKIP`, never folded into the pass count.

`run_negative_control()` returns both directions —
`negative_control` (violators that must be rejected),
`positive_control` (a clean network that must pass), and the two roll-ups
`negative_control_all_rejected` / `positive_control_all_pass`. A law that stops
rejecting violators has gone blind; one that starts rejecting good networks has
gone hysterical, and only checking both catches the pair.

## Troubleshooting

**`cannot infer port count from filename 'model.txt'`** — Touchstone encodes the
port count in the extension, not in the file. Rename to `.s2p`, `.s4p`, and so on.

**`18 numbers is not a multiple of 33 … is this really a .s4p, or should it be
.s2p?`** — the commonest real failure: the extension disagrees with the
contents. The message names the port count the row width actually fits.

**`2 non-finite value(s) (NaN/Inf). Refusing to parse`** — the file contains
`NaN` or `Inf`, usually from a failed solve or a de-embedding step that divided
by zero. The tool refuses rather than reporting a verdict computed on `NaN`.
Fix the export; there is no flag to override this, on purpose.

**`frequencies are not strictly increasing -- row 42 repeats`** — sort the rows
by frequency and drop duplicates. Group delay is a derivative and cannot be
computed across an unordered sweep.

**`only S-parameter files supported, got Y`** — the option line declares
Y-parameters. Re-export as S, or convert with `scikit-rf` first.

**A lossless line fails passivity by a hair** — the battery allows σ_max up to
`1 + 1e-9` (`PASSIVITY_TOL`), which is floating-point slack, not physics slack.
A genuinely lossless line sits at σ_max = 1 and passes. If yours fails by more
than that margin, the excess is in the model, not in the arithmetic.

**Reciprocity fails on a device you know is real** — non-reciprocal media
(ferrites, isolators, circulators) violate reciprocity by design. See the worked
example above: record the expectation for that file rather than disabling the law.

**Exit code 2 in CI and no obvious error** — a glob matched nothing, or matched
a file that is not Touchstone. Print the glob before running it; `2` means "not
checked", never "fine".

## Two things this parser gets right

**Two-port column-major order.** Touchstone stores 2-port data as
`S11 S21 S12 S22`, while 3-port and above are row-major. A parser that assumes
row-major everywhere silently *transposes every 2-port file it reads*, which
turns a reciprocity check into a no-op. We handle it, and there is a test for it.

**Non-finite values are refused, not propagated.** A file containing `NaN` or
`Inf` raises rather than flowing into a physics check that would then return a
meaningless verdict.

## Scope, honestly

This tells you whether a model is **physically admissible**. It does not tell
you whether the model is *accurate* — a perfectly passive model of the wrong
structure passes every law here. Passivity is necessary, not sufficient.

The group-delay check evaluates the through path (S₂₁ for a 2-port). Networks
with fewer than three frequency points skip that law and say so rather than
guessing.

Files with three or more ports parse and check correctly (row-major, per the
Touchstone spec), and there are tests for it — but the bundled examples are
2-port, so N-port coverage is tested rather than demonstrated.

## Where the models that pass come from

`sparam-lint` grades a model that already exists. Producing one that is passive
*by construction* — so it cannot fail these laws whatever its parameters — is a
different problem, and it is the [ChipletOS](https://chipletos.com) closed core:
a scattering synthesis whose passivity and reciprocity hold exactly for any
parameter values, with no post-hoc repair step, behind a fail-closed signoff
certificate.

If this tool keeps failing your vendor models, that is the conversation to have.

## The rest of the toolkit

Eight artifacts that answer one question in different places: **is this
model physically possible?** Each is a grader — it can tell you a model is
wrong; none can tell you one is right.

| | |
|---|---|
| [`sparam-lint`](https://github.com/nickharris808/sparam-lint) ← you are here | Is an S-parameter model physically possible? Five laws + a negative control. |
| [`maxwell-lint`](https://github.com/nickharris808/maxwell-lint) | Does a coupling extractor predict impossible physics? Screening ceiling k ≤ 1. |
| [`abstain-bench`](https://github.com/nickharris808/abstain-bench) | Does a model know when to shut up? Abstention recall, never pooled with accuracy. |
| [`sparam-conformance`](https://huggingface.co/datasets/nickh007/sparam-conformance) | 11 labelled networks with verified ground truth. Grades the graders. |
| [`screening-ceiling`](https://huggingface.co/datasets/nickh007/screening-ceiling) | A certified impossibility result + 27 counterexamples. Zero-dependency verifier. |
| [`physics-lint-action`](https://github.com/nickharris808/physics-lint-action) | The same checks, in your CI. |
| [`physics-lint-mcp`](https://github.com/nickharris808/physics-lint-mcp) | A physics oracle your AI agent can call. |
| [**Try it in your browser**](https://huggingface.co/spaces/nickh007/physics-lint) | All three checks, no install, runs client-side. |

These tools **grade** a model. Producing one that is passive *by
construction* — so it cannot fail these laws whatever its parameters — and
accurate at speed in the many-body regime, with calibrated abstention and a
fail-closed signoff certificate, is the commercial core:
**[ChipletOS](https://chipletos.com)**.

## License

Apache-2.0. See [LICENSE](LICENSE); copyright is declared in [NOTICE](NOTICE).
