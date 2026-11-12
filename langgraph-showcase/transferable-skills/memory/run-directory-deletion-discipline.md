---
name: run-directory-deletion-discipline
description: Deleting a run directory makes a healthy feature look broken in exactly the way a real bug would, and destroys the evidence needed to disprove it — a completed run is the artifact the human is reading, not scratch space (2026-08-19)
metadata:
  type: feedback
---

## What happened

After shipping the CQRS/NATS seam work ([[cqrs-message-flow-seams]]), I created verification runs via
the web API, checked them, and deleted them as "throwaway". Joao then reported that run `0b90dcf1`
showed **no story points in the Seams tab and no feature specs** — read, reasonably, as a regression
introduced by the change that had just shipped.

It was not a regression. I had deleted `runs/0b90dcf1/` while it was still open in his browser. Every
artifact request returned `404 "Run not found"`, so the Seams tab rendered empty and feature specs
appeared "not calculated" — **visually identical to a genuine calculation bug**. Two independent
reproductions (direct phases, and the full `run_full_pipeline()` with gates) both produced complete,
correct output: 21 seams / 206 pts, 21 specs / 206 pts.

## The rule

**Do not delete run directories.** A completed run is not scratch space — it is the artifact the
person is reading, and they will keep reading it after the turn ends. This is not the same as the
already-known hazard of deleting an *in-progress* run's directory (which crashes the container mid-write,
see [[llm-mode-confirm-toggle]]); this is about **completed** runs, which look safe to remove and are not.

If cleanup is genuinely wanted, ask — don't infer it from "I created this run, therefore it's mine".

## Why this failure mode is unusually expensive

1. **The symptom is maximally misleading.** A missing directory produces exactly what a broken feature
   produces: empty panels, no numbers. There is no error banner distinguishing "this run's data is
   gone" from "this calculation returned nothing".
2. **It lands right after a change**, so the natural inference is "the change broke it" — and that
   inference is very hard to argue against without evidence.
3. **The deletion destroyed the evidence.** The one artifact that could have settled it in seconds —
   the run's own `seam.json` — no longer existed. Confidence had to be rebuilt from scratch via two
   fresh reproductions plus a surviving control run (`883c1fb4`).

## How to diagnose this class of report quickly

Before assuming a regression when a UI shows empty data:

```bash
ls runs/<id>/                                   # does the directory even exist?
curl -b cookies -s -o /dev/null -w '%{http_code}' \
     localhost:8080/runs/<id>/artifacts/seam     # 404 "Run not found" == missing run, not a bug
```
A `404 Run not found` on **every** artifact endpoint means the run is gone. A real calculation bug
returns `200` with empty or zero-valued content. That single distinction separates the two cases
immediately — check it before reading any application code.

Then reproduce on a **fresh** run with the identical config before claiming either outcome, and keep
a known-good earlier run as a control (here `883c1fb4`, which returned 200 / 32KB of feature specs
and proved the endpoint itself was healthy).

## Related product gap worth knowing

The UI renders "run not found" and "artifact not yet generated" identically — both are just empty
panels. That ambiguity is what let a deleted run masquerade as a broken feature. Flagged as a real UX
gap in `docs/bug-2-…MD` §11, deliberately not fixed there (product decision, not part of a bug fix).

Related: [[cqrs-message-flow-seams]], [[llm-mode-confirm-toggle]], [[claude-response-style]].
