# Outcome And Oracle Discipline

For non-trivial implementation, state the business outcome, the independent
source of truth, constraints, invalid solution classes, negative controls,
positive controls, missing-data handling, and final outcome verification before
writing production code.

Tests must reject plausible bad implementations. A passing test suite is not
enough when the tests only repeat private helpers, constants, generated IDs, or
intermediate implementation details. Do not weaken an oracle to make a change
pass; fix the implementation or update the spec with an explicit decision.
