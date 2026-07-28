# sparam-lint

![CI](https://github.com/nickharris808/sparam-lint/actions/workflows/ci.yml/badge.svg) ![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue) ![Licence](https://img.shields.io/badge/licence-Apache--2.0-green) ![Tests](https://img.shields.io/badge/tests-30%20passing-brightgreen)

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
- run: pip install ./sparam-lint        # or `pip install sparam-lint` once published
- run: sparam-lint --self-test          # prove the checker works
- run: sparam-lint models/*.s2p --json  # then check the models
```

Running `--self-test` *before* the models is the recommended order: a clean
report from a checker you have not verified is worth nothing.

## Library use

```python
from sparam_lint import read_touchstone, run_battery

net = read_touchstone("my_model.s2p")
for law in run_battery(net.s, net.freq_hz, net.z0):
    print(law.name, law.passed, law.message)
```

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
