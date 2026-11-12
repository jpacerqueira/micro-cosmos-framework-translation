---
name: cartographer-fixture-must-travel-with-test
description: A Cartographer regression test ported from beyond-alchemy without its estate (examples/AxonFramework_AxonBank) fails with assert 1 >= 20; the local java-axonframework-example-app is a different codebase and cannot stand in (2026-09-16)
metadata:
  type: project
---

`tests/test_cartographer_classification.py::test_axonbank_java_layer_split_stays_under_concentration_limit`
arrived in the 2026-09-11 port (`e887e96`) but **its fixture estate did not**.
`examples/AxonFramework_AxonBank` existed only in `beyond-alchemy` (324K, 72 files, 46 `.java`,
package shape `org/axonframework/samples/bank/<subpkg>/File.java`).

Pointed at a missing directory, `analyse_bounded_contexts()` returned a single `prog.` node, so
the guard-path precondition `assert prog_total >= 20` failed with `assert 1 >= 20`. The test had
been red for a day, unrelated to whatever change was being verified.

## Do not repoint it at `examples/java-axonframework-example-app`

That is a **different** Axon codebase (`com/customer/can/...`) with a different package shape and
concentration profile. The assertions (`{"Bankaccount", "Banktransfer"} <= names`, the 40% guard
path that the old 3-segment `_classify_java_layer` heuristic broke) would then assert nothing
about the bug being regressed. The standing rule still holds: a parser/classifier check is only
added alongside a **real fixture** that produces the shape under test.

## What we did

Copied the 324K estate from `beyond-alchemy/examples/AxonFramework_AxonBank` into this repo
(Joao approved — it also appears as a new card in the landing-page picker, detected as
java×46 / javascript×3). The test is unconditional again and passes.

If the estate is ever missing again, skip **loudly** (`skipif(not Path(...).is_dir())` with the
full reason) rather than weakening the assertions into a green test that proves nothing.

## Standing rule for beyond-alchemy ports

When a test path contains `examples/<Name>`, confirm that directory exists **in this repo**, not
just in the source of the port. `beyond-alchemy` and `micro-cosmos` do not share an `examples/`
tree — names differ (`AxonFramework_AxonBank` vs `java-axonframework-example-app`) even when both
are "an Axon example".
