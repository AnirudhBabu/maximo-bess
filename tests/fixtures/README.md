# Test fixtures

There are no static fixture files here on purpose.

The site fixture is generated deterministically from `(seed, as_of)` by
`mxbess.seed.generate.generate_site`, and the defect fixture is derived from it by
`mxbess.seed.defects.inject_defects`. Tests assert that two runs are byte-identical, so a
checked-in snapshot would add nothing and would drift.

The unit tests also build a small hand-crafted site in `tests/support.py` (`tiny_dataset`)
for the "clean record / one defect" check tests. The stateful fake Maximo used by the
loader tests lives in the same file.
