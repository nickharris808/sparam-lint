# Contributing to sparam-lint

Thanks for looking. This project has one unusual rule, and it is the important one.

## Every new law needs a negative control

If you add a physical law, you must also add a **violator** to
`src/sparam_lint/control.py` — a network that deliberately breaks that law —
plus a test asserting the new check rejects it.

A check without a violator is untested in the only direction that matters. We
have no way to distinguish "this law passes because the network is good" from
"this law passes because the check is broken", and a battery that has stopped
discriminating looks exactly like a healthy one.

Where physics allows, make the violator break **exactly one** law. A fault that
trips three checks does not tell you which of the three is alive.

## Running the tests

```bash
pip install -e ".[dev]"
pytest -q
sparam-lint --self-test    # the negative control, as a user sees it
```

## Style

- numpy is the only runtime dependency. Please keep it that way.
- Prefer an explicit refusal to a silent default. If input is malformed, raise
  `TouchstoneError` with a message naming the file and the problem.
- Tolerances are floating-point slack, not physics slack. If you find yourself
  widening one to make a real network pass, the bug is elsewhere.

## Reporting a false verdict

A false PASS is far more serious than a false FAIL. If you have a network that
`sparam-lint` passes but that you know to be non-physical, please open an issue
with the file attached — that is the highest-value bug report this project can
receive.
