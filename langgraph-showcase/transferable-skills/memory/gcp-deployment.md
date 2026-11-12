---
name: gcp-deployment
description: All-Cloud-Run GCP deployment architecture (GPU LMStudio + web app) — replaced the Compute Engine VM approach on 2026-07-03
metadata:
  type: project
---

Micro-Cosmos deploys to GCP as **two Cloud Run services in the same
project**, with no Compute Engine VM and no VPC connector. Rebuilt
2026-07-03, replacing the earlier Cloud Run + Compute Engine VM architecture
(`deployment/cloudrun-cloudcompute.md`, now superseded).

## Architecture

```
Browser → micro-cosmos-web (Cloud Run, 5Gi RAM, 4 vCPU, public ingress)
            → micro-cosmos-lmstudio (Cloud Run, 32Gi RAM, 8 vCPU, 1× nvidia-l4, --ingress=internal)
                → LMStudio server → google/gemma-4-12b
                    weights cached in gs://$PROJECT-lmstudio-models (GCS FUSE mount)
```

**Key mechanism:** Cloud Run treats a call from one Cloud Run service to
another in the **same GCP project** as internal traffic when the target uses
`--ingress=internal` — no Direct VPC Egress, no Serverless VPC Access
connector, no firewall rules. This is what let all the VPC-networking flags
(`--network`, `--subnet`, `--vpc-egress`) get deleted entirely from the web
app's deploy script compared to the old architecture.

## Files

| File | Role |
|---|---|
| `deployment/deploy.py` | Orchestrator — dynamically imports the two hyphenated scripts below via `importlib.util` (plain `import` doesn't work on filenames containing `-`), deploys LMStudio first, wires its URL into the web app deploy. Supports `SKIP_LLM=true` to skip the GPU deploy for deterministic-mode testing. |
| `deployment/deploy_cloudrun-lmstudio-llms.py` | Deploys `micro-cosmos-lmstudio`: GPU Cloud Run service, creates + IAM-binds a GCS bucket (`$PROJECT-lmstudio-models`) mounted via GCS FUSE at `/root/.lmstudio` so model weights persist across redeploys/cold starts. Exposes `deploy_lmstudio()`. |
| `deployment/deploy_cloudrun-micro-cosmos-app.py` | Deploys `micro-cosmos-web`. Has `discover_lmstudio_url()` — auto-looks-up the LMStudio service URL via `gcloud run services describe` when `LLM_BASE_URL` isn't set. Exposes `deploy_micro_cosmos()`. |
| `deployment/Dockerfile.lmstudio` | Minimal CUDA-runtime base image with LMStudio CLI. Model weights are **not** baked in — pulled at container start into the mounted bucket. |
| `deployment/lmstudio-entrypoint.sh` | Container entrypoint: pull model (no-op if cached) → start server → poll health → load onto GPU. |
| `deployment/README.md` | Full guide: prerequisites, GPU quota/region caveat, one-shot deploy, per-service deploy, manual gcloud equivalents, config reference, operational notes. |
| `deployment/cloudrun-cloudcompute.md` | Superseded (marked with a pointer to README.md) — kept for historical reference only, describes the old Compute Engine VM approach. |

## Environment variable convention — three vars, not interchangeable

| Var | What it is | Used for |
|---|---|---|
| `PROJECT_NAME` | Human-readable display name | Reference only — no script reads it |
| `PROJECT_ID` | The GCP **Project ID** (a string, e.g. `my-project-id`) | Required by `gcloud iam service-accounts create` / `gcloud projects add-iam-policy-binding` — these reject a numeric Project Number |
| `PROJECT` | Mirrors `PROJECT_ID` | What the three deploy scripts actually read: `os.environ.get("PROJECT") or os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")` |

**Real incident (2026-07-03):** `gcloud config set project $PROJECT` and
`gcloud services enable` both silently accepted a numeric Project *Number*
with no warning, but `gcloud iam service-accounts create --project=$PROJECT`
failed with `The value of \`--project\` flag was set to Project number. To
use this command, set it to PROJECT ID instead.` Fix: normalize before
running IAM commands —
```bash
export PROJECT_ID=$(gcloud projects describe $PROJECT --format="value(projectId)")
export PROJECT=$PROJECT_ID
```
This asymmetry (some gcloud commands accept either form, IAM commands don't)
is why the three-var convention exists — `PROJECT_ID` is the one that must
always be the string form, and `PROJECT` must be kept mirrored to it.

## Real incident (2026-07-03): Cloud Build default SA has no permissions

First live `gcloud builds submit` on the `micro-cosmos` repo failed with
`INVALID_ARGUMENT: could not resolve source: ... does not have
storage.objects.get access` on the just-uploaded source tarball in
`gs://$PROJECT_cloudbuild/`. Root cause: this project has no dedicated Cloud
Build service account (Google stopped auto-provisioning
`PROJECT_NUMBER@cloudbuild.gserviceaccount.com` with pre-baked roles for
projects created after Sept 2024) — builds instead run as the **Compute
Engine default service account**
(`PROJECT_NUMBER-compute@developer.gserviceaccount.com`), which starts with
zero IAM roles. Fix:
```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder"
# if push to Artifact Registry then also fails with a 403:
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```
Documented in `deployment/README.md` under "Cloud Build permissions" and in
`.claude/commands/deploy-gcp.md` step 5, so this is a pre-flight check next
time, not a live debug session.

**Also fixed the same day:** `run()` in both `deploy_cloudrun-lmstudio-llms.py`
and `deploy_cloudrun-micro-cosmos-app.py` used
`subprocess.run(cmd, check=True, capture_output=True, text=True)` — this
swallows stdout/stderr, so `CalledProcessError` on any gcloud failure showed
only "returned non-zero exit status 1" with none of gcloud's actual error
text. `run()` now checks the return code manually and prints captured
stdout/stderr before raising, so the real gcloud error (like the one above)
is visible instead of hidden.

## Real incident (2026-07-03): LMStudio installer needs libatomic1

After fixing the Cloud Build SA permissions above, the build reached the
Dockerfile's `curl -fsSL https://lmstudio.ai/install.sh | sh && lms bootstrap`
step and failed with `Missing required dependency: "libatomic" is not
installed on your system`. The base image
(`nvidia/cuda:12.4.1-runtime-ubuntu22.04`) only had `curl ca-certificates`
installed before running the LMStudio installer. Fix: added `libatomic1` to
the `apt-get install` line in `deployment/Dockerfile.lmstudio` (before the
`curl | sh` step). If a future LMStudio installer version needs another
system library, the fix pattern is the same — install it in that same
`apt-get` line before the installer runs.

## Real incident (2026-07-03): GPU zonal redundancy needs separate quota

After the image build succeeded, `gcloud run deploy --gpu=1 --gpu-type=nvidia-l4
...` failed with `You do not have quota for using GPUs with zonal redundancy`
(`spec.template.metadata.annotations[autoscaling.knative.dev/maxScale]`
error). Cloud Run GPU services default to zonal redundancy (GPU replicated
across zones for HA), which is quota-gated separately from base GPU quota —
most projects only have the base quota. gcloud's own error message names the
fix: `--no-gpu-zonal-redundancy`. Added as the default in
`deploy_service()`/`deploy_lmstudio()` in
`deployment/deploy_cloudrun-lmstudio-llms.py`, controllable via
`LMSTUDIO_GPU_ZONAL_REDUNDANCY=true` for projects that do have that quota
approved (a single `MAX_INSTANCES=1` GPU instance gets no benefit from
cross-zone HA anyway, so off is the sane default). Documented in
`deployment/README.md` ("GPU zonal redundancy") and
`.claude/commands/deploy-gcp.md` step 6.

## Switching models (2026-07-03): no code changes needed, but VRAM assumptions must move with the model

User asked what's required to switch `MODEL_REASONING`/`MODEL_FAST` to
`qwen/qwen3.6-27b` (dense 27.8B, 64 layers, hybrid linear/full attention —
full attention on only ~1-in-4 layers, native 262,144 context, LM
Studio-verified for agentic tool calling, GGUF weights: Q4_K_M ≈16.8GB,
Q5_K_M ≈19.5GB, Q6_K ≈22.5GB, Q8_0 ≈28.6GB — found via WebSearch, not prior
knowledge, since this model postdates training data). Decision: user chose
env-var-override only, not changing `DEFAULT_MODEL_ID` in
`deploy_cloudrun-lmstudio-llms.py` (still `google/gemma-4-12b`).

**Mechanism check (confirmed by reading the code, not assumed):** model
selection is already fully parameterized — `MODEL_REASONING`/`MODEL_FAST`/
`MODEL_CONTEXT_LENGTH` are plain env vars read by both deploy scripts *and*
by `micro_cosmos/settings.py` (the running app). Tool-calling goes through
LiteLLM's `openai/` provider in `Settings.build_llm()`, which is
model-agnostic OpenAI function-calling format — no ADK/agent code cares which
model is behind it. `lmstudio-entrypoint.sh`'s `lms pull`/`lms load` take the
model ID as an opaque string, so even a multimodal model shipped as two GGUF
files (text + `mmproj.gguf` vision projector) needs no entrypoint changes —
LM Studio manages that split internally under one model ID. **So switching
models is a pure config change, zero code changes for the switch itself.**

**What *does* need a code change every time the model changes:** the VRAM
heads-up warning. `check_vram_fit()` in `deploy_cloudrun-lmstudio-llms.py`
previously hardcoded `assumed_weights_gb = 7.0` (sized for
`google/gemma-4-12b`). Fixed by exposing `LMSTUDIO_ASSUMED_WEIGHTS_GB` (env
var, default `7.0` via new `DEFAULT_ASSUMED_WEIGHTS_GB` constant) and
threading it into `check_vram_fit(model_id, context_length, gpu_layers,
assumed_weights_gb)`. Forgetting to set this when switching models makes the
warning check a different (wrong) model's weight size silently.

**Also fixed:** the KV-cache formula in `estimate_kv_cache_gb()` assumes
every layer does full quadratic attention. That's a reasonable rough
approximation for a dense non-hybrid model, but for hybrid linear/full
attention architectures (Qwen3.6's whole design point) it substantially
*overestimates* real KV cache, since only ~1-in-4 layers pay the quadratic
cost. Docstring and the printed warning now say this explicitly — treat the
number as a conservative upper bound for such models, not a real prediction,
and verify actual VRAM usage via Cloud Run logs on first deploy.

Documented in `deployment/README.md` under "Switching models — no code
changes required" (with the Qwen3.6-27B numbers as a worked example) and
`.claude/commands/deploy-gcp.md` step 7.

## Real incident (2026-07-03): container startup probe timeout, not an IAM issue

After the zonal-redundancy fix, `gcloud run deploy micro-cosmos-lmstudio`
(deploying with `MODEL_ID=qwen/qwen3.6-27b`) failed with `The user-provided
container failed to start and listen on the port ... within the allocated
timeout`. A "Setting IAM Policy failed" warning appeared in the same output
just above it, which looked auth-related but was a red herring — separate,
harmless side effect of `--allow-unauthenticated` + `--ingress=internal`
(internal ingress blocks public access regardless of that IAM binding
outcome). The real cause: `lmstudio-entrypoint.sh` ran `lms pull
"${MODEL_ID}"` **before** starting the LMStudio server / binding `$PORT`.
Cloud Run's default startup probe is a plain TCP check on `$PORT` with a
~240 second total timeout — no awareness of model download progress. Pulling
a 16.8GB+ model (Qwen3.6-27B at Q4_K_M) on a cold GCS FUSE mount easily
exceeds 240s, so Cloud Run killed the revision before the entrypoint ever
reached the `lms server start` line. This was a latent bug present for
`google/gemma-4-12b` too (~7GB pull, still plausibly slow on a cold mount) —
it just hadn't surfaced yet because every earlier deploy attempt in this
session failed at an earlier stage (Cloud Build IAM → libatomic1 → zonal
redundancy) before ever reaching this race.

**Fix:** reordered `lmstudio-entrypoint.sh` — start `lms server start` (binds
`$PORT` almost immediately, independent of model size) *first*, then the
health-check wait loop, *then* `lms pull`/`lms load`. This is model-size-
independent and correct for any model, not just Qwen3.6-27B. Documented in
`deployment/README.md` under "Container startup timeout" and
`.claude/commands/deploy-gcp.md` step 8.

**Update (2026-07-06): this fix was necessary but NOT sufficient** — see the
next entry below. The exact same "container failed to start" error recurred
with a completely different model (`qwen/qwen3.6-35b-a3b`) and GPU type
(`nvidia-rtx-pro-6000`), which ruled out model size as the actual cause and
pointed at something more fundamental.

## Real incident (2026-07-06): GCS FUSE volume mount was shadowing the `lms` binary itself

Root cause of the recurring "container failed to start and listen on the
port" error (same symptom as the entry above, but survived that fix):
`Dockerfile.lmstudio` sets `PATH="/root/.lmstudio/bin:${PATH}"` — `lms
bootstrap` installs the `lms` binary to `.lmstudio/bin` at *image build*
time. But `deploy_service()` in `deploy_cloudrun-lmstudio-llms.py` mounted
the GCS bucket at `--add-volume-mount=volume=model-cache,mount-path=/root/.lmstudio`
— the **entire** `.lmstudio` directory, not just where model weights live.
At container start, that mount shadows everything the image baked in at
that path, including `bin/lms`. Every `lms` command in the entrypoint then
fails with "command not found," the script exits under `set -euo pipefail`,
and `$PORT` is never bound — the identical symptom regardless of which
model or GPU type is in play, which is exactly why the previous fix (server
before pull) didn't help: neither `lms pull` nor `lms server start` could
run at all, so their *order* was irrelevant.

Confirmed via LM Studio's own docs/CLI layout (not guessed): `lms` lives at
`~/.lmstudio/bin/`, model weights live in the sibling `~/.lmstudio/models/`
— LM Studio's own default models directory, used automatically with no
GUI-only config needed in a headless container.

**Fix:** changed the mount path to `/root/.lmstudio/models` (the `models`
subdirectory only) — preserves `bin/` from the image while still persisting
the actual multi-GB weights across redeploys/cold starts. **Never mount
this volume at the `.lmstudio` root** if this script is modified again.
Documented in `deployment/README.md` ("Container startup timeout", now
rewritten to lead with this as the confirmed root cause) and
`.claude/commands/deploy-gcp.md` step 8.

**Update (still 2026-07-06): the mount-path fix alone didn't take effect on
redeploy — real Cloud Run revision spec (Logs Explorer JSON, ground truth,
not guessed) showed BOTH `/root/.lmstudio` and `/root/.lmstudio/models` as
separate `volumeMounts` entries for the same `model-cache` volume after
redeploying. Root cause: `gcloud run deploy --add-volume-mount` is
**additive on a redeploy of an existing service** — it doesn't replace a
previous revision's volume config for the same volume name, it accumulates
alongside it. Since `micro-cosmos-lmstudio` already had the stale
`/root/.lmstudio` mount from before the path fix landed, redeploying only
added the corrected mount without removing the old (still binary-shadowing)
one — the exact same "container failed to start" / `DEADLINE_EXCEEDED` TCP
probe failure recurred as a direct result. Fix: added `--clear-volumes
--clear-volume-mounts` to `deploy_service()`, before `--add-volume`/
`--add-volume-mount`, so every deploy fully replaces volume config instead
of layering onto whatever the previous revision had. General lesson for
this script: `gcloud run deploy`'s `--add-*` flags are not idempotent
`--set-*` flags on a redeploy — assume additive semantics unless docs say
otherwise, and clear first when a flag value ever needs to change on an
existing service.**

Separately spotted in the same session: the user's **persistent gcloud CLI
config** (`gcloud config get-value project`, distinct from the `$PROJECT`
shell env var fixed earlier) is still set to the numeric project number, not
the string ID — surfaced when a manually-run remediation command (without
an explicit `--project` flag) failed with `the value of 'core/project'
property is set to project number`. Doesn't affect `deploy.py` (always
passes `--project=$PROJECT` explicitly) but will keep breaking any ad hoc
gcloud command run without `--project`. Fix (told to user, not a repo
change): `gcloud config set project micro-cosmos`.

## Real incident (2026-07-06): Cloud Run's 4-minute startup probe too short for GPU cold start — unconfirmed hypothesis, unlike the two entries above

After the mount-path and `--clear-volumes` fixes above, the IAM policy step
finally succeeded ("Setting IAM Policy...............done") and the deploy
got further, but hit a **different** error: `Container failed to become
healthy. Startup probes timed out after 4m (1 attempts with a period of 4m
each)`. The GCS bucket's `models/` folder was still empty — consistent
with, but not proof of, the server never starting (since `lms pull` only
runs after the server binds `$PORT`, per the 2026-07-03 entrypoint fix).

**Important distinction from the two entries above:** those were confirmed
from ground truth (the live revision's `volumeMounts` JSON). This one is
NOT — I don't have access to the actual container runtime logs (only
`gcloud run deploy`'s own output, which doesn't include entrypoint stdout).
The fix below is the best-supported hypothesis from Google's own published
Cloud Run GPU docs (WebSearch), not a confirmed root cause. Said explicitly
to the user rather than presenting it as certain.

**Hypothesis:** standard Cloud Run services get a hard 4-minute (240s)
default startup probe. Google's own docs break a GPU cold start into node
provisioning (60-120s), image pull (30-60s — the prior revision's audit log
already showed 1m54s=114s for this image), CUDA context init (5-30s) — easily
consuming most of a 240s budget on a first-ever deploy of a new GPU
type/config, before `lms server start` even gets a chance to bind the port.
Google explicitly recommends a higher `failureThreshold` for GPU/AI
workloads (supports up to 30 min total).

**Fix:** `deploy_service()` now passes an explicit `--startup-probe`
(verified flag syntax via WebSearch against Google's docs:
`tcpSocket.port=8080,initialDelaySeconds=0,periodSeconds=10,
failureThreshold=N`), replacing the 4-minute default with 10 minutes
(`DEFAULT_STARTUP_TIMEOUT_SECONDS`), overridable via
`LMSTUDIO_STARTUP_TIMEOUT_SECONDS`. Applied to both GPU types — extra probe
headroom costs nothing if the container starts quickly. Documented in
`deployment/README.md` ("GPU cold-start startup probe timeout") and
`.claude/commands/deploy-gcp.md` step 9, both explicitly flagging this as
unconfirmed and pointing at `gcloud run services logs read
micro-cosmos-lmstudio` as the next real diagnostic step if it doesn't resolve
the issue.

## Real incident (2026-07-06): confirmed — the startup-probe hypothesis above was NOT the fix; `lms server start --host` doesn't exist

The very next deploy timed out the **full** 30-minute startup probe window
(`180 attempts × 10s`) with zero success — strong evidence it was never a
timing problem, since some fraction of a 30-minute budget would have
succeeded if slowness were the real cause. Pulled the actual container logs
this time (`gcloud run services logs read micro-cosmos-lmstudio --region=... `)
— the first real ground truth from inside the container all session — and
found the entrypoint failing on every single attempt with:
```
error: unknown option '--host'
(Did you mean --port?)
```

**Root cause:** `lmstudio-entrypoint.sh` called `lms server start --port
"${PORT}" --host 0.0.0.0`. `lms server start` has no `--host` flag — checked
against LM Studio's own CLI docs (WebSearch/WebFetch, not assumed): the
correct flag is `--bind`. The CLI rejected the unrecognized option and
exited immediately every time, so the server process never even attempted
to bind `$PORT` — completely independent of the startup probe timeout,
which is exactly why extending it to the documented 30-minute maximum
didn't help even slightly.

**Also confirmed important:** `lms server start`'s default bind address
(if `--bind` is omitted entirely) is `127.0.0.1` (localhost-only) — Cloud
Run requires `0.0.0.0`. So the fix isn't just removing the bad flag, it's
using the *correct* flag name with the *correct* value.

**Fix:** `lmstudio-entrypoint.sh` now calls `lms server start --port
"${PORT}" --bind "${LMSTUDIO_HOST_BIND}"` (new `LMSTUDIO_HOST_BIND` env var,
default `0.0.0.0`, also used for the entrypoint's own internal
`curl`-based health check URL). `Dockerfile.lmstudio` also now sets
`ENV LMS_SERVER_HOST=0.0.0.0` — the CLI honors this env var as an
alternative to `--bind`, so it acts as a durable image-level default even
if the entrypoint's explicit flag were ever wrong again.

**Lesson for this whole multi-fix saga:** the previous entry's startup-probe
extension was a reasonable, well-sourced hypothesis, but the fact that it
didn't resolve the issue was itself diagnostic information — when a fix
doesn't work, the right move is pulling real logs immediately, not trying a
third or fourth variation of the same class of guess. The probe extension
is still worth keeping (a genuine GPU cold start can plausibly need more
than 4 minutes), it just wasn't *this* bug.

## Real incident (2026-07-06): `lms pull` doesn't exist — the correct command is `lms get`

With the `--host`/`--bind` fix applied, the server finally started and
bound the port successfully — the next deploy attempt progressed further
and hit a *new*, different failure. Real container logs showed:
```
[entrypoint] pulling qwen/qwen3.6-35b-a3b (no-op if already cached on the mounted volume)…
error: unknown command 'pull'
```
`lmstudio-entrypoint.sh` called `lms pull "${MODEL_ID}"` — but `lms pull`
was never a valid `lms` CLI command (confirmed against LM Studio's own CLI
docs via WebSearch/WebFetch, not guessed). The correct command is `lms
get`. Checked specifically whether `lms get` with a full/exact model ID
prompts interactively (which would hang a headless container): confirmed
it auto-selects and downloads non-interactively by default — the flags
that force an interactive quantization prompt
(`--always-show-download-options`/`--always-show-all-results`) are opt-in.

**Fix:** `lms pull` → `lms get` in `lmstudio-entrypoint.sh`. User also
asked to strip the debugging-narrative comments this incident (and the
`--host`/`--bind` one before it) had accumulated directly in the script —
per this repo's comment style (state the current fact, not the incident
history), that narrative belongs in this memory file and
`changes-log.md`, not inline in production script comments. Rewrote
`lmstudio-entrypoint.sh` to be lean; the full incident history lives here.

**Correction to the entry below:** it opens with "all four bugs above
fixed" / "finally deploying successfully" — written before this fifth bug
(`lms pull`) was discovered, so that framing was premature. Left as
written below since it's what was true/believed *at that point*, but
noting the correction here for anyone reading forward.

## Real incident (2026-07-06): `micro-cosmos-web` deploy blocked by org policy `constraints/run.allowedIngress` — architecture-level, not a script bug

With `micro-cosmos-lmstudio` finally deploying successfully (all four bugs above
fixed), `micro-cosmos-web`'s deploy failed at the Cloud Run creation step —
different in kind from every previous fix this session, since this one is
an actual GCP **Organization Policy**, not an application bug:
```
ERROR: (gcloud.run.deploy) FAILED_PRECONDITION: Constraint
constraints/run.allowedIngress violated for attempting CreateService with
annotation "run.googleapis.com/ingress" set to the default value all.
```
`deploy_cloudrun-micro-cosmos-app.py` never set `--ingress` explicitly, so it
defaulted to `all` (fully public) — and this project's org policy doesn't
allow that value. Confirmed via WebSearch: `constraints/run.allowedIngress`
supports exactly three values (`all`, `internal`,
`internal-and-cloud-load-balancing`); this org evidently disallows `all`.
This is very likely deliberate — an enterprise "no publicly-exposed Cloud
Run services" guardrail, consistent with the compliance-focused context of
this GCP org — not something to route around without
explicit confirmation.

**This directly invalidates the original architecture's stated premise**
(`README.md`'s original diagram showed `Browser --HTTPS(public)-->
micro-cosmos-web`) — the web UI was never going to be reachable from a random
browser on this project, regardless of any script fix. This is also
probably the same category of org guardrail behind the earlier
`run.services.setIamPolicy`/`allUsers` IAM investigation a few turns
earlier in this session (though that one specifically turned out to be a
permissions gap, not org policy — this is a *confirmed* separate org
policy, on ingress rather than IAM membership).

**Decision, asked explicitly via AskUserQuestion (three options: internal-only
/ external LB+IAP / request org policy exception):** user chose
**internal-only**, matching the existing `micro-cosmos-lmstudio` pattern. Fix:
added `--ingress=internal` to `micro-cosmos-web`'s `deploy_service()` in
`deploy_cloudrun-micro-cosmos-app.py` (kept `--allow-unauthenticated` — same
reasoning as `micro-cosmos-lmstudio`: `--ingress=internal` is the actual
security boundary, IAM auth is a secondary concern here). Updated
`deploy.py`'s completion message to explain `gcloud run services proxy
micro-cosmos-web --region=...` as the actual access method (an authenticated
local tunnel using the caller's own `gcloud` credentials) instead of
telling the user to "open the web app URL" in a browser, which no longer
works. Rewrote the "Why no VPC connector" architecture diagram in
`deployment/README.md` and added a full "Web UI access" section, since the
old diagram's "Browser → HTTPS (public) → micro-cosmos-web" framing is now
false.

**Not implemented, flagged as bigger decisions for later if actually
needed:** external Application Load Balancer + Identity-Aware Proxy
(`--ingress=internal-and-cloud-load-balancing`) for genuine public access
with org-mandated controls, or requesting a per-project org policy
exception through the org's GCP admin/IT (per the org's own escalation
process — not something to attempt via a clever gcloud flag).

**Superseded later the same day — see below.** The internal-only decision
above held only until the user actually tried to reach `micro-cosmos-web` via
`gcloud run services proxy` (per this entry's own suggested access method)
and hit the *same* 404 as a direct browser request. That surfaced a real
mistake: `gcloud run services proxy` does **not** bypass
`--ingress=internal` — confirmed against Google's own docs afterward. It
only attaches an IAM identity token to a request against the same public
endpoint; that still has to pass the ingress network check first, so it
fails identically to a plain browser request when the target is
internal-only. It only helps for services requiring IAM auth on an
otherwise-public ingress. **This was bad guidance given in this session and
should not be repeated** — don't suggest `gcloud run services proxy` as an
internal-ingress bypass again.

Given that correction, and since this is explicitly "a harmless demo," the
user asked what it would take for genuine internet access, was given both
real options (org policy exception vs. external LB+IAP), and chose the
**org policy exception route**: `micro-cosmos-web` now deploys
`--ingress=all` (public) instead of `internal`, on the assumption the user
secures a per-project exception to `constraints/run.allowedIngress`
separately (not something I can grant). `micro-cosmos-lmstudio` is unaffected —
stays `--ingress=internal`, since it's never meant to be reached directly,
only called by `micro-cosmos-web`. See "Web UI access" in `deployment/README.md`
for the current, corrected state — the "internal-only" framing throughout
the entry above is no longer current for `micro-cosmos-web` (kept as-is above
since it accurately describes what was decided and why at that time).

**Superseded again, next day (2026-07-07) — see the Load Balancer entry
below.** The org policy exception for `--ingress=all` was requested and
**declined**. `micro-cosmos-web` moved to the Load Balancer route instead.

## External Application Load Balancer for `micro-cosmos-web` (2026-07-07)

The org policy exception for `--ingress=all` (previous entry) was
**declined** — that route is closed for this project. User's explicit
instruction: "ingress=all is invalid by company policy needs to rollback
to ingress=internal, so we need to go onto the route of defining an
external load balancer for the service."

**Caught before implementing — plain `--ingress=internal` would NOT have
worked with an LB in front.** Cloud Run treats load-balancer-routed traffic
as a distinct category from same-project internal Cloud-Run-to-Cloud-Run
calls. Plain `internal` only allows the latter (what `micro-cosmos-lmstudio`
needs). For an LB to reach `micro-cosmos-web` at all, the ingress value must be
the org policy's third allowed value: `internal-and-cloud-load-balancing`.
Implemented that instead of the literal "rollback to internal" ask, and
explained the correction rather than silently deviating.

Planned via `EnterPlanMode`/`ExitPlanMode` per explicit user request ("plan
me the solution before executing... before any approvals of my side").
Asked two clarifying questions before writing the plan, since both are hard
blockers I couldn't guess: (1) domain name for the Google-managed SSL cert
— `app.micro-cosmos.tools`, user has DNS control; (2) IAP or fully open —
fully open, no IAP, matching the "harmless demo" framing (same exposure
level `--ingress=all` would have given, just achieved through an
org-compliant mechanism).

**Design:** new standalone script, `deployment/setup_micro_cosmos_web_lb.py`,
kept separate from `deploy_cloudrun-micro-cosmos-app.py` because LB
infrastructure (static IP, NEG, backend service, URL map, cert, proxies,
forwarding rules) is create-once, not something to re-provision on every
app code deploy. Idempotent throughout — `_ensure()` helper mirrors the
try/except `ALREADY_EXISTS` pattern from `ensure_artifact_repo()`/
`ensure_model_bucket()` in the other two scripts. 8 resources: static IP,
serverless NEG, backend service (+ NEG attached as backend, with an
explicit `describe` check first since `add-backend` isn't itself
idempotent — adding the same backend twice errors), URL map, Google-managed
SSL cert, target HTTPS proxy, HTTPS forwarding rule (443), and an
HTTP→HTTPS redirect (port 80, sharing the same static IP).

**Real mistake caught and fixed before it shipped:** first draft of the
HTTP→HTTPS redirect used `gcloud compute url-maps import ... --source=-`
(stdin) — but the `run()` helper used throughout this file's scripts uses
`subprocess.run(..., capture_output=True)` with no `input=` piping, so
`--source=-` would have read empty stdin and failed on every run, silently
broken until someone actually exercised that code path. Caught during
self-review before presenting as done (not by the user), fixed by writing
the YAML to a `tempfile.TemporaryDirectory()` and using
`--source=<path>` instead — verified via WebSearch that gcloud has no
direct CLI flag for URL map redirects (YAML import is the only supported
method, confirmed against Google's own docs, not guessed).

**Fix in `deploy_cloudrun-micro-cosmos-app.py`:** `--ingress=all` →
`--ingress=internal-and-cloud-load-balancing`. `--allow-unauthenticated`
kept (comment updated: "gated by the LB below, not IAM" — access control
lives in DNS/whether-the-LB-exists, not IAM, matching the "fully open"
decision).

**Two things the script cannot do, called out explicitly in its own
output:** (1) create the DNS A record — no access to whatever DNS provider
hosts `micro-cosmos.tools`, the script just prints the reserved IP and the exact
record to create; (2) the SSL cert only reaches `ACTIVE` after DNS
resolves and Google validates it (up to ~60 min after propagation) — the
user must wait for that and then redeploy `micro-cosmos-web` separately so it
picks up the new ingress value (the LB script does NOT touch the Cloud Run
service's ingress setting itself — that's `deploy_cloudrun-micro-cosmos-app.py`'s
job).

**Verification:** full dry-run of `setup_load_balancer()` (monkeypatched
`run()`, simulated `describe` responses, inspected all 13 generated gcloud
commands including the temp-file YAML path) plus the usual syntax checks.
**Not run against the live project** — provisions real, billed
infrastructure (static IP + forwarding rules bill even when idle) and
touches DNS, consistent with this session's standing practice of not
executing live infra-affecting gcloud commands.

**Update — confirmed working end-to-end against the live project.** User
ran `setup_micro_cosmos_web_lb.py` for real: static IP, NEG, backend service,
URL map, SSL cert, HTTPS proxy/forwarding rule all provisioned; DNS A
record created at GoDaddy (slow to propagate — normal registrar-DNS
behavior, nothing GCP-side speeds this up; explained TTL/negative-caching
and suggested Cloud DNS delegation as the fix if this recurs, not
implemented); SSL cert reached `ACTIVE`; `micro-cosmos-web` redeployed with
`--ingress=internal-and-cloud-load-balancing`; confirmed reachable at
`https://app.micro-cosmos.tools/demo`. The real domain
(`app.micro-cosmos.tools`) replaced the `app.micro-cosmos.tools`
placeholder throughout `deployment/README.md`,
`.claude/commands/deploy-gcp.md`, and `setup_micro_cosmos_web_lb.py`'s
docstring/error message once confirmed. First real end-to-end validation
of the whole session's `setup_micro_cosmos_web_lb.py` design — no flag-syntax
surprises hit.

## Login gate (demo/demobxyz) added to micro-cosmos-web, session-cookie based (2026-07-09)

User asked for the whole web app to require login (username `demo`,
password initially `demo1`, later changed to `demobxyz` — see below),
landing on `/demo` after success, with the existing "New run"/"Demo" nav
(already in `base.html`) staying reachable afterward — no menu
restructuring actually needed, since that nav already existed; the
"landing page becomes reachable via menu" part of the ask was already true
once the default post-login destination changed to `/demo`.

**Multi-instance constraint driving the design, identified before writing
any code:** `micro-cosmos-web` runs `MIN_INSTANCES=1`/`MAX_INSTANCES=3` on Cloud
Run — a server-side in-memory session store would break the moment a
user's requests land on a different instance. Used Starlette's built-in
`SessionMiddleware` (signed cookie via `itsdangerous`, newly added to
`pyproject.toml` — no other new dependency) instead: stateless, any
instance can verify the cookie, no shared store needed.

**Design, approved via `EnterPlanMode`/`ExitPlanMode` before writing code:**
new `demo_username`/`demo_password`/`session_secret_key`/`session_https_only`
settings in `micro_cosmos/settings.py` (same shape as the pre-existing
`gate_token` setting — precedent already in this file for a "simple
shared-secret gate"); a `require_login` HTTP middleware in
`micro_cosmos/web/app.py` redirecting anything except `/login`/`/healthz`/
`/static/*` to `/login` if `request.session.get("authenticated")` is
falsy; `GET`/`POST /login` and `GET /logout` routes; a new standalone
`login.html` template (reuses existing `.hero`/`.run-form` CSS classes,
zero new CSS); a "Logout" link added to `base.html`'s nav (flagged to the
user as slightly beyond the literal ask, since a login with no logout is
an incomplete feature for ~2 lines of code — not vetoed).
`secrets.compare_digest` used for the credential check, not `==` (free
constant-time fix, not scope creep — a plain `==` password comparison is a
textbook timing-attack surface).

**Real bug caught by actual verification, not just syntax checks:**
`SessionMiddleware` was initially `app.add_middleware()`'d *before* the
`require_login` middleware. Starlette wraps middleware such that the LAST
one added is OUTERMOST (executes first on the way in) — so with that
order, `require_login` ran *before* `SessionMiddleware` had populated
`request.session`, raising `AssertionError: SessionMiddleware must be
installed to access request.session` on every single request. Caught by
building a standalone Starlette test harness (not the full app — `app.py`
eagerly imports the entire heavy pipeline stack at module level: google-adk,
chromadb, sentence-transformers, faiss — so a lightweight scratch venv
with just fastapi/starlette/itsdangerous plus a `TestClient`-driven replica
of the actual middleware/route logic was the only practical way to exercise
this without a multi-GB dependency install or a running Docker daemon,
neither available in this environment at the time). 12 checks (unauthenticated
redirect, `/healthz` staying public, wrong-password rejection, correct-password
success + `Set-Cookie`, session granting access, re-visiting `/login` while
authenticated, logout clearing the session) all failed on the first run
with exactly that assertion error, confirming the ordering bug; fixed by
moving the `add_middleware(SessionMiddleware, ...)` call to after
`require_login`'s definition, then all 12 passed. Fixed in the real
`micro_cosmos/web/app.py`, not just the test harness.

**Wired through both environments per the explicit ask:**
`docker-compose.yml` gets `DEMO_USERNAME`/`DEMO_PASSWORD` (default
`demo`/`demobxyz`) with `SESSION_HTTPS_ONLY` deliberately left unset
(stays `false` — plain `http://localhost:8080`, a `Secure` cookie
wouldn't even be sent by the browser over plain HTTP).
`deploy_cloudrun-micro-cosmos-app.py` sets the same two plus
`SESSION_HTTPS_ONLY=true` (real HTTPS via the LB now) and generates
`SESSION_SECRET_KEY` fresh via `secrets.token_hex(32)` on every deploy
unless the env var is set explicitly (setting it persists sessions across
redeploys instead of forcing everyone to log in again).

**Password changed from `demo1` to `demobxyz` mid-implementation** — user
asked explicitly, updated in every file where it appeared: `docker-compose.yml`,
`micro_cosmos/settings.py`, `deployment/deploy_cloudrun-micro-cosmos-app.py`,
`deployment/README.md` (including the markdown-anchor-affecting section
heading and cross-reference), and the top-level `README.md`'s quickstart.
Grepped the whole repo afterward to confirm zero remaining `demo1`
references outside `.claude/worktrees` (unrelated agent sandboxes).

**Not yet exercised against a live deploy** — the standalone Starlette
harness proves the auth logic itself is correct, but this hasn't been
through an actual `docker compose up` or a live Cloud Run redeploy. Treat
the first real login attempt after redeploying as validation, same
caveat-flagging discipline as every other never-yet-live-tested piece this
session.

## Identity-Aware Proxy (IAP) attempted, then reverted — blocked on permissions, not a design problem (2026-07-09)

Added in commit `5e9ea25`, reverted in `8f3de67` the same day. Full
incident detail (root-cause chain, the `iap.web.getIamPolicy` red herring,
and how to retry) lives in `changes-log.md`'s "Reverted: Identity-Aware
Proxy" entry — kept there instead of duplicated here since that's now the
more complete account. Short version: the user doesn't currently have the
permissions to complete the one unscriptable step (creating the OAuth
consent screen + OAuth Client via Cloud Console), and `enable_micro_cosmos_web_iap.py`
can't proceed without it — so the whole change was reverted rather than
left half-applied (`--no-allow-unauthenticated` with no working IAP in
front would have locked out `micro-cosmos-web` entirely). `deployment/enable_micro_cosmos_web_iap.py`
and this file's own detailed IAP entry no longer exist in the working tree
— recoverable from git history (commit `5e9ea25`) if/when someone with
IAP admin rights completes the Console step. The design itself (grant
order: invoker before backend-IAP-enable; `--no-allow-unauthenticated`
only after the invoker grant lands; keep the app-level login as a second
layer) doesn't need to change on retry.

## Real incident (2026-07-09): `micro-cosmos-web` Cloud Build failing at Trivy install — GitHub API rate limit, not a code bug

`python3 deployment/deploy.py` failed rebuilding `micro-cosmos-web`'s image:
`apt-get install` succeeded, `aquasecurity/trivy`'s `contrib/install.sh`
printed `found version: 0.70.0 for v0.70.0/Linux/64bit`, then the whole
`RUN` step exited non-zero with no further output. Root cause:
`install.sh` resolves releases via `api.github.com`, which enforces an
**unauthenticated** rate limit (60 req/hr per source IP) — Cloud Build's
builder VMs share a pool of IPs across many customers, so this call
intermittently 403s. Nothing in this session's changes touched
`Dockerfile`'s Trivy line before this broke.

**Fix:** `Dockerfile` downloads the pinned release tarball directly
(`https://github.com/aquasecurity/trivy/releases/download/v0.70.0/trivy_0.70.0_Linux-64bit.tar.gz`
— exact asset name confirmed via the GitHub releases API, not guessed)
and extracts the binary with `tar -xz`, instead of piping `install.sh`
through `sh`. This skips the rate-limited `api.github.com` call entirely —
release *asset* downloads are served from GitHub's release CDN, a
different, non-rate-limited path. **Not yet confirmed on a subsequent
build** — if the exact "found version… then silent exit 1" pattern
recurs even after this fix, that points to something else (e.g. Cloud
Build's egress genuinely can't reach GitHub), not rate limiting again.

## Real incident (2026-07-09): `lms get` stalls on GCS FUSE "legacy staged writes", `lms load` then hangs forever in an interactive picker

Found while switching `micro-cosmos-lmstudio`'s model down from
`qwen/qwen3.6-35b-a3b` to `qwen/qwen3.6-27b` to rule out size/GPU as the
cause of a download failure (same diagnostic pattern as the earlier
startup-timeout incidents — same failure survived the size change, so
size wasn't it). Two separate bugs, stacked:

1. **The download wasn't slow, it was stalled.** Live Cloud Run logs
   showed the progress bar frozen at exactly `5.00% | 874.03 MB / 17.48 GB`
   for the whole visible window before `lms` gave up with `Error: Download
   failed: Timed-out.` — zero progress, not a total-duration timeout. The
   gcsfuse log lines printed right alongside it explain why: `Existing
   file .../downloading_*.gguf.part of size N bytes (non-zero) will use
   legacy staged writes. Streaming writes is supported for sequential
   writes to new/empty files.` The `.part` files were leftovers from
   earlier failed attempts (both this model and the previous 35B one —
   ties directly into the "why does the bucket have two model folders"
   question asked earlier the same day). Every retry resumed into an
   already-partial file, forcing gcsfuse's slow staged-write path (its
   fast streaming path only applies to new/empty files written
   sequentially from byte zero) — slow enough to trip `lms`'s own
   download-stall detection, repeatedly, without ever finishing.
2. **`lms load` hung instead of failing.** `lmstudio-entrypoint.sh`
   unconditionally called `lms load` after `get`, even with no complete
   model on disk. Per the logs, `lms load` printed `Cannot find a model
   matching the provided model key` and dropped into an **interactive TUI
   picker** (`? Select a model to load |`) — Cloud Run has no TTY, so the
   process just hung; the exact same prompt was still rendering 4+ minutes
   later. `set -euo pipefail` doesn't catch this, since a blocked stdin
   read never returns non-zero — the container silently never became
   ready, indistinguishable from a slow model load until the startup probe
   timeout.

**Fix, `lmstudio-entrypoint.sh`:** `lms get` retries up to 99 times (5s
backoff) with `-y`. `lms load` gets `-y </dev/null` — if it still can't
resolve `MODEL_ID` and tries to fall back to the interactive picker,
reading stdin hits EOF immediately and the command fails fast instead of
hanging. **Bucket-level, not scripted:** the stale `.part` files causing
the staged-write fallback need a one-off manual delete (`gcloud storage rm
-r gs://$PROJECT-lmstudio-models/lmstudio-community/<model>-GGUF/`) before
the next deploy, so the retry starts as a genuinely new/empty file.
Deliberately not automated in a deploy script — deleting bucket contents
automatically is a much bigger blast radius than warranted here. **Not yet
verified against a live redeploy.**

## Follow-up (2026-07-10): the manual `.part`-file cleanup above recurred with a new model — now automated; plus a new, separate `lms get` auth bug

The bucket-level manual cleanup from the 2026-07-09 incident above wasn't
a one-time fix — it recurred on `google/gemma-4-12b-qat`'s first-ever live
deploy (a different model, same underlying GCS FUSE staged-writes stall).
`lmstudio-entrypoint.sh`'s `lms get` retry loop now cleans up
`*.part`/`downloading_*` files itself before **every** attempt (not just
once at the top — a failed attempt within the same loop re-poisons the
file for the next retry too, per the root-cause mechanics above), so this
no longer needs a human to remember a manual `gcloud storage rm` before
each redeploy.

**Separately, a new bug surfaced in the same incident**: `lms get` failing
repeatedly with `[...AuthenticatedWsClientTransport] WebSocket error:
Error: Failed to authenticate: Invalid passkey for lms CLI client.` —
still failing at retry 10/99, ~90+ seconds after the server reported
healthy, so not a one-off startup race. Root-caused against the actual
`lms` CLI source (`lmstudio-ai/lms` on GitHub, `src/createClient.ts` +
`src/lmstudioPaths.ts`, fetched directly): every privileged `lms` command
authenticates over WebSocket with `lmsKey + lmsKey2`, where `lmsKey` is
baked into the CLI binary at build time and `lmsKey2` is re-read on every
invocation from `$HOME/.lmstudio/.internal/lms-key-2` (outside the GCS
FUSE `models` mount — ordinary container filesystem). `lms server start`
(entrypoint.sh) authenticates successfully first, but every subsequent
`lms get` is a **separate CLI process** re-deriving its own client from
that same key file — and that kept failing across 10+ retries, meaning
the cached key had genuinely desynced, not just raced on startup timing.
Checked the two most relevant `lmstudio-ai/lms`/`lmstudio-bug-tracker`
GitHub issues for this exact error: both open, undiagnosed, no fix.

**Mitigation** (not a confirmed root-cause fix — no public fix exists to
confirm against): when `lms get`'s captured output matches `Invalid
passkey`, delete the cached `lms-key-2` file before the next retry. This
forces the next attempt down `createClient.ts`'s own missing-key/fresh-
refetch path instead of reusing a value already proven stale — the same
recovery pattern the CLI's own source already has for a first-ever run
with no key file yet, just triggered deliberately instead of waiting for
it to happen naturally. **Not yet verified against a live redeploy** — if
this recurs even after clearing the key on every retry, that points at
the background daemon itself (not just the cached file) as the real
source, which would need a bigger fix (recycling the `lms server start`
process) than current evidence justifies.

## `examples/` mounted via GCS bucket, matching local docker-compose (2026-07-06)

User asked whether `docker-compose.yml`'s bind mounts (`./examples:/app/examples`,
`./runs:/app/runs`) have Cloud Run equivalents. They don't — the root
`Dockerfile` only `COPY`s `micro_cosmos/`/`scripts/`/`pyproject.toml`;
`deploy_cloudrun-micro-cosmos-app.py` had zero volume mounts. Checked
`examples/` specifically (not assumed): `git ls-files examples/` showed
**514 real files** (~6.8MB, COBOL/Java/C#/etc. demo projects) that the
local `/demo` gallery displays via the bind mount. On Cloud Run,
`micro_cosmos/web/app.py`'s `/demo` route guards with `if examples_dir.is_dir()`
so it degrades to an empty gallery rather than crashing — but the built-in
examples are simply invisible, and `/demo/upload`'s writes land in
ephemeral, per-instance container storage.

User explicitly asked for a **mount** (not just baking `examples/` into the
image), matching the `micro-cosmos-lmstudio` model-cache pattern. Planned via
`EnterPlanMode`/`ExitPlanMode` given the real design decision involved (how
to seed an initially-empty bucket with the built-in files without
clobbering future user uploads), then confirmed by the user
("...same behaviour as in docker-desktop run for examples and load new
project from demo").

**Implementation:** new `ensure_examples_bucket()` in
`deploy_cloudrun-micro-cosmos-app.py` — direct copy of `ensure_model_bucket()`'s
create-if-missing + IAM-grant shape from `deploy_cloudrun-lmstudio-llms.py`,
plus a `gcloud storage rsync examples/ gs://$BUCKET --recursive` seed step
(verified syntax via WebSearch, not guessed) run on **every** deploy, not
just first creation. Bucket: `MICRO_COSMOS_EXAMPLES_BUCKET` (default
`$PROJECT-micro-cosmos-examples`), mounted at `/app/examples` — matches the
hardcoded `Path("examples")` in `app.py` (relative to `WORKDIR /app`), so
no application code changes needed. `deploy_service()` also gained
`--clear-volumes --clear-volume-mounts` preemptively (same lesson as the
LMStudio additive-mount bug earlier this session — applied proactively here
even though this is micro-cosmos-web's first-ever volume mount, so future
changes to the bucket/mount-path can't silently accumulate stale config).

**Why plain `rsync` (no `--delete-unmatched-destination-objects`) is the
right choice:** it only adds/updates files, never deletes — so anything a
user uploads later via the running app's `/demo/upload` (which won't exist
in the local `examples/` checkout) is never touched by the sync and
persists across redeploys. This is what actually delivers "same behavior
as docker-desktop" — the built-in gallery AND user uploads both survive,
where before this change *neither* did on Cloud Run.

**Explicitly out of scope (at the time):** `runs/` (`RUNS_DIR=/app/runs`) has the
identical gap — not yet mounted, still ephemeral per-instance storage —
but wasn't requested. Same fix pattern (bucket + mount, though without a
"built-in files to seed" step since runs/ is pure runtime output) would
apply if/when asked. Not yet exercised against a live deploy — flagged in
README as such, same as every other never-yet-verified piece this session.

**Superseded — see the "`runs/` mounted via GCS bucket" entry below.** This
was asked for on branch `feat/deploy-runs-gcs`.

## Container port standardized to match local docker-compose (2026-07-06)

User noticed `docker-compose.yml` runs LM Studio on `1234` and the micro-cosmos
app on `8080` locally, but Cloud Run defaulted `micro-cosmos-lmstudio` to `8080`
(no `--port` flag was ever set) — asked to make Cloud Run match the local
convention. Implemented: `DEFAULT_PORT = "1234"` in
`deploy_cloudrun-lmstudio-llms.py`, new `LMSTUDIO_PORT` env override,
`--port={port}` added to `deploy_service()`'s gcloud command.
`micro-cosmos-web` needed no change (already defaults to Cloud Run's `8080`,
matching docker-compose already).

**Important gotcha caught while implementing:** the `--startup-probe` flag
(added 2026-07-06, the GPU-cold-start fix) had `tcpSocket.port=8080`
hardcoded as a literal. Changing `--port` without also updating the probe
would have made the health probe check the wrong port and fail every
future deploy — the exact same class of self-inflicted bug as the
`--add-volume-mount` path mismatch earlier this session. Fixed by deriving
both `--port` and the probe's `tcpSocket.port` from the same `port`
variable so they can't drift apart again. `lmstudio-entrypoint.sh`'s `$PORT`
fallback (for running the image outside Cloud Run) also updated to `1234`
to match.

**Explicitly cosmetic, not functional:** the container port never appears
in `LLM_BASE_URL` (e.g. `https://micro-cosmos-lmstudio-xxxx.a.run.app/v1`)
— Cloud Run always terminates HTTPS on 443 externally and routes
internally to whichever port the service specifies. This change is purely
for environment parity/debugging consistency, not because anything was
broken. Documented in `deployment/README.md` ("Container port convention"),
`.claude/commands/deploy-gcp.md` step 12.

Also documented (code comment + README) why
`deploy_cloudrun-micro-cosmos-app.py`'s `SKIP_LLM=true` path sets
`lmstudio_url = "http://unused:1234/v1"`: a deliberately unresolvable
placeholder (not "localhost", so a future bug dialing it despite
`SKIP_LLM=true` fails loudly via DNS error rather than silently succeeding
against an accidental real host), needed only because
`micro_cosmos/settings.py`'s `llm_base_url` is a plain string field that
must be set to *something* even though deterministic mode never reads it.

## Default model changed to `google/gemma-4-31b-qat` (2026-07-03)

Explicit user instruction (not an env-var-override discussion like the
earlier Qwen3.6-27B case — this one directly changes the hardcoded default):
`DEFAULT_MODEL_ID` in `deploy_cloudrun-lmstudio-llms.py` and the
`MODEL_REASONING`/`MODEL_FAST` fallback strings in
`deploy_cloudrun-micro-cosmos-app.py` all moved from `google/gemma-4-12b` to
`google/gemma-4-31b-qat`. Per WebSearch (postdates training data): QAT
(quantization-aware training) variant, ~18GB at 4-bit vs ~20GB for a
naively-quantized model of similar size — moved `DEFAULT_ASSUMED_WEIGHTS_GB`
from `7.0` to `18.0` to match, per the standing rule that this constant must
track whichever model is actually the default (see the Qwen3.6-27B
"Switching models" entry above for why — `check_vram_fit()` silently checks
the wrong size otherwise). `qwen/qwen3.6-35b-a3b` (35B-total/3B-active MoE,
GGUF Q4_K_M ≈22.1GB — heavier than the dense `qwen/qwen3.6-27b` at the same
quant level, since MoE doesn't reduce weight VRAM) was added as a second
documented optional alternative in `deployment/README.md`, same treatment as
`qwen/qwen3.6-27b`. `micro_cosmos/settings.py`'s own defaults
(`google/gemma-4-e4b`) were deliberately left untouched — local/non-deployed
dev config, out of scope for "the deploy scripts."

## Production spec locked in: `qwen/qwen3.6-35b-a3b` @ context 131512 on `nvidia-rtx-pro-6000`, verified not guessed (2026-07-09)

After the `lms get`/`lms load` stall-and-hang fix above got the model
actually loading, user asked to raise `MODEL_CONTEXT_LENGTH` well past the
initial conservative `65536` (first to a proposed `132000`, then run in
production at `131512`). Before confirming this was safe, ran the
project's own `check_vram_fit()` KV-cache formula directly (not eyeballed):
at 131512 tokens, conservative (full-attention, worst-case) KV cache ≈
**20.1 GB**, against **73.9 GB** headroom (96 GB VRAM − 22.1 GB Q4_K_M
weights) on `nvidia-rtx-pro-6000` — ~27% of headroom used, with real usage
likely lower still given this model's mostly-linear (Gated DeltaNet)
attention. Also confirmed the model's native context window (262,144,
extensible to 1,010,000) isn't a limiting factor at this length. Full
math and the current copy-paste production spec block now live in
`deployment/README.md`'s "Example: qwen/qwen3.6-35b-a3b" section — not
duplicated here. Also flagged in that section:
`LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000` is now a **required** part of this
spec, not optional — an L4's 24GB VRAM would not fit this context length
regardless of quant.

## Third model option added: `google/gemma-4-12b-qat`, a genuinely lower-spec alternative (2026-07-10)

User asked for a lower-spec model option to document alongside the two
Qwen models, given `https://lmstudio.ai/models/google/gemma-4-12b-qat`.
Verified specs via three sources (LM Studio's model page, its Hugging Face
GGUF repo, Google's official Gemma 4 model card) rather than guessed: dense
11.95B params, 48 layers, hybrid attention that's almost entirely local
sliding-window (1024-token) — **only the final layer is full/global
attention**, an even more extreme local-attention skew than either Qwen
model's hybrid designs. Native context 256K. Only one GGUF quant is
currently published (Q4_0, ≈6.98GB, community-quantized by the LM Studio
team) — small enough to run on the cheaper default `nvidia-l4` (24GB
VRAM) rather than requiring `nvidia-rtx-pro-6000`.

Computed the VRAM math with the project's own conservative formula rather
than asserting fit, then user asked to document this model at its native
max context (`262144`) rather than the initial moderate `65536`. At that
length, `check_vram_fit()`'s naive formula (assumes every layer does full
attention) estimates ≈48GB of KV cache against only ≈17GB headroom (24GB
VRAM − 7.0GB weights) on `nvidia-l4` — **the deploy-time warning will fire
loudly and say this doesn't fit.** Did a second, per-layer calculation
given the actual architecture instead of stopping there: 47 layers capped
at the 1024-token sliding window (cache doesn't grow with context, ≈0.19GB
combined) + 1 genuinely global layer that does scale with context (≈1.0GB
at 262,144 tokens) = **≈1.2GB realistic total**, nowhere near the 17GB
budget. llama.cpp-based backends (what LM Studio runs on) implement
bounded KV cache for sliding-window layers correctly, so this realistic
number should be the one that matters in practice — but flagged explicitly
as more speculative than the Qwen recommendations, since this model hasn't
been deployed at all yet, unlike the Qwen models which have live-log
confirmation behind them. Full spec block, both calculations, and the
copy-paste example now live in `deployment/README.md`'s "Example:
google/gemma-4-12b-qat" section, not duplicated here. **Not yet deployed/exercised against a live project** —
this is a documented option, not a tested one.

## Global SKIP_LLM default flipped to True — Deterministic is now the whole-app default, not just a UI toggle (2026-07-10)

User asked for the `/demo`/`/` new-run toggle to default to Deterministic
instead of LLM. First attempt (hardcoding `skip_llm_default=True` directly
in `micro_cosmos/web/app.py`, independent of `Settings.skip_llm`) was correct
and side-effect-free, but the user reverted it and asked to do it via
`settings.py` instead — asked me to validate that approach before
proceeding.

**Real correctness problem found and flagged, not glossed over:**
`Settings` is a `pydantic_settings.BaseSettings` — any environment
variable present always overrides the Python-level field default. Both
`docker-compose.yml` (`SKIP_LLM: "false"`) and
`deploy_cloudrun-micro-cosmos-app.py` (`os.environ.get("SKIP_LLM", "false")`,
passed as an explicit `--set-env-vars`) set `SKIP_LLM` explicitly in every
real deployment — so changing only `settings.py`'s default would have been
a no-op in practice; the toggle would have kept showing LLM as default in
both environments. Presented this via `AskUserQuestion` rather than
silently agreeing.

User chose the broader option anyway: flip `Settings.skip_llm` to `True`
**and** update `docker-compose.yml`'s explicit value to `"true"` so it
actually takes effect locally. This is a whole-app default now, not just
the toggle — `micro_cosmos/retrieval/chat.py` (ASK tab → extractive-only
answers) and `micro_cosmos/retrieval/embedder.py` (embeddings disabled, lexical
fallback) read the exact same `Settings.skip_llm` field, so those default
to non-LLM behavior too now, everywhere `SKIP_LLM` isn't explicitly
overridden.

**Second real risk caught before applying it:** `deploy_cloudrun-micro-cosmos-app.py`'s
`os.environ.get("SKIP_LLM", "false")` fallback is exactly what every
`deploy.py`/`deploy_cloudrun-micro-cosmos-app.py` run this session has relied
on (none of them exported `SKIP_LLM` explicitly) — changing that fallback
to `"true"` too would have made the **next redeploy of the actual running
production `micro-cosmos-web`** silently revert to Deterministic mode, killing
the `qwen/qwen3.6-35b-a3b` LLM pipeline this whole session was spent
getting working, unless `SKIP_LLM=false` was remembered and exported
before every future deploy. Flagged this explicitly via a second
`AskUserQuestion` with concrete before/after previews. **User chose to
leave the Cloud Run fallback at `"false"`** — so production Cloud Run
deploys are unaffected by this change; only `docker-compose` (local dev)
and any environment with `SKIP_LLM` completely unset now default to
Deterministic. This also means the live `https://app.micro-cosmos.tools/demo`
toggle will keep defaulting to LLM mode, not Deterministic — the new
default only applies locally. Flagged this gap explicitly rather than
letting it go unnoticed.

## Real incident (2026-07-10): ephemeral disk migration tried and fully reverted — the 100GB figure was the wrong quota to look at

Full saga, in order: `micro-cosmos-lmstudio`'s model cache was migrated from
this GCS bucket to a Cloud Run **ephemeral disk** (commit `feff777`),
because live logs showed model downloads onto the GCS bucket never
reaching 100% even after the `lms get`/`lms load` retry/fail-fast fix
(previous entries above) — the working hypothesis was that `lms`'s
downloader, built around local-disk semantics, kept hitting friction
against GCS FUSE's object-storage semantics no matter the retry count.

The migration's disk size was first set to `300Gi` (requiring an explicit
Google Cloud quota increase, flagged as a hard manual prerequisite), then
reduced same-day to `100Gi` (commit `4a04ee0`) on the belief that 100GB
was Cloud Run's own default ephemeral-disk quota and needed no request at
all.

**That belief was wrong, confirmed by an actual live deploy failure, not
a doc re-read:** `gcloud beta run deploy` rejected `size=100Gi` outright
with `spec.template.spec.volumes: Total size of 'ephemeral-disk' volumes
cannot exceed 10 GiB`. The real quota structure: **10 GiB is the
hard per-service ceiling with no quota request** — the "100GB per
project/region" figure from Google's docs is a separate, higher-level
aggregate quota across the whole project, not something any single Cloud
Run service can consume by itself. Setting `LMSTUDIO_DISK_SIZE=100Gi` was
never actually free of the quota-increase requirement; the two numbers
were conflated when "simplifying" the config to avoid that manual step.
Since the current production model (`qwen/qwen3.6-35b-a3b`, Q4_K_M ≈22GB)
doesn't fit in 10GiB regardless of quant or config, **no version of the
ephemeral-disk approach for this model avoids a quota-increase request.**

**Decision: fully reverted, not re-tuned.** Given a quota increase is
unavoidable either way, chose to go back to the GCS bucket model cache
(`deployment/deploy_cloudrun-lmstudio-llms.py`, `.claude/commands/deploy-gcp.md`,
and this file all restored to their pre-`feff777` state) rather than pay
the Google quota-request wait for ephemeral disk. The bet: the original
GCS FUSE stall bug was traced specifically to **stale `.part` files**
forcing gcsfuse's slow "legacy staged writes" fallback (see the 2026-07-09
`lms get` stall entry above) — that diagnosis was never actually tested
against a **genuinely clean** bucket combined with the already-shipped
99x-retry/fail-fast entrypoint fix (`lmstudio-entrypoint.sh` needed no
changes for either migration direction — its retry logic is storage-backend-agnostic).
If a clean bucket + existing retry fix still stalls, that would be real
evidence GCS FUSE itself (not just stale files) is the root cause, and
the ephemeral-disk-plus-quota-increase path would need to be revisited —
but that hasn't been disproven, only untested with a clean starting
state.

**Manual step needed before the next deploy:** delete the stale bucket
contents so `lms get` starts genuinely fresh:
```bash
gcloud storage rm -r gs://$PROJECT-lmstudio-models/lmstudio-community/
```

**Lesson for next time a Google quota number gets quoted:** verify the
exact scope (per-instance vs per-service vs per-region vs per-project)
against an actual `gcloud` error or the specific quota's Console page —
"a limit exists" and "this specific request is under that limit" are two
different claims, and this incident is a direct example of conflating
them.

## Real incident (2026-07-10/11): `micro-cosmos-lmstudio` crash-loops on `lms load` with zero error text — an observability gap, not (necessarily) disk

Live incident, diagnosed from the actual Cloud Run revision YAML and log
timestamps the user pasted, not guessed. Symptom: `qwen/qwen3.6-35b-a3b` @
`MODEL_CONTEXT_LENGTH=131512` on `nvidia-rtx-pro-6000` downloads fine, then
crashes during `lms load` every time, consistently around 34-40% progress,
with `Container called exit(1)` and **no error text anywhere in the logs**.

**Ruled out, with evidence:**
- **Disk space** (the user's own first theory) — doesn't fit the mechanism.
  GGUF is memory-mapped and used directly in its quantized form (see the
  2026-07-09 "Production spec locked in" entry below); there's no
  decompress-to-N×-size step that would need extra local disk, and the
  download itself completes successfully every time.
- **Wrong GPU type** — the live revision's own YAML confirmed
  `nodeSelector.run.googleapis.com/accelerator: nvidia-rtx-pro-6000` (96GB
  VRAM) with `memory: 80Gi` host RAM, both already the correct/required
  values from the "Production spec locked in" entry — not `nvidia-l4`.
- **Startup-probe timeout** — the same YAML showed `Ready: True` about 2
  seconds *before* the crash timestamp, because `lms server start` binds
  `$PORT` before the model finishes loading (`lmstudio-entrypoint.sh:22-23`)
  — Cloud Run's probe is TCP-only and has no awareness of load progress.
  This is a genuine runtime crash-loop (Cloud Run just keeps restarting the
  container), not a startup failure.

**What actually stands out:** this exact model previously loaded
successfully on this same GPU type at a lower context (`65536`,
2026-07-09 entry below) — `131512` was only ever validated by
`check_vram_fit()`'s KV-cache arithmetic, never by an actual live load, and
this incident may be the first real attempt at that specific value.
Combined with `lms load` having **zero output capture** in the entrypoint
(a single unguarded line, unlike the `lms get` loop right above it which
already tees to a log file), there was no way to tell a VRAM/host-RAM
allocation failure apart from anything else from Cloud Run's logs — that
observability gap, not a confirmed root cause, is what produced the "must
be disk" guess.

**Fix, deliberately scoped to closing the observability gap:**
- `lmstudio-entrypoint.sh`: `lms load` now captured via `tee` to a log file
  under `pipefail` (same pattern as `lms get`), invoked with
  `CI=true NO_COLOR=1 TERM=dumb` (common conventions to disable animated
  spinner rendering — no documented `lms`-specific flag found) so real
  error text isn't overwritten by `\r`-driven progress frames before the
  container dies. On failure: prints exit code, last 50 captured lines, and
  model/context/gpu_layers/`GPU_TYPE`/`LMSTUDIO_VRAM_GB` to stderr before
  exiting with the original code. Verified the exit-code capture logic
  (`if pipeline; then ... else load_exit=${PIPESTATUS[0]}; ...; fi`, not
  `if ! pipeline; then load_exit=$?; ...; fi` — the latter's `$?` reflects
  the `!` negation, always 0, not the pipeline's real code) with a
  standalone `bash -c` harness against exit codes 0/1/42.
- `deploy_cloudrun-lmstudio-llms.py`: `deploy_service()` gained a `vram_gb`
  parameter; `--set-env-vars` now also passes `GPU_TYPE`/`LMSTUDIO_VRAM_GB`
  into the container (previously only `MODEL_ID`/`MODEL_CONTEXT_LENGTH`/
  `GPU_LAYERS` were passed) — the container had no way to report its own
  GPU type/VRAM in a crash diagnostic before this.
- Corrected a stale `GPU_DEFAULTS` comment claiming `nvidia-rtx-pro-6000`
  was "not yet exercised against a live deploy in this project" — it has
  been, successfully, at a lower context, since 2026-07-06.

**Not a code fix, recommended as the next diagnostic step:** redeploy once
with `MODEL_CONTEXT_LENGTH=65536` (last confirmed-working) to bisect
whether `131512` itself is the trigger. If the crash disappears, step up
gradually rather than jumping straight back to `131512`, and treat
`check_vram_fit()`'s estimate as unreliable for this model/context
combination until proven by a real load. If it still crashes at `65536`,
something else changed (image rebuild, bucket content, LM Studio version)
and the newly-captured diagnostic output is the next thing to read.

**Not yet verified against a live deploy** — no Cloud Run/GPU access in
that session. Verified via `bash -n`, a standalone `bash -c` PIPESTATUS
harness, and `ast.parse()` only.

## Follow-up (2026-07-11): the crash is `llama-server exitCode=127`, not VRAM/context — added `lms runtime`/`lms ps` diagnostics

The diagnostic-capture fix from the entry above worked exactly as intended:
the very next crash (bisection redeploy at `MODEL_CONTEXT_LENGTH=65536`, the
last confirmed-working value) surfaced real error text for the first time:
```
Error: Engine protocol runtime llama-server for QwBueDDT5P0WA+HGBkSS8zHI exited before becoming healthy. exitCode=127, signal=null
```
Crucially, this happened at the identical ~34-41% load progress at **both**
`131512` and `65536` — model loading proceeds layer-by-layer, and context
length only changes KV-cache *size*, not *which layer* is being loaded at a
given progress %, so the same crash point at two very different context
values rules out a context-length/VRAM-sizing cause. **This invalidates the
entry above's leading hypothesis** (untested `131512` context) — the real
cause is structural, not resource-sizing.

`exitCode=127` is the standard POSIX "command not found / exec failed" code.
`lms load` itself is fine — it's the **separate `llama-server` subprocess**
it spawns to actually run inference that can't execute at all. Verified via
LM Studio's own CLI docs (`lmstudio.ai/docs/cli/runtime/runtime`), not
guessed: `lms` manages inference backends as independently-installable
"runtimes" (`lms runtime ls/get/select/remove/update`), separate from the
`lms` CLI binary that `lms bootstrap` installs at image build time. Two
structural facts about this project's own pipeline line up with a
missing/mismatched runtime:
1. `Dockerfile.lmstudio`'s `RUN lms bootstrap` runs during a Cloud Build step
   with **no GPU attached** — hardware auto-detection can't identify
   `nvidia-rtx-pro-6000` (a newer Blackwell-class GPU) at build time, so
   whatever runtime `bootstrap` installs by default is unlikely to be the
   correct CUDA 13.0-compatible backend this GPU needs at runtime.
2. Only `$HOME/.lmstudio/models` persists on the GCS FUSE-mounted bucket
   (`deploy_cloudrun-lmstudio-llms.py:363`) — wherever `lms runtime` stores
   installed engine backends is not on that mount, so it resets to whatever
   was baked into the image on every fresh container start — making the
   failure 100% reproducible on every attempt regardless of model/context,
   exactly as observed.

Also found via WebSearch against `lmstudio-ai/lmstudio-bug-tracker`: multiple
open, unresolved issues (#1930, #1970, #1972) describe LM Studio's "Engine
Protocol runtime" — the exact subsystem named in this error — as a
recently-introduced, currently-buggy beta feature, including one report of
VRAM-detection failures on a newest-generation Blackwell consumer GPU (RTX
5090). No maintainer-confirmed fix or documented non-interactive CLI syntax
exists yet for disabling it or forcing a specific backend.

**Deliberately did not guess at exact `lms runtime get`/`select` flags
against a live, cost-incurring GPU deploy** — public docs confirm the
subcommands exist but not their non-interactive syntax, and picking the
wrong one risks wasting a GPU cold-start cycle or installing the wrong
backend. Shipped two safe pieces instead:
- `lmstudio-entrypoint.sh` now logs `lms runtime ls` and `--help` dumps for
  `lms runtime`/`get`/`select` at startup, before `lms get`/`lms load` run —
  read-only, can't hang, can't modify state — so the next deploy's Cloud
  Run logs contain the exact real runtime state and CLI flag syntax needed
  to write a correct install/select fix, instead of guessing again.
- Added an `lms ps` confirmation (LM Studio's own "list models currently
  loaded in memory" command) right after a successful `lms load` — the
  direct, authoritative answer to "is `llama-server` actually up and
  running," stronger than the existing TCP-only startup-probe check (which
  only proves `lms server start` bound a port, before any model load is
  attempted).

**Not yet fixed, not yet verified against a live deploy** — this pass adds
diagnostics and a confirmation mechanism, not the runtime-install fix
itself; that depends on reading this session's new `lms runtime ls`/
`--help` output from the next redeploy's Cloud Run logs.

## Follow-up 2 (2026-07-11): confirmed "No runtimes found" — installing the missing CUDA runtime

The diagnostics above worked immediately: live Cloud Run logs showed
`lms runtime ls` printing **`No runtimes found.`** — confirmed, not just
hypothesized: no inference-engine backend is installed at all. The
`--help` dumps captured the exact real CLI surface: `lms runtime get
[query]` (examples: `llama.cpp`, `llama.cpp:cuda`, `llama.cpp@1.2.3`) with
`-l/--list`, `--allow-incompatible`, `--channel <stable|beta>`, `-y/--yes`;
`lms runtime select [alias] [--latest]`; and `lms runtime survey` (hardware
compatibility detection).

**Judgment call, resolved via `AskUserQuestion`:** whether to pass
`--allow-incompatible` given `nvidia-rtx-pro-6000` is a very new
Blackwell-class GPU `lms`'s compatibility database may not yet recognize.
**User chose not to** — try compatible-only first; forcing an engine `lms`
itself flags incompatible risks a worse, harder-to-diagnose failure than
today's clean `exitCode=127`, or a silent degraded/wrong mode.

`lmstudio-entrypoint.sh`'s diagnostic block (before `lms get`/`lms load`)
now: kept `lms runtime ls`; replaced the `--help` dumps (already captured
here, no longer needed every container start) with `lms runtime survey`
and `lms runtime get llama.cpp -l` (lists available variants without
downloading); added the real install attempt `lms runtime get
llama.cpp:cuda -y < /dev/null`, captured via `tee` with the same
`PIPESTATUS[0]`-in-else exit-code pattern as `lms load`; and a confirming
`lms runtime ls` afterward. Best-effort throughout — failure is logged but
doesn't abort the entrypoint, since `lms get`/`lms load` were already going
to fail without this change.

**Not yet verified against a live deploy** — no Cloud Run/GPU access in
this session. Real proof requires a redeploy: read `survey`/`get -l`
output for compatibility, confirm the install succeeds, and whether `lms
load` gets past ~41% this time.

## Engine switch (2026-07-11): `micro-cosmos-lmstudio` moved from LM Studio to vLLM for `nvidia-rtx-pro-6000` — Gemma-4-31B, `google/gemma-4-31B-it-qat-w4a16-ct`

**Superseded same day — see "Model reconsidered" entry below.** The model
default here was replaced with `Qwen/Qwen3.6-35B-A3B-FP8`. The engine
decision (vLLM, `nvidia-rtx-pro-6000`, ruling out `cu130-nightly`/SGLang/
`voipmonitor/*`) is unchanged — only the model choice and its VRAM math
were revised.

The follow-up install attempt above also failed on the next live redeploy:
`lms runtime get llama.cpp:cuda -y` → `No runtime extensions matched the
query`. Combined with `lms runtime survey` → `No runtime survey results`
and `lms runtime get llama.cpp -l` listing only a CPU-only
`llama.cpp-linux-x86_64-avx2` build as available — **there is no
CUDA-flavored `llama.cpp` runtime for this GPU at all**, confirmed, not a
config gap to work around. User decided to abandon Qwen3.6/LM-Studio for
this GPU and switch engines to **vLLM**, defaulting back to a **Google
Gemma-4 model** (this repo's documented primary default family), scoped
first to one model end-to-end (own chosen sequencing, via
`AskUserQuestion`) before generalizing to others.

**Model + quantization chosen, and why:** `google/gemma-4-31B-it-qat-w4a16-ct`
— official Google QAT checkpoint, `compressed-tensors` (w4a16) format.
Confirmed via its own HF model card: **ungated, Apache 2.0**. The
NVFP4-quantized alternative found first (`nvidia/Gemma-4-31B-IT-NVFP4`,
from a directly-relevant dual-RTX-PRO-6000 reference) is **gated** — user
doesn't have license access, so it's ruled out. w4a16 also sidesteps
NVFP4's real Blackwell gotchas found in that reference
(`--disable-custom-all-reduce` mandatory since the custom kernel doesn't
support cc 12.0; `VLLM_NVFP4_GEMM_BACKEND=cutlass`; `cu130` specifically
documented broken — "CUDA 13.0 fails with custom_all_reduce crashes on cc
12.0," they used `cu129-nightly` instead) — verified via vLLM's own GitHub
issues that w4a16 uses a different, more portable kernel path (Marlin) not
affected by the SM120 gaps found for NVFP4/W4A8/MXFP4. Single GPU (not
dual, like that reference) removes the all-reduce concern entirely — no
tensor parallelism means no all-reduce communication regardless of
quantization format.

**Also investigated and ruled out**: `vllm/vllm-openai:cu130-nightly` and
`lmsysorg/sglang:dev-cu13`/`:blackwell` (SGLang) — `cu130-nightly` doesn't
exist as a stable pinnable tag; SGLang's own Blackwell tracker
(`sgl-project/sglang#5338`) only confirms DeepSeek V3/Llama 4 on this GPU,
not Qwen3.6; a real open SGLang bug (discussion #9543) shows standard
sgl-kernel wheels lack some SM120 kernels; community `voipmonitor/*` images
are unofficial personal builds with daily-rotating, unpinnable tags — too
much unverified risk for production.

**Real VRAM math** (computed from `nvidia/Gemma-4-31B-IT-NVFP4`'s actual
`config.json` — same base dense architecture as the w4a16 checkpoint): 60
layers, hybrid local/global attention (5 sliding-window + 1 full-attention
layer, repeating — 10 full-attention layers total, 1024-token sliding
window on the other 50 whose KV cache doesn't grow with context), 16 KV
heads, head_dim 256, native context 262,144.
- Full-attention KV cache (bf16): `2×10×16×256×2 = 160KB/token` → **~40.0
  GB at the full native context 262,144**.
- Sliding-window layers: ≈0.8GB, negligible.
- Weights (w4a16, ~34B params): ≈**17GB**.
- **Total ≈57.8GB** vs 96GB×0.9 utilization = 86.4GB budget — **~28.6GB
  headroom**, comfortable even at full native context (not the dual-GPU
  NVFP4 reference's rough, unbenchmarked "~90K tokens" single-GPU guess —
  this is a real per-architecture calculation, verified by running the
  actual `estimate_kv_cache_gb()` function added to the new deploy script:
  reproduces 40.00GB/57.00GB/29.40GB headroom exactly).
- `--kv-cache-dtype bfloat16` set explicitly, not `auto` (which the NVFP4
  reference found resolves to `fp8_e4m3` with an uncalibrated `scale=1.0`).

**Implementation** — new, parallel path, LM Studio path left intact:
`deployment/Dockerfile.vllm` (thin wrapper around
`vllm/vllm-openai:cu129-nightly`, floating tag — pin to a digest once
confirmed working), `deployment/vllm-entrypoint.sh` (env-var-driven `vllm
serve`, `HF_HOME` on the GCS-FUSE mount for cache persistence, `tee`-captured
diagnostics matching `lms load`'s pattern), `deployment/deploy_cloudrun-vllm-llms.py`
(modeled on `deploy_cloudrun-lmstudio-llms.py`'s structure,
`DEFAULT_GPU_TYPE="nvidia-rtx-pro-6000"` since this model needs the 96GB
card). **`SERVICE_NAME` deliberately stays `"micro-cosmos-lmstudio"`** — same
Cloud Run service, only the image/entrypoint swap, so
`discover_lmstudio_url()` in `deploy_cloudrun-micro-cosmos-app.py` needs no
changes (both engines expose an OpenAI-compatible `/v1` API). The
script-says-vllm/service-still-named-lmstudio mismatch is a deliberate,
flagged follow-up rename. `deployment/deploy.py` gained `LMSTUDIO_ENGINE=vllm`
to opt into this path (defaults to `lmstudio`, unchanged behavior).

**Startup-probe assumption, not yet confirmed**: vLLM's server likely
doesn't bind its port until the model is already loaded (unlike LM Studio's
split bind-then-load design that needed a custom TCP-then-poll dance), so
the existing TCP-only startup probe should reflect real readiness with no
extra health-check logic — to be confirmed on first live deploy, per this
session's repeated finding that real behavior on this hardware differs
from documentation.

**Deferred, not forgotten**: MTP/speculative decoding; generalizing to the
other 4 models discussed (`gemma-4-26b-a4b-qat`, `gemma-4-12b-qat`,
`qwen3.6-35b-a3b`, `qwen3.6-27b`) via a per-model config table, once this
one is proven working.

**Not yet verified against a live deploy** — no Docker/Cloud Run/GPU access
this session.

## Model reconsidered (2026-07-11): vLLM default switched Gemma-4-31B → `Qwen/Qwen3.6-35B-A3B-FP8` — plus two real app-level bugs found and fixed

Before the Gemma-based vLLM path above was ever deployed, user asked
directly whether it's actually optimized for this pipeline's use case
(coding translation) — checked via WebSearch rather than assumed. Most
comparison sites found are SEO/content-farm, low-confidence — but the
directional finding held across independent searches and matches this
repo's own already-verified claim that Qwen3.6 is "benchmarked specifically
on coding/agentic tasks (SWE-bench, Terminal-Bench)," a closer match to
this pipeline's iterative, tool-calling TDD loop than Gemma 4's strength on
isolated code generation (HumanEval/MBPP). The original reason Qwen3.6 was
dropped (no LM Studio CUDA runtime for this GPU) was specific to
`llama.cpp`, not vLLM — `Qwen/Qwen3.6-35B-A3B-FP8` (already confirmed
ungated + vLLM-compatible from earlier research) sidesteps that blocker
entirely. Presented via `AskUserQuestion`; user chose to switch.

**Real VRAM math, redone for this model's actual architecture** (from its
own `config.json`, not reused from Gemma's): 40 layers, 10 full-attention
among 30 linear-attention (Gated DeltaNet) layers, only **2 KV heads**
(extreme GQA, vs Gemma's 16) → `2×10×2×256×2 = 20KB/token` → **~5.0GB KV
cache at full native context 262,144** (vs Gemma's ~40.0GB) + ~35GB FP8
weights = **~40.0GB total**, ~46.4GB headroom on 96GB×0.9 — *more*
comfortable than Gemma's ~28.6GB despite more total params. Verified by
running `estimate_kv_cache_gb()` after updating its constants.

**Implementation**: `deploy_cloudrun-vllm-llms.py`'s defaults updated
(`DEFAULT_MODEL_ID`, `DEFAULT_ASSUMED_WEIGHTS_GB=35.0`,
`DEFAULT_KV_HEADS=2`, new `DEFAULT_REASONING_PARSER="qwen3"`).
`vllm-entrypoint.sh`: removed the hardcoded `--quantization compressed-tensors`
flag (Gemma-specific, would've been silently wrong for Qwen's `fp8`
checkpoint — exactly the kind of bug this pre-empts) in favor of vLLM's
own auto-detection from the checkpoint's HF config; added a conditional
`--reasoning-parser` (only passed when set, so it doesn't break a
non-Qwen model).

**Two real bugs found while double-checking `micro_cosmos/settings.py`
alignment** (user asked directly, checked rather than assumed):
1. `micro_cosmos/orchestration/driver.py`'s `_wait_for_llm_ready()` only
   knew LM Studio's native `/api/v0/models` endpoint — doesn't exist on
   vLLM, would have hung the pipeline's pre-flight readiness wait on every
   vLLM-backed run. Fixed: falls back to plain `/v1/models` on any non-200
   from the native endpoint. Verified with a mocked async harness (both
   backend shapes).
2. `deploy_cloudrun-micro-cosmos-app.py` independently defaulted
   `MODEL_REASONING`/`MODEL_FAST` to `"google/gemma-4-31b-qat"`, and
   `deploy.py` didn't pass the GPU service's actual model through — so
   `LMSTUDIO_ENGINE=vllm python deploy.py` without manually exporting
   `MODEL_REASONING` would silently deploy vLLM with Qwen3.6 while telling
   `micro-cosmos-web` to request a Gemma model that doesn't exist there (vLLM,
   unlike LM Studio, rejects any other model ID outright). Fixed:
   `deploy.py` now resolves one model ID from the selected engine's own
   default and passes it to both deploys. **Not fixed for standalone
   `deploy_cloudrun-micro-cosmos-app.py` invocation** — can't safely
   auto-discover the real served model (`micro-cosmos-lmstudio` is
   `--ingress=internal`); documented as an operator responsibility instead.

Full doc sweep done per [[feedback_deploy_changes_sync]] — `deployment/README.md`,
`changes-log.md`, `.claude/commands/deploy-gcp.md` all now describe
Qwen3.6-35B-A3B-FP8 as the vLLM default.

**Not yet verified against a live deploy** — no Docker/Cloud Run/GPU access
this session.

## Known uncertainty — verify before trusting on a live project

- **GPU region**: defaults to `europe-west4` for `LMSTUDIO_REGION`/
  `GOOGLE_CLOUD_LOCATION`, believed Cloud Run GPU (L4)-capable, but Cloud Run
  GPU region support changes over time. Always verify with
  `gcloud run regions list` and check GPU quota before deploying — don't
  assume the default region is still correct without checking.
- **gcloud flag syntax**: `--gpu`, `--gpu-type`, `--no-cpu-throttling`,
  `--add-volume`/`--add-volume-mount` (GCS FUSE) are based on documented
  Cloud Run features but have **not been exercised against a live GCP
  project**. If a real deploy run surfaces a flag syntax error, that's
  expected risk, not a sign the whole approach is wrong — check
  `gcloud run deploy --help` for the current exact flag name/syntax.
- Sizing: 32Gi RAM requires 8 vCPU on Cloud Run (GPU memory/CPU coupling);
  5Gi RAM requires ≥2 vCPU (using 4 vCPU for pipeline responsiveness).
- **Context length vs GPU VRAM**: `MODEL_CONTEXT_LENGTH` default is `262144`.
  `--memory=32Gi` on the LMStudio service is host RAM, not GPU VRAM — the L4's
  24GB VRAM is fixed by GCP and does not grow with `--memory`/`--cpu`. At this
  context length, KV cache alone will very likely exceed a single L4's VRAM
  budget for almost any model. `deploy_cloudrun-lmstudio-llms.py` runs
  `check_vram_fit()` at deploy time and prints a loud (non-blocking) warning.
  `LMSTUDIO_GPU_LAYERS` (default `max`) is the lever that actually uses host
  RAM productively here — set it to a partial layer count to spill excess
  layers/KV cache into host RAM instead of GPU VRAM, at a real inference-speed
  cost. See the "Context length vs GPU VRAM" section in `deployment/README.md`
  for the full option list.
- **NVIDIA RTX PRO 6000 Blackwell GPU option (added 2026-07-03)**:
  `LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000` (96GB VRAM vs L4's 24GB) is now
  supported via `GPU_DEFAULTS` in `deploy_cloudrun-lmstudio-llms.py` — auto-
  applies the Cloud-Run-enforced 20 vCPU/80GiB minimum, routes through
  `gcloud beta run deploy` (preview feature), and required bumping
  `Dockerfile.lmstudio`'s base image to `nvidia/cuda:12.8.2-runtime-ubuntu22.04`
  (from `12.4.1`) per NVIDIA's CUDA>12.2-needs-newer-image guidance for this
  GPU's 580.x/CUDA 13.0 driver. Region availability is narrower than L4:
  `asia-southeast1`, `asia-south2`, `europe-west4`, `us-central1` — this
  project's default region is supported. **Live-deployed repeatedly since
  2026-07-06** (container start, FUSE mount, and model download all
  confirmed working) — the currently open, unresolved question is a
  `llama-server exitCode=127` crash during `lms load` itself (see the
  "Real incident (2026-07-10/11)" and its exitCode=127 follow-up entries
  below), not whether this GPU path can be deployed at all. Default GPU
  type remains `nvidia-l4` (opt-in only, not a default change) — see "GPU
  type" in `deployment/README.md`.

## Two more real vLLM-compatibility gaps found proactively, plus LM Studio default changed to `google/gemma-4-e4b`/`nvidia-l4` (2026-07-11)

User asked directly whether `micro-cosmos-web` is actually confirmed compatible
with vLLM and to fix issues in advance — checked further rather than
declaring the earlier two fixes sufficient.

**Gap 1 — tool calling silently breaks on vLLM without explicit flags.**
This pipeline's ADK agents rely entirely on OpenAI-style function calling.
Verified via vLLM's own tool-calling docs: unlike LM Studio, vLLM does not
parse tool calls out of a model's output unless `--enable-auto-tool-choice
--tool-call-parser <name>` is passed — without it, every tool-using agent
would silently break (tool calls return as plain text, not structured
`tool_calls`). Fix: `vllm-entrypoint.sh` gained conditional
`VLLM_TOOL_CALL_PARSER` (default `hermes` — vLLM's documented general
parser for Qwen3-class models; Qwen3.6 specifically not confirmed, verify
on first live tool call), same conditional pattern as
`VLLM_REASONING_PARSER`.

**Gap 2 — `extra_body={"num_ctx": ...}` would break every vLLM request.**
`micro_cosmos/settings.py`'s `build_llm()` unconditionally sent this LM
Studio/llama.cpp-specific parameter. Verified via vLLM's own GitHub
discussion ("Why has vLLM such a strict schema definition?"): vLLM's
OpenAI endpoint rejects unrecognized top-level fields, and
`drop_params=True` does NOT strip `extra_body` contents. Fix: new
`Settings.llm_engine` field (`LLM_ENGINE` env var, default `lmstudio`) —
`build_llm()` only includes `extra_body` when `llm_engine == "lmstudio"`.
Threaded through `deploy_cloudrun-micro-cosmos-app.py` and `deploy.py` the same
"resolve once, pass explicitly to both deploys" way as `model_reasoning`.

**Separate request — LM Studio's own default confirmed/fixed.** User asked
whether zero-env-vars deploys `google/gemma-4-e4b` on `nvidia-l4`; it
didn't (`DEFAULT_MODEL_ID` was still `google/gemma-4-31b-qat`, GPU type was
already correct). Changed `deploy_cloudrun-lmstudio-llms.py`'s
`DEFAULT_MODEL_ID` to `google/gemma-4-e4b` (matches `micro_cosmos/settings.py`'s
own local `docker-compose` default — now one universal default),
`DEFAULT_CONTEXT_LENGTH` to `131072` (this model's real native max — LM
Studio's model page confirms 128K; the old `262144` was sized for the 31B
model), `DEFAULT_ASSUMED_WEIGHTS_GB` to `5.0` (conservative, unconfirmed —
no exact GGUF size published). Also fixed
`deploy_cloudrun-micro-cosmos-app.py`'s own independent standalone-invocation
fallback to match. Confirmed end-to-end via direct inspection of resolved
constants, not just asserted.

**Not yet verified against a live deploy** for any of these — no
Docker/Cloud Run/GPU access this session.

## Confirmed live + PR #12 follow-up: `Dockerfile.vllm` pinned off `cu129-nightly` (2026-07-13)

Real, live deploys since the entries above confirmed the vLLM path
works end-to-end: `MIN_INSTANCES=1` fix verified in the live revision YAML
(`autoscaling.knative.dev/minScale: 1`), and every log line the user
walked through individually (non-default args showing `tool_call_parser`/
`reasoning_parser` correctly applied, the ulimit warning, the `Unknown
vLLM environment variable` ×2 naming-collision warnings, the
unauthenticated-HF-Hub warning, the DeepGemm-auto-disabled-on-Blackwell
line) were each evaluated and confirmed expected/harmless, not active
problems.

PR #12 review flagged one non-blocking follow-up: pin `Dockerfile.vllm`'s
floating `cu129-nightly` tag now that it's confirmed working. Real
complication: the tag had already moved since the 2026-07-11/12 deploys
(Docker Hub showed it last updated 2026-07-13 — these nightly builds
rebuild roughly daily), so the *exact* historical digest can't be
reconstructed without Cloud Build's own logs (not accessible this
session). Presented the tradeoff via `AskUserQuestion`; user chose to pin
to the freshly-resolved current digest, having already independently
confirmed a redeploy on it works. `Dockerfile.vllm` now pins
`FROM vllm/vllm-openai@sha256:e271b70a...` instead of the floating tag —
closes off silent-drift risk; re-pinning is now a deliberate,
re-verified action, not automatic.

Also added (separate follow-up, same session): optional `HF_TOKEN` for
the vLLM deploy (raises HuggingFace's unauthenticated rate limit; not
required for this ungated model), with a `redact` mechanism added to
`deploy_cloudrun-vllm-llms.py`'s `run()` helper so a real token value
can't leak into cleartext terminal output if the `gcloud run deploy`
command itself ever fails for an unrelated reason — verified via a
standalone harness (deliberately-failing command echoing a fake secret,
confirmed scrubbed from output).

## Real incident (2026-07-13): LM Studio readiness check never sent its API key — every LLM-mode run silently stuck for the full timeout

Found via `/debug-run` on a real stuck local run (`99d1e308`): only
`run_meta.json` existed on disk minutes in, no `ir_graph.json` — Observer
never started. Live evidence, not guessed: `curl` against
`http://localhost:1234/v1/models` (both from inside the micro-cosmos container
and directly from the host, ruling out any Docker-networking angle)
returned a real `401 invalid_api_key` — LM Studio's own "Require
Authentication" server setting was on for this local instance, and neither
of the readiness probe's two endpoints (`/api/v0/models`, `/v1/models`)
had ever been sent an `Authorization` header.

**Root cause**: `_wait_for_llm_ready()` in
`micro_cosmos/orchestration/driver.py` — added 2026-07-11 for the LM
Studio/vLLM engine-detection fallback (see the "Model reconsidered" entry
above) — built its own bare `httpx.AsyncClient()` with no auth header at
all, unlike `build_llm()` which already sends `llm_api_key`
correctly for real completions. Every poll of both endpoints got 401
forever, so the function could never observe a 200, and the pipeline sat
at "[LMStudio] waiting for `<model>` to load…" for the entire
`llm_ready_timeout_seconds` (1500s default) before giving up and
proceeding anyway with just a warning. Not a crash, not a missing
artifact from an exception — a silent, fully-explained-by-the-code stall.

**Verified before and after the fix, not just patched and moved on**:
confirmed the `.env`'s `LLM_API_KEY` was already the *correct* token
(direct `curl` with it returned 200 + the real model catalog) — so this
was purely a missing-header bug, not a bad key. Fix: `api_key` parameter
added to `_wait_for_llm_ready()`, sent as `Authorization: Bearer` on
both probes; call site passes `settings.llm_api_key`. Verified with
a standalone `httpx.MockTransport` harness (function body copied verbatim
to dodge the `google-adk` import chain) across 4 scenarios: no key vs.
auth-requiring server (times out, reproducing the bug), correct key
(ready), wrong key (still correctly times out, not a false-ready), vLLM
fallback path with a key (ready) — all passed.

## Follow-up (2026-07-13): `LLM_API_KEY` made real end-to-end — enforceable on vLLM, confirmed unenforceable on LM Studio

Prompted by the incident above, user asked for this key to be genuinely
configurable and enforced (not just sent hopefully) across docker-compose
and both Cloud Run engines.

**vLLM: fully wired.** `vllm serve --api-key <key>` is a real, documented
flag (confirmed via vLLM's own docs). `vllm-entrypoint.sh` reads
`VLLM_API_KEY` → conditional `--api-key`. `deploy_cloudrun-vllm-llms.py`
threads a new `api_key` param through `deploy_service()`/`deploy_vllm()`,
resolved from the **same** `LLM_API_KEY` env var `micro-cosmos-web`
already reads (one shared secret, not a second name) — `run()`'s `redact`
param extended from a single string to a list so both `hf_token` and
`api_key` get scrubbed from failure output.

**LLM: confirmed impossible headlessly, not left as an open gap.**
Checked via WebSearch against LM Studio's own docs/issue tracker first:
`lms server start` has no CLI flag for "Require Authentication" — GUI-only
(open, unresolved: `lmstudio-ai/lms#489`). A Cloud Run container never has
a GUI session, so this can't be enabled for `micro-cosmos-lmstudio` when
`LMSTUDIO_ENGINE=lmstudio`, full stop — `--ingress=internal` stays the
only real boundary for this engine. Documented explicitly in
`deploy_cloudrun-lmstudio-llms.py`'s docstring, with an explicit warning
against guessing an undocumented `lms` config-file workaround (this
session's own `--host`/`lms pull` incidents are the standing lesson for
why not to guess `lms` CLI behavior).

`deploy.py` resolves `LLM_API_KEY` once and passes it to
`deploy_micro_cosmos()` always, and to `deploy_vllm()` only when the engine is
vllm. `.env.example`'s comment corrected — it previously implied any dummy
value works; a real, exactly-matching token is required whenever local LM
Studio's own auth toggle is on, which is exactly what this incident hit.

## Follow-up (2026-07-13): composed-URL / `200 OK` logging added, `MICRO_COSMOS_LOG_LEVEL` documented

Direct consequence of the incident above: it took a live `curl` from the
host, bypassing the app entirely, to discover the 401 — nothing in
`docker compose logs` said anything about it, because `_wait_for_llm_ready()`
never logged the URLs it was hitting or the status codes it got back.
User asked for logging on exactly those composed URLs (`native_url`,
`openai_url`), then broadened to "every place the web app talks to the
lmstudio machine (vllm or lmstudio flavour)," then to explicit `200 OK`
lines (not just errors).

**Every runtime call site that composes a URL to the GPU service now
logs it**, via loggers that are children of the `micro-cosmos` root logger
already configured in `micro_cosmos/__init__.py` (same handler as
`micro_cosmos.diagnostics` — inherits automatically, no per-module setup):

| Site | Logs |
|---|---|
| `driver.py`'s `_wait_for_llm_ready()` | `native_url`/`openai_url` at wait-start; `GET <url> -> 200 OK — <state>` per successful poll; a `WARNING` naming `LLM_API_KEY`/`VLLM_API_KEY` specifically on a 401 (this is the line that would have made the original incident a 10-second log read instead of a live-`curl` investigation); final ready/timeout |
| `settings.py`'s `build_llm()` | composed `api_base`, model, engine, whether an API key is configured — fires once per agent's LLM construction |
| `embedder.py`'s `build_embedder()`/`embed()` | composed embedding `api_base` + model; `POST .../embeddings -> 200 OK (N text(s))` after each successful call |
| `chat.py`'s ASK-tab completion | composed `api_base` + model before the call; `POST <url> -> 200 OK` after |

None log the actual API key value, only `api_key_configured=True/False`.

**`MICRO_COSMOS_LOG_LEVEL`** (`micro_cosmos/__init__.py`, default `INFO`) is the one
knob for both environments — same stderr handler, captured automatically
by `docker compose logs` and `gcloud run services logs read`, no
per-environment log-shipping config needed:
- `DEBUG` — adds a line for every individual readiness-check poll, even
  when nothing changed (verbose; meant for actively debugging a stuck run).
- `INFO` (default) — composed URLs, `200 OK` responses, state transitions.
- `WARNING` — 401s, readiness timeout, gate retries (see
  `micro_cosmos/diagnostics.py`'s own severity tiers for the broader pipeline).
- `ERROR` — pipeline-halting failures only.

Verified the readiness-check logging live via a standalone
`httpx.MockTransport` harness (function body copied verbatim, same
technique as the incident's own fix verification) — confirmed the
`200 OK` line fires at `INFO` with no `MICRO_COSMOS_LOG_LEVEL` override needed,
and the 401 path logs the `LLM_API_KEY`-naming warning before
falling back/retrying.

Documented in `deployment/README.md`'s new "Logging" section (config-table
row + full level table) and a shorter pointer added to the top-level
`README.md`'s Configuration section.

## Bug fix (cosmetic, 2026-07-13): `VLLM_TOOL_CALL_PARSER`/`VLLM_REASONING_PARSER` renamed — found via the logging above, on a real production log

Direct payoff of the logging work above: a real Cloud Run log for a live
vLLM deploy showed `WARNING [envs.py:2094] Unknown vLLM environment
variable detected: VLLM_TOOL_CALL_PARSER` and `VLLM_REASONING_PARSER` —
but the same log's `non-default args` line confirmed
`tool_call_parser: 'hermes'`, `reasoning_parser: 'qwen3'`, and
`api_key: ['micro-cosmos-demo1']` all correctly reached `vllm serve`.
So nothing was actually broken — this is vLLM's own env-var scanner
(`vllm/envs.py`) flagging any `VLLM_*`-prefixed name it doesn't itself
recognize. `VLLM_TOOL_CALL_PARSER`/`VLLM_REASONING_PARSER` were never real
vLLM env vars — they're this repo's own `vllm-entrypoint.sh` convention
(read by the entrypoint, translated into real `--tool-call-parser`/
`--reasoning-parser` CLI flags before `vllm serve` runs), and just
happened to collide with vLLM's reserved prefix. (`VLLM_API_KEY`, also
added this session, is NOT affected — it's a real, vLLM-documented env
var vLLM reads natively, confirmed via vLLM's own docs; no warning for it
in the same log.)

**Fix: renamed to `LMSTUDIO_TOOL_CALL_PARSER`/`LMSTUDIO_REASONING_PARSER`**
— matches this repo's existing convention of `LMSTUDIO_*` for GPU-service
config that applies regardless of which engine is actually deployed
(`LMSTUDIO_GPU_TYPE`, `LMSTUDIO_ASSUMED_WEIGHTS_GB`,
`LMSTUDIO_STARTUP_TIMEOUT_SECONDS`, etc. — the service name, not the
engine name). Pure rename, no behavior change — same conditional
"omit when unset" logic in `vllm-entrypoint.sh`, same threading through
`deploy_cloudrun-vllm-llms.py`'s `deploy_service()`/`deploy_vllm()`.

**Confirmed scoped to the vLLM deploy path only, not guessed:** grepped
the whole repo for both old names before touching anything — zero
references in `docker-compose.yml`, `.env.example`, or any `micro_cosmos/*.py`
app code. Neither the LM Studio engine path nor `micro-cosmos-web`'s own
deploy script needed any change. Historical entries above (and
`changes-log.md`'s past entries) still use the old `VLLM_*` names — left
as-is since they accurately describe what was true/named at that time;
this entry and the code are what's current now.

## Feature + open concern (2026-07-13): `llm_ready_timeout_seconds` floored at 25 min (same as the default) — corrected same-day from an initial 16-min floor

User asked to guarantee the app-level readiness wait gives Cloud Run
"enough ground [minimum] time" to provision a fresh GPU instance before
giving up, worried a misconfigured short timeout could race ahead of a
genuine cold start. Presented via `AskUserQuestion` (options: enforce a
floor / lower to exactly 10 min / check Cloud Run's own instance status
via its Admin API); user initially chose a 16-minute floor (960s), keeping
the existing 25-minute default/ceiling untouched — reasoned as "headroom
above the ~11-12 min cold start measured earlier the same day."

**Corrected same-day, before ever shipping**: once the fresh-`CreateService`
evidence below (16m38s just to bind the port, before model loading even
starts) showed a worst-case deploy could approach the *full* 25 minutes,
the user called the 16-minute floor pointless — a floor meaningfully below
the ceiling doesn't protect against the actual worst case at all, only
against a much smaller subset of misconfigurations. **Rolled back to a
1500s (25 min) floor — i.e. the floor now equals the default/ceiling
exactly, so `LMSTUDIO_READY_TIMEOUT_SECONDS` can never be configured below
the one value already known to be needed.**

**Implementation**: `micro_cosmos/settings.py`'s
`_MIN_LLM_READY_TIMEOUT_SECONDS = 1500` and a `field_validator` on
`llm_ready_timeout_seconds` that clamps any lower value up to the
floor, logging a warning naming the actual vs. floored value. Verified
against real `pydantic` (not just `ast.parse` — this session's usual
minimum bar), by copying the updated file into the *running* local
container (which already has the real dependency set installed) and
exercising all five cases directly: default (1500) passes through,
below-floor (60 and 1499) both clamp to 1500 with the warning logged,
exactly-at-floor (1500) passes through unchanged, above-floor (2000)
passes through unchanged. Re-verified after the 960→1500 correction, not
just assumed still-correct.

**Real, concerning evidence that drove the correction, from a live
`micro-cosmos-lmstudio` Cloud Run log** (revision `micro-cosmos-lmstudio-00001-hm8`,
a genuinely fresh `CreateService`, not just a revision update): the
`STARTUP TCP probe succeeded after 91 attempts` — at the configured
`periodSeconds=10`, that's **~15.2 minutes** before the container even
bound port 1234, and the Cloud Run audit log independently confirms
`"Deploying revision succeeded in 16m37.94s"` — all of this *before* vLLM's
model loading even starts (which itself takes another ~10-12 min per the
earlier measurement). A worst-case genuinely-fresh deploy could therefore
plausibly total **~27-29 minutes** end-to-end — at or beyond the 1500s
(25 min) ceiling itself. (This also means the *ceiling* may need revisiting
too, in a future pass — not done here, since the user's explicit ask this
round was only to fix the floor.)

**Also concerning, not yet explained**: this same revision's log shows
**zero `EngineCore`/model-loading activity for the 44 minutes** between
becoming Cloud-Run-"Ready" (15:12:41) and the last log line pasted
(15:56:10) — only periodic GCS-FUSE garbage-collection heartbeats
("0 objects deleted" each time). Meanwhile, a real pipeline run submitted
from `micro-cosmos-web` at 15:47:31 (run `45e187b6`) was still showing
`[LMStudio] waiting for Qwen/Qwen3.6-35B-A3B-FP8 to load…` in its trace
well after that point — i.e. the readiness check never saw a 200. Two
competing explanations, not yet distinguished:
1. **Stale/mismatched `LLM_BASE_URL`** — if `micro-cosmos-lmstudio` was
   genuinely re-created (not just updated) between when `micro-cosmos-web` was
   last deployed and this run starting, `micro-cosmos-web`'s baked-in env var
   could point at a URL that no longer resolves to anything live — a
   permanent 404 that no amount of waiting fixes. Verify: compare
   `micro-cosmos-web`'s current `LLM_BASE_URL` against
   `gcloud run services describe micro-cosmos-lmstudio --format='value(status.url)'`.
2. **The model genuinely never loads on this revision** — vLLM's
   `APIServer` (HTTP process) coming up cleanly (confirmed: Uvicorn's own
   "Application startup complete" logged, TCP probe passes) does not by
   itself prove `EngineCore` (the separate process that actually loads the
   model) ever started. If it silently didn't, Cloud Run would still
   report the revision "Ready" (its probe is TCP-only, unaware of model
   state) and route real traffic to a container that can never actually
   serve a completion.

**Not yet resolved which of the two is the real cause** — needs the two
verification steps above (URL match-check; full unfiltered logs for the
`45e187b6` time window, specifically checking for `EngineCore` lines) run
against the live project before deciding a fix. If it's (1), the fix is
operational (redeploy `micro-cosmos-web`). If it's (2), it points at either a
genuine vLLM/entrypoint bug on this revision, or — more likely worth
adopting regardless — replacing Cloud Run's plain TCP startup probe with
an HTTP probe against `/v1/models` for the vLLM engine, so Cloud Run's own
"Ready" signal actually reflects model-serving readiness instead of just
"a process is listening on the port." That would be a more fundamental fix
than the app-level polling workaround this repo has relied on so far.

**Follow-up same day: the HTTP-startup-probe idea above doesn't actually
work, researched before attempting it.** Two real blockers found:
1. `/health` — the obvious unauthenticated candidate (vLLM's
   `AuthenticationMiddleware` exempts any path not starting with `/v1` by
   design) — turns out to have the **same blind spot as the current TCP
   probe**: per vLLM's own open GitHub issues (#6073, #36960), `/health`
   only checks "is the engine process alive," returns 200 ~16 seconds
   after the process spawns, and does **not** verify a model is actually
   loaded. Switching to it would change nothing.
2. `/v1/models` — the endpoint that actually reflects real readiness — is
   `/v1`-prefixed, so it's always behind `--api-key` auth once that's
   configured (which it now is). Cloud Run's `--startup-probe` CLI flag
   has no way to attach a custom `Authorization` header — `httpHeaders`
   only exists in the YAML/`gcloud run services replace` form, a bigger
   structural departure from this repo's established flag-based
   `gcloud run deploy` pattern used everywhere else.

**Port convention hypothesis raised, then ruled out, during the same
investigation**: user suspected forcing vLLM onto LM Studio's `1234`
convention might be the cause. Ruled out by evidence already in hand — the
same log's `STARTUP TCP probe succeeded ... on port 1234` line proves the
port was wired correctly (a mismatch would show as permanent
connection-refused, never an eventual success, and never an HTTP 404 either
way — a 404 requires a completed HTTP exchange on the right port). Made
the change anyway as a legitimate convention fix, independent of the 404
investigation: vLLM's own native default (`8000`, confirmed via its docs)
replaces the forced `1234` for the vLLM engine only —
`deploy_cloudrun-vllm-llms.py`'s `DEFAULT_PORT` and `vllm-entrypoint.sh`'s
`PORT` fallback both changed; LM Studio's path (`1234`) is untouched. No
`micro-cosmos-web` change needed (`LLM_BASE_URL` is always the Cloud Run
HTTPS URL, port 443 externally, never the container's internal port).

**Better fix identified, not yet implemented**: since neither vLLM's
current health endpoints nor Cloud Run's probe mechanism can cheaply give
a trustworthy "model is actually loaded" signal from the platform side,
the more promising path is an **in-container self-check inside
`vllm-entrypoint.sh` itself** — start `vllm serve` in the background,
poll `http://localhost:$PORT/v1/models` *from inside the container*
(where the `Authorization` header is trivial to add, unlike Cloud Run's
external probe) with a generous internal timeout, and if it never
succeeds, proactively log a clear error and exit non-zero. This converts
today's actual failure mode — a container that looks "Ready" forever
while genuinely non-functional — into a visible Cloud Run crash-loop,
which is far easier to detect and alert on than requiring this kind of
log archaeology every time. Not implemented this session; flagged as the
next concrete step once the current live-run root cause (stale
revision-routing vs. a genuine `EngineCore` failure) is confirmed.

## Feature: vLLM engine default switched to `google/gemma-4-31B-it` (2026-07-13) — model history, real VRAM math, new tool-calling requirement

Switched while the Qwen3.6 readiness/404 investigation above was still
open — a deliberate reset to a different model+image, not a confirmed fix
for that bug. Full model history for this GPU service:
`google/gemma-4-31B-it-qat-w4a16-ct` (planned 2026-07-11, never actually
deployed) → `Qwen/Qwen3.6-35B-A3B-FP8` (deployed, chosen for SWE-bench/
agentic-coding benchmarks) → **`google/gemma-4-31B-it`** (this entry, full
BF16, no quantization).

**Image**: `vllm/vllm-openai:gemma4` (CUDA 12.9), replacing the pinned
`cu129-nightly` digest — per vLLM's own official Gemma 4 deployment recipe
(docs.vllm.ai/projects/recipes/.../Google/Gemma4.html). Floating tag, not
yet pinned — same discipline as before (pin once a live deploy on this
exact tag is confirmed working).

**Real architecture, from the checkpoint's own `config.json`, not
guessed**: 60 layers, every 6th is full-attention (10 total), the other 50
are sliding-window (1024-token window, capped regardless of context — a
real, if small, contribution, **unlike Qwen3.6's Gated DeltaNet layers**
which are truly zero-KV-cache). 16 KV heads, head_dim 256, native context
262144. No `quantization_config` field at all — this checkpoint is full
BF16, unlike every earlier model this script has defaulted to.

**`estimate_kv_cache_gb()` extended, not just re-parameterized**: the
existing formula only summed full-attention layers, correct for Qwen3.6
(whose non-full-attention layers are truly linear/zero-cache) but wrong
for Gemma 4 (whose sliding-window layers have a small but nonzero,
context-capped contribution). Added a second term for
`sliding_window_layers`/`sliding_window_tokens`, verified by direct
execution against the real numbers: at context 65536, full-attention
KV ≈10.0GB + sliding ≈0.78GB = 10.78GB, matching the hand-computed math
exactly.

**VRAM conclusion**: `~62GB` of BF16 weights (31B × 2 bytes) alone exceed
`nvidia-l4`'s entire 24GB — `nvidia-rtx-pro-6000` (96GB) is required, same
GPU type as Qwen3.6 needed, so no GPU-type change this time. At the
**native max context (262144)**, even the RTX PRO 6000 doesn't fit:
weights 62GB + KV ≈40.78GB = 102.78GB, exceeds the 86.4GB budget
(96GB×0.9). `DEFAULT_CONTEXT_LENGTH` set to **65536** instead: total
≈72.78GB, **~13.6GB headroom** — real, computed margin, not guessed. The
real ceiling for this GPU (computed the same way) is ~150K tokens, well
short of the 262144 native max.

**New requirement found, not present for Qwen3.6**: vLLM's own Gemma 4
recipe documents `--chat-template examples/tool_chat_template_gemma4.jinja`
as required **alongside** `--tool-call-parser gemma4` for tool calling to
work at all — bundled in the `gemma4` image itself, no separate
download/mount. `vllm-entrypoint.sh` had zero `--chat-template` support
before this; added a new `LMSTUDIO_CHAT_TEMPLATE` env var, same
conditional "omit when unset" pattern as the existing optional flags.
`LMSTUDIO_REASONING_PARSER` left unset by default (vLLM's recipe documents
`--reasoning-parser gemma4` for reasoning-tuned variants, not confirmed
necessary for this specific checkpoint) — a real behavior difference from
Qwen3.6, where the reasoning parser was always needed.

**Also fixed while in this area**: `deploy_cloudrun-vllm-llms.py`'s
`--startup-probe` comment previously claimed (unconfirmed, written before
this session's live evidence) that vLLM doesn't bind its port until the
model is loaded. Corrected with the real finding from the same day's
`EngineCore`/readiness investigation above: `APIServer` binds the port and
starts responding well before `EngineCore`/model loading finishes — the
TCP probe only proves a process is listening, not that the model is ready.

**Not yet verified against a live deploy** — no Docker/Cloud Run/GPU
access in the session that made this change.

## Feature: in-container watchdog for the vLLM engine (2026-07-13) — the actual fix for the "Ready but EngineCore never started" incident above

Direct follow-up to the "no `EngineCore` activity for 44+ minutes" incident
documented above. First instinct was to make Cloud Run's own
`--startup-probe` HTTP-based instead of TCP-only, so the platform's own
"Ready" signal would actually reflect model readiness — researched
properly before attempting it, and **ruled out**: `/health` (the one
vLLM endpoint exempt from `--api-key` auth by design — its
`AuthenticationMiddleware` skips any path not starting with `/v1`) has the
*same* blind spot as the TCP probe per vLLM's own open GitHub issues
(#6073, #36960) — it only checks "is the process alive," not "is a model
loaded," returning 200 ~16 seconds after the process spawns regardless.
`/v1/models` (which *would* reflect real readiness) requires the
`Authorization` header once `--api-key` is set, and Cloud Run's
`--startup-probe` CLI flag has no way to attach custom headers — only the
YAML/`gcloud run services replace` form supports `httpHeaders`, a bigger
structural departure from this repo's flag-based `gcloud run deploy`
pattern used everywhere else.

**Actual fix: move the self-check inside the container itself**, where
adding the auth header is trivial. `vllm-entrypoint.sh` now starts `vllm
serve` in the background (previously ran it in the foreground, piped
through `tee`) and runs its own poll loop against
`http://localhost:$PORT/v1/models` (with `Authorization: Bearer
$VLLM_API_KEY` when set) every `LMSTUDIO_WATCHDOG_POLL_SECONDS` (10s
default) for up to `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS` (1500s default,
matching `micro_cosmos/settings.py`'s own readiness-wait floor/default — same
number, same reasoning). Two failure paths, both handled: the model never
reports ready within the timeout (kill + exit 1), or `vllm serve` itself
crashes before ever becoming ready — detected immediately via `kill -0`
on the tracked PID rather than waiting out the full timeout. Once ready,
the script switches to supervising the real background process (`wait
$VLLM_PID`), so a *later* crash still propagates vLLM's own real exit
code, preserving the existing `tee`-to-log failure-diagnostics behavior.
A `trap ... TERM INT` forwards Cloud Run's shutdown signal to the
backgrounded process — without it, backgrounding would have silently
broken graceful shutdown on scale-down/redeploy, since bash (PID 1 in the
container) doesn't forward signals to background children by default.

**Verified with a real standalone bash test harness before ever touching
a live deploy** — this session's established minimum bar for nontrivial
bash changes, applied here too. Built a fake `vllm` CLI (a bash script
simulating each scenario) and ran the *actual, unmodified*
`vllm-entrypoint.sh` against it for 5 cases: reports ready then receives
SIGTERM (expect graceful exit 0 — confirmed), never becomes ready (expect
exit 1 after the full timeout — confirmed, 3s in the test's shortened
timeout), crashes before ever becoming ready (expect fast exit 1, not the
full timeout — confirmed, ~1s), crashes after becoming ready (expect the
real crash exit code propagated — confirmed, exit 9), and a real HTTP
auth check (a fake server that only returns 200 when the `Authorization`
header matches — confirmed the header is sent and correctly matched).

**Real bug caught by the harness, not by luck**: the first version used
`"${WATCHDOG_HEADERS[@]}"` unconditionally — on an empty array (no
`VLLM_API_KEY` set), this raises `unbound variable` under `set -u` on
bash 3.2 (macOS's default `/bin/bash`, which is what the test harness
runs on). The Cloud Run image's bash is likely newer (this specific
empty-array-under-`set -u` behavior was fixed in bash 4.4), so this might
never have surfaced in production — but relying on "probably fine on a
newer bash" is exactly the kind of assumption this project has been
burned by before. Fixed with the portable, version-safe idiom:
`"${WATCHDOG_HEADERS[@]+"${WATCHDOG_HEADERS[@]}"}"`.

**Not yet verified against a live deploy** — the test harness proves the
watchdog logic itself is correct in isolation; a real Cloud Run redeploy
is the next actual test, same caveat as every other new mechanism this
session.

## Feature: same watchdog ported to LM Studio (2026-07-13) — a design that was built, tested, and abandoned before shipping

Direct follow-up to the vLLM watchdog above — LM Studio has the identical
underlying gap: Cloud Run's TCP-only startup probe passes as soon as
`lms server start` binds the port, long before `lms load` (the actual
model-loading step) finishes.

**First design, built and verified to NOT work, before it ever shipped**:
an outer watchdog wrapping the *entire* startup sequence
(health-wait/runtime-install/`lms get`/`lms load`) — a background timer
that would `kill -TERM` the script's own PID if a "ready" marker file
hadn't appeared within the timeout, with a `trap ... TERM` on the main
script to handle it. Built a standalone bash test harness (a fake `lms`
CLI covering the full command surface used by this script: `server
start`, `runtime ls/survey/get`, `get`, `load`, `ps`) before trusting the
design — and the harness caught a **fundamental flaw**: bash defers
running trap handlers until the current **foreground** command finishes.
A hung `lms load` (a single long-blocking foreground pipeline) is exactly
the situation that creates — the watchdog's `SIGTERM` would sit queued,
never acted on, until the hang resolved on its own. Concretely observed:
the `hang_load` test case ran for the full 2-minute tool-call timeout
under the buggy design, versus completing correctly once redesigned.

**Redesigned to mirror `vllm-entrypoint.sh` exactly, once the flaw was
understood**: `lms load` itself now runs in the **background**
(previously ran synchronously, piped through `tee`), and the script polls
its PID directly via `kill -0` every `LMSTUDIO_WATCHDOG_POLL_SECONDS` (2s
default) for up to `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS` (1500s default,
same number/reasoning as vLLM and `micro_cosmos/settings.py`'s floor). Because
bash is never blocked in a single long foreground call this way, the poll
loop always regains control promptly — no dependency on signal/trap
delivery at all. Deliberately scoped to just `lms load`, not the whole
sequence: the health-wait loop and `lms get` retry loop already self-bound
via their own retry×sleep ceilings and already correctly propagate
explicit failures (this script's very first version of this session
already had that right) — only `lms load` has a proven history of hanging
(the interactive-picker hang from 2026-07-09) that warranted this
treatment.

**Verified against the real, unmodified script** (not the isolated
mechanism alone) across 3 scenarios: normal completion (reaches the final
`wait` on the server PID, unaffected), `lms load` hangs forever (killed,
exits 1, within the timeout rather than hanging indefinitely), `lms load`
fails explicitly (its real exit code still propagates immediately,
completely unaffected by the watchdog's presence).

**Lesson worth generalizing**: this is the second time this session a
signal/trap-based approach looked correct on paper but failed a real
test — always verify bash control-flow assumptions (signal delivery,
trap timing, background/foreground interaction) with an actual harness
before trusting them, especially for anything meant to interrupt a
possibly-hung external command.

## Feature: `--limit-mm-per-prompt image=0,audio=0` for the vLLM engine (2026-07-13) — confirmed applicable, made conditional after finding a real crash risk

User asked whether vLLM's Gemma 4 recipe's "text-only workloads" tip
(`--limit-mm-per-prompt image=0,audio=0`, to skip multimodal profiling
entirely) applies to this pipeline — confirmed yes: Gemma 4 is multimodal
(vision + audio encoders, per the checkpoint's own `config.json`, fetched
earlier this session) but Micro-Cosmos only ever translates source code
— 100% text, never image/audio input.

**Real crash risk found before applying it unconditionally**: a live
vLLM bug report confirms this flag raises a hard `ValueError`
("`limit_mm_per_prompt` is only supported for multimodal models") on a
genuinely text-only checkpoint. This same `vllm-entrypoint.sh` also
serves `Qwen/Qwen3.6-35B-A3B-FP8` (pure text, no multimodal config at
all) via `MODEL_REASONING` override — applying the flag unconditionally
would have broken that path outright at server startup, exactly the
"hardcoded model-specific flag, silently wrong the moment the model
changes" mistake this same file's own comments already warn about (from
the earlier `--quantization compressed-tensors` incident). Made
conditional via a new `LMSTUDIO_LIMIT_MM_PER_PROMPT` env var instead, same
"omit when unset" pattern as every other optional flag in this script.

**Second real risk found, a gcloud-specific gotcha**: this flag's own
value contains a comma (`image=0,audio=0`) — folding it into the existing
single comma-joined `--set-env-vars` string would corrupt gcloud's
`KEY=VALUE,KEY=VALUE` parsing (confirmed via gcloud's own documented
guidance on exactly this scenario). Fixed by passing it as its own,
separate `--set-env-vars` flag occurrence in the same `gcloud run deploy`
command — confirmed via Cloud Run's own docs that repeated
`--set-env-vars` flags within one command are additive, not
destructive/overriding of each other (a materially different question
from whether values across *separate* deploy invocations are additive,
which they are not — this is specifically about multiple flag instances
in the same single command).

**Verified, not just added**: confirmed via a fake `vllm` binary that
echoes its received arguments, run against the real, unmodified
`vllm-entrypoint.sh` — the flag reaches `vllm serve` correctly when set,
and is fully absent from the command line when unset.

## Bug fix: `--limit-mm-per-prompt`'s flat `image=0,audio=0` form is the WRONG syntax — real Cloud Run vLLM deploy failure (2026-07-14)

The value shipped in the change above broke a live Cloud Run vLLM deploy
at container start:

```
vllm serve: error: argument --limit-mm-per-prompt: Value image=0 cannot
be converted to <function loads at 0x7f018b4d7380>.
```

**Root cause**: `--limit-mm-per-prompt`'s real argparse type is
`json.loads` (the `loads` in the error message names it directly), not
the flat `key=value,key=value` string the community recipe page
suggested. Confirmed independently via vLLM's own canonical
`docs.vllm.ai/en/stable/configuration/engine_args/` reference — the
correct form is a JSON object (`{"image": 0, "audio": 0}`) or a dotted
individual-keys alternative (`--limit-mm-per-prompt.image 0`). **Lesson:
a community "recipe"/cookbook page can be right about *whether* to use a
flag while being wrong about its exact CLI syntax — the canonical
engine/CLI reference is the source of truth for syntax, even when the
recipe page is what surfaced the feature in the first place.**

**Second, independently-discovered gotcha**: an **unquoted** JSON value
undergoes bash brace-expansion on `export` — `export
X={"image":0,"audio":0}` silently strips the double quotes, corrupting
the value to `X={image:0,audio:0}` (confirmed via direct bash testing,
not assumed). Any shell-facing example of this value (docs,
`gclud-run-setup*.txt`) must single-quote the whole JSON string:
`LMSTUDIO_LIMIT_MM_PER_PROMPT='{"image":0,"audio":0}'`.

**What did NOT need to change**: the separate-`--set-env-vars`-flag
mechanism added in the prior entry (to dodge gcloud's comma-delimited
parsing) required no update — JSON also contains a comma, so the same
treatment already covers it.

**Verified end-to-end**: re-ran the fake-`vllm`-echo-args harness with
the env var set exactly as Cloud Run's `--set-env-vars` would inject it
(no shell re-parsing) — confirmed the corrected value reaches `vllm
serve` as a single, uncorrupted, valid-JSON argv token.

**Lesson worth generalizing**: this is the second time this session a
flag/argument's exact syntax, sourced from a secondary/community
reference rather than the tool's own canonical docs, turned out subtly
wrong only once exercised against the real live system (the first was
the LM Studio trap-deferral watchdog design). Any config surface adopted
from a "recipe"/blog/cookbook page — as opposed to the primary tool's own
reference docs — deserves either a real syntax check with a fake-binary
harness, or a direct cross-check against the canonical CLI/API reference,
before being treated as verified.

## Revert: `--limit-mm-per-prompt`/`LMSTUDIO_LIMIT_MM_PER_PROMPT` removed entirely — `gcloud --set-env-vars` can't parse a JSON-shaped value at all (2026-07-14)

The JSON-format fix above (same day) still failed the live deploy — a
THIRD, different failure, this time from `gcloud` itself rather than
`vllm serve`:

```
ERROR: (gcloud.beta.run.deploy) argument --set-env-vars: Bad syntax for
dict arg: ["audio":0}]. Please see `gcloud topic flags-file` or `gcloud
topic escaping` for information on providing list or dictionary flag
values with special characters.
```

**Root cause**: `gcloud run deploy --set-env-vars` has its own
dict-argument parser for `KEY=VALUE,KEY=VALUE` lists, and that parser
cannot handle a value containing JSON's own braces/colons — this holds
regardless of correct shell single-quoting (already verified working one
layer up) and regardless of passing the value as its own separate
`--set-env-vars` flag occurrence (which correctly solved the earlier
comma-delimiting problem, but not this one). A real fix would require
`gcloud topic escaping`'s dedicated escape syntax or switching to
`--env-vars-file` with a YAML/JSON file — real complexity for what is
only a minor optimization flag.

**Decision**: drop the flag/env var entirely rather than keep patching
around gcloud's escaping rules for a minor optimization.
`GPU_MEMORY_UTILIZATION` already covers the meaningful memory-tuning
knob for this deployment. Removed from `deploy_cloudrun-vllm-llms.py`
(constant, `deploy_service()`/`deploy_vllm()` param, the
`extra_env_var_flags` mechanism it was the sole user of, print-summary
mention), `vllm-entrypoint.sh` (env var declaration + conditional flag
append), `deployment/README.md` (every example/table row/manual-gcloud
mention, replaced with a short paragraph explaining the three-stage
history so a future reader doesn't rediscover the same dead end), and
both `gclud-run-setup*.txt` files (line deleted outright).

**Lesson worth generalizing (extends the one above)**: this single flag
broke in three genuinely different ways across two days — `vllm serve`'s
own argparse rejected the flat form, then `gcloud`'s dict-arg parser
rejected the corrected JSON form. Each failure was invisible until
exercised against the real binary at that specific layer (shell → gcloud
CLI parsing → container env → target binary's argparse) — no amount of
reading either tool's docs in isolation would have caught the
`gcloud`-layer failure, since the JSON format is *correct* for `vllm
serve` and the bug is purely in how `gcloud`'s flag parser tokenizes the
value before it ever reaches the container. When a config value must
survive multiple independent parsing layers and two of them have already
broken in different ways, dropping the feature is often more
proportionate than continuing to patch around progressively deeper
tooling quirks — especially for a value that was only ever a minor
optimization, not a functional requirement.

## Feature: `LMSTUDIO_REASONING_PARSER` now defaults to `gemma4` for the vLLM engine (2026-07-14)

Previously left unset (`DEFAULT_REASONING_PARSER = ""`) for
`google/gemma-4-31B-it` — the existing comment noted vLLM's own Gemma 4
recipe documents `--reasoning-parser gemma4` for "reasoning-tuned
variants" but this hadn't been confirmed necessary for this specific
checkpoint. User supplied a real example command straight from that
recipe:

```
vllm serve google/gemma-4-31B-it \
  --max-model-len 16384 \
  --enable-auto-tool-choice \
  --reasoning-parser gemma4 \
  --tool-call-parser gemma4 \
  --chat-template examples/tool_chat_template_gemma4.jinja
```

Cross-checking this against existing config confirmed every other flag
already matched this repo's defaults (`LMSTUDIO_TOOL_CALL_PARSER=gemma4`,
`LMSTUDIO_CHAT_TEMPLATE=examples/tool_chat_template_gemma4.jinja`) —
`--reasoning-parser gemma4` was the one gap, and since the recipe pairs
it directly with `--tool-call-parser gemma4` for this exact model, that's
strong enough confirmation to flip the default rather than leave it
opt-in.

**No mechanism changes needed** — `vllm-entrypoint.sh` already appends
`--reasoning-parser` whenever `LMSTUDIO_REASONING_PARSER` is set (this
plumbing existed since the original Gemma 4 switch); only
`DEFAULT_REASONING_PARSER` changed, from `""` to `"gemma4"`. Both
`gclud-run-setup.txt`/`gclud-run-setup-vllm.txt` were already
independently updated to `LMSTUDIO_REASONING_PARSER=gemma4` by the time
this landed — only `deployment/README.md`'s stale "left unset"/`(unset)`
mentions needed updating.

**Lesson**: when a user supplies a real reference command (from a vendor
recipe or official docs), diff it flag-by-flag against the current
defaults rather than only checking the one flag they're asking about —
this surfaced that every other flag already matched, isolating exactly
one real gap instead of guessing at the scope of the question.

## Bug fix: `--kv-cache-dtype bfloat16` crashes every Gemma 4 vLLM deploy — misdiagnosed live as a startup-probe timeout (2026-07-14)

A live `micro-cosmos-lmstudio` (vLLM engine) deploy hit `Container failed to
become healthy. Startup probes timed out after 30m (180 attempts with a
period of 10s each)`, and the user's first hypothesis — reasonably,
since it's the same generic Cloud Run error family as several earlier
incidents — was that Cloud Run's "container running" state needed to be
decoupled from "model finished warming up," i.e. that the fix was a
probe/timeout/background-loading change.

**Root cause was confirmed via real logs, not guessed**, per this
project's own established rule (see the many "if this happens
frequently, consider adjusting probe settings" false leads earlier in
this file — the actual rule is the opposite: if a deploy times out the
*entire* configured window with zero success, that's a strong signal
it's not a timing issue, stop extending timeouts and pull
`gcloud run services logs read` first). The logs showed `vllm serve`
loading the model fine (fast — a single ~15GB w4a16-quantized shard),
then crashing deterministically right after with `AssertionError:
unsupported kv_cache_dtype (str), got bfloat16` inside vLLM's
`triton_reshape_and_cache_flash` kernel. vLLM force-selects the
`TRITON_ATTN` backend for **any** Gemma 4 model (`Gemma4 model has
heterogeneous head dimensions... Forcing TRITON_ATTN backend` — a
blanket architecture-level behavior, not specific to the w4a16 variant
that happened to be deployed), and that backend's kernel only accepts
`kv_cache_dtype == "auto"` or an `fp8*` value — never a literal
`"bfloat16"` string. `vllm-entrypoint.sh` had hardcoded
`--kv-cache-dtype bfloat16` unconditionally (added earlier specifically
to avoid `auto`'s uncalibrated fp8_e4m3 scale=1.0 numerics — see the
"Feature: vLLM engine default switched to `google/gemma-4-31B-it`" entry
above), so every single startup attempt crashed at the same point.
Because the container crash-looped fast, Cloud Run's TCP probe (checking
port 8000 every 10s) never caught the port open even once across the
full 30-minute ceiling — producing a "timed out" error indistinguishable
at a glance from a genuinely slow load.

**The in-container watchdog worked exactly as designed**: it caught
`vllm serve` exiting before `/v1/models` ever reported ready and printed
the full crash traceback to the logs — this is precisely the mechanism
added in the 2026-07-13 "in-container watchdog" entry above, and it's
what made this diagnosable in minutes via one log read instead of
another multi-round guessing cycle.

**Fix**: dropped the hardcoded `--kv-cache-dtype bfloat16` entirely,
falling back to vLLM's own `"auto"` default, which the Triton kernel's
assertion explicitly permits. The previously-flagged "auto resolves to
an uncalibrated fp8 scale" numerics concern still stands as a known
tradeoff — worth revisiting with a calibrated fp8 checkpoint if output
quality issues surface later — but it's no longer optional, since
`bfloat16` cannot work at all for this model family.

**On the user's actual question (decoupling "running" from "warmed
up")**: confirmed via Google's own docs that Cloud Run's 30-minute
startup-probe ceiling is a hard platform limit and cannot be raised
further. But the existing architecture already implements exactly this
decoupling — vLLM's APIServer binds the port before EngineCore/the model
is ready, the in-container watchdog supervises real readiness
independently of Cloud Run's own probe, and `driver.py`'s
`_wait_for_llm_ready()` gates real application traffic on genuine
`/v1/models` readiness rather than Cloud Run's revision-ready state. This
crash — not a missing decoupling mechanism — was the actual blocker; once
model load genuinely takes only a few minutes (as it does for this
~15GB shard), the existing architecture needs no further changes.

**Lesson worth generalizing**: a Cloud Run "startup probe timed out"
error is a symptom shared by at least two unrelated root causes now seen
in this project — a genuinely slow model load (fixed earlier via the
in-container watchdog + probe-ceiling tuning) and a deterministic
post-load crash that just happens to repeat fast enough to never be
caught by a 10-second-interval TCP check (this entry). The two require
opposite fixes (speed up loading vs. fix a crash) — always pull real
container logs before assuming which one applies, regardless of how
plausible the timing explanation seems.

---

## Real incident: micro-cosmos-web could never reach micro-cosmos-lmstudio — same-project ≠ internal ingress (2026-07-14)

`_wait_for_llm_ready()` 404'd forever on every run, regardless of
whether `micro-cosmos-lmstudio` was warm (`min-instances=1`) or cold —
ruling out both an HTTP/HTTPS scheme theory and a cold-start/timeout
race theory (both investigated with direct evidence and ruled out).

Ground truth pulled directly via `gcloud logging read` /
`gcloud run services describe` (not inferred from app logs):

- `micro-cosmos-lmstudio`'s `run.googleapis.com/requests` log — Cloud Run's
  own per-request GFE log — had **zero entries ever**, across all
  revisions since first deploy. The connection had never once
  succeeded; this was never a timing issue.
- `micro-cosmos-lmstudio`: `--ingress=internal`, confirmed enforced
  (`ingress-status: internal`). IAM already grants `allUsers` →
  `roles/run.invoker`, so IAM was never the blocker.
- `micro-cosmos-web`: no VPC network, connector, or Direct VPC egress
  configured at all.

**The false assumption, now corrected**: `deploy_cloudrun-micro-cosmos-app.py`
previously claimed same-project Cloud-Run-to-Cloud-Run traffic is
automatically treated as "internal" by ingress control, no VPC needed.
It is not. `--ingress=internal` only accepts traffic that actually
arrives over Google's private network path. Without Direct VPC egress
on the *caller*, its outbound calls to the callee's public `*.run.app`
hostname leave over the public internet and get silently dropped at the
GFE layer — upstream of the container and upstream of Cloud Run's own
per-service request logging. That's why the callee's logs showed
literally nothing, not even a rejected request.

This project's org policy (`constraints/run.allowedIngress`) blocks
`--ingress=all`, so relaxing `micro-cosmos-lmstudio`'s ingress was not a
viable alternative fix.

**Fix**: Direct VPC egress on `micro-cosmos-web`, not a change to
`micro-cosmos-lmstudio`. Created a custom-mode VPC (`micro-cosmos-vpc`) + subnet
(`micro-cosmos-vpc-europe-west4`, `10.10.0.0/24`) in `europe-west4` once:

```bash
gcloud compute networks create micro-cosmos-vpc --subnet-mode=custom
gcloud compute networks subnets create micro-cosmos-vpc-europe-west4 \
    --network=micro-cosmos-vpc --region=europe-west4 --range=10.10.0.0/24
```

Then wired into `micro-cosmos-web`'s deploy (now baked into
`deploy_cloudrun-micro-cosmos-app.py` as defaults, no extra env vars needed
for a normal `python deployment/deploy_cloudrun-micro-cosmos-app.py` run):

```
--network=micro-cosmos-vpc --subnet=micro-cosmos-vpc-europe-west4 --vpc-egress=all-traffic
```

`--vpc-egress=all-traffic` is required, not the default
`private-ranges-only` — the LMStudio URL is a public `*.run.app`
hostname, not an RFC1918 address, so `private-ranges-only` would leave
this exact traffic unchanged (still public-internet-routed).
`micro-cosmos-lmstudio` itself does not need to be redeployed — this is
entirely a caller-side fix.

**Lesson**: when app-side symptoms and infra-side reasoning disagree,
pull the actual Cloud Run request log (`run.googleapis.com/requests`)
for the target service directly — it's generated by Cloud Run's
front end before the container is involved, so "zero entries ever" is
a much stronger and more specific signal than "404 response" alone,
and immediately rules out cold-start/timing theories in favor of a
network-path theory.

---

## Real incident, follow-up: Direct VPC egress needs Cloud NAT + Private Google Access, not just --network/--subnet (2026-07-14)

Direct follow-up to the "micro-cosmos-web could never reach micro-cosmos-lmstudio"
incident above. The fix shipped there (`--network`/`--subnet`/
`--vpc-egress=all-traffic`) was necessary but incomplete — the first live
redeploy failed with a generic "container failed to start and listen on
the port" error.

Real logs showed the actual failure was unrelated to `micro-cosmos-lmstudio`:
the `examples-data` GCS FUSE volume mount (calls `storage.googleapis.com`
at container startup, before app code runs) timed out completely —
`dial tcp <google-ip>:443: i/o timeout`. Root cause: `micro-cosmos-vpc` had a
network and subnet but **no route out** — confirmed via `gcloud compute
routers list` (no router → no Cloud NAT) and `gcloud compute networks
subnets describe` (`privateIpGoogleAccess: false`). `--vpc-egress=all-traffic`
routes *every* outbound call through the VPC, not just the one to
`micro-cosmos-lmstudio` — so without NAT/PGA, the GCS mount (and would-be
Anthropic API calls) had nowhere to go.

No outage resulted — Cloud Run kept 100% traffic on the prior healthy
revision throughout (its atomic-deploy behavior; a failed revision never
receives traffic).

**Fix**: added a Cloud Router + Cloud NAT gateway to `micro-cosmos-vpc` in
`europe-west4` (scoped to `micro-cosmos-vpc-europe-west4`'s primary IP range,
auto-allocated external IPs), and enabled Private Google Access on that
subnet. Verified via `gcloud compute routers nats describe` (NAT actually
covers the right subnet/range) and `gcloud compute routes list` (a
`0.0.0.0/0 → default-internet-gateway` route already existed, auto-created
with the VPC) — Private Google Access carries Google-API traffic
(GCS, Artifact Registry) directly; Cloud NAT is the fallback for
everything else. Also checked and ruled out: no VPC Service Controls
perimeter exists in this project (`accesscontextmanager.googleapis.com`
isn't even enabled) that could add an independent block; bucket IAM was
already correct and was never the problem.

**Confirmed `micro-cosmos-lmstudio` needs none of this** — it's the ingress=internal
callee, not the caller, and has no Direct VPC egress attached. Its own
egress (GCS model bucket) already works via Cloud Run's default
unrestricted path. Only the caller side of an internal-ingress
relationship needs Direct VPC egress; the callee needs nothing extra
beyond `--ingress=internal` itself.

**Confirmed unaffected**: the report/output-code download endpoints
(`micro_cosmos/web/app.py`) are pure local-disk zip + `FileResponse` — zero
outbound calls, never touched by any of this.

**Lesson**: `--vpc-egress=all-traffic` is an all-or-nothing switch for a
Cloud Run revision — the moment it's set, *every* outbound call from that
service depends on the VPC having a real route out (NAT and/or Private
Google Access), not just the one call that motivated adding VPC egress in
the first place. Audit every outbound dependency a service has (GCS
mounts, external APIs, Artifact Registry) before flipping this on, not
just the one you're trying to fix.

---

## Real incident, second follow-up: API key rotation must be applied to both services together (2026-07-14)

Once the VPC-egress + NAT/Private-Google-Access fixes above actually let
`micro-cosmos-web` reach `micro-cosmos-lmstudio`, the readiness poll returned a real
application-level response for the first time in this incident chain —
`401 (invalid/missing API key)` instead of silence/404. This is a
distinct, easily-recognizable failure signature: the readiness-wait log
line already prints `api_key_configured=True`, and a `401` (vs a `404` or
no response at all) specifically means the two services are alive and
routable but disagree on the token.

Root cause: `LLM_API_KEY` (set on `micro-cosmos-web`) and vLLM's
`--api-key` (set on `micro-cosmos-lmstudio`) are the same logical secret
deployed independently to two services. The key had been rotated on
`micro-cosmos-web` only (after being exposed in a pasted console log earlier
in this session) — `micro-cosmos-lmstudio` still had the old value baked into
its running revision.

**Fix**: redeployed both services with the identical new key
(`micro-cosmos-lmstudio-00006-cvl` + a new `micro-cosmos-web` revision). Verified in
logs: the `401` retry loop stopped and `GET .../v1/models -> 200 OK`
followed immediately; a subsequent fresh readiness-wait cycle succeeded
cleanly with zero 401s. This is the final confirmation that today's whole
incident chain (VPC egress → NAT/PGA → API key sync) is fully resolved
end-to-end.

**Lesson, generalizing**: any credential shared between `micro-cosmos-web` and
`micro-cosmos-lmstudio` (currently just the API key, but the same would apply
to anything similar added later) must be rotated on both services in the
same change, not just the one currently being touched — otherwise the
result is a `401`, not an obvious "forgot to redeploy" signal.

---

## Rename (2026-07-15): `micro-cosmos-lmstudio` → `micro-cosmos-llmgateway` — service identity + UI text only

The GPU Cloud Run service was renamed to reflect that it's engine-agnostic
(runs LM Studio software or vLLM interchangeably) — "LMStudio" as the
service's identity was inaccurate branding, flagged as a pending follow-up
since the 2026-07-11 engine switch.

**Scope, deliberately limited**: the Cloud Run service name and the web
client's trace text only. NOT renamed: the `LMSTUDIO_*` env var
convention, `LLM_ENGINE=lmstudio` (a real engine selector), deploy script
filenames, or the GCS model-cache bucket name — renaming any of those
would add blast radius/cost with no benefit and wasn't what was asked.

**Key fact**: the UI trace pill ("LMSTUDIO") was never hardcoded in
`dashboard.js` — it's generic, rendering whatever `driver.py`'s
`payload.author` field contains. So the entire UI-facing change was
`driver.py`'s `"author"`/`"[LMStudio] ..."` strings, nothing in the
frontend.

**Cloud Run has no rename primitive** — this required deploying a
brand-new `micro-cosmos-llmgateway` service (fresh cold start, same ~10 min
timeline as any vLLM cold start observed earlier), verifying it, then
repointing `micro-cosmos-web` at it via `discover_lmstudio_url()` (which
auto-discovers by service name, so only the `LMSTUDIO_SERVICE_NAME`
constant needed to change), and only then deleting the old service — kept
short to limit double-GPU-billing overlap.

See `changes-log.md`'s "Rename" entry for the full file-by-file diff.

## `runs/` mounted via GCS bucket, matching local docker-compose (2026-07-2x)

Branch `feat/deploy-runs-gcs`. Closes the gap flagged (and deliberately
deferred) in the `examples/` bucket entry above: `runs/` (`RUNS_DIR=/app/runs`)
is where every pipeline run's JSON artifacts, generated code, and HTML
reports live — locally a `docker-compose.yml` bind mount, but plain
ephemeral container disk on Cloud Run, wiped on every cold start/redeploy.

**Implementation:** new `ensure_runs_bucket()` in
`deploy_cloudrun-micro-cosmos-app.py` — but mirrors `ensure_model_bucket()` in
`deploy_cloudrun-lmstudio-llms.py` (create + IAM-bind only), **not**
`ensure_examples_bucket()`'s shape (which also does a `gcloud storage rsync`
seed step). `runs/` has no built-in content to seed — it's pure runtime
output — same reasoning the model-cache bucket already uses for not
needing a seed step. Bucket: `MICRO_COSMOS_RUNS_BUCKET` (default
`$PROJECT-micro-cosmos-runs`), mounted at `/app/runs` via a second
`--add-volume`/`--add-volume-mount` pair in `deploy_service()`, right
alongside the existing `examples-data` pair — confirmed `gcloud run deploy`
accepts multiple `--add-volume`/`--add-volume-mount` pairs in one command,
one per volume. The existing `--clear-volumes`/`--clear-volume-mounts`
flags (added for the examples bucket, to avoid the additive-mount bug
documented earlier in this file for the LMStudio model-cache volume)
needed no change — they clear once, before both `--add-volume*` pairs
apply.

**Two design questions asked explicitly, both resolved toward the simpler
option, not over-engineered:**
1. **GCS FUSE write latency** — `runs/` is written far more heavily than
   `examples/` (e.g. `seam.json` gets rewritten after every seam, dozens of
   times per run, per the TDD-writer-hardening feature — see
   [[project_tdd_writer_hardening]]). Each write is a full GCS object PUT,
   not a fast local write. Confirmed *correctness* is not at risk before
   proceeding: a repo-wide grep found no `os.rename`/`shutil.move`/`fcntl`/
   `flock`/`FileLock` usage anywhere touching `runs/` — only plain
   `mkdir(parents=True, exist_ok=True)` + `write_text`/`json.dump` — and
   GCS FUSE's lack of atomic-rename/locking support is exactly the class of
   thing that would have broken had this codebase relied on either. Decision:
   accept the write-latency tradeoff (same as `examples/`/model-cache
   already do), don't build anything more complex (e.g. write-local-then-sync)
   without first seeing whether it's actually a problem on a live deploy.
2. **Bucket retention** — since `runs/` will now grow unboundedly forever
   (every run's data persists across every future redeploy, unlike today's
   ephemeral status quo where a cold start silently wipes old runs),
   whether to add a GCS lifecycle policy now. Decision: no — matches
   today's status quo exactly (nothing deletes old runs from local disk
   either), and picking a real retention window is a separate decision not
   worth bundling into "give runs/ a bucket."

**Docs updated per [[feedback_deploy_changes_sync]]:** `deployment/README.md`
(new "Run artifacts" section + config table row + manual-gcloud example),
`.claude/commands/deploy-gcp.md` (new item 43, item 14 marked superseded),
`changes-log.md`.

**Not yet exercised against a live deploy** — this provisions real, billed
GCP infrastructure (a new bucket + IAM binding + Cloud Run volume config),
consistent with this repo's standing practice of not executing live
infra-affecting `gcloud` commands from an agent session. Verified via
`ast.parse()` and a standalone dry-run harness (monkeypatched `run()`,
same technique used for `setup_micro_cosmos_web_lb.py` earlier — see that
entry above) exercising `ensure_runs_bucket()` and the updated
`deploy_service()` directly, confirming every generated gcloud command's
flag syntax/values. Two things to actually watch for on the first real
deploy: (1) whether GCS FUSE write latency is noticeable across a
58-seam run's worth of `seam.json` rewrites, and (2) that both volume
mounts (`examples-data` and `runs-data`) show up correctly in the live
revision's YAML — not just one — given `--add-volume`'s additive-on-redeploy
behavior documented earlier in this file for the LMStudio model-cache bug.

## Feature + bug fix: `LMSTUDIO_ENABLE_THINKING` for Gemma 4, and `MODEL_TEMPERATURE` actually parameterized (2026-07-2x)

Prompted by Joao asking how to enable "thinking mode" for Gemma 4 on the
current vLLM setup (`gcloud-run-setup-vllm.txt`), specifically for COBOL
translation quality (`COMP-3` computational arithmetic, `PERFORM THRU`
loops — source constructs where getting the model to reason step-by-step
before emitting code plausibly reduces structural bugs). The suggestion
Joao had been given (send a literal `<|think|>` control token via
`AutoProcessor` at the start of the system prompt) was **wrong for this
deployment** — confirmed via WebSearch against vLLM's own docs/Gemma 4
recipe (`docs.vllm.ai/projects/recipes/.../Google/Gemma4.html`,
`docs.vllm.ai/.../reasoning/gemma4_reasoning_parser/`), not assumed.
`AutoProcessor` is for raw `transformers` inference; this pipeline calls
vLLM's OpenAI-compatible chat completions API via LiteLLM
(`micro_cosmos/settings.py::build_llm()`) — manually splicing a special token
into request text bypasses the chat template entirely and isn't the
correct mechanism.

**Real finding, the actual gap**: `--reasoning-parser gemma4` (already set
via `LMSTUDIO_REASONING_PARSER=gemma4` in every vLLM setup file) only
*parses* reasoning content out of the response if the model produces
any — it does not itself turn thinking on. Thinking is **off by vLLM's
own default**. The correct mechanism is `chat_template_kwargs:
{"enable_thinking": true}`, either per-request (`extra_body=...`) or as a
server-wide default (`vllm serve --default-chat-template-kwargs
'{"enable_thinking": true}'`).

**Scope decision, asked explicitly**: server-wide default (matches every
other `LMSTUDIO_*` flag's existing shape in this repo) vs. per-request
only for `role="reasoning"` LLM calls (more surgical, avoids slowing down
`model_fast`-role calls like Observer, but requires a `settings.py` code
change rather than just deploy config). **Chose server-wide** — simpler,
consistent with the rest of this file's conventions.

**Implementation**: new `LMSTUDIO_ENABLE_THINKING` env var (vLLM only,
default off) threaded through `deploy_cloudrun-vllm-llms.py`
(`deploy_service()`/`deploy_vllm()`, same "omit entirely when unset/false"
pattern as `LMSTUDIO_CHAT_TEMPLATE`) and `vllm-entrypoint.sh` (conditionally
appends `--default-chat-template-kwargs '{"enable_thinking": true}'` to
`VLLM_ARGS`). Added to all three vLLM-engine `gcloud-run-setup*.txt` files
(not the LM Studio one — no equivalent mechanism exists for that engine).

**Second, unrelated bug found and fixed while in this area**:
`deploy_cloudrun-micro-cosmos-app.py`'s `deploy_service()` had
`"MODEL_TEMPERATURE=0.3"` as a **hardcoded literal string**, never
parameterized, never reading an env var at all — meaning every
`gcloud-run-setup*.txt` file's already-correct `MODEL_TEMPERATURE=0.2`
line (and `.env.example`'s, and `docker-compose.yml`'s) was silently
ignored by the actual deploy script for `micro-cosmos-web`. Fixed: threaded
through as a real `model_temperature` param, resolved via
`os.environ.get("MODEL_TEMPERATURE", "0.2")` — default changed from the
old hardcoded `0.3` to `0.2` in the same fix, matching what every
reference config file already assumed.

**Verified** via `bash -n`/a manual `VLLM_ARGS` assembly simulation
(confirmed the flag appears correctly quoted when
`LMSTUDIO_ENABLE_THINKING=true`, absent when unset) and a standalone
Python dry-run harness (monkeypatched `run()`) for both
`deploy_cloudrun-vllm-llms.py` (confirmed `LMSTUDIO_ENABLE_THINKING=true`
present/absent correctly in the generated `--set-env-vars` string) and
`deploy_cloudrun-micro-cosmos-app.py` (confirmed `MODEL_TEMPERATURE=0.2` now
actually reaches the generated command, and the no-env-var-set default
resolves to `0.2`). **Not yet exercised against a live deploy** — same
standing caveat as every other deploy-script change in this file; the
specific thing to watch for on the first real deploy: whether
`google/gemma-4-31B-it-qat-w4a16-ct` (the quantized checkpoint in
`gcloud-run-setup-vllm.txt`, a model this file's own history notes as
"planned 2026-07-11, never actually deployed") supports thinking mode the
same way the plain BF16 `google/gemma-4-31B-it` checkpoint does — not
independently confirmed for this specific quantization.

## Bug fix: `VLLM_ASSUMED_WEIGHTS_GB=62.0` was wrong for the quantized checkpoint — caused a real production `ContextWindowExceededError` (2026-07-23)

**Confirms the open question above**: `google/gemma-4-31B-it-qat-w4a16-ct`
*is* live on `micro-cosmos-llmgateway` (Cloud Run revision
`micro-cosmos-llmgateway-00001-54j`, `europe-west4`) — no longer "planned,
never actually deployed." Its own startup log gives the real number:
`Model loading took 19.62 GiB memory` — consistent with 4-bit weight
quantization of a 31B model (~31B × 4bit/8 ≈ 15.5GB + overhead ≈ 19.6GB),
and nowhere near the `62.0` in `VLLM_ASSUMED_WEIGHTS_GB` across all three
`gcloud-run-setup*.txt` files. That `62.0` was carried over from
`check_vram_fit()`'s own doc comment assumption of "full BF16, no
`quantization_config` in the checkpoint's own config.json" (see the
"Switching models" entry above) — true for the plain BF16
`google/gemma-4-31B-it` checkpoint, false for this `-qat-w4a16-ct` one.

**Symptom**: `test_reviewer_agent` crashed mid-run with
`litellm.ContextWindowExceededError` — "prompt contains at least 162513
input tokens" against `MODEL_CONTEXT_LENGTH=162512`, "0 output tokens
requested" (vLLM/litellm's remaining-budget calc clamped to 0 once the
prompt alone exceeded the configured context, then still sent the
request). Root cause was **not** session contamination — traced through
`driver.py`/`pipeline.py` and confirmed `reset_session()` already runs
before every reviewer phase (`_run_tdd_loop_for_seam()`), and none of the
three reviewer agents' instructions reference the large analysis
artifacts (`ir_graph`, `tnas`, `security_report`, etc.) via `{key?}`
placeholders — only `{run_dir?}`/`{target_lang?}`/`{source_lang?}`/
`{current_seam?}`. The overflow is `MODEL_CONTEXT_LENGTH` itself being
sized far too conservatively relative to actual available VRAM, compounded
by `read_generated_files()` in `coding_loop_tools.py` sending full file
content per seam (see open follow-up below).

**Verified the fix has real headroom**, using this repo's own
`estimate_kv_cache_gb()` (not eyeballed): at the old
`MODEL_CONTEXT_LENGTH=162512`, KV cache needs ~25.6GB; real weights are
19.62GB; `nvidia-rtx-pro-6000` has 96GB VRAM — headroom was never actually
the constraint even under the wrong 62GB assumption (34GB headroom vs
25.6GB needed). The model's native max context is 262144 (10
full-attention + 50 sliding-window layers, per `estimate_kv_cache_gb()`'s
own docstring) — that's the real ceiling, not GPU memory.

**Fix applied**: corrected `VLLM_ASSUMED_WEIGHTS_GB` to match each engine
profile's actual model (`62.0` → `20.0` in `gcloud-run-setup.txt` and
`gcloud-run-setup-vllm.txt`; `16` → `16.0` in `gcloud-run-setup-vllm-lite.txt`,
value already correct, just normalized), and raised
`MODEL_CONTEXT_LENGTH` `162512` → `230512` in `gcloud-run-setup-vllm.txt`
only (the `nvidia-rtx-pro-6000` profile — the other two profiles' context
lengths were never near their own ceilings and were left unchanged).
Chose `230512` over the full `262144` native max to keep a safety margin
rather than pin exactly at the model's limit.

**Open follow-up, explicitly flagged, not yet actioned**: this fixes the
immediate crash but does not cap future growth. `read_generated_files()`
in `micro_cosmos/tools/coding_loop_tools.py` returns full content for every
file in the current seam on every reviewer call, with only a partial
mitigation (files with no BLOCKER/MAJOR findings from a prior review get
stubbed to their first ~10 lines — but this requires a prior review to
already exist, so the *first* reviewer in each TDD iteration always reads
every file in full, uncompacted). There is no hard ceiling on this: a
large enough seam (many files, or a few very large files) will eventually
reach whatever `MODEL_CONTEXT_LENGTH` is set to, just at a bigger number
than 162512. If this recurs, the durable fix is bounding/filtering
`read_generated_files()`'s output (e.g. test-file-only content for
`test_reviewer_agent`, which per its own instruction only ever analyzes
test files, not implementation files) rather than raising context length
again.
