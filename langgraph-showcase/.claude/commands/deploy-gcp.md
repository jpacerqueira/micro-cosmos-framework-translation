# Deploy Micro-Cosmos to GCP (all Cloud Run)

Walk the user through deploying or redeploying the GCP environment: two Cloud
Run services in the same project (GPU LLMGateway + web app), no Compute Engine
VM. `micro-cosmos-web` DOES require Direct VPC egress (see checklist item 39) —
same-project Cloud-Run-to-Cloud-Run traffic is not automatically "internal"
just because it's the same project, confirmed by a real 2026-07-14 incident.

$ARGUMENTS = optional: `full` (deploy both), `lmstudio` (LLMGateway service,
LM Studio engine), `vllm` (LLMGateway service, vLLM engine — see checklist
item 22), `micro-cosmos` (web app only), `deterministic` (SKIP_LLM=true, web app
only, no GPU), `load-balancer` (one-time external LB setup for public
micro-cosmos-web access). Default to asking which scope if not specified.

## Before running anything

0. Load a deploy profile into the shell instead of hand-typing exports — the
   `gcloud-run-setup*.txt` files at the repo root hold the full env-var set for
   each engine/model combination:
   ```bash
   source ./deploy-vars-in-env.sh            # gcloud-run-setup-vllm.txt (default)
   source ./deploy-vars-in-env.sh vllm-lite  # or: lmstudio | base | any path
   ```
   It must be **sourced**, not executed. Everything below still applies —
   the profile is a starting point, not a substitute for the checks in step 1.
1. Confirm all three project env vars are set and consistent:
   `echo $PROJECT_NAME $PROJECT_ID $PROJECT` — `PROJECT` and `PROJECT_ID`
   must be identical, and both must be the string Project ID, **not** the
   numeric Project Number (some gcloud commands accept the number silently;
   `gcloud iam service-accounts create` and `add-iam-policy-binding` reject
   it). If unsure, resolve it explicitly:
   ```bash
   export PROJECT_ID=$(gcloud projects describe $PROJECT --format="value(projectId)")
   export PROJECT=$PROJECT_ID
   ```
   If none of these are set, stop and ask the user for the project (do not
   guess a project ID).
2. Read `deployment/README.md` for the current prerequisites and config
   reference — it is the source of truth, more detailed than this checklist.
3. If deploying LLMGateway (GPU), remind the user to verify Cloud Run GPU
   region support and quota first — region availability for NVIDIA L4 changes
   over time:
   ```bash
   gcloud run regions list --format="value(locationId)"
   ```
   The scripts default to `europe-west4`; if quota is approved for a
   different region, the user must set `GOOGLE_CLOUD_LOCATION` before running.
4. If `MODEL_CONTEXT_LENGTH` is being raised above ~32768, warn the user that
   a single L4's 24GB VRAM (fixed, independent of the `--memory` host-RAM
   setting) is likely to OOM — see "Context length vs GPU VRAM" in
   `deployment/README.md`. `deploy_cloudrun-lmstudio-llms.py` prints its own
   warning at deploy time (`check_vram_fit()`), but flag it proactively too.
5. Before the first-ever `gcloud builds submit` on a project, confirm the
   Cloud Build service account has permissions — see "Cloud Build
   permissions" in `deployment/README.md`. Projects created after Google's
   Sept 2024 default-SA change have no dedicated Cloud Build SA; builds run
   as the Compute Engine default SA (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`)
   with zero roles, and fail with a 403 reading their own uploaded source
   tarball. Fix:
   ```bash
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
   gcloud projects add-iam-policy-binding $PROJECT \
     --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
     --role="roles/cloudbuild.builds.builder"
   ```
6. LLMGateway (GPU) deploys pass `--no-gpu-zonal-redundancy` by default — most
   projects don't have the separate zonal-redundancy GPU quota approved (base
   GPU quota is not the same thing). If the user's project *does* have it and
   they want cross-zone HA, they can set `LMSTUDIO_GPU_ZONAL_REDUNDANCY=true`.
   See "GPU zonal redundancy" in `deployment/README.md`.
7. If the user is switching `MODEL_REASONING`/`MODEL_FAST` away from the
   default `google/gemma-4-31b-qat`, they MUST also set
   `LMSTUDIO_ASSUMED_WEIGHTS_GB` to that model's actual quantized weight size
   in GB — otherwise `check_vram_fit()` silently uses the default model's
   sized default (`18.0`) and the VRAM warning becomes meaningless for the
   new model. No script/entrypoint changes are needed for the model swap
   itself — tool calling goes through LiteLLM's provider-agnostic `openai/`
   format (`micro_cosmos/settings.py::build_llm()`), and `lms get`/`lms load` in
   `lmstudio-entrypoint.sh` take the model ID as an opaque string (this
   includes multimodal models shipped as two GGUF files — LM Studio manages
   that internally). Three documented alternatives: `qwen/qwen3.6-27b`
   (dense), `qwen/qwen3.6-35b-a3b` (MoE), and `google/gemma-4-12b-qat`
   (dense, lower-spec) — see "Switching models" in `deployment/README.md`.
   **`qwen/qwen3.6-35b-a3b` on `nvidia-rtx-pro-6000` at
   `MODEL_CONTEXT_LENGTH=131512` is the current production spec
   (confirmed 2026-07-09)** — `LMSTUDIO_ASSUMED_WEIGHTS_GB=22.1` and
   `LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000` must both be set for it; the
   context length was raised from an initial conservative `65536` only
   after verifying the VRAM math (see the "Example: qwen/qwen3.6-35b-a3b"
   section in `deployment/README.md`), not guessed. `google/gemma-4-12b-qat`
   (only ~6.98GB GGUF published, Q4_0) is the lower-spec option — small
   enough to run on the cheaper default `nvidia-l4` instead of requiring
   `nvidia-rtx-pro-6000`; set `LMSTUDIO_ASSUMED_WEIGHTS_GB=7.0` and leave
   `LMSTUDIO_GPU_TYPE` unset. Documented at its native max
   `MODEL_CONTEXT_LENGTH=262144` — at that length `check_vram_fit()`'s
   naive formula estimates ~48GB of KV cache against only ~17GB headroom
   on `nvidia-l4` and **will print a loud "won't fit" warning**, but a
   per-layer accounting (47 layers capped at a 1024-token sliding window +
   1 genuinely global layer) gives a realistic estimate of only ~1.2GB —
   expect and ignore that warning, then verify the real outcome via
   `gcloud run services logs read micro-cosmos-llmgateway`, since this model
   hasn't been deployed live yet and nothing here is confirmed. See the
   "Example: google/gemma-4-12b-qat" section in `deployment/README.md` for
   the full VRAM math.
8. If `gcloud run deploy micro-cosmos-llmgateway` fails with "The user-provided
   container failed to start and listen on the port ... within the allocated
   timeout" — this is NOT an IAM/auth issue, even if a "Setting IAM Policy
   failed" warning appears just above it in the same output (that's a
   harmless, unrelated side effect of `--allow-unauthenticated` +
   `--ingress=internal`). Confirmed root cause (reproduced with two
   different models and both GPU types, ruling out size/GPU as the cause):
   `deploy_service()`'s `--add-volume-mount` MUST target
   `/root/.lmstudio/models`, never the `.lmstudio` root — mounting at the
   root shadows the `lms` binary that `lms bootstrap` installs to
   `.lmstudio/bin` at image build time, so every `lms` command in
   `lmstudio-entrypoint.sh` fails with "command not found" and `$PORT` is
   never bound. Separately, the entrypoint also starts the LMStudio server
   *before* `lms get`/`lms load` to avoid a secondary race (large model
   pulls can otherwise exceed the ~240s probe timeout). `deploy_service()`
   passes `--clear-volumes --clear-volume-mounts` before `--add-volume`/
   `--add-volume-mount` on every deploy — `--add-volume-mount` is additive
   on a redeploy of an *existing* service (it doesn't replace a previous
   revision's volume config for the same volume name), so without the clear
   flags, redeploying a service that already had a stale `/root/.lmstudio`
   mount from before this fix would leave BOTH mounts present and the bug
   would silently recur even with the corrected path in the command. If
   this exact error recurs on an already-existing service, check the live
   revision's `volumeMounts` (Cloud Run Logs Explorer JSON, or `gcloud run
   services describe ... --format=export`) for duplicate/stale mounts before
   assuming the fix didn't work. See "Container startup timeout" in
   `deployment/README.md`.
9. If the deploy fails with "Container failed to become healthy. Startup
   probes timed out after Nm" — this is a **different** issue from the two
   bugs above (same generic Cloud Run error family, different cause).
   `deploy_service()` passes a 30-minute `--startup-probe` by default
   (`LMSTUDIO_STARTUP_TIMEOUT_SECONDS`, Cloud Run's documented ceiling for
   GPU/AI workloads) instead of relying on Cloud Run's 4-minute default —
   worth keeping since a genuine GPU cold start can need more than 4
   minutes. **But if the deploy times out the FULL configured window with
   zero success, that's a strong signal it isn't a timing issue at all —
   stop extending the timeout further and pull the real container logs**
   (`gcloud run services logs read micro-cosmos-llmgateway --region=<region>
   --limit=100`) before guessing again. That's exactly what happened here:
   the real cause turned out to be `lmstudio-entrypoint.sh` calling `lms
   server start --host 0.0.0.0` — `lms server start` has no `--host` flag
   (the CLI rejected it and exited immediately, every attempt, regardless
   of timeout). The correct flag is `--bind`; its default if omitted is
   `127.0.0.1` (localhost-only), which would also break Cloud Run routing,
   so it must be passed explicitly (now also set via `LMS_SERVER_HOST` in
   `Dockerfile.lmstudio` as a durable backup). See "GPU cold-start startup
   probe timeout" in `deployment/README.md` for the full account.
10. If the deploy log shows `error: unknown command 'pull'` right after
   `[entrypoint] pulling ...` — `lms pull` was never a valid `lms` CLI
   command. The correct command is `lms get`, already fixed in
   `lmstudio-entrypoint.sh`. With a full, exact model ID (`MODEL_ID` always
   is one), `lms get` auto-selects and downloads non-interactively by
   default. See "`lms pull` doesn't exist" in `deployment/README.md`.
11. If the user wants to deploy on `LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000`
   (96GB VRAM, preview) instead of the `nvidia-l4` default: confirm they know
   it enforces a 20 vCPU/80GiB minimum (auto-applied via `GPU_DEFAULTS` in
   `deploy_cloudrun-lmstudio-llms.py`, materially pricier than L4), is only
   available in `asia-southeast1`/`asia-south2`/`europe-west4`/`us-central1`,
   requires `gcloud beta` (handled automatically by the script), and needs
   the bumped CUDA base image already in `Dockerfile.lmstudio`
   (`12.8.2-runtime-ubuntu22.04`). Not yet exercised against a live deploy in
   this project — treat the first real run as validation, not a known-good
   path. See "GPU type" in `deployment/README.md`.
12. `micro-cosmos-web` gets public internet access via an **external Application
   Load Balancer**, not `--ingress=all` — a per-project org policy
   exception for `all` on `constraints/run.allowedIngress` was requested
   and declined, so `deploy_cloudrun-micro-cosmos-app.py` deploys
   `micro-cosmos-web` with `--ingress=internal-and-cloud-load-balancing`
   instead (the policy's third allowed value). `micro-cosmos-llmgateway` is
   unaffected — stays plain `--ingress=internal`, never public, only
   called by `micro-cosmos-web`.

   The LB itself is a **separate, one-time setup script**,
   `deployment/setup_micro_cosmos_web_lb.py` (idempotent — safe to re-run),
   requiring `MICRO_COSMOS_LB_DOMAIN` (a domain the user controls DNS for — a
   Google-managed SSL cert needs one, an IP alone won't do HTTPS). It
   provisions a static IP, serverless NEG, backend service, URL map, SSL
   cert, HTTPS proxy/forwarding rule, and an HTTP→HTTPS redirect. Two
   things this script cannot do, which the user must do themselves: create
   the DNS A record (no DNS provider access from here), and wait for the
   cert to reach `ACTIVE` (up to ~60 min after DNS propagates) before
   redeploying `micro-cosmos-web` to pick up the new ingress value. See "Web UI
   access" in `deployment/README.md` for the full sequence.

   **Do NOT suggest `gcloud run services proxy` as a way to bypass
   `--ingress=internal`** (e.g. if debugging `micro-cosmos-llmgateway` directly) —
   confirmed against Google's docs that it does not tunnel through the VPC,
   it only attaches an IAM identity token to a request against the same
   public endpoint, so it fails identically to a plain browser request
   against an internal-only service. This was incorrect guidance given
   earlier in this project's history — don't repeat it.
13. Container ports now match the local `docker-compose.yml` convention:
   `micro-cosmos-llmgateway` on `1234` (`LMSTUDIO_PORT`), `micro-cosmos-web` on `8080`
   (Cloud Run's default, unchanged). This is cosmetic parity only — the
   port number never appears in `LLM_BASE_URL` since Cloud Run
   terminates HTTPS on 443 externally regardless of the internal container
   port. If touching `deploy_cloudrun-lmstudio-llms.py`'s port again, keep
   `--port` and the `--startup-probe`'s `tcpSocket.port` in sync — they're
   derived from the same variable specifically so they can't drift apart
   (a mismatch would make the health probe check the wrong port and fail
   every deploy). See "Container port convention" in `deployment/README.md`.
14. `micro-cosmos-web`'s `/app/examples` is backed by a GCS bucket
   (`MICRO_COSMOS_EXAMPLES_BUCKET`, default `$PROJECT-micro-cosmos-examples`), mounted
   via `--add-volume`/`--add-volume-mount` — matching docker-compose's
   `./examples:/app/examples` bind mount so the `/demo` gallery and
   `/demo/upload` behave the same in both environments. `ensure_examples_bucket()`
   in `deploy_cloudrun-micro-cosmos-app.py` syncs the repo's `examples/` into the
   bucket on **every** deploy via `gcloud storage rsync` (non-destructive —
   never deletes, so uploads made via the running app persist across
   redeploys). `runs/` had the same local-bind-mount-vs-nothing-on-Cloud-Run
   gap — **now closed too, see item 43 below.** See "Examples gallery" in
   `deployment/README.md`.
15. The web app has a login gate (`DEMO_USERNAME`/`DEMO_PASSWORD`, default
   `demo`/`demobxyz`) — every route redirects to `/login` until
   authenticated, in both `docker-compose` and Cloud Run. Because
   `micro-cosmos-web` is deployed with `--allow-unauthenticated` and is reachable
   via the public load balancer, this login is the only gate between the
   internet and the app — `deploy_cloudrun-micro-cosmos-app.py` now hard-fails
   (`sys.exit(1)`) if both env vars are left at their defaults, so you must
   set real values before deploying. Session is a
   signed cookie (Starlette `SessionMiddleware`, needs the `itsdangerous`
   dependency added to `pyproject.toml`) — no server-side store, so it
   works correctly across `micro-cosmos-web`'s multiple Cloud Run instances.
   **Middleware order matters**: `SessionMiddleware` must be
   `app.add_middleware()`'d *after* the `require_login` middleware in
   `micro_cosmos/web/app.py` — Starlette wraps middleware so the last one added
   is outermost (runs first on the way in); get this backwards and
   `request.session` raises `AssertionError: SessionMiddleware must be
   installed`. `SESSION_SECRET_KEY` must be identical across every instance
   of a Cloud Run revision (env vars already are, automatically) —
   `deploy_cloudrun-micro-cosmos-app.py` generates one fresh per deploy unless
   the env var is set explicitly (setting it persists sessions across
   redeploys). `SESSION_HTTPS_ONLY=true` only for Cloud Run (served over
   real HTTPS via the LB); stays `false` for local `docker-compose` (plain
   `http://localhost:8080` — browsers won't send a `Secure` cookie over
   plain HTTP at all). See "Login" in `deployment/README.md`.
16. If `gcloud builds submit` for `micro-cosmos-web` fails during the Trivy
   install step — `apt-get install` succeeds, then `aquasecurity/trivy`'s
   `contrib/install.sh` prints `found version: ...` and the whole `RUN`
   step exits non-zero with no further output — this is `install.sh`
   hitting `api.github.com`'s unauthenticated rate limit (60 req/hr per
   IP), which Cloud Build's shared builder IPs run into intermittently.
   `Dockerfile` now downloads the pinned release tarball directly instead
   of piping `install.sh` through `sh`, skipping that rate-limited call
   entirely. If this exact failure recurs anyway, that points to Cloud
   Build's egress genuinely not reaching GitHub, not rate limiting — check
   the Cloud Build logs link in the failure output.
17. If `micro-cosmos-llmgateway` fails to serve requests (e.g. the web app gets a
   generic HTML 404 instead of a proper LM Studio JSON error) — check for
   two distinct bugs found via live logs: (a) `lms get` can **stall**
   (progress frozen, not slow) when resuming into a stale `.part` file
   left on the GCS-mounted bucket from an earlier failed attempt — gcsfuse
   logs `will use legacy staged writes` for any non-empty existing file,
   which is slow enough to trip `lms`'s own download-stall timeout; fix by
   deleting the stale `.part` files (`gcloud storage rm -r
   gs://$PROJECT-lmstudio-models/lmstudio-community/<model>-GGUF/`) so the
   retry starts as a genuinely new/empty file. (b) `lms load` can hang
   **indefinitely** in an interactive "Select a model to load" picker if
   the model isn't fully present — Cloud Run has no TTY to answer it, and
   `set -e` doesn't catch a blocked stdin read. `lmstudio-entrypoint.sh`
   now retries `lms get` 99x and runs `lms load` with `-y </dev/null` so an
   unresolvable model fails fast instead of hanging. See the two
   2026-07-09 "Real incident" entries in
   `transferable-skills/memory/gcp-deployment.md` for the full log
   evidence.
18. `Settings.skip_llm` (`micro_cosmos/settings.py`) now defaults to `True`
   (Deterministic) — a whole-app default, not just the web UI's new-run
   toggle: it also governs the ASK tab (extractive-only answers) and
   embeddings (disabled, lexical fallback). `docker-compose.yml` sets
   `SKIP_LLM: "true"` to match. **`deploy_cloudrun-micro-cosmos-app.py`'s
   fallback was deliberately left at `os.environ.get("SKIP_LLM", "false")`
   — do not change this** without exporting `SKIP_LLM=false` first: every
   deploy this session has relied on that fallback to keep the production
   `qwen/qwen3.6-35b-a3b` LLM pipeline running, and flipping it to `"true"`
   would silently revert the next `micro-cosmos-web` redeploy to Deterministic
   mode. Net effect: local `docker-compose up` now defaults to
   Deterministic; the live Cloud Run `/demo` toggle still defaults to LLM
   mode, since Cloud Run always sets `SKIP_LLM` explicitly. See
   `transferable-skills/memory/gcp-deployment.md`'s "Global SKIP_LLM
   default flipped to True" entry for the full reasoning.
19. If `micro-cosmos-llmgateway` crash-loops with `Container called exit(1)` and
   **no accompanying error text** in the logs, check whether it happened
   during `lms load` (not `lms get`) — a live incident on 2026-07-10/11 hit
   exactly this on `nvidia-rtx-pro-6000` at the production context
   (`131512`), which had never actually been load-tested (only validated by
   `check_vram_fit()`'s arithmetic — the model previously loaded fine at a
   lower context, `65536`). `lms server start` binds `$PORT` before the
   model finishes loading, so Cloud Run's `Ready` condition can go `True`
   from the startup probe passing seconds before a load-time crash — this
   is a genuine runtime crash-loop, not a startup failure, and does **not**
   mean disk space is the problem (GGUF is memory-mapped, no
   decompress-to-N×-size step). `lmstudio-entrypoint.sh` now captures
   `lms load`'s output via `tee` (same pattern as the `lms get` retry loop)
   and prints exit code + last 50 log lines + model/context/gpu_layers/
   `GPU_TYPE`/`LMSTUDIO_VRAM_GB` config to stderr on failure — both new env
   vars are threaded from `deploy_cloudrun-lmstudio-llms.py`'s
   `GPU_DEFAULTS`. First diagnostic step on a fresh occurrence: read the
   captured log tail; if it's still empty/unhelpful, bisect by redeploying
   with `MODEL_CONTEXT_LENGTH=65536` (last confirmed-working) to check
   whether the context length itself is the trigger before assuming
   anything about VRAM/RAM capacity. See the 2026-07-11 "Bug fix" entry in
   `changes-log.md` and `transferable-skills/memory/gcp-deployment.md` for
   the full incident writeup.
20. **Follow-up to item 19**: the bisection redeploy (`MODEL_CONTEXT_LENGTH=65536`)
   crashed at the *identical* load progress (~34-41%) as `131512` did — ruling
   out context length/VRAM sizing as the cause, since context only affects
   KV-cache size, not which layer is being loaded at a given progress %. The
   captured log tail (from item 19's fix) revealed the real error: `Error:
   Engine protocol runtime llama-server for <id> exited before becoming
   healthy. exitCode=127, signal=null` — `127` is the standard POSIX "command
   not found/exec failed" code. `lms load` itself is fine; the separate
   `llama-server` backend subprocess it spawns can't execute. `lms` manages
   inference backends as independently-installable "runtimes" (`lms runtime
   ls/get/select`), distinct from the `lms` CLI binary `lms bootstrap`
   installs at image build time — build time has **no GPU attached**, so the
   default runtime `bootstrap` picks is unlikely to match `nvidia-rtx-pro-6000`,
   and only `.lmstudio/models` (not wherever runtimes live) persists across
   container restarts, making this 100% reproducible every time regardless of
   model/context. `lmstudio-entrypoint.sh` now logs `lms runtime ls` and
   `--help` dumps for `runtime`/`get`/`select` at startup (read-only, safe) so
   the next redeploy's logs give the exact CLI syntax needed for a confident
   install/select fix instead of guessing against a live GPU deploy, and logs
   `lms ps` after a successful `lms load` as a direct confirmation that
   `llama-server` is actually loaded and healthy. **Not yet fixed** — this is
   diagnostics plus a confirmation mechanism; the actual runtime-install fix
   is the next step once the new log output is read. See the 2026-07-11
   "Bug fix (follow-up)" entry in `changes-log.md` and the corresponding
   "Follow-up (2026-07-11)" entry in `transferable-skills/memory/gcp-deployment.md`.
21. **Follow-up to item 20**: live logs confirmed `lms runtime ls` prints
   **"No runtimes found."** — the root cause is confirmed, not just
   hypothesized: no inference-engine backend is installed at all. `lms
   runtime get [query]` (examples: `llama.cpp`, `llama.cpp:cuda`,
   `llama.cpp@1.2.3`) with `-l/--list`, `--allow-incompatible`,
   `--channel <stable|beta>`, `-y/--yes`; `lms runtime select [alias]
   [--latest]`; and `lms runtime survey` are the real, confirmed CLI
   surface (captured from the actual binary's `--help`, not guessed).
   `lmstudio-entrypoint.sh` now attempts `lms runtime get llama.cpp:cuda -y`
   (best-effort, captured via `tee`, non-fatal on failure) before `lms
   get`/`lms load` run, plus `lms runtime survey`/`get llama.cpp -l`
   diagnostics. **Deliberately does not pass `--allow-incompatible`** — user
   decision (`AskUserQuestion`) to try the compatible-only path first, since
   `nvidia-rtx-pro-6000` is a very new Blackwell-class GPU `lms`'s
   compatibility database may not yet recognize, and forcing an
   incompatible engine risks a worse, harder-to-diagnose failure than
   today's clean `exitCode=127`. If this reports zero compatible matches on
   the next deploy, that's the justified next signal to revisit
   `--allow-incompatible`. See the 2026-07-11 "Bug fix (follow-up 2)" entry
   in `changes-log.md` and "Follow-up 2" in
   `transferable-skills/memory/gcp-deployment.md`.
22. **Follow-up to item 21 — engine switch** (model default superseded by
   item 23 below — vLLM/Blackwell architecture decision here is unchanged):
   the install attempt also
   failed live (`No runtime extensions matched the query`) — confirmed,
   not just suspected, that no CUDA `llama.cpp` runtime exists for
   `nvidia-rtx-pro-6000` at all. `micro-cosmos-llmgateway` switched engines to
   **vLLM**, defaulting back to **`google/gemma-4-31B-it-qat-w4a16-ct`**
   (ungated, Apache 2.0 — the gated `nvidia/Gemma-4-31B-IT-NVFP4` checkpoint
   found first was ruled out since the user has no license access), on
   `vllm/vllm-openai:cu129-nightly` (not `cu130` — documented to crash
   `custom_all_reduce` on this GPU's compute capability, moot for us since
   single-GPU has no tensor parallelism/all-reduce at all). Real per-layer
   VRAM math (not a rough guess): ~57.8GB (17GB weights + ~40GB bf16 KV
   cache for the model's 10 full-attention layers) fits comfortably under
   96GB×0.9 utilization even at the full native 262,144 context. New files:
   `deployment/Dockerfile.vllm`, `deployment/vllm-entrypoint.sh`,
   `deployment/deploy_cloudrun-vllm-llms.py` (modeled directly on
   `deploy_cloudrun-lmstudio-llms.py`'s proven structure) — invoke via
   `LMSTUDIO_ENGINE=vllm python deployment/deploy.py` (defaults to
   `lmstudio`, unchanged, if unset). **`SERVICE_NAME` deliberately stays
   `micro-cosmos-llmgateway`** — same Cloud Run service regardless of engine,
   only image/entrypoint swapped, so `discover_lmstudio_url()` needs no
   changes. (Originally flagged here as a pending rename from
   `micro-cosmos-lmstudio`, since the script-says-vllm/service-named-after-a-
   different-product mismatch was confusing — completed 2026-07-15, see
   the "Rename" entry in `changes-log.md`.) **Not yet verified
   against a live deploy** — no Docker/Cloud Run/GPU access this session.
   See the 2026-07-11 "Feature: switch micro-cosmos-llmgateway to vLLM" entry in
   `changes-log.md` and "Engine switch" in
   `transferable-skills/memory/gcp-deployment.md` for the full research
   trail (ruled out `cu130-nightly`, SGLang, and community `voipmonitor/*`
   images with specific reasons for each).
23. **Follow-up to item 22 — model reconsidered before ever deploying**:
   user asked directly whether the vLLM default is actually optimized for
   this pipeline's coding-translation use case. Checked (WebSearch, mostly
   low-confidence SEO sources but a consistent directional finding matching
   this repo's own already-verified claim that Qwen3.6 is benchmarked on
   SWE-bench/agentic-coding specifically): switched the vLLM default from
   `google/gemma-4-31B-it-qat-w4a16-ct` to **`Qwen/Qwen3.6-35B-A3B-FP8`**
   (ungated, official checkpoint, already confirmed vLLM-compatible — the
   original blocker for Qwen3.6 was LM Studio/`llama.cpp`-specific, not
   vLLM). Real VRAM math redone for this model's actual architecture
   (2 KV heads, extreme GQA, vs Gemma's 16): ~40GB total (5GB KV cache +
   35GB FP8 weights) vs Gemma's ~57.8GB — *more* headroom despite more
   total params. See the 2026-07-11 "Model reconsidered" entries in
   `changes-log.md` and `transferable-skills/memory/gcp-deployment.md`.
24. **Follow-up to item 23 — two more compatibility gaps found proactively,
   plus LM Studio's own default fixed**: user asked to confirm `micro-cosmos-web`
   is actually compatible with vLLM and fix issues in advance. Found:
   (a) vLLM needs `--enable-auto-tool-choice --tool-call-parser <name>` or
   it silently returns tool calls as plain text, breaking every ADK
   `FunctionTool`-using agent — fixed via new conditional
   `VLLM_TOOL_CALL_PARSER` (default `hermes`, unconfirmed for Qwen3.6
   specifically); (b) `micro_cosmos/settings.py`'s `build_llm()` unconditionally
   sent `extra_body={"num_ctx": ...}`, an LM Studio-specific parameter that
   vLLM's strict schema validation would reject on every request — fixed
   via new `Settings.llm_engine`/`LLM_ENGINE` env var, threaded through
   `deploy_cloudrun-micro-cosmos-app.py` and `deploy.py` the same way as
   `model_reasoning`. **Separately**: LM Studio's own default was confirmed
   NOT to actually be `google/gemma-4-e4b`/`nvidia-l4` with zero env vars
   set (GPU type was right, model wasn't) — fixed
   `deploy_cloudrun-lmstudio-llms.py`'s `DEFAULT_MODEL_ID`/
   `DEFAULT_CONTEXT_LENGTH`/`DEFAULT_ASSUMED_WEIGHTS_GB` and
   `deploy_cloudrun-micro-cosmos-app.py`'s matching standalone fallback so this
   is now confirmed true for both the orchestrated and standalone paths.
   **None of this verified against a live deploy** — no Docker/Cloud
   Run/GPU access this session. See the 2026-07-11 "two more real
   vLLM-compatibility gaps" entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md`.
25. **Confirmed live, 2026-07-12/13**: the vLLM path actually works —
   `MIN_INSTANCES=1` fix verified in the live revision YAML, tool-call/
   reasoning-parser flags confirmed applied via `non-default args` in the
   real startup log, and a genuine `micro-cosmos-web`→`micro-cosmos-llmgateway` 404
   traced to Cloud Run's request-pending timeout being far shorter than
   this GPU workload's real ~15-minute cold start (`MIN_INSTANCES=0` is
   not just slower but **structurally unreliable** here — fixed by
   `MIN_INSTANCES=1`). Follow-up per PR #12 review: `Dockerfile.vllm`
   pinned off the floating `cu129-nightly` tag to a specific digest
   (`sha256:e271b70a...`) — the tag had already moved since the earlier
   deploys (nightly rebuilds ~daily), so this is "pin to current + verify"
   not "pin to the exact historical one," a deliberate tradeoff the user
   confirmed. Also added optional `HF_TOKEN` support with failure-output
   redaction. See the 2026-07-13 entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md`.
26. **Bug fix + feature (2026-07-13), found via `/debug-run` on a real
   stuck local run**: `_wait_for_llm_ready()` in
   `micro_cosmos/orchestration/driver.py` never sent an `Authorization` header,
   so any LM Studio instance with "Require Authentication" on (confirmed
   via direct `curl`: real 401 `invalid_api_key` on both probe endpoints)
   silently stalled every LLM-mode run at "waiting for `<model>` to load…"
   for the full `LMSTUDIO_READY_TIMEOUT_SECONDS` before proceeding anyway.
   Fixed — both probes now send `Authorization: Bearer {llm_api_key}`.
   Follow-up: `LLM_API_KEY` is now enforceable end-to-end on vLLM
   (`vllm serve --api-key`, wired through `deploy_cloudrun-vllm-llms.py`
   and `deploy.py`) but **confirmed impossible to enable headlessly on LM
   Studio** — `lms server start` has no CLI flag for it (GUI-only,
   `lmstudio-ai/lms#489`); `--ingress=internal` remains that engine's only
   real boundary. If a fresh LLM-mode run seems stuck at the "waiting for
   `<model>` to load…" trace message with no further progress, check the
   GPU service's own logs for `401 invalid_api_key` before assuming a slow
   cold start. See the 2026-07-13 entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md`.
27. **Feature (2026-07-13), follow-up to item 26**: composed-URL/`200 OK`
   logging added at every point `micro-cosmos-web` talks to the LM Studio/vLLM
   machine — `_wait_for_llm_ready()` (`driver.py`), `build_llm()`
   (`settings.py`), `build_embedder()` (`embedder.py`), and the ASK tab's
   completion call (`chat.py`). All via loggers that are children of the
   `micro-cosmos` root logger configured in `micro_cosmos/__init__.py`, so they
   appear in `docker compose logs` / `gcloud run services logs read` with
   no extra setup. Controlled by `MICRO_COSMOS_LOG_LEVEL` (default `INFO` —
   composed URLs, `200 OK`, 401/timeout warnings; `DEBUG` adds a line per
   individual readiness-check poll). When debugging a run that looks stuck
   or slow, set `MICRO_COSMOS_LOG_LEVEL=DEBUG` and redeploy (or restart the
   local container) before digging further — see "Logging" in
   `deployment/README.md` for the full level table.
28. **Bug fix (cosmetic, 2026-07-13), found via item 27's own logging**: a
   real production log (`non-default args` line confirmed `tool_call_parser`/
   `reasoning_parser`/`api_key` all correctly reaching `vllm serve` — nothing
   actually broken) also showed `WARNING [envs.py:2094] Unknown vLLM
   environment variable detected: VLLM_TOOL_CALL_PARSER` and
   `VLLM_REASONING_PARSER`. Root cause: those two names are this repo's own
   entrypoint convention, not real vLLM-recognized env vars — the `VLLM_`
   prefix just happened to collide with vLLM's own env-var scanner, which
   flags any unrecognized `VLLM_*` name. Renamed to `LMSTUDIO_TOOL_CALL_PARSER`/
   `LMSTUDIO_REASONING_PARSER` (matching the existing `LMSTUDIO_*` convention
   for GPU-service config that applies regardless of engine, e.g.
   `LMSTUDIO_GPU_TYPE`) — eliminates the warning entirely. **Scoped to the
   vLLM GPU-service deploy path only** — grepped the repo first and confirmed
   zero references in `docker-compose.yml`, `.env.example`, or any
   `micro_cosmos/*.py` app code, so neither the LM Studio engine path nor
   `micro-cosmos-web`'s own deploy needed any change. If you have these two old
   names exported in your shell/`.env`, update them to the `LMSTUDIO_*` form
   before your next vLLM deploy. See the 2026-07-13 entries in
   `changes-log.md` and `transferable-skills/memory/gcp-deployment.md`.
29. **Feature (2026-07-13)**: `micro_cosmos/settings.py`'s
   `llm_ready_timeout_seconds` (default 1500s/25min, controls how long
   `micro-cosmos-web`'s pre-flight readiness check waits before proceeding
   anyway) now has a floor of **1500s (25 min) — same as the default**,
   enforced by a `field_validator` — any lower configured value is silently
   clamped up with a warning logged, rather than letting a misconfigured
   short timeout race ahead of a genuine cold start. (First implemented
   with a 16-min floor; corrected same-day to 25 min once evidence showed a
   worst-case fresh deploy could approach that full 25 minutes — see
   below — so a lower floor would have been pointless.) Verified live
   against real `pydantic` (not just `ast.parse`) via a throwaway copy in
   the running container: default passes through unchanged, values above
   the floor pass through unchanged, values below get clamped to exactly
   1500 with the warning.
   **Open question found the same day, not yet resolved**: a genuinely
   fresh `micro-cosmos-llmgateway` `CreateService` (first-ever deploy of a new
   revision, full image pull) was measured taking **16m38s just for the
   container to bind port 1234** (91 failed TCP startup-probe attempts at
   10s intervals) — before vLLM's model loading even starts. Combined with
   the ~10-12 min model-load time measured separately, a worst-case fresh
   deploy can plausibly approach ~25-29 minutes total — right at or beyond
   the 1500s ceiling itself, which is exactly why the floor now matches the
   ceiling rather than sitting comfortably below it. See
   `transferable-skills/memory/gcp-deployment.md`'s
   2026-07-13 entries for the live run (`45e187b6`) that appeared to get
   stuck on exactly this.
30. **Convention change (2026-07-13)**: the vLLM engine's Cloud Run
   service now defaults to port `8000` (vLLM's own native default,
   confirmed via vLLM's docs) instead of being forced onto LM Studio's
   `1234` convention — raised while investigating the item 29 incident
   (a hypothesis that turned out **not** to be the actual cause, ruled out
   by the `STARTUP TCP probe succeeded ... on port 1234` line in that same
   log, which proves the port was already wired correctly end-to-end; a
   port mismatch produces connection-refused/timeout, never an HTTP 404).
   Made anyway as a legitimate convention fix: `deploy_cloudrun-vllm-llms.py`'s
   `DEFAULT_PORT` and `vllm-entrypoint.sh`'s `PORT` fallback both changed to
   `8000`; `deploy_cloudrun-lmstudio-llms.py`'s LM Studio path is untouched
   (`1234`, still matches local docker-compose). No `micro-cosmos-web`/app-code
   change needed — `LLM_BASE_URL` is always the Cloud Run HTTPS URL
   (port 443 externally), never the container's internal port.
31. **Feature (2026-07-13)**: vLLM engine default switched to
   `google/gemma-4-31B-it` — image `vllm/vllm-openai:gemma4` (replaces the
   pinned `cu129-nightly` digest), model history now Gemma-w4a16 (planned,
   never deployed) → Qwen3.6-FP8 (deployed) → Gemma-4-31B-it BF16 (this
   entry), switched while the item 29/30 Qwen3.6 readiness/404
   investigation was still open — a deliberate reset, not a confirmed fix
   for that bug. Real VRAM math from this checkpoint's own `config.json`
   (60 layers, 10 full-attention + 50 sliding-window at 1024 tokens, 16 KV
   heads): `~62GB` BF16 weights alone rule out `nvidia-l4`; at the native
   max context (262144) even `nvidia-rtx-pro-6000` doesn't fit (~102.8GB
   vs 86.4GB budget) — `DEFAULT_CONTEXT_LENGTH` set to `65536`
   (~72.8GB total, ~13.6GB headroom) instead. `estimate_kv_cache_gb()`
   extended to add the sliding-window layers' bounded-but-nonzero
   contribution (previously assumed zero, correct only for Qwen3.6's
   truly-linear-attention layers). New requirement found: Gemma 4 tool
   calling needs `--chat-template examples/tool_chat_template_gemma4.jinja`
   **alongside** `--tool-call-parser gemma4` (new `LMSTUDIO_CHAT_TEMPLATE`
   env var) — Qwen3.6/hermes needed no such template. `gclud-run-setup.txt`
   and `deployment/README.md` (new example section, Qwen3.6 section marked
   superseded, config-reference rows, manual `gcloud` equivalent) all
   updated. See `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-13 entries.
32. **Feature (2026-07-13), direct follow-up to item 29's incident**: added
   an in-container watchdog to `vllm-entrypoint.sh` — the real root cause
   of that incident was Cloud Run's TCP-only `--startup-probe` marking a
   revision "Ready" while `EngineCore` had zero activity for 44+ minutes.
   Switching Cloud Run's own probe to HTTP was researched and ruled out
   (`/health` has the same blind spot per vLLM's own GitHub issues;
   `/v1/models` needs an auth header Cloud Run's probe CLI can't send).
   Instead, `vllm serve` now runs in the background inside the container
   while the script itself polls `/v1/models` (with the auth header) for
   up to `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS` (default 1500s) — on failure,
   kills the process and exits non-zero (a real Cloud Run crash-loop,
   easy to alert on) instead of staying silently "Ready." Verified with a
   standalone bash harness (fake `vllm` binary, 5 scenarios) **before**
   touching a live deploy — caught a real `set -u`/empty-array bug in the
   process (fixed with the standard `${ARR[@]+"${ARR[@]}"}` idiom). See
   `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-13 entries.
33. **Feature (2026-07-13)**: same in-container watchdog ported to the LM
   Studio engine (`lmstudio-entrypoint.sh`) — same underlying gap
   (`lms server start` binds the port long before `lms load` finishes).
   **First attempt (an outer watchdog wrapping the whole startup
   sequence, signaling the script's own PID) was built, tested, and
   abandoned before shipping** — a standalone bash harness caught that
   bash defers trap handlers until the current foreground command
   finishes, so it could never actually interrupt a hung `lms load` (the
   exact scenario it existed for). Redesigned to mirror vLLM exactly:
   `lms load` runs in the background, polled directly via `kill -0` —
   verified with a fake `lms` CLI across 3 scenarios (normal completion,
   `lms load` hangs forever → killed within the timeout, `lms load` fails
   explicitly → real exit code still propagates immediately). New
   `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS`/`LMSTUDIO_WATCHDOG_POLL_SECONDS`
   (shared var names with vLLM, separate `DEFAULT_*` constants per
   script). See `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-13 entries.
34. **Feature (2026-07-13)**: `--limit-mm-per-prompt image=0,audio=0`
   added for the vLLM engine — per vLLM's own official Gemma 4 recipe's
   "text-only workloads" tip (this pipeline never sends image/audio
   input). New `LMSTUDIO_LIMIT_MM_PER_PROMPT` env var, **must stay
   conditional** — confirmed via a real vLLM bug report that this flag
   raises a hard `ValueError` on a genuinely text-only model like
   `Qwen/Qwen3.6-35B-A3B-FP8` (also served by this same entrypoint via
   `MODEL_REASONING` override), not just a warning. Also fixed a comma-
   safety issue: this value's own content contains a comma, which would
   corrupt gcloud's `--set-env-vars` parsing if folded into the main
   comma-joined string — passed as its own separate `--set-env-vars` flag
   instead (confirmed additive, not destructive, via Cloud Run's own
   docs). See `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-13 entries.
35. **Bug fix (2026-07-14), found via a live Cloud Run deploy failure**:
   item 34's flat `image=0,audio=0` form for `--limit-mm-per-prompt` is
   the WRONG syntax — `vllm serve` failed at startup with `error: argument
   --limit-mm-per-prompt: Value image=0 cannot be converted to <function
   loads at ...>`. The flag's real type is `json.loads`; the correct value
   is a JSON object (`'{"image":0,"audio":0}'`), confirmed via vLLM's own
   canonical `docs.vllm.ai/en/stable/configuration/engine_args/`
   reference, not the less-authoritative recipe page item 34 was based
   on. Also fixed: an **unquoted** JSON value undergoes bash
   brace-expansion on `export`, silently stripping the double quotes —
   always single-quote this value in shell contexts. Updated
   `DEFAULT_LIMIT_MM_PER_PROMPT` in `deploy_cloudrun-vllm-llms.py`,
   `vllm-entrypoint.sh`'s comment, `deployment/README.md`'s every
   shell-facing example, and both `gclud-run-setup*.txt` files. The
   separate-`--set-env-vars`-flag comma-safety mechanism from item 34 did
   NOT need to change (JSON also contains a comma). Re-verified end-to-end
   with the fake-`vllm`-echo-args harness. See
   `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-14 entries.
36. **Revert (2026-07-14), items 34/35 fully superseded**: the JSON fix in
   item 35 still failed the live deploy — this time `gcloud` itself
   rejected the value: `ERROR: (gcloud.beta.run.deploy) argument
   --set-env-vars: Bad syntax for dict arg: ["audio":0}]`. `gcloud run
   deploy --set-env-vars` has its own dict-argument parser that can't
   handle a JSON-shaped value at all — regardless of shell quoting or
   being passed as its own separate flag occurrence. Properly fixing this
   would need `gcloud topic escaping`'s escape syntax or an
   `--env-vars-file`, real complexity for a minor optimization. **Decision:
   removed `--limit-mm-per-prompt`/`LMSTUDIO_LIMIT_MM_PER_PROMPT` entirely**
   rather than keep patching around gcloud's escaping rules — deleted from
   `deploy_cloudrun-vllm-llms.py` (constant, param, `extra_env_var_flags`
   mechanism, print-summary mention), `vllm-entrypoint.sh` (env var +
   conditional flag), `deployment/README.md` (all examples/table
   row/manual-gcloud mentions, replaced with a short explanatory
   paragraph), and both `gclud-run-setup*.txt` files (line deleted). Items
   34/35 remain in this log as the historical record of why this dead end
   was explored and ruled out — do not re-add this flag without first
   testing against a live `gcloud run deploy` call. See
   `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-14 "Revert" entries.
37. **Feature (2026-07-14)**: `LMSTUDIO_REASONING_PARSER` now defaults to
   `gemma4` for the vLLM engine (was previously left unset/`""`). User
   supplied an example command straight from vLLM's own Gemma 4 recipe
   pairing `--reasoning-parser gemma4` with `--tool-call-parser gemma4`
   for `google/gemma-4-31B-it` — confirming it should be on by default.
   No mechanism changes needed (`vllm-entrypoint.sh` already appends
   `--reasoning-parser` whenever the env var is set); only
   `DEFAULT_REASONING_PARSER` in `deploy_cloudrun-vllm-llms.py` and
   `deployment/README.md`'s stale "left unset" mentions changed. Set
   `LMSTUDIO_REASONING_PARSER=` (empty) to disable if you don't want
   "thinking" content surfaced. See
   `changes-log.md`/`transferable-skills/memory/gcp-deployment.md`'s
   2026-07-14 entries.
38. **Bug fix (2026-07-14)**: if a vLLM-engine deploy fails with "Container
   failed to become healthy. Startup probes timed out after 30m" AND the
   real logs (pulled per item 9's rule — don't extend the timeout, read
   logs first) show model loading finishing normally (`Loading weights
   took Ns`) followed by an `AssertionError: unsupported kv_cache_dtype
   (str), got bfloat16` inside `triton_reshape_and_cache_flash.py` — this
   is the **same 30-minute-timeout error family as item 9, but a different,
   unrelated cause**: not a slow load, a deterministic crash. vLLM forces
   the `TRITON_ATTN` backend for **any** Gemma 4 model
   (`Forcing TRITON_ATTN backend to prevent mixed-backend numerical
   divergence`), and that backend's kernel only accepts
   `kv_cache_dtype == "auto"` or an `fp8*` value, never a literal
   `"bfloat16"` string. `vllm-entrypoint.sh` had hardcoded
   `--kv-cache-dtype bfloat16` (added for a real numerics reason — `auto`
   resolves to an uncalibrated fp8_e4m3 scale=1.0 on this GPU generation —
   but that tradeoff turned out not to be optional once it crashes
   outright). Because the container crash-loops fast (~8 min per cycle:
   mount → load → compile → crash → watchdog exit(1) → restart), Cloud
   Run's TCP probe never catches port 8000 open even once across the full
   30-minute window, producing an error indistinguishable at a glance from
   a genuinely slow model load. Fixed by removing the hardcoded flag
   entirely (falls back to vLLM's own `auto` default). **If you ever
   reintroduce an explicit `--kv-cache-dtype` value for a Gemma 4 model,
   it must be `"auto"` or start with `"fp8"` — nothing else will pass this
   kernel's assertion.** See the 2026-07-14 "Bug fix: `--kv-cache-dtype
   bfloat16` crashes every Gemma 4 vLLM deploy" entries in `changes-log.md`
   and `transferable-skills/memory/gcp-deployment.md` for the full log
   evidence and the lesson on telling these two failure modes apart.
39. **Bug fix (2026-07-14)**: `micro-cosmos-web` could never reach
   `micro-cosmos-llmgateway` at all — `run.googleapis.com/requests` (Cloud Run's own
   per-request log for the GPU service) had **zero entries ever**, confirmed
   directly via `gcloud logging read`, across every revision since first
   deploy. This was previously assumed to be same-project Cloud Run traffic
   automatically counting as "internal" (`--ingress=internal` on
   `micro-cosmos-llmgateway`) — **that assumption is false**. Without Direct VPC
   egress on the *caller*, its outbound calls to the callee's public
   `*.run.app` hostname leave over the public internet and get silently
   dropped at Google's front end, upstream of both the container and Cloud
   Run's own request logging (which is why the GPU service's logs showed
   nothing at all, not even a rejected request). This project's org policy
   blocks `--ingress=all` (see item 12), so relaxing `micro-cosmos-llmgateway`'s
   ingress was not a viable alternative — Direct VPC egress on `micro-cosmos-web`
   is the fix, and it keeps `micro-cosmos-llmgateway` fully non-public. One-time
   prerequisite (already done for `micro-cosmos`; needed once per new
   project):
   ```bash
   gcloud compute networks create micro-cosmos-vpc --subnet-mode=custom
   gcloud compute networks subnets create micro-cosmos-vpc-europe-west4 \
       --network=micro-cosmos-vpc --region=europe-west4 --range=10.10.0.0/24
   # Required — see item 40: without these, --vpc-egress=all-traffic
   # strands every OTHER outbound call the service makes (GCS, Anthropic API).
   gcloud compute routers create micro-cosmos-vpc-router \
       --network=micro-cosmos-vpc --region=europe-west4
   gcloud compute routers nats create micro-cosmos-vpc-nat \
       --router=micro-cosmos-vpc-router --region=europe-west4 \
       --nat-custom-subnet-ip-ranges=micro-cosmos-vpc-europe-west4 \
       --auto-allocate-nat-external-ips
   gcloud compute networks subnets update micro-cosmos-vpc-europe-west4 \
       --region=europe-west4 --enable-private-ip-google-access
   ```
   `deploy_cloudrun-micro-cosmos-app.py` now passes `--network=micro-cosmos-vpc
   --subnet=micro-cosmos-vpc-europe-west4 --vpc-egress=all-traffic` by default
   (overridable via `MICRO_COSMOS_VPC_NETWORK`/`MICRO_COSMOS_VPC_SUBNET` if a
   different project uses different names) — no extra steps needed for a
   normal `python deployment/deploy_cloudrun-micro-cosmos-app.py` run beyond
   having the network/subnet/NAT exist first. `all-traffic` is required, not
   the default `private-ranges-only` — the LLMGateway URL is a public
   `*.run.app` hostname, not an RFC1918 address, so `private-ranges-only`
   would leave this traffic unchanged (still public-internet-routed).
   `micro-cosmos-llmgateway` itself does not need to be redeployed for this fix,
   and does NOT need any VPC config of its own — it's the ingress=internal
   callee, not the caller; only the caller side needs Direct VPC egress.
   See the 2026-07-14 entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md` for the full incident
   writeup.
40. **Bug fix (2026-07-14), direct follow-up to item 39**: the first live
   redeploy with item 39's VPC egress config failed —
   "container failed to start and listen on the port ... within the
   allocated timeout." Real logs showed the failure was unrelated to
   `micro-cosmos-llmgateway`: the pre-existing `examples-data` GCS FUSE volume
   mount (backs the `/demo` gallery) calls `storage.googleapis.com` at
   container startup and timed out completely
   (`dial tcp <ip>:443: i/o timeout`), because `micro-cosmos-vpc` had a network
   and subnet but no route out at all — confirmed via
   `gcloud compute routers list` (no router → no Cloud NAT) and
   `gcloud compute networks subnets describe`
   (`privateIpGoogleAccess: false`). **`--vpc-egress=all-traffic` routes
   every outbound call through the VPC, not just the one to
   `micro-cosmos-llmgateway`** — the fix in item 39 was necessary but incomplete
   without also giving the VPC a route to the internet/Google APIs. No
   outage resulted — Cloud Run's atomic-deploy behavior kept 100% traffic
   on the prior healthy revision throughout. Fix: the Cloud Router/NAT/
   Private Google Access commands now folded into item 39's one-time
   prerequisite block above. Also confirmed unaffected by any of this: the
   report/output-code download endpoints in `micro_cosmos/web/app.py` are pure
   local-disk zip + `FileResponse` operations with zero outbound calls. See
   the 2026-07-14 follow-up entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md`.
41. **Bug fix (2026-07-14), second follow-up to item 39**: once items
   39/40's fixes let `micro-cosmos-web` actually reach `micro-cosmos-llmgateway`, the
   readiness poll returned its first real application-level response —
   `401 (invalid/missing API key)` instead of silence/404. `LLM_API_KEY`
   (on `micro-cosmos-web`) and vLLM's `--api-key` (on `micro-cosmos-llmgateway`) are the
   same logical secret deployed independently to both services — if you
   rotate one without the other, you get a `401`, not an obvious
   "forgot to redeploy" signal. The readiness-wait log line already prints
   `api_key_configured=True`, so a `401` specifically (vs `404`/no
   response) means the services are reachable and only disagree on the
   token. **Whenever this key is rotated, redeploy both services with the
   identical new value** — confirmed fixed by doing exactly that (new
   revisions on both sides), verified via logs: the `401` loop stopped,
   followed by a clean `200 OK`, and a subsequent fresh readiness cycle had
   zero 401s. See the 2026-07-14 entries in `changes-log.md` and
   `transferable-skills/memory/gcp-deployment.md`.
42. **Rename (2026-07-15)**: the GPU Cloud Run service was renamed
   `micro-cosmos-lmstudio` → `micro-cosmos-llmgateway` — it's engine-agnostic (runs
   either the real LM Studio software or vLLM), so naming it after one
   specific engine was inaccurate branding. Scope was deliberately limited
   to the service identity and the web client's trace text (`[LMStudio]` →
   `[LLMGateway]`, trace pill `LMSTUDIO` → `LLMGATEWAY` — driven by
   `driver.py`'s `author`/`source` fields, not hardcoded in `dashboard.js`).
   **Explicitly NOT renamed**: the `LMSTUDIO_*` env var convention
   (`LMSTUDIO_GPU_TYPE`, `LMSTUDIO_PORT`, etc.), `LLM_ENGINE=lmstudio` (a
   real engine selector, distinct from `vllm`), deploy script filenames,
   and the GCS model-cache bucket name (avoids re-caching model weights).
   Cloud Run has no rename primitive — this required deploying a brand-new
   `micro-cosmos-llmgateway` service (fresh cold start), repointing `micro-cosmos-web`
   at it via `discover_lmstudio_url()`, verifying end-to-end, and only then
   deleting the old `micro-cosmos-lmstudio` service. See the 2026-07-15 "Rename"
   entry in `changes-log.md` and `transferable-skills/memory/gcp-deployment.md`
   for the full sequence and verification.
43. **Feature (2026-07-2x)**: item 14's "`runs/` is intentionally out of
   scope" note above is now stale — `micro-cosmos-web`'s `/app/runs` is also
   backed by a GCS bucket (`MICRO_COSMOS_RUNS_BUCKET`, default
   `$PROJECT-micro-cosmos-runs`, mounted via a second `--add-volume`/
   `--add-volume-mount` pair alongside the examples one), created and
   IAM-bound by the new `ensure_runs_bucket()` in
   `deploy_cloudrun-micro-cosmos-app.py`. Unlike `examples/`, there is **no**
   rsync/seed step — `runs/` has no built-in content, it's pure runtime
   output, same reasoning `micro-cosmos-llmgateway`'s model-cache bucket already
   uses. Two deliberate trade-offs: no lifecycle/retention policy (matches
   today's status quo — nothing deletes old runs locally either), and GCS
   FUSE write latency is accepted as-is (confirmed no atomic-rename/locking
   pattern anywhere touches `runs/`, so correctness isn't a concern, but
   this hasn't been load-tested against the TDD loop's per-seam rewrite
   pattern on a live deploy). See "Run artifacts" in `deployment/README.md`
   and `transferable-skills/memory/gcp-deployment.md`.
44. **Feature + bug fix (2026-07-2x)**: two vLLM/model-config gaps closed
   together. (1) `--reasoning-parser gemma4` being set does **not** by
   itself turn Gemma 4's chain-of-thought reasoning on — that flag only
   parses reasoning content out of the response *if* the model produces
   any. New `LMSTUDIO_ENABLE_THINKING` env var (vLLM only, default off)
   forces it on via `--default-chat-template-kwargs
   '{"enable_thinking": true}'`, confirmed via vLLM's own Gemma 4
   docs/recipe, not guessed — worth it for source estates with intricate
   semantics (e.g. COBOL `COMP-3` arithmetic, `PERFORM THRU` loops), at
   the cost of extra generated tokens against the same
   `MODEL_CONTEXT_LENGTH` budget. (2) `deploy_cloudrun-micro-cosmos-app.py` had
   hardcoded `MODEL_TEMPERATURE=0.3` unconditionally — every
   `gcloud-run-setup*.txt` already specified `MODEL_TEMPERATURE=0.2`, but
   the deploy script silently ignored it. Now actually parameterized,
   default changed to `0.2`. See "Run artifacts"-adjacent config table rows
   in `deployment/README.md` and `transferable-skills/memory/gcp-deployment.md`.

45. **Bug fix (2026-07-23), found via a real production crash**:
   `VLLM_ASSUMED_WEIGHTS_GB=62.0` assumed full BF16 weights, but
   `google/gemma-4-31B-it-qat-w4a16-ct` is 4-bit quantized — its own
   startup log showed real weight usage of 19.62 GiB, not 62GB. This
   under-counted VRAM headroom made `MODEL_CONTEXT_LENGTH=162512` look
   riskier than it was, and it was actually undersized: `test_reviewer_agent`
   hit `litellm.ContextWindowExceededError` (prompt exceeded context by a
   handful of tokens). Fixed: `VLLM_ASSUMED_WEIGHTS_GB` corrected to `20.0`
   (`gcloud-run-setup.txt`, `gcloud-run-setup-vllm.txt`) /`16.0`
   (`gcloud-run-setup-vllm-lite.txt`, normalized), and
   `MODEL_CONTEXT_LENGTH` raised `162512` → `230512` in
   `gcloud-run-setup-vllm.txt` (verified against this repo's own
   `estimate_kv_cache_gb()` — comfortable headroom on `nvidia-rtx-pro-6000`'s
   96GB VRAM; native model max is 262144, kept a margin below it). **Open
   follow-up, not yet actioned**: this does not cap future growth —
   `read_generated_files()` in `micro_cosmos/tools/coding_loop_tools.py` sends
   full file content per seam with no hard ceiling, so a large enough seam
   will eventually hit whatever `MODEL_CONTEXT_LENGTH` is set to next. If
   this recurs, filter `read_generated_files()`'s output per reviewer (e.g.
   test-file-only for `test_reviewer_agent`) rather than raising context
   length again. See `transferable-skills/memory/gcp-deployment.md`'s
   matching entry.

## Steps by scope

**`full`** (both services):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
python deployment/deploy.py
```

**`deterministic`** (web app only, SKIP_LLM, no GPU cost):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
SKIP_LLM=true python deployment/deploy.py
```

**`lmstudio`** (GPU service only):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
python deployment/deploy_cloudrun-lmstudio-llms.py
```

**`vllm`** (GPU service only, vLLM engine — see checklist item 22):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
python deployment/deploy_cloudrun-vllm-llms.py
# or, via deploy.py for both services in one shot:
LMSTUDIO_ENGINE=vllm python deployment/deploy.py
```

**`micro-cosmos`** (web app only — requires LLMGateway already deployed, or
`LLM_BASE_URL` set manually, or `SKIP_LLM=true`):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
python deployment/deploy_cloudrun-micro-cosmos-app.py
```

**`load-balancer`** (one-time, only needed once per environment for public
`micro-cosmos-web` access — see checklist item 12):
```bash
export PROJECT_ID=my-project-id
export PROJECT=$PROJECT_ID
export MICRO_COSMOS_LB_DOMAIN=app.micro-cosmos.tools
python deployment/setup_micro_cosmos_web_lb.py
```

## After deploying

- Print the returned service URL(s) back to the user.
- Both services are `--ingress=internal` — neither URL is reachable from a
  browser or `curl` directly on the user's laptop. For `micro-cosmos-llmgateway`,
  verification happens via
  `gcloud run services logs read micro-cosmos-llmgateway --region=<region>` or by
  hitting the web app's pipeline (which calls it internally). For
  `micro-cosmos-web`, tell the user to run
  `gcloud run services proxy micro-cosmos-web --region=<region> --project=$PROJECT`
  and open the printed local URL in their browser.
- If this is the first-ever LLMGateway deploy, the first request will be slow
  (model pull + load into GPU) — check logs before assuming it's stuck:
  ```bash
  gcloud run services logs read micro-cosmos-llmgateway --region=<region> --limit=50
  ```

## Known uncertainty to flag to the user

See `transferable-skills/memory/gcp-deployment.md` for full detail. In short:
the `--gpu`, `--gpu-type`, `--no-cpu-throttling`, `--add-volume`/
`--add-volume-mount` (GCS FUSE) flags are based on documented Cloud Run
features but have not been exercised against a live GCP project. If the first
real deploy errors on flag syntax, check `gcloud run deploy --help` for the
current exact syntax rather than assuming the whole architecture is wrong.
