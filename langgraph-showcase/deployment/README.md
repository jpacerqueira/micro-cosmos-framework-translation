# Micro-Cosmos — all-Cloud-Run deployment


#### Contact : joao@fuelbigdata.com - for a Cloud Run , GKE or EKS Demo.




Two Cloud Run services, same GCP project, no VPC connector, no Compute Engine VM:

| Service | What runs there | RAM | Script |
|---|---|---|---|
| **`micro-cosmos-llmgateway`** | GPU inference backend — **two interchangeable engines**, see [GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) below | 32 GB (LM Studio/L4) or 80 GB (vLLM/RTX PRO 6000) | `deploy_cloudrun-lmstudio-llms.py` (LM Studio, default) or `deploy_cloudrun-vllm-llms.py` (vLLM) |
| **`micro-cosmos-web`** | Micro-Cosmos FastAPI web app | 5 GB | `deploy_cloudrun-micro-cosmos-app.py` |

`deploy.py` runs both in the right order and wires them together automatically.
Both GPU-service scripts deploy the **same Cloud Run service name**
(`micro-cosmos-llmgateway`) — it's an engine choice, not two separate services;
`micro-cosmos-web` talks to whichever one is deployed via the same
`LLM_BASE_URL`/auto-discovery, unaware of which engine is behind it.

---

## GPU engine choice — LM Studio vs vLLM

**LM Studio is the default** (`deploy_cloudrun-lmstudio-llms.py`) — the `lms`
CLI, defaulting to `google/gemma-4-e4b` on `nvidia-l4` (matches
`micro_cosmos/settings.py`'s own local `docker-compose` default — the one
universal default across local dev and Cloud Run when no env vars are set).

**vLLM is the alternative** (`deploy_cloudrun-vllm-llms.py`), added after a
confirmed dead end: on `nvidia-rtx-pro-6000` (Blackwell), `lms runtime ls`
reports **"No runtimes found"** and `lms runtime get llama.cpp:cuda`
reports **"No runtime extensions matched the query"** — there is no
CUDA-flavored `llama.cpp` backend for this GPU at all, confirmed via live
Cloud Run logs, not a config problem to work around. See `changes-log.md`'s
2026-07-11 entries and `transferable-skills/memory/gcp-deployment.md`'s
"Engine switch" entry for the full incident and research trail. **This only
affects `nvidia-rtx-pro-6000`** — LM Studio on `nvidia-l4` (the default) is
unaffected.

**To use vLLM instead of LM Studio**, set `LMSTUDIO_ENGINE=vllm` before
running `deploy.py` (or invoke `deploy_cloudrun-vllm-llms.py` directly for a
GPU-service-only deploy):

```bash
export PROJECT=my-project
export LMSTUDIO_ENGINE=vllm
python deployment/deploy.py
```

Defaults to **`google/gemma-4-31B-it`** on `nvidia-rtx-pro-6000` — see
[Example: `google/gemma-4-31B-it`](#example-googlegemma-4-31b-it-vllm-nvidia-rtx-pro-6000)
below for the real VRAM math and every env var this engine reads. This
default has changed twice (`google/gemma-4-31B-it-qat-w4a16-ct` →
`Qwen/Qwen3.6-35B-A3B-FP8` → back to `google/gemma-4-31B-it`, this time
full BF16, no quantization) — see that section and
[Example: `Qwen/Qwen3.6-35B-A3B-FP8`](#example-qwenqwen36-35b-a3b-fp8-vllm-nvidia-rtx-pro-6000--superseded-by-the-googlegemma-4-31b-it-example-below)
for the history. **Not yet verified against a live deploy** — no
Docker/Cloud Run/GPU access in the session that built this path; treat the
first real deploy as the actual test, same as every other "not yet
exercised" entry in this file.

**In-container watchdog (2026-07-13).** Cloud Run's own `--startup-probe`
for this service is TCP-only — confirmed (not assumed) that it marks the
container "Ready" as soon as vLLM's `APIServer` process binds the port,
well before `EngineCore` (the separate process that actually loads the
model) finishes, or even in one real incident, ever started at all: a
revision sat "Ready" with zero `EngineCore` activity for 44+ minutes,
silently 404ing every real request. `vllm-entrypoint.sh` now runs `vllm
serve` in the background and polls `/v1/models` itself (with the
`Authorization` header, which Cloud Run's own probe mechanism can't send)
— if the model never reports ready within `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS`
(default 1500s, matching `micro_cosmos/settings.py`'s own readiness-wait
floor), it kills `vllm serve` and exits non-zero, turning that failure
mode into a visible Cloud Run crash-loop instead of a silently-stuck
"healthy" container. Verified with a standalone bash harness (a fake
`vllm` binary simulating never-ready / crash-before-ready / crash-after-ready
/ graceful-shutdown) before ever touching a live deploy.

**LM Studio has the same watchdog now too** (same day) — `lmstudio-entrypoint.sh`
runs `lms load` in the background and polls its PID directly, same
`LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS`/`LMSTUDIO_WATCHDOG_POLL_SECONDS` knobs.
The two designs differ in one respect worth knowing: an *earlier* version
wrapped LM Studio's *entire* startup sequence (health-wait, runtime
install, `lms get`, `lms load`) in an outer watchdog that sent `SIGTERM`
to the script's own PID from a background timer — a standalone test
harness proved this does **not** reliably work, because bash defers
running trap handlers until the current foreground command finishes,
which is exactly the situation a hung `lms load` creates. Scoping the
watchdog to just `lms load` (background + direct PID poll, same technique
as vLLM) sidesteps that bash quirk entirely, since bash is never blocked
in a single long foreground call. `lms load`'s existing explicit-failure
handling (a real exit code from `lms load` itself) is unaffected and
still propagates immediately, unrestricted by the watchdog.

Both engines expose an OpenAI-compatible `/v1` API on the same Cloud Run
service name, so `LLM_BASE_URL` auto-discovery keeps working either
way — but **`micro-cosmos-web`'s config is not a no-op switch**. Three real gaps
were found and fixed (all checked and fixed proactively, before ever
running against a live vLLM deploy):

1. `micro_cosmos/orchestration/driver.py`'s `_wait_for_llm_ready()` — this
   previously only knew LM Studio's native `/api/v0/models` readiness
   endpoint (which doesn't exist on vLLM). It now falls back to a plain
   `/v1/models` check when the native endpoint isn't present, so the
   pipeline's pre-flight readiness wait works against either engine without
   further config.
2. **`MODEL_REASONING`/`MODEL_FAST` must match whatever the GPU service is
   actually serving** — unlike LM Studio (which can serve whatever's
   cached), vLLM only recognizes the single model ID it was launched with;
   any other value in a request fails outright. `deploy.py` now resolves
   one model ID from the selected engine's own default (or `MODEL_REASONING`
   if you set it) and passes it to **both** the GPU deploy and the
   `micro-cosmos-web` deploy, so they can't drift apart — this closed a real bug
   where `deploy_cloudrun-micro-cosmos-app.py`'s independent hardcoded fallback
   would have silently mismatched whichever engine's own default was
   actually deployed. **This protection only applies when using
   `deploy.py`'s orchestrated flow** — if you run
   `deploy_cloudrun-micro-cosmos-app.py` standalone against an
   already-deployed vLLM service, you must set `MODEL_REASONING`/
   `MODEL_FAST` yourself to match; the script can't safely auto-discover it
   (`micro-cosmos-llmgateway` is `--ingress=internal`, unreachable from outside the
   GCP project's network where this script runs).
3. **`Settings.build_llm()`'s `extra_body={"num_ctx": ...}` would break
   every single vLLM request.** `num_ctx` is an LM Studio/llama.cpp-specific
   parameter; vLLM's OpenAI endpoint has strict schema validation that
   rejects unrecognized top-level fields. New `LLM_ENGINE` setting
   (`lmstudio` default, set to `vllm` automatically by `deploy.py` when
   `LMSTUDIO_ENGINE=vllm`) makes this conditional — `build_llm()` only sends
   `num_ctx` when `llm_engine == "lmstudio"`. **Separately, vLLM also needs
   `--enable-auto-tool-choice --tool-call-parser <name>` to parse OpenAI
   function calls at all** — without it, every ADK `FunctionTool`-using
   agent in this pipeline (nearly all of them) would silently break, since
   tool calls would come back as plain text instead of a structured
   `tool_calls` array. See `LMSTUDIO_TOOL_CALL_PARSER` in the
   [Example: `google/gemma-4-31B-it`](#example-googlegemma-4-31b-it-vllm-nvidia-rtx-pro-6000)
   section below.

---

## Why no VPC connector

Cloud Run treats a call from one Cloud Run service to another **in the same
GCP project** as internal traffic when the target service is deployed with
`--ingress=internal` — no Direct VPC Egress, no Serverless VPC Access
connector, no firewall rules. `micro-cosmos-llmgateway` is deployed with
`--ingress=internal --allow-unauthenticated`: reachable from `micro-cosmos-web`
(same project) with a plain HTTPS call and no IAM identity token, but not
reachable from the public internet.

```
Browser
  │  HTTPS (public)
  ▼
External Application Load Balancer  (static IP + SSL cert for your domain —
  │                                   see "Web UI access" below)
  ▼
micro-cosmos-web  (Cloud Run · 5 GB RAM · 4 vCPU · --ingress=internal-and-cloud-load-balancing)
  │  HTTPS (internal — same-project Cloud Run traffic, no VPC needed)
  ▼
micro-cosmos-llmgateway  (Cloud Run · 32 GB RAM · 8 vCPU · 1× NVIDIA L4 · --ingress=internal)
  └── LMStudio server → google/gemma-4-e4b (default — see "GPU engine choice" above for the vLLM alternative)
        model weights cached in gs://$PROJECT-lmstudio-models (GCS FUSE mount)
```

### Web UI access — `micro-cosmos-web` is public via an external Load Balancer, `micro-cosmos-llmgateway` stays internal-only

`micro-cosmos-llmgateway` is deployed with `--ingress=internal` and is never meant
to be public — it's only ever called by `micro-cosmos-web` over Cloud Run's
same-project internal traffic path.

`micro-cosmos-web` needs genuine internet access, but this project's org policy
(`constraints/run.allowedIngress`) blocks Cloud Run's default public "all"
ingress value, and a **per-project exception for `all` was requested and
declined.** The org-compliant path is the policy's third allowed value,
`internal-and-cloud-load-balancing`: Cloud Run only accepts traffic from a
real external Application Load Balancer (plus same-project internal
traffic) — not directly from the internet, but the LB itself is
internet-facing.

**Setup (one-time, not part of the routine deploy):**

```bash
export PROJECT=my-project
export MICRO_COSMOS_LB_DOMAIN=app.micro-cosmos.tools   # your domain, DNS under your control
python deployment/setup_micro_cosmos_web_lb.py
```

This provisions (idempotently — safe to re-run): a global static IP, a
serverless NEG pointing at `micro-cosmos-web`, a backend service, a URL map, a
Google-managed SSL certificate for `MICRO_COSMOS_LB_DOMAIN`, a target HTTPS
proxy, the HTTPS forwarding rule (port 443), and an HTTP→HTTPS redirect
(port 80) — 8 resources total, none of them free (static IP + forwarding
rules are billed even when idle).

**Manual steps this script cannot do for you:**
1. It prints the reserved static IP at the end — create an **A record** for
   `MICRO_COSMOS_LB_DOMAIN` pointing at that IP with your domain's DNS provider
   (this script has no access to your DNS unless it's Google Cloud DNS,
   which it doesn't assume).
2. The SSL certificate only reaches `ACTIVE` after that DNS record resolves
   and Google validates it — can take up to ~60 minutes after DNS
   propagates. Check:
   ```bash
   gcloud compute ssl-certificates describe micro-cosmos-web-cert --global \
     --project=$PROJECT --format='value(managed.status)'
   ```
3. Once `ACTIVE`, redeploy `micro-cosmos-web`
   (`python deployment/deploy_cloudrun-micro-cosmos-app.py`) so it actually picks
   up `--ingress=internal-and-cloud-load-balancing` — the ingress value is
   set by the app deploy script, not the LB setup script.

No Identity-Aware Proxy at the infrastructure level — anyone who reaches
`https://app.micro-cosmos.tools` reaches the app itself (same
exposure level a plain `--ingress=all` grant would have given; the LB
requirement is about org-policy compliance, not infra-level access
control). **The app itself now has a login gate** — see "Login" below.

**Confirmed working against the live project** (2026-07-07/09) — this
section previously carried a "not yet exercised" caveat; it's now been
exercised end-to-end (LB provisioned, DNS resolved via GoDaddy, SSL
certificate issued, `micro-cosmos-web` reachable at
`https://app.micro-cosmos.tools/demo`). If a *new* environment's
first setup errors on flag syntax, that's still worth checking against
`gcloud compute <resource> create --help`, but the overall approach itself
is proven, not theoretical.

### Login — demo/demobxyz

The web app itself (not the LB) requires a login before anything is
usable: `GET /` and every other route redirect to `/login` until you
authenticate. Default credentials, in both docker-compose and Cloud Run:

```
username: demo
password: demobxyz
```

Override via `DEMO_USERNAME`/`DEMO_PASSWORD` (docker-compose: `.env` or
shell export; Cloud Run: same env vars read by
`deploy_cloudrun-micro-cosmos-app.py`). On success you land on `/demo`; the
existing nav (`New run` / `Demo` / `Logout`) reaches everything else.

**Required on Cloud Run:** `micro-cosmos-web` is deployed with
`--allow-unauthenticated` and is reachable via the public load balancer, so
this login is the only thing gating the app from the internet.
`deploy_cloudrun-micro-cosmos-app.py` hard-fails (`ERROR: ... sys.exit(1)`) if both
`DEMO_USERNAME` and `DEMO_PASSWORD` are left unset — you must set real values
before deploying. This check does not apply to manual `gcloud run deploy`
invocations (see the example below), so set real values there too.

**Session mechanism:** a signed cookie (Starlette's `SessionMiddleware`,
via `itsdangerous`) — no server-side session store, so it works correctly
across `micro-cosmos-web`'s multiple Cloud Run instances
(`MIN_INSTANCES=1`/`MAX_INSTANCES=3`) without any shared state.
`SESSION_SECRET_KEY` signs the cookie and is generated fresh on every
`deploy_cloudrun-micro-cosmos-app.py` run unless you set it yourself (setting it
persists sessions across redeploys instead of forcing everyone to log in
again each time). `SESSION_HTTPS_ONLY=true` is set automatically for Cloud
Run (cookie marked `Secure`, required now that the app is reachable over
real HTTPS via the LB) and left `false` for local docker-compose (plain
`http://localhost:8080` — a `Secure` cookie wouldn't even be sent by the
browser over plain HTTP).

**Login not yet exercised against a live Cloud Run deploy** (the LB itself
has been — see above) — the session middleware and routes were verified
with a standalone Starlette test harness (real middleware-ordering bug
caught and fixed that way, see `transferable-skills/memory/gcp-deployment.md`),
not a full `docker compose up`/live redeploy. Treat the first real login
attempt after redeploying as validation.

### Container port convention — matches local docker-compose

| Service | Cloud Run port | Local (`docker-compose.yml`) |
|---|---|---|
| `micro-cosmos-llmgateway` (LM Studio engine) | `1234` (`LMSTUDIO_PORT`) | `1234` |
| `micro-cosmos-llmgateway` (vLLM engine) | `8000` (`LMSTUDIO_PORT`) — vLLM's own native default, left untouched (2026-07-13) rather than forced onto LM Studio's `1234` convention; this is a genuinely different engine, not the same service reused | *(vLLM has no local docker-compose path)* |
| `micro-cosmos-web` | `8080` (Cloud Run's default; not overridden) | `8080` |

`deploy_cloudrun-lmstudio-llms.py` passes `--port=1234` and derives the
`--startup-probe`'s `tcpSocket.port` from the same value, so they can never
drift out of sync (a mismatch there would make the health probe check the
wrong port and fail every deploy). `lmstudio-entrypoint.sh`'s `$PORT`
fallback (for running the image outside Cloud Run) also defaults to `1234`
to match. `deploy_cloudrun-vllm-llms.py`/`vllm-entrypoint.sh` follow the
exact same pattern, just defaulting to `8000` instead. **This is cosmetic
parity/convention, not a functional requirement** — the actual port number
never appears in `LLM_BASE_URL`
(e.g. `https://micro-cosmos-llmgateway-xxxx.a.run.app/v1`), since Cloud Run always
terminates HTTPS on 443 externally and routes internally to whichever port
the service specifies, regardless of what that port number is. Override
with `LMSTUDIO_PORT` if you ever need a different value.

### Examples gallery — mounted, matching local docker-compose

`docker-compose.yml` bind-mounts `./examples:/app/examples` from the host
— the repo's 500+ built-in demo projects (COBOL, Java, C#, etc.) that
`micro_cosmos/web/app.py`'s `/demo` route lists, and that `/demo/upload` writes
new uploads into. Cloud Run has no bind mounts, so `micro-cosmos-web` uses the
same GCS-FUSE-volume pattern as `micro-cosmos-llmgateway`'s model cache:
`MICRO_COSMOS_EXAMPLES_BUCKET` (default `$PROJECT-micro-cosmos-examples`), mounted at
`/app/examples`.

**Every deploy syncs the repo's `examples/` directory into the bucket**
(`gcloud storage rsync examples/ gs://$BUCKET --recursive`, run by
`ensure_examples_bucket()` in `deploy_cloudrun-micro-cosmos-app.py`) — this is
what makes the built-in gallery show up on a fresh Cloud Run deploy instead
of an empty list. Plain `rsync` without
`--delete-unmatched-destination-objects` only adds/updates files, **never
deletes** — so anything uploaded later via the running app's `/demo/upload`
(which isn't in the local `examples/` checkout) is untouched by this sync
and persists across redeploys, unlike before this change.

Not yet exercised against a live deploy: GCS FUSE's behavior under the
`/demo/upload` route's zip-extraction + nested-directory-creation pattern.
Standard file writes should work fine (no locks/symlinks/hardlinks in that
code path), but treat the first real upload test as validation, not a
known-good path.

### Run artifacts — mounted, matching local docker-compose

`runs/` (`RUNS_DIR=/app/runs`) had the identical bind-mount-locally/
nothing-on-Cloud-Run gap `examples/` had — now closed the same way:
`MICRO_COSMOS_RUNS_BUCKET` (default `$PROJECT-micro-cosmos-runs`), mounted at
`/app/runs`, created and IAM-bound by `ensure_runs_bucket()` in
`deploy_cloudrun-micro-cosmos-app.py`.

**Unlike `examples/`, there is no seed/rsync step** — `runs/` has no
built-in content; it's pure runtime output, same reasoning
`micro-cosmos-llmgateway`'s model-cache bucket already uses (create + IAM-bind
only). This means every pipeline run's JSON artifacts, generated code, and
HTML reports now survive cold starts and redeploys instead of living on
ephemeral container disk.

Two deliberate trade-offs, not oversights:
- **No lifecycle/retention policy.** The bucket grows unboundedly with
  every run ever executed — matches today's status quo exactly (nothing
  deletes old runs from local disk either). A real retention policy is a
  separate decision to make later, not bundled into this change.
- **GCS FUSE write latency, accepted.** `runs/` is written far more
  heavily than `examples/` — e.g. `seam.json` gets rewritten after every
  seam, dozens of times per run — each write is a full GCS object PUT, not
  a fast local write. Confirmed safe from a *correctness* standpoint (no
  atomic-rename or file-locking pattern anywhere in this codebase touches
  `runs/`, which is what GCS FUSE can't support well), but not yet
  load-tested for real-world latency impact on the TDD loop. Revisit if a
  live deploy shows a meaningful slowdown.

---

## Prerequisites

You have the Google Cloud SDK installed and authenticated. This project uses
**three related env vars** — set all three, they're not interchangeable:

| Var | What it is | Used for |
|---|---|---|
| `PROJECT_NAME` | Human-readable display name (e.g. `Micro-Cosmos Prod`) | Your own reference only — no gcloud command reads this |
| `PROJECT_ID` | The GCP **Project ID** — a string (e.g. `my-project-id`) | Required by `gcloud iam service-accounts create` and `gcloud projects add-iam-policy-binding` — these reject a numeric Project Number |
| `PROJECT` | Mirrors `PROJECT_ID` | This is what the three deploy scripts read (`deploy.py`, `deploy_cloudrun-lmstudio-llms.py`, `deploy_cloudrun-micro-cosmos-app.py` all fall back through `PROJECT` → `PROJECT_ID` → `GOOGLE_CLOUD_PROJECT`) |

```bash
export PROJECT_NAME="Micro-Cosmos Prod"   # optional, human label only
export PROJECT_ID=my-project-id             # the GCP Project ID — a string
export PROJECT=$PROJECT_ID                  # keep this mirrored to PROJECT_ID

gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT
```

### Shortcut: load a whole profile with `deploy-vars-in-env.sh`

Every env var in this file is read via `os.environ.get()` and nothing else, so
the `gcloud-run-setup*.txt` profiles at the repo root can be loaded wholesale
instead of exported line by line:

```bash
source ./deploy-vars-in-env.sh              # gcloud-run-setup-vllm.txt (default)
source ./deploy-vars-in-env.sh vllm-lite    # gcloud-run-setup-vllm-lite.txt
source ./deploy-vars-in-env.sh lmstudio     # gcloud-run-setup-lmstudio.txt
source ./deploy-vars-in-env.sh base         # gcloud-run-setup.txt
source ./deploy-vars-in-env.sh -q vllm      # summary line only
python deployment/deploy.py
```

It must be **sourced**, not executed (a child process can't export into its
parent — the script says so and refuses if you run it directly). It is an exact
loader: it exports what the file says, with no defaulting and no validation of
the values, so the VRAM/model/region guidance in the rest of this file still
applies. Values whose names contain `TOKEN`/`KEY`/`PASSWORD`/`SECRET` print as
`***`. Any later `export` on the command line overrides the profile as usual.

### Why `PROJECT` must be the Project ID string, not the Project Number

`gcloud config set project` and `gcloud services enable` silently accept
either the Project ID (e.g. `my-project-id`) or the numeric Project Number
(e.g. `424279939916`) — both succeed with no warning. But
`gcloud iam service-accounts create` and `gcloud projects
add-iam-policy-binding` (used in the next step) **require the string Project
ID** and fail with:

```
ERROR: (gcloud.iam.service-accounts.create) The value of ``--project'' flag
was set to Project number. To use this command, set it to PROJECT ID instead.
```

If you're not sure whether your existing project reference is the ID or the
number, resolve it explicitly — this works either way:

```bash
export PROJECT_ID=$(gcloud projects describe $PROJECT --format="value(projectId)")
export PROJECT=$PROJECT_ID
echo $PROJECT   # confirm this is now the string ID, not a number
```

Enable the required APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  --project=$PROJECT
```

Create the runtime service account (shared by both Cloud Run services):

```bash
gcloud iam service-accounts create micro-cosmos-runtime \
  --display-name="Micro-Cosmos runtime" \
  --project=$PROJECT

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"
```

(`deploy_cloudrun-lmstudio-llms.py` grants this service account
`roles/storage.objectAdmin` on the model-cache bucket automatically.)

### Cloud Build permissions — required before the first `gcloud builds submit`

Both deploy scripts build the container image via `gcloud builds submit`,
which runs as a **Cloud Build service account**, not as you or
`micro-cosmos-runtime`. For projects created after Google's Sept 2024 default
service account change, Cloud Build has no dedicated service account
pre-provisioned — it falls back to the **Compute Engine default service
account** (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`), which
starts with zero IAM roles. Without this grant, the build fails immediately
trying to read the source tarball it just uploaded:

```
ERROR: (gcloud.builds.submit) INVALID_ARGUMENT: could not resolve source:
googleapi: Error 403: PROJECT_NUMBER-compute@developer.gserviceaccount.com
does not have storage.objects.get access to the Google Cloud Storage object.
```

Fix — grant that service account the Cloud Build builder role (bundles read
access to the Cloud Build staging bucket, log writing, and Artifact Registry
push):

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder"
```

If the build later succeeds but pushing to Artifact Registry fails with a
separate 403, also grant:

```bash
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

### `micro-cosmos-web` build fails at the Trivy install step — GitHub API rate limit, not permissions

If `gcloud builds submit` for `micro-cosmos-web` fails with `apt-get install`
succeeding, then `aquasecurity/trivy`'s installer printing `found version:
0.70.0 for v0.70.0/Linux/64bit` followed by the whole `RUN` step exiting
non-zero with no further output — that's `contrib/install.sh` hitting
`api.github.com`'s unauthenticated rate limit (60 req/hr per source IP),
which Cloud Build's shared builder IPs run into intermittently. Not an
IAM/permissions issue like the one above. `Dockerfile` now downloads the
pinned release tarball directly instead of piping `install.sh` through
`sh`, skipping that rate-limited call entirely. If this exact failure
recurs anyway, that points to Cloud Build's egress genuinely not reaching
GitHub — check the Cloud Build logs link in the failure output rather than
assuming rate limiting again.

### GPU quota and region — read this before running

Cloud Run GPU support (NVIDIA L4) is region-limited and requires quota
approval. **Region availability changes over time** — verify before deploying:

```bash
gcloud run regions list --format="value(locationId)" --project=$PROJECT
```

The scripts default to `europe-west4`. If your project's GPU quota is
approved for a different region, override it:

```bash
export GOOGLE_CLOUD_LOCATION=europe-west4   # or your approved region
```

If you've never requested Cloud Run GPU quota for this project, request it
in the Cloud Console (IAM & Admin → Quotas → filter "Total Nvidia L4 GPU
allocation, per project per region") before running the deploy — the first
`gcloud run deploy --gpu=...` call will fail with a clear quota error
otherwise.

### GPU type — NVIDIA RTX PRO 6000 Blackwell (preview)

`LMSTUDIO_GPU_TYPE` defaults to `nvidia-l4` (24 GB VRAM). Cloud Run also
supports **NVIDIA RTX PRO 6000 Blackwell** (`nvidia-rtx-pro-6000`, preview as
of 2026-07) — **96 GB VRAM**, which removes most of the VRAM-headroom
pressure described above (e.g. `qwen/qwen3.6-27b` at Q4_K_M leaves only ~7GB
headroom on an L4, but ~79GB on this GPU — room for a much longer context or
a less aggressive quant):

```bash
export LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000
export LMSTUDIO_ASSUMED_WEIGHTS_GB=16.8   # unchanged — VRAM budget is what changes
```

Differences from `nvidia-l4` you should know before switching:

- **Minimum 20 vCPU / 80 GiB memory** (Cloud-Run-enforced, not a suggestion —
  `deploy_service()` picks these up automatically from `GPU_DEFAULTS` in
  `deploy_cloudrun-lmstudio-llms.py`; override via `LMSTUDIO_MEMORY`/
  `LMSTUDIO_CPU` only if you need to size even higher).
- **Region availability is narrower**: `asia-southeast1`, `asia-south2`,
  `europe-west4`, `us-central1` — this project's default region
  (`europe-west4`) is supported, so no region change is needed.
- **Preview status**: the deploy script automatically routes this GPU type
  through `gcloud beta run deploy` instead of the stable `gcloud run deploy`
  used for L4 — this is preview functionality, syntax may change.
- **Newer CUDA base image required**: `Dockerfile.lmstudio` was bumped to
  `nvidia/cuda:12.8.2-runtime-ubuntu22.04` (from `12.4.1`) — this GPU's
  driver (580.x/CUDA 13.0) needs a base image newer than CUDA 12.2 per
  NVIDIA's guidance. This bump is backward compatible with `nvidia-l4` too
  (Cloud Run injects the matching host driver at runtime regardless of the
  container's CUDA userspace version).
- **Quota**: unlike L4 (no quota request needed), this is milli-GPU quota
  with a small initial grant reported by Google — verify actual availability
  in the Cloud Console (IAM & Admin → Quotas) before deploying, same
  principle as the L4 quota check above.
- **Cost**: 20 vCPU + 80 GiB + this GPU class is a materially larger,
  pricier instance than the L4 default — confirm budget expectations before
  a live deploy. Zonal redundancy is on by default here too;
  `--no-gpu-zonal-redundancy` (passed by default, see below) keeps cost down.

**Live-deployed repeatedly since 2026-07-06** — container start, GCS FUSE
mount, and model download all confirmed working on this GPU type via LM
Studio. **But confirmed dead end for LM Studio specifically as of
2026-07-11: there is no CUDA-flavored `llama.cpp` runtime available for
this GPU at all** (`lms runtime ls` → "No runtimes found"; `lms runtime get
llama.cpp:cuda` → "No runtime extensions matched the query" — not a config
gap, a genuine missing backend). **If you're targeting
`nvidia-rtx-pro-6000`, use the vLLM engine instead** — see
[GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) at the top of
this file. This dead end is specific to LM Studio/`llama.cpp` on this GPU
generation; `nvidia-l4` (e.g. `google/gemma-4-12b-qat` below) is unaffected.

### GPU zonal redundancy — separate quota from base GPU quota

Cloud Run GPU services default to **zonal redundancy** (replicating the GPU
across zones in the region for HA), which requires its own quota on top of
base GPU quota. Most projects don't have it approved, and the deploy fails
with:

```
ERROR: (gcloud.run.deploy) spec.template.metadata.annotations[autoscaling.knative.dev/maxScale]:
You do not have quota for using GPUs with zonal redundancy.
```

`deploy_cloudrun-lmstudio-llms.py` passes `--no-gpu-zonal-redundancy` by
default for this reason — a single L4 instance (`MAX_INSTANCES=1`) doesn't
benefit from cross-zone HA anyway. If your project later gets zonal
redundancy quota approved and you want it, set:

```bash
export LMSTUDIO_GPU_ZONAL_REDUNDANCY=true
```

### Container startup timeout — the `lms` binary must not be shadowed by the volume mount

Cloud Run's default startup probe is a plain **TCP check on `$PORT`** with a
~240 second total timeout — it has no awareness of model download/load
progress, it just needs something listening. If the deploy fails with:

```
ERROR: (gcloud.run.deploy) The user-provided container failed to start and
listen on the port defined provided by the PORT=8080 environment variable
within the allocated timeout.
```

this is **not** an IAM/auth problem (ignore any earlier "Setting IAM Policy
failed" warning in the same output — that's a separate, harmless side effect
of `--allow-unauthenticated` combined with `--ingress=internal`, which blocks
public access anyway regardless of that binding).

**Confirmed root cause (this bit twice — first with `google/gemma-...`+L4,
then again with `qwen/qwen3.6-35b-a3b`+`nvidia-rtx-pro-6000`, ruling out
model size and GPU type):** `Dockerfile.lmstudio` installs the `lms` binary
to `.lmstudio/bin` at build time (`PATH="/root/.lmstudio/bin:${PATH}"`). If
the GCS FUSE volume is ever mounted at `/root/.lmstudio` itself (rather than
the `models` subdirectory), that mount **shadows the entire directory at
container start — including `bin/lms`**. Every `lms` command in the
entrypoint then fails with "command not found," the script exits under
`set -euo pipefail`, and `$PORT` is never bound. The fix is the
`--add-volume-mount=volume=model-cache,mount-path=/root/.lmstudio/models`
flag already in `deploy_service()` — mounting only the `models` subdirectory
(LM Studio's own default models location) leaves `bin/` intact from the
image while still persisting the multi-GB weights. If you ever customize
this script, **never mount the volume at the `.lmstudio` root.**

**If you already redeployed an existing service after this fix and the exact
same error recurred** — check the live revision's `volumeMounts` in Cloud
Run's audit log (`gcloud run services describe micro-cosmos-llmgateway
--region=... --format=export`, or the Logs Explorer JSON payload for the
failed revision). `gcloud run deploy --add-volume-mount` is **additive on a
redeploy of an existing service** — it does not replace a previous
revision's volume config for the same volume name, it accumulates alongside
it. If the service already had a stale mount at `/root/.lmstudio` from
before this fix landed, redeploying only *added* the corrected
`/root/.lmstudio/models` mount without removing the old one — both ended up
present simultaneously, and the old, broader mount still shadowed `bin/lms`
exactly as before. `deploy_service()` now passes `--clear-volumes
--clear-volume-mounts` before `--add-volume`/`--add-volume-mount` on every
deploy specifically to prevent this — it forces each deploy to fully
replace volume config with exactly what's specified, rather than layering
on top of whatever the previous revision had.

Separately, `lmstudio-entrypoint.sh` also starts the LMStudio server
(binding `$PORT` almost immediately) *before* `lms get`/`lms load` — this
avoids a real but secondary race where a large model pull alone could
exceed the 240s probe timeout even with the mount path fixed. If you've
customized the entrypoint, keep both fixes: mount at `.lmstudio/models`,
*and* start the server before pulling/loading the model.

### GPU cold-start startup probe timeout — a different symptom, same generic error text

This is a **separate issue from the binary-shadowing bug above** — same
generic Cloud Run error text, different cause. If the deploy fails with:

```
ERROR: (gcloud.run.deploy) Container failed to become healthy. Startup
probes timed out after 4m (1 attempts with a period of 4m each).
```

**this is Cloud Run's hard 4-minute default startup probe window, not
necessarily an application bug.** A full GPU cold start breaks down into
sequential stages — node provisioning (60-120s), container image pull
(30-60s; can run longer — 1m54s was observed for this image), CUDA context
initialization (5-30s) — which can plausibly consume most or all of a 240s
budget on a **first-ever** deploy of a new GPU type/config, before the
entrypoint's `lms server start` even gets a chance to bind `$PORT`. Google's
own Cloud Run GPU docs recommend raising the startup probe's
`failureThreshold` for exactly this case (supports up to 30 minutes total).

`deploy_service()` now passes an explicit `--startup-probe` (30-minute
default: `periodSeconds=10`, `failureThreshold=180` — Cloud Run's
documented ceiling for GPU/AI startup probes) instead of relying on Cloud
Run's 4-minute default. Override the total budget with:

```bash
export LMSTUDIO_STARTUP_TIMEOUT_SECONDS=900   # 15 minutes, e.g. to fail faster during iteration
```

**Update — this alone was NOT the actual fix.** A subsequent deploy timed
out the full 30-minute window (`180 attempts × 10s`) with zero success,
which is strong evidence the container was never going to bind the port no
matter how long the probe waited. Pulling the real container logs
(`gcloud run services logs read micro-cosmos-llmgateway --region=europe-west4
--limit=100`) confirmed the actual root cause:

```
error: unknown option '--host'
(Did you mean --port?)
```

`lmstudio-entrypoint.sh` called `lms server start --port "${PORT}" --host
0.0.0.0` — but `lms server start` has no `--host` flag (confirmed against
LM Studio's own CLI docs). The CLI rejected the unrecognized option and
exited immediately, every single attempt, regardless of the probe timeout.
**The correct flag is `--bind`, not `--host`.** The default bind address if
you omit it is `127.0.0.1` (localhost-only) — Cloud Run requires the
container to listen on `0.0.0.0`, so `--bind 0.0.0.0` must be passed
explicitly (or set via the `LMS_SERVER_HOST` env var, which the CLI also
honors — now baked into `Dockerfile.lmstudio` as a durable default,
belt-and-suspenders alongside the corrected entrypoint flag).

The extended startup probe above is still worth keeping — a genuine GPU
cold start can still plausibly need more than 4 minutes — but it was
solving a real, separate concern, not this one. Lesson: when a fix doesn't
resolve a recurring failure, that's itself a signal to stop hypothesizing
and pull real logs, rather than trying a fourth variation on the same
guess.

### `lms pull` doesn't exist — the correct command is `lms get`

With the server successfully starting (all fixes above applied), the next
deploy attempt got further and failed differently — real container logs
showed:

```
[entrypoint] pulling qwen/qwen3.6-35b-a3b (no-op if already cached on the mounted volume)…
error: unknown command 'pull'
```

`lmstudio-entrypoint.sh` called `lms pull "${MODEL_ID}"` to download the
model — but `lms pull` was never a valid `lms` CLI command (confirmed
against LM Studio's own CLI docs). The correct command is **`lms get`**.
With a full, exact model ID (which `MODEL_ID` always is), `lms get`
auto-selects and downloads non-interactively by default — the flags that
force an interactive quantization prompt
(`--always-show-download-options`/`--always-show-all-results`) are opt-in,
so this is safe to run unattended in a container.

### `lms get` stalls on GCS FUSE, then `lms load` hangs forever — two distinct bugs

Found switching the model from `qwen/qwen3.6-35b-a3b` down to
`qwen/qwen3.6-27b` (ruling out size/GPU as the cause — same failure at a
smaller size). Live logs showed the download progress bar frozen at
exactly `5.00% | 874.03 MB / 17.48 GB` — not slow, **stalled** — before
`lms` reported `Error: Download failed: Timed-out.`. The GCS FUSE mount
logs alongside it explain why: any `.part` file with non-zero size (a
leftover from an earlier failed attempt) forces gcsfuse's slow "legacy
staged writes" path instead of its fast streaming-write path (which only
applies to new/empty files) — slow enough to trip `lms`'s own
download-stall detection on every retry, without ever finishing.

Worse: `lmstudio-entrypoint.sh` unconditionally called `lms load` after
`get`, even with no complete model on disk. `lms load` responded `Cannot
find a model matching the provided model key` and dropped into an
**interactive TUI picker** — Cloud Run has no TTY to answer it, so the
container just hung indefinitely, silently never becoming ready.

**Fix:** `lmstudio-entrypoint.sh` retries `lms get` up to 99 times (5s
backoff) with `-y`, and runs `lms load ... -y </dev/null` — if it still
can't resolve the model and tries to fall back to the interactive picker,
stdin hits EOF immediately and the command fails fast instead of hanging.
**You must also manually clear any stale `.part` files** before retrying a
failed model download, so gcsfuse starts a genuinely new/empty file:

```bash
gcloud storage rm -r gs://$PROJECT-lmstudio-models/lmstudio-community/<model>-GGUF/
```

Not automated in a deploy script — deleting bucket contents automatically
carries more blast radius than warranted here.

**Update (2026-07-10): a Cloud Run "ephemeral disk" migration was tried
and fully reverted the same day** — the model cache briefly moved off
this GCS bucket entirely, but hit a hard, unavoidable Cloud Run quota wall
for this model's size (10GiB per-service ceiling without a manual Google
quota increase — see
`transferable-skills/memory/gcp-deployment.md`'s "ephemeral disk migration
tried and fully reverted" entry for the full story, including why the
100GB figure quoted earlier was the wrong quota to look at). Back on the
GCS bucket described in this section — **before the next deploy, delete
the stale `.part` files above** so the retry actually starts clean; that
combination (clean bucket + the already-shipped 99x-retry/fail-fast fix)
has not yet been tested together and is the next real thing to verify.

---

## Context length vs GPU VRAM — read this before raising `MODEL_CONTEXT_LENGTH`

**`MEMORY=32Gi` on `micro-cosmos-llmgateway` is host RAM, not GPU VRAM.** The L4's
24 GB of VRAM is fixed by GCP and does not change no matter how high you set
`--memory` or `--cpu` — 32Gi/8vCPU is already the ceiling for a single-GPU
(1× L4) Cloud Run instance; there is no larger single-GPU tier to move to.
KV cache (the memory that scales with context length) lives in GPU VRAM, so
**raising host RAM does not let you fit a longer context.**

The default `MODEL_CONTEXT_LENGTH=262144` is large enough that it will very
likely **not** fit in a single L4's 24 GB VRAM alongside model weights, for
almost any model. `deploy_cloudrun-lmstudio-llms.py` runs a rough estimate at
deploy time and prints a loud warning banner if this looks like it will OOM
— it does not block the deploy, since the real answer depends on the model's
actual architecture (`lms info <model>` for exact figures).

If you hit an OOM (LMStudio server crashes on model load, or Cloud Run logs
show a CUDA out-of-memory error), you have four options, roughly in order of
how much they help without changing infrastructure:

1. **Lower `MODEL_CONTEXT_LENGTH`.** `32768` is the safe reference point used
   by the previous architecture (Compute Engine `g2-standard-8`, same L4).
2. **Set `LMSTUDIO_GPU_LAYERS` to a partial layer count instead of `max`.**
   This spills the layers/KV cache that don't fit in VRAM into the
   already-provisioned 32Gi host RAM — this is the one case where the "RAM
   machine" size actually matters for fitting a large context. It works, but
   generation speed drops significantly for the CPU-resident layers.
3. **Use a smaller or more aggressively quantized model.** Smaller weights
   leave more of the 24 GB VRAM budget for KV cache.
4. **Move this workload to a multi-GPU Compute Engine VM** (the superseded
   architecture in `cloudrun-cloudcompute.md`), where VRAM pools across
   multiple GPUs. Cloud Run currently deploys a single GPU per instance —
   there's no `--gpu=2` equivalent here to pool L4s.

---

## Switching models — no code changes required

`MODEL_REASONING` / `MODEL_FAST` are plain env vars read by both deploy
scripts and by the running app (`micro_cosmos/settings.py`), so pointing at a
different LM Studio catalog model is purely a deploy-time config change:

```bash
export MODEL_REASONING=qwen/qwen3.6-27b
export MODEL_FAST=qwen/qwen3.6-27b       # or keep a smaller/faster model for this role
export MODEL_CONTEXT_LENGTH=65536        # see VRAM note below — don't leave this at 262144 unverified
export LMSTUDIO_ASSUMED_WEIGHTS_GB=16.8  # see below — the VRAM checker needs this per model
python deployment/deploy.py
```

`lms get`/`lms load` in `lmstudio-entrypoint.sh` take the model ID as an
opaque string — no script changes needed even for a multimodal model shipped
as two GGUF files (text tower + vision projector), LM Studio manages that
internally under one model ID.

**Tool calling / agentic coding readiness:** `micro_cosmos/settings.py`'s
`build_llm()` calls LM Studio through LiteLLM's `openai/` provider, which
serializes ADK's `FunctionTool` declarations in standard OpenAI
function-calling format — this is provider-agnostic; any model LM Studio
exposes through its OpenAI-compatible endpoint with tool-calling support
works with the Code Writer / Reviewer agents' tool-call loops without
further changes.

### Example: `qwen/qwen3.6-27b`

Dense 27.8B-param model, 64 layers with hybrid linear/full attention (full
attention on ~1-in-4 layers only), native 262,144 context (extensible to
1,010,000), LM Studio-verified for agentic tool calling and benchmarked
specifically on coding/agentic tasks (SWE-bench, Terminal-Bench) — a good
match for this pipeline's Code Writer/Reviewer loops.

**VRAM is the real constraint, not tool-calling compatibility.** GGUF sizes:
Q4_K_M ≈ 16.8 GB, Q5_K_M ≈ 19.5 GB, Q6_K ≈ 22.5 GB, Q8_0 ≈ 28.6 GB. At Q4_K_M
on a 24 GB L4, weights alone leave only ~7 GB for KV cache + the vision
projector — noticeably tighter than `google/gemma-4-31b-qat`'s ~18 GB weight
footprint (leaving even less headroom — see the default model note below).
Two things follow:

1. **Always set `LMSTUDIO_ASSUMED_WEIGHTS_GB`** when using this model (e.g.
   `16.8` for Q4_K_M). Without it, `check_vram_fit()` silently falls back to
   the default model's sized default and prints a misleading warning (or
   lack of one).
2. **The KV-cache warning's formula assumes uniform full attention on every
   layer** — for a hybrid linear/full-attention model like this, real KV
   cache growth is well below what the formula predicts (only ~1-in-4 layers
   pay the quadratic cost). Treat any warning it prints for this model as a
   conservative upper bound, not a precise prediction — start with a moderate
   `MODEL_CONTEXT_LENGTH` (e.g. `65536`, comfortably enough for tool schemas +
   source file content in a single agent turn) and verify actual VRAM usage
   via `gcloud run services logs read micro-cosmos-llmgateway` on first deploy before
   raising it further.

### Example: `qwen/qwen3.6-35b-a3b` (LM Studio) — superseded by the vLLM example below

**Update (2026-07-11): the "confirmed working" claim below is now known to
be unreliable.** Later investigation found `lms runtime ls` reports **"No
runtimes found"** on `nvidia-rtx-pro-6000` — no CUDA-flavored `llama.cpp`
backend exists for this GPU at all, and this is 100% reproducible on every
fresh container (runtime backends aren't installed at Docker build time —
no GPU is attached during Cloud Build — and don't persist across container
restarts). The 2026-07-09 "confirmed working" note below predates that
finding; a subsequent redeploy at both `65536` and `131512` crashed
identically (`llama-server ... exitCode=127`). **Use the vLLM engine
instead for this model class on this GPU** — see
[Example: `Qwen/Qwen3.6-35B-A3B-FP8`](#example-qwenqwen36-35b-a3b-fp8-vllm-nvidia-rtx-pro-6000--superseded-by-the-googlegemma-4-31b-it-example-below)
below for how to run a Qwen3.6-class model via vLLM (no longer this
engine's default — see
[Example: `google/gemma-4-31B-it`](#example-googlegemma-4-31b-it-vllm-nvidia-rtx-pro-6000)
for the current one). Kept below for historical/LM-Studio-on-`nvidia-l4`
reference only.

Sparse MoE model — 35B total params, only 3B active per forward pass (10 ×
[3 × (Gated DeltaNet → MoE) → 1 × (Gated Attention → MoE)], 40 layers total),
native 262,144 context (extensible to 1,010,000), benchmarked specifically
on agentic coding tasks. Inference cost tracks the ~3B active-param class;
quality tracks the full 35B. Same tool-calling readiness note as
`qwen/qwen3.6-27b` above applies (provider-agnostic OpenAI function-calling
format via LiteLLM — no code changes needed).

**MoE does not reduce VRAM for weights** — all 35B parameters must still be
resident even though only 3B activate per token, so this is not a "3B-sized"
deploy. GGUF sizes: Q4_K_M ≈ 22.1 GB, Q5_K_M ≈ 26.5 GB, Q6_K ≈ 29.3 GB, Q8_0
≈ 36.9 GB — heavier than `qwen/qwen3.6-27b` at the same quant level, and
Q8_0 alone exceeds a single L4's 24 GB VRAM before any KV cache. On an L4,
Q4_K_M is close to the practical ceiling; on `nvidia-rtx-pro-6000` (96GB
VRAM, see "GPU type" above) any quant level here fits comfortably with room
for a large context.

**Current production spec (confirmed working, 2026-07-09)** — Q4_K_M on
`nvidia-rtx-pro-6000`, context raised from the initial conservative `65536`
to `131512` after verifying the VRAM math (see below), not just guessed:

```bash
export MODEL_REASONING=qwen/qwen3.6-35b-a3b
export MODEL_FAST=qwen/qwen3.6-35b-a3b       # or keep a smaller/faster model for this role
export MODEL_CONTEXT_LENGTH=131512           # verified — see VRAM math below
export LMSTUDIO_ASSUMED_WEIGHTS_GB=22.1      # Q4_K_M; update if you pick a different quant
export LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000 # required at this context — an L4's 24GB VRAM would not fit it
python deployment/deploy.py
```

Like `qwen/qwen3.6-27b`'s hybrid attention, this architecture's mostly-linear
(Gated DeltaNet) design means the KV-cache warning's full-attention formula
overestimates real usage even more here (only 1-in-4 blocks use quadratic
Gated Attention) — treat any warning as a conservative upper bound and
verify actual usage via Cloud Run logs before raising context further.

**Why `131512` is safe, computed with `check_vram_fit()`'s own formula, not
just asserted:** at this context length the conservative (full-attention,
worst-case) KV-cache estimate is **~20.1 GB**, against **73.9 GB** headroom
(96 GB VRAM − 22.1 GB weights) on `nvidia-rtx-pro-6000` — only ~27% of
headroom used, and real usage is very likely lower given the mostly-linear
attention design noted above. The model's native context window (262,144,
extensible to 1,010,000) is nowhere near a limiting factor either.

### Example: `google/gemma-4-12b-qat` — lower-spec option, fits comfortably on the cheaper default `nvidia-l4`

Dense 11.95B-param model, 48 layers, **hybrid local/global attention: local
sliding-window (1024-token) attention on nearly every layer, with only the
final layer doing full/global attention** — an even more extreme
local-attention skew than either Qwen model above. Native context 256K
(262,144) tokens. Multimodal (text + image, audio on some variants) via an
encoder-free "Unified" design that projects inputs directly into the LLM
embedding space — no separate vision/audio encoder. Confirmed via LM
Studio's model page, its Hugging Face GGUF repo, and Google's official
Gemma 4 model card.

**Only one GGUF quant is currently published**: Q4_0, **≈6.98 GB**
(community-quantized by the LM Studio team via `llama.cpp`) — noticeably
smaller than either Qwen option above, and small enough to run on a single
`nvidia-l4` (24GB VRAM, this project's cheaper default GPU type) rather
than requiring `nvidia-rtx-pro-6000`.

```bash
export MODEL_REASONING=google/gemma-4-12b-qat
export MODEL_FAST=google/gemma-4-12b-qat
export MODEL_CONTEXT_LENGTH=262144             # native max — see VRAM note below, this one needs care
export LMSTUDIO_ASSUMED_WEIGHTS_GB=7.0         # only published quant is Q4_0 ≈6.98GB
python deployment/deploy.py                    # LMSTUDIO_GPU_TYPE unset — defaults to nvidia-l4
```

**VRAM math — read before trusting the deploy-time warning.** `check_vram_fit()`
has no per-model awareness of attention architecture; it assumes every
layer does full quadratic attention. At `MODEL_CONTEXT_LENGTH=262144` that
naive formula estimates **~48.0 GB** of KV cache against only **17.0 GB**
headroom (24 GB VRAM − 7.0 GB weights) on `nvidia-l4` — **the deploy-time
warning will fire loudly and say this doesn't fit.**

That naive number is a poor fit for this specific model, though. With
local sliding-window attention (1024-token window) on 47 of 48 layers and
only the final layer doing genuine full/global attention, a per-layer
accounting gives a very different picture: the 47 local layers' cache is
capped at the 1024-token window regardless of total context (≈0.19 GB
combined), plus one global layer that does scale with context (≈1.0 GB at
262,144 tokens) — **≈1.2 GB realistic total**, nowhere near the 17 GB
budget. llama.cpp-based backends (what LM Studio runs on) implement
bounded KV cache for sliding-window layers correctly, so this realistic
number should be the one that matters in practice.

**This is more speculative than the Qwen recommendations above** — unlike
those, `google/gemma-4-12b-qat` has not been deployed at all yet in this
project, so nothing here is confirmed against live logs. Treat the first
real deploy as the actual test: expect (and ignore) the loud VRAM warning
at deploy time, then check `gcloud run services logs read micro-cosmos-llmgateway`
for the real model-load outcome before trusting this context length.

### Example: `Qwen/Qwen3.6-35B-A3B-FP8` (vLLM, `nvidia-rtx-pro-6000`) — superseded by the `google/gemma-4-31B-it` example below

**No longer the vLLM engine's default** (switched 2026-07-13, see
[Example: `google/gemma-4-31B-it`](#example-googlegemma-4-31b-it-vllm-nvidia-rtx-pro-6000)
below) — kept here for historical/reference-model reasons (real, verified
VRAM math for a hybrid-MoE architecture, still a valid option via
`MODEL_REASONING`/`MODEL_FAST` override). The switch back to Gemma happened
while an unrelated Qwen3.6 readiness/404 investigation was still open (see
`changes-log.md`'s 2026-07-13 entries) — a deliberate reset to a different
model+image, not a confirmed fix for that specific bug.

This was the default for the vLLM engine — see
[GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) at the top of this
file for why vLLM exists at all (LM Studio has no working CUDA runtime on
this GPU). This section is also why Qwen3.6, not Gemma, was chosen at the
time: the first version of this path defaulted to
`google/gemma-4-31B-it-qat-w4a16-ct`, reconsidered after checking actual
coding/agentic benchmarks — Gemma 4 scores well on isolated code generation
(HumanEval/MBPP/LiveCodeBench) but Qwen3.6 is specifically benchmarked on
SWE-bench/agentic-coding tasks, a much closer match to this pipeline's Code
Writer/Reviewer TDD loop (iterative, tool-calling, codebase-navigating) than
isolated function generation.

Same architecture as `qwen/qwen3.6-35b-a3b` above (sparse MoE, 35B total/3B
active per token, 40 layers, hybrid Gated DeltaNet/full-attention design,
native 262,144 context) — but this is the **official FP8 (e4m3) safetensors
checkpoint**, `Qwen/Qwen3.6-35B-A3B-FP8` (~35GB), not a GGUF quant, since
vLLM doesn't load GGUF the way LM Studio/`llama.cpp` does. Confirmed
ungated (Apache-family license, no HF access request needed) via its own
model card.

```bash
export LMSTUDIO_ENGINE=vllm
export MODEL_REASONING=Qwen/Qwen3.6-35B-A3B-FP8
export MODEL_FAST=Qwen/Qwen3.6-35B-A3B-FP8      # single self-hosted GPU service — same model for both roles
export MODEL_CONTEXT_LENGTH=262144              # native max — comfortably fits, see VRAM math below
export LMSTUDIO_REASONING_PARSER=qwen3              # keeps "thinking" output out of the main response content
export LMSTUDIO_TOOL_CALL_PARSER=hermes             # REQUIRED — without this vLLM returns tool calls as plain
                                                 # text, breaking every ADK FunctionTool-using agent
export LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000    # required — MoE weights don't fit nvidia-l4's 24GB
export HF_TOKEN=<your-huggingface-access-token>  # optional — see below
export LLM_API_KEY=<a-secret-you-generate>  # optional — see "API key authentication" below
python deployment/deploy.py
```

(These are also `deploy_cloudrun-vllm-llms.py`'s own built-in defaults —
the block above is for clarity/override reference, not strictly required if
you're happy with the defaults.)

**`HF_TOKEN` — optional, not required for this model.** `Qwen/Qwen3.6-35B-A3B-FP8`
is public/ungated, so no token is needed to download it at all. Setting
`HF_TOKEN` only raises HuggingFace's rate limit above the unauthenticated
tier — worth doing if you redeploy frequently (each fresh container boot
makes a metadata call to HuggingFace Hub even when the weights themselves
are already cached in the GCS bucket, and repeated redeploys in a short
window could plausibly approach the unauthenticated per-IP limit, though no
actual rate-limit error has been hit in practice so far). To get one:
`huggingface.co` → Settings → **Access Tokens** → create one scoped to
**"Read"** (no write access needed). **Never commit this value or paste it
into a chat/issue** — export it directly in your shell only. If unset,
`HF_TOKEN` is omitted entirely from the deploy (not passed as an empty
value), and the deploy script redacts it from any printed error output if
the `gcloud run deploy` command itself ever fails, so it can't leak into
your terminal/logs even on a failed deploy attempt.

**`LMSTUDIO_TOOL_CALL_PARSER` is not optional in practice.** This pipeline's
agents (`micro_cosmos/agents/*.py`, via `micro_cosmos/settings.py`'s `build_llm()`)
rely entirely on OpenAI-style function calling for every tool call (seam
submission, review results, spec generation, etc.). Unlike LM Studio, vLLM
does not parse tool calls out of the model's raw output unless
`--enable-auto-tool-choice --tool-call-parser <name>` is passed — without
it, tool calls come back as plain text and every tool-using agent breaks.
`hermes` is vLLM's documented general-purpose parser for Qwen3-class
models — **not yet confirmed specifically for Qwen3.6** (vLLM's docs show
`qwen3_xml`/`qwen3_coder` for the Coder-branded variants and `hermes` for
general Qwen3, but Qwen3.6 wasn't explicitly listed) — verify against the
first real tool call and switch parsers if calls aren't parsed correctly.

**Real VRAM math, computed from this exact checkpoint's `config.json`, not
guessed:** 40 layers total, hybrid attention — 10 full-attention layers
interspersed among 30 linear-attention (Gated DeltaNet) layers whose state
does **not** grow with context length (only the 10 full-attention layers'
KV cache does). Extreme GQA: only **2 KV heads** (vs Gemma-4-31B's 16) —
this is what makes this model's real KV-cache footprint so much smaller
than a naive estimate would suggest, despite having more total params than
the Gemma checkpoint this script originally defaulted to.

- Full-attention KV cache (bf16): `2×10×2×256×2 bytes = 20KB/token` → **~5.0
  GB at the full native context 262,144**.
- Weights (FP8, ~35B params at ~8 bits): ≈**35GB**.
- **Total ≈40GB** vs `nvidia-rtx-pro-6000`'s 96GB×0.9 utilization = 86.4GB
  budget — **~46GB headroom**, comfortably more than the Gemma checkpoint's
  ~28.6GB headroom despite this model's larger total param count. Verified
  by running the actual `estimate_kv_cache_gb()` function in
  `deploy_cloudrun-vllm-llms.py`: reproduces 5.00GB/40.00GB/46.40GB exactly.
- No `--kv-cache-dtype` flag (vLLM's own `auto` default) — a prior version
  hardcoded `bfloat16` here to avoid `auto`'s uncalibrated fp8 scale, but
  that's confirmed wrong for any Gemma 4 model (see the entry below) — this
  script inherits the same `vllm-entrypoint.sh` and would hit the identical
  crash if `bfloat16` were reintroduced.

**Not yet verified against a live deploy** — no Docker/Cloud Run/GPU access
in the session that built this path. `--quantization` is deliberately not
passed explicitly in `vllm-entrypoint.sh` — vLLM auto-detects FP8/compressed-tensors
from the checkpoint's own HF config, keeping the entrypoint model-agnostic
rather than hardcoding a value that would be wrong for a different model.

### Example: `google/gemma-4-31B-it` (vLLM, `nvidia-rtx-pro-6000`)

**This is the current default for the vLLM engine** (`deploy_cloudrun-vllm-llms.py`,
2026-07-13). Dense 31B-parameter model, full BF16 precision — **no
quantization at all** (no `quantization_config` in the checkpoint's own
`config.json`), unlike every earlier model this script has defaulted to.
Ungated, Apache-family license, per its own HF model card. Uses vLLM's
official `gemma4`-tagged image (see `Dockerfile.vllm`) rather than the
generic `cu129-nightly`/pinned-digest image the earlier models used — per
vLLM's own Gemma 4 deployment recipe
(docs.vllm.ai/projects/recipes/.../Google/Gemma4.html), `gemma4` is the
CUDA 12.9 build (same cc-12.0-safe generation as before; a `gemma4-cu130`
tag exists too, deliberately not used — `cu130` is documented elsewhere to
crash `custom_all_reduce` on this GPU's compute capability).

```bash
export LMSTUDIO_ENGINE=vllm
export MODEL_REASONING=google/gemma-4-31B-it
export MODEL_FAST=google/gemma-4-31B-it         # single self-hosted GPU service — same model for both roles
export MODEL_CONTEXT_LENGTH=65536               # NOT the native max (262144) — see VRAM math below for why
export LMSTUDIO_TOOL_CALL_PARSER=gemma4         # REQUIRED — without this vLLM returns tool calls as plain
                                                 # text, breaking every ADK FunctionTool-using agent
export LMSTUDIO_CHAT_TEMPLATE=examples/tool_chat_template_gemma4.jinja  # REQUIRED alongside the parser
                                                 # above — bundled in the gemma4 image itself, no download needed
export LMSTUDIO_GPU_TYPE=nvidia-rtx-pro-6000    # required — this model's ~62GB of BF16 weights alone
                                                 # exceed nvidia-l4's entire 24GB VRAM
export HF_TOKEN=<your-huggingface-access-token>  # optional — see below
export LLM_API_KEY=<a-secret-you-generate>  # optional — see "API key authentication" below
python deployment/deploy.py
```

(These are also `deploy_cloudrun-vllm-llms.py`'s own built-in defaults —
the block above is for clarity/override reference, not strictly required if
you're happy with the defaults.)

**`LMSTUDIO_REASONING_PARSER` defaults to `gemma4` (2026-07-14).** vLLM's
own Gemma 4 deployment recipe pairs `--reasoning-parser gemma4` with
`--tool-call-parser gemma4` for this exact model — set
`LMSTUDIO_REASONING_PARSER=` (empty) to disable it if you don't want
"thinking"/chain-of-thought content surfaced.

**`LMSTUDIO_CHAT_TEMPLATE` is not optional in practice, same as
`LMSTUDIO_TOOL_CALL_PARSER`.** Unlike Qwen3.6/`hermes` (which needed no
custom template), vLLM's own Gemma 4 recipe documents
`--chat-template examples/tool_chat_template_gemma4.jinja` as required
alongside `--tool-call-parser gemma4` for tool calling to work at all — this
pipeline's agents rely entirely on OpenAI-style function calling, so
skipping this would silently break every tool-using agent the same way a
missing `--tool-call-parser` would. The path is relative to the image's own
`WORKDIR` — the `gemma4` image bundles this file already, no separate
download or volume mount needed.

**Real VRAM math, computed from this exact checkpoint's `config.json`, not
guessed:** 60 layers total, hybrid attention — every 6th layer (10 total) is
full-attention, the other 50 are sliding-window (1024-token window, capped
regardless of context length — small but **not zero**, unlike Qwen3.6's
Gated DeltaNet layers). 16 KV heads, head_dim 256, native context 262,144.

- Full-attention KV cache (bf16): `2×10×16×256×2 bytes = 160KB/token` → **40.0
  GB at the full native context 262,144** — this alone, before weights, would
  exceed the GPU's budget (see below), which is why `MODEL_CONTEXT_LENGTH`
  is set to 65536 instead.
- Sliding-window layers (50, capped at 1024 tokens): ≈0.78GB, small but
  included in the real formula (unlike a purely-linear-attention model like
  Qwen3.6, these layers' cache isn't zero).
- At context **65536**: full-attention KV ≈10.0GB + sliding ≈0.78GB ≈
  **10.8GB total KV cache**.
- Weights (full BF16, ~31B params at 2 bytes): ≈**62GB**.
- **Total ≈72.8GB** vs `nvidia-rtx-pro-6000`'s 96GB×0.9 utilization = 86.4GB
  budget — **~13.6GB headroom**. Verified by running the actual
  `estimate_kv_cache_gb()` function in `deploy_cloudrun-vllm-llms.py`
  (extended 2026-07-13 to add the sliding-window contribution rather than
  treat it as zero): reproduces 10.78GB/72.78GB/13.62GB exactly. At the
  native max context (262144) this model does **not** fit this GPU
  (~102.8GB required, exceeds the 86.4GB budget) — raise
  `MODEL_CONTEXT_LENGTH` only with this math in mind, not past ~150K tokens
  (the real ceiling, computed the same way).
- No `--kv-cache-dtype` flag (vLLM's own `auto` default), **since 2026-07-14**.
  A prior version hardcoded `--kv-cache-dtype bfloat16` here as a
  hardware/numerics caveat, but a live deploy crashed immediately after
  model load with `AssertionError: unsupported kv_cache_dtype (str), got
  bfloat16` — vLLM forces the `TRITON_ATTN` backend for **any** Gemma 4
  model ("heterogeneous head dimensions... Forcing TRITON_ATTN backend"),
  and that backend's kernel only accepts `kv_cache_dtype == "auto"` or an
  `fp8*` value, never a literal `bfloat16` string. Because the container
  crash-looped on every startup attempt, Cloud Run's TCP startup probe never
  caught port 8000 open across the full 30-minute window, and the deploy
  failed with a misleading "startup probes timed out" error that looked like
  a slow model load, not a crash. See `changes-log.md`'s 2026-07-14 entries.

**`--limit-mm-per-prompt` (text-only profiling skip) — tried and reverted,
not supported by this deployment path.** vLLM's own Gemma 4 recipe
recommends this flag to skip multimodal profiling for text-only workloads
(this pipeline never sends image/audio input). A first attempt
(2026-07-13) used the flat `image=0,audio=0` form, which fails `vllm
serve`'s argument parser outright (its real type is `json.loads`,
confirmed via vLLM's own canonical
`docs.vllm.ai/en/stable/configuration/engine_args/` reference — the
correct CLI value is JSON). A second attempt (2026-07-14) switched to the
correct JSON form, single-quoted for shell safety, but **`gcloud run
deploy --set-env-vars` cannot parse a JSON-shaped value at all** — its own
dict-argument parser chokes on the braces/colons regardless of quoting or
being passed as a separate flag occurrence (`Bad syntax for dict arg:
["audio":0}]`). Rather than fight gcloud's escaping rules
(`gcloud topic escaping`/`--env-vars-file`) for what's a minor
optimization, this flag has been dropped entirely — `GPU_MEMORY_UTILIZATION`
already covers the meaningful memory-tuning knob. See
`changes-log.md`'s 2026-07-14 entries for the full history.

### Example: `google/gemma-4-E4B-it` (vLLM, `nvidia-l4`) — lite setup

**Lite alternative to the `google/gemma-4-31B-it`/`nvidia-rtx-pro-6000`
default above** — same vLLM engine, much smaller model and GPU. Small
MoE, ~7.9B total params ("effective 4B" active — MoE doesn't reduce
resident weight VRAM, only compute; same reasoning already used for this
model's LM Studio-engine default in `deploy_cloudrun-lmstudio-llms.py`).
128K native context. Full BF16, no `quantization_config` in the
checkpoint's `config.json`.

**Naming matters here — vLLM needs a different model ID than LM Studio
uses.** LM Studio's engine (`deploy_cloudrun-lmstudio-llms.py`) already
defaults to this model via its GGUF-community ID, `google/gemma-4-e4b`
(lowercase, no `-it` suffix — LM Studio's own naming convention for this
checkpoint). **vLLM needs the official Hugging Face/safetensors repo
instead: `google/gemma-4-E4B-it`** (capital `E4B`, `-it` for
instruction-tuned) — confirmed via vLLM's own recipe page and the
model's Hugging Face page. Using the LM Studio-style lowercase ID here
would not resolve as a vLLM-loadable checkpoint.

```bash
export LMSTUDIO_ENGINE=vllm
export MODEL_REASONING=google/gemma-4-E4B-it
export MODEL_FAST=google/gemma-4-E4B-it         # single self-hosted GPU service — same model for both roles
export MODEL_CONTEXT_LENGTH=131072              # native max — real per-layer math below shows this fits comfortably
export LMSTUDIO_TOOL_CALL_PARSER=gemma4         # REQUIRED — same flags apply across all Gemma 4 sizes,
export LMSTUDIO_REASONING_PARSER=gemma4         # confirmed via vLLM's own Gemma 4 recipe page (not
export LMSTUDIO_CHAT_TEMPLATE=examples/tool_chat_template_gemma4.jinja  # size-specific guidance)
export LMSTUDIO_GPU_TYPE=nvidia-l4              # vLLM's own recipe confirms E4B fits a single 24GB+ GPU in BF16
export VLLM_ASSUMED_WEIGHTS_GB=15.8             # ~7.9B params × 2 bytes (BF16) — see VRAM math below
export HF_TOKEN=<your-huggingface-access-token>  # optional — see below
export LLM_API_KEY=<a-secret-you-generate>  # optional — see "API key authentication" below
python deployment/deploy.py
```

**Real VRAM math, computed from this exact checkpoint's `config.json`
(fetched directly, not guessed)**: 42 layers total — 6 full/global
attention layers (every 6th, same hybrid pattern as the 31B model), 36
sliding-window layers (**512-token window**, half the 31B model's 1024).
Only **2 KV heads** (extreme GQA — an 8× reduction vs the 31B model's 16),
head_dim 256.

- Full-attention KV cache (bf16): `2×6×2×256×2 bytes = 12KB/token` → at the
  full native context **131,072**: **1.5GB**.
- Sliding-window layers (36, capped at 512 tokens): `2×36×2×256×2 bytes ×
  512 = ~0.04GB` — negligible.
- **Total KV cache at the full native context ≈1.54GB** — tiny, thanks to
  the extreme GQA (2 KV heads).
- Weights (BF16, ~7.9B params): ≈**15.8GB**.
- **Total ≈17.3GB** vs `nvidia-l4`'s 24GB×0.9 utilization = **21.6GB
  budget — ~4.3GB headroom**, even at the model's full native context.
  This is why `MODEL_CONTEXT_LENGTH` is set to the full 131072 here, unlike
  the 31B example above which has to stay well below its native max.

**`check_vram_fit()`'s warning will very likely fire anyway — expect and
ignore it, same pattern as the `google/gemma-4-12b-qat` example above.**
Unlike that example (a generic naive-full-attention assumption),
`deploy_cloudrun-vllm-llms.py`'s per-layer constants
(`DEFAULT_FULL_ATTENTION_LAYERS`/`DEFAULT_KV_HEADS`/`DEFAULT_SLIDING_WINDOW_*`)
are hardcoded specifically for `google/gemma-4-31B-it`'s real architecture
(10 full-attention layers, 16 KV heads, 1024-token window) — not exposed
via env var, and **wrong** for this model's real numbers (6/2/512 above).
Plugging this model's real weight size into that mismatched formula
produces a KV-cache estimate around 20.8GB (vs the real ~1.54GB) — loud,
and incorrect. Trust the real per-layer math above, verified against this
model's actual `config.json`, not the script's generic warning output.

**Tool calling — same flags as every Gemma 4 size, confirmed via vLLM's
own recipe page, not assumed:** `--enable-auto-tool-choice
--reasoning-parser gemma4 --tool-call-parser gemma4 --chat-template
examples/tool_chat_template_gemma4.jinja` — the recipe explicitly states
these apply identically across all Gemma 4 variants, not just the 31B
model. `vllm-entrypoint.sh` already adds `--enable-auto-tool-choice`
automatically whenever `LMSTUDIO_TOOL_CALL_PARSER` is set, so no script
changes are needed for this lite setup — it's purely an env var
configuration swap.

**Not yet verified against a live deploy** — no Docker/Cloud Run/GPU
access in the session that wrote this. Treat the first real deploy as the
actual test, same caveat as every other not-yet-deployed example in this
file.

### API key authentication — `LLM_API_KEY`, and why it behaves differently per engine

`LLM_API_KEY` is the one shared secret `micro-cosmos-web` sends as
`Authorization: Bearer <value>` on every request to whichever engine is
serving `micro-cosmos-llmgateway` — real LLM calls (`micro_cosmos/settings.py`'s
`build_llm()`) and the pipeline's own pre-flight readiness check
(`_wait_for_llm_ready()` in `micro_cosmos/orchestration/driver.py`) both
send it. Whether the *server* side actually enforces it depends on the
engine:

- **vLLM (`LMSTUDIO_ENGINE=vllm`)** — fully enforced. Set `LLM_API_KEY`
  before running `deploy.py` and the same value is passed to the GPU
  service too, which starts `vllm serve` with `--api-key` (a real,
  documented vLLM flag). Requests without the correct key get a real 401
  from vLLM itself. Leave it unset and vLLM runs with no request-level
  auth at all — `--ingress=internal` remains the only boundary, same as
  before this was wired up.
- **LM Studio (`LMSTUDIO_ENGINE=lmstudio`, the default)** — **not
  enforceable headlessly.** LM Studio's "Require Authentication" toggle is
  GUI-only; `lms server start` has no CLI flag for it (open, unresolved:
  `lmstudio-ai/lms#489`). Setting `LLM_API_KEY` still makes
  `micro-cosmos-web` send the header, but the Cloud Run LM Studio container
  never had a GUI session to enable the check, so it has no effect there
  — `--ingress=internal` is the real (and only) boundary for this engine.
- **Local docker-compose** — LM Studio here runs on your own host machine
  (`host.docker.internal:1234`), the one place its GUI toggle can actually
  be used. If you've turned "Require Authentication" ON in LM Studio's
  Developer tab → Server Settings, `LLM_API_KEY` in your `.env`
  **must be the exact token LM Studio generated on that same page** — not
  an arbitrary placeholder. A mismatch fails every request with
  `401 invalid_api_key`, including the pipeline's readiness check, which
  will then sit at "waiting for `<model>` to load…" for the full
  `LMSTUDIO_READY_TIMEOUT_SECONDS` (confirmed 2026-07-13) before giving up
  and proceeding anyway. If authentication is OFF (the default), any
  non-empty value works — LM Studio's own docs describe this as accepting
  "any non-empty value" in that mode.

---

## Deploy everything in one shot

```bash
export PROJECT=my-project
python deployment/deploy.py
```

This runs, in order:
1. `deploy_cloudrun-lmstudio-llms.py` — builds the LMStudio image, creates the
   model-cache bucket, deploys the GPU Cloud Run service, returns its internal URL.
2. `deploy_cloudrun-micro-cosmos-app.py` — builds the app image, deploys it wired to
   the LLMGateway URL from step 1.

Takes ~10–15 minutes (image builds + Cloud Run GPU cold start for the first
model load).

### Deterministic mode (no LLM, no GPU cost)

```bash
export PROJECT=my-project
SKIP_LLM=true python deployment/deploy.py
```

Skips the LLMGateway GPU deployment entirely and deploys `micro-cosmos-web` with
`SKIP_LLM=true` — gate approvals still work; pipeline agents return symbolic
fallbacks instead of calling a model.

**`LLM_BASE_URL` in this mode:** since no LLMGateway service exists to
discover, `deploy_cloudrun-micro-cosmos-app.py` sets it to a placeholder,
`http://unused:1234/v1`. This is a syntactically valid URL, just not a
reachable one — `unused` isn't a real hostname and won't resolve via DNS.
It's needed only because `micro_cosmos/settings.py` declares `llm_base_url`
as a plain string field with a default, so the env var must be set to
*something* to keep the wiring consistent with LLM mode — but in
deterministic mode every agent phase uses symbolic fallbacks, so the value
is never actually read by `Settings.build_llm()`, let alone dialed over the
network. The unresolvable placeholder is deliberate: if a future bug ever
caused it to be dialed despite `SKIP_LLM=true`, it fails immediately with a
DNS error instead of silently succeeding against some accidental real host.

---

## Deploy services individually

### LM Studio engine only

```bash
export PROJECT=my-project
export MODEL_REASONING=google/gemma-4-e4b       # optional override — this is already the default
export MODEL_CONTEXT_LENGTH=131072              # optional override — see VRAM note below
export LMSTUDIO_REGION=europe-west4             # optional override
export LMSTUDIO_PORT=1234                       # optional override — matches local docker-compose
python deployment/deploy_cloudrun-lmstudio-llms.py
```

What it does:
1. Ensures the `micro-cosmos` Artifact Registry repo exists.
2. Ensures `gs://$PROJECT-lmstudio-models` exists and grants the runtime
   service account write access (this is where pulled model weights persist).
3. Builds `Dockerfile.lmstudio` from a minimal build context (just the
   Dockerfile + entrypoint script — not the whole repo).
4. Deploys `micro-cosmos-llmgateway` to Cloud Run: 32 Gi RAM, 8 vCPU, 1× NVIDIA L4,
   `--ingress=internal`, GCS FUSE volume mounted at `/root/.lmstudio/models`
   (deliberately the `models` subdirectory, not `.lmstudio` itself — see
   "Container startup timeout" above for why).

First deploy: the container pulls the model into the mounted bucket on
container start (~5–15 min depending on model size and Cloud Run cold-start
network throughput). Subsequent cold starts reuse the cached weights.

### vLLM only

```bash
export PROJECT=my-project
export MODEL_REASONING=google/gemma-4-31B-it      # optional override — this is already the default
export MODEL_CONTEXT_LENGTH=65536                 # optional override — see VRAM math above
export GPU_MEMORY_UTILIZATION=0.9                 # optional override
export LMSTUDIO_REASONING_PARSER=gemma4           # optional override — this is already the default; set to empty to disable
export LMSTUDIO_TOOL_CALL_PARSER=gemma4           # optional override — REQUIRED in practice, see above
export LMSTUDIO_CHAT_TEMPLATE=examples/tool_chat_template_gemma4.jinja  # optional override — REQUIRED alongside the parser above
export LMSTUDIO_REGION=europe-west4               # optional override
export HF_TOKEN=<your-huggingface-access-token>   # optional — see "Example: google/gemma-4-31B-it" above
# export LMSTUDIO_PORT=8000                       # optional override — this is already the default (vLLM's own, not LM Studio's 1234)
python deployment/deploy_cloudrun-vllm-llms.py
```

**Important — running this standalone (not via `deploy.py`) does not
protect against a `MODEL_REASONING`/`micro-cosmos-web` mismatch.** If
`micro-cosmos-web` is already deployed pointing at a different model, redeploy
it too (or set its `MODEL_REASONING`/`MODEL_FAST` to match) — see
[GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) at the top of
this file for why this matters for vLLM specifically.

What it does:
1. Ensures the `micro-cosmos` Artifact Registry repo exists.
2. Ensures `gs://$PROJECT-lmstudio-models` exists and grants the runtime
   service account write access (same bucket name as the LM Studio path —
   this is where the pulled HuggingFace model cache persists).
3. Builds `Dockerfile.vllm` from a minimal build context (just the
   Dockerfile + entrypoint script — not the whole repo).
4. Deploys `micro-cosmos-llmgateway` to Cloud Run: 80 Gi RAM, 20 vCPU, 1×
   `nvidia-rtx-pro-6000`, `--ingress=internal`, GCS FUSE volume mounted at
   `/root/.cache/huggingface` (vLLM/HuggingFace's own cache root, so the
   ~35GB download persists across redeploys/cold starts).

First deploy: the container pulls the model into the mounted bucket on
container start. **Not yet verified against a live deploy** — no
Docker/Cloud Run/GPU access in the session that built this path.

### Micro-Cosmos web app only

```bash
export PROJECT=my-project
# LLM_BASE_URL is auto-discovered from the micro-cosmos-llmgateway service if unset:
# export LLM_BASE_URL=https://micro-cosmos-llmgateway-xxxx.a.run.app/v1
python deployment/deploy_cloudrun-micro-cosmos-app.py
```

If `micro-cosmos-llmgateway` isn't deployed yet and `LLM_BASE_URL` isn't set,
this exits with an error telling you to deploy LLMGateway first or set
`SKIP_LLM=true`.

---

## Configuration reference

| Env var | Default | Used by |
|---|---|---|
| `PROJECT_NAME` | *(optional)* | human label only — no script reads it |
| `PROJECT_ID` | *(required)* | GCP Project ID string — fallback source for `PROJECT` in all three scripts |
| `PROJECT` | *(required)* | all three scripts read this first; mirror it from `PROJECT_ID` |
| `GOOGLE_CLOUD_LOCATION` | `europe-west4` | region for both services |
| `LMSTUDIO_REGION` | `europe-west4` | LMStudio-specific region override |
| `LMSTUDIO_ENGINE` | `lmstudio` | `vllm` switches the GPU service's engine and script — see [GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) |
| `MODEL_REASONING` / `MODEL_FAST` | `google/gemma-4-e4b` (LM Studio) or `google/gemma-4-31B-it` (vLLM) | model ID — via `deploy.py`, resolved once from the selected engine's default and passed to both deploys so they can't mismatch |
| `LLM_ENGINE` | `lmstudio` | Read by `micro_cosmos/settings.py`'s `build_llm()` — must match whichever engine actually deployed `micro-cosmos-llmgateway` (vLLM's stricter API rejects LM Studio's `num_ctx` extra param). `deploy.py` sets this automatically from `LMSTUDIO_ENGINE` |
| `MODEL_CONTEXT_LENGTH` | `131072` (LM Studio/`gemma-4-e4b`) or `65536` (vLLM/`gemma-4-31B-it`) | KV-cache window — see [Context length vs GPU VRAM](#context-length-vs-gpu-vram--read-this-before-raising-model_context_length) below |
| `MODEL_TEMPERATURE` | `0.2` | Sampling temperature sent on every LLM call (`Settings.build_llm()`) — low value favors precise, low-variance output, appropriate for code translation. **Bug fixed 2026-07-2x**: `deploy_cloudrun-micro-cosmos-app.py` previously hardcoded `MODEL_TEMPERATURE=0.3` unconditionally, silently ignoring this env var entirely (and every `gcloud-run-setup*.txt`'s already-correct `MODEL_TEMPERATURE=0.2` line) — now actually parameterized and read |
| `LMSTUDIO_GPU_LAYERS` | `max` | LM Studio only — `max` = fully offload to GPU VRAM; a number partially offloads, spilling the rest into host RAM (slower) |
| `GPU_MEMORY_UTILIZATION` | `0.9` | vLLM only — fraction of GPU VRAM vLLM is allowed to use |
| `LMSTUDIO_REASONING_PARSER` | `gemma4` | vLLM only — enabled by default (2026-07-14), pairing `--reasoning-parser gemma4` with `--tool-call-parser gemma4` per vLLM's own Gemma 4 deployment recipe. Empty disables it if you don't want "thinking"/chain-of-thought content surfaced. Renamed from `VLLM_REASONING_PARSER` (2026-07-13) — the `VLLM_` prefix isn't a real vLLM-recognized var, and made vLLM's own env scanner log a false-positive "Unknown vLLM environment variable" warning on every startup |
| `LMSTUDIO_TOOL_CALL_PARSER` | `gemma4` | vLLM only — **required** for this pipeline's agents to work at all; without `--enable-auto-tool-choice` + a parser, vLLM returns tool/function calls as plain text instead of a structured `tool_calls` array, silently breaking every ADK `FunctionTool`-using agent. Empty disables it (don't disable unless you know the model needs no tool-calling). Renamed from `VLLM_TOOL_CALL_PARSER` (2026-07-13), same reason as `LMSTUDIO_REASONING_PARSER` above |
| `LMSTUDIO_CHAT_TEMPLATE` | `examples/tool_chat_template_gemma4.jinja` | vLLM only — **required alongside `LMSTUDIO_TOOL_CALL_PARSER`** for Gemma 4 tool calling to work at all (added 2026-07-13; Qwen3.6/`hermes` needed no such template). Bundled in the `gemma4` image itself, no download/mount needed. Empty omits the flag entirely |
| `LMSTUDIO_ENABLE_THINKING` | *(unset — off)* | vLLM only — set to `true` to force Gemma 4 chain-of-thought reasoning on for every request via `--default-chat-template-kwargs '{"enable_thinking": true}'`. **Not the same as `LMSTUDIO_REASONING_PARSER` being set** — that flag only parses reasoning content out of the response if the model produces any; it does not by itself turn thinking on. Confirmed via vLLM's own Gemma 4 docs/recipe, not guessed. Worth enabling for translation tasks with intricate source semantics (COBOL `COMP-3` arithmetic, `PERFORM THRU` loops); costs extra generated tokens against the same `MODEL_CONTEXT_LENGTH` budget as everything else |
| `HF_TOKEN` | *(unset)* | vLLM only, optional — HuggingFace access token (Settings → Access Tokens → "Read" scope). Not required for the ungated default model; only raises the unauthenticated-request rate limit. Never commit or paste this value — set it directly in your shell. Omitted entirely from the deploy when unset, and redacted from any printed error output if the deploy command itself fails |
| `LMSTUDIO_ASSUMED_WEIGHTS_GB` (LM Studio) / `VLLM_ASSUMED_WEIGHTS_GB` (vLLM) | `5.0` / `62.0` | Weight size of `MODEL_REASONING`, in GB (quantized size if applicable — the current vLLM default, `google/gemma-4-31B-it`, is full BF16, unquantized) — feeds the VRAM heads-up warning in `check_vram_fit()`. Must be updated when switching models — see [Switching models](#switching-models--no-code-changes-required) |
| `LMSTUDIO_GPU_TYPE` | `nvidia-l4` (LM Studio) / `nvidia-rtx-pro-6000` (vLLM) | `nvidia-rtx-pro-6000` for the 96GB-VRAM option — see [GPU type](#gpu-type--nvidia-rtx-pro-6000-blackwell-preview) |
| `LMSTUDIO_MEMORY` / `LMSTUDIO_CPU` | per-GPU-type default (`GPU_DEFAULTS` in the script) | Override Cloud Run's `--memory`/`--cpu`; only needed to size above the selected GPU type's enforced minimum |
| `LMSTUDIO_GPU_ZONAL_REDUNDANCY` | `false` | `true` only if your project has separate GPU zonal-redundancy quota approved — see [GPU zonal redundancy](#gpu-zonal-redundancy--separate-quota-from-base-gpu-quota) |
| `LMSTUDIO_STARTUP_TIMEOUT_SECONDS` | `1800` | Total Cloud Run startup probe budget (replaces the 4-minute default; 1800s is Cloud Run's documented ceiling for GPU/AI workloads) — see [GPU cold-start startup probe timeout](#gpu-cold-start-startup-probe-timeout--a-different-symptom-same-generic-error-text) |
| `LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS` | `1500` | Both engines — how long the in-container watchdog waits before giving up and killing the backend process, exiting non-zero. vLLM: waits for `/v1/models` to report ready (polling from inside the container, where an `Authorization` header is trivial to add — Cloud Run's own `--startup-probe` can't). LLM: waits for the backgrounded `lms load` process to finish at all (success or explicit failure — an explicit failure is unaffected by the watchdog and propagates immediately). Added 2026-07-13 after a real incident where a vLLM container reported "Ready" (TCP probe passing) for 44+ minutes with the model never actually loading — see [GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) |
| `LMSTUDIO_WATCHDOG_POLL_SECONDS` | `10` (vLLM) / `2` (LM Studio) | Both engines — poll interval for the watchdog above |
| `LMSTUDIO_HOST_BIND` | `0.0.0.0` | Bind address passed to `lms server start --bind` and used for the entrypoint's internal health check — must be `0.0.0.0` for Cloud Run to route traffic in; the CLI's own default (`127.0.0.1`) would break this |
| `LMSTUDIO_PORT` | `1234` (LM Studio) / `8000` (vLLM) | Container port for `micro-cosmos-llmgateway` — LM Studio matches the local docker-compose convention; vLLM uses its own native default (2026-07-13, left untouched rather than forced onto LM Studio's `1234`) — see [Container port convention](#container-port-convention--matches-local-docker-compose) |
| `LMSTUDIO_MODEL_BUCKET` | `$PROJECT-lmstudio-models` | GCS bucket for model cache — same bucket name for both engines, mounted at `/root/.lmstudio/models` (LM Studio) or `/root/.cache/huggingface` (vLLM) |
| `LMSTUDIO_SERVICE_ACCOUNT` | `micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com` | LMStudio Cloud Run identity |
| `LMSTUDIO_MIN_INSTANCES` | `0` | scale-to-zero by default (see cost note below) |
| `LMSTUDIO_MAX_INSTANCES` | `1` | single-GPU serving |
| `LMSTUDIO_CONCURRENCY` | `1` | one generation at a time per GPU instance |
| `LLM_BASE_URL` | auto-discovered | override to point `micro-cosmos-web` at a different LLMGateway endpoint |
| `LLM_API_KEY` | `lm-studio` | Sent by `micro-cosmos-web` as `Authorization: Bearer <value>` on every request (real LLM calls and the pre-flight readiness check). Fully enforced server-side on vLLM (`--api-key`, wired via `deploy.py`); has no effect on LM Studio, which has no headless auth flag — see [API key authentication](#api-key-authentication--llm_api_key-and-why-it-behaves-differently-per-engine) |
| `LMSTUDIO_READY_TIMEOUT_SECONDS` | `1500` (25 min) | `micro_cosmos/settings.py`'s `llm_ready_timeout_seconds` — how long `micro-cosmos-web`'s pre-flight readiness check (`_wait_for_llm_ready()`) polls before giving up and proceeding anyway. **Floored at 1500s (25 min) — same as the default** as of 2026-07-13: this value can never be configured lower, any lower value is silently clamped up, logged as a warning. A genuinely fresh `CreateService` (first-ever deploy, full image pull) has been measured taking **16m38s just to bind the port**, before model loading (~11-12 min more) even starts — a worst-case fresh deploy can plausibly approach ~25-29 minutes total, which is why 1500s is the floor, not just the default |
| `SERVICE_ACCOUNT` | `micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com` | micro-cosmos-web Cloud Run identity |
| `MICRO_COSMOS_EXAMPLES_BUCKET` | `$PROJECT-micro-cosmos-examples` | GCS bucket mounted at `/app/examples`, synced from the repo's `examples/` on every deploy — see [Examples gallery](#examples-gallery--mounted-matching-local-docker-compose) |
| `MICRO_COSMOS_RUNS_BUCKET` | `$PROJECT-micro-cosmos-runs` | GCS bucket mounted at `/app/runs` — no seed/sync step, pure runtime output, no lifecycle policy — see [Run artifacts](#run-artifacts--mounted-matching-local-docker-compose) |
| `MICRO_COSMOS_LB_DOMAIN` | *(required for `setup_micro_cosmos_web_lb.py`)* | Domain the SSL certificate is issued for, e.g. `app.micro-cosmos.tools` — see [Web UI access](#web-ui-access--micro-cosmos-web-is-public-via-an-external-load-balancer-micro-cosmos-llmgateway-stays-internal-only) |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | `demo` / `demobxyz` *(must override — `deploy_cloudrun-micro-cosmos-app.py` fails otherwise)* | Web UI login credentials — see [Login](#login--demodemobxyz) |
| `SESSION_SECRET_KEY` | generated fresh per deploy/container start | Signs the session cookie; set explicitly to persist sessions across redeploys/restarts instead of forcing re-login every time |
| `SESSION_HTTPS_ONLY` | `false` (docker-compose) / `true` (Cloud Run, set by `deploy_cloudrun-micro-cosmos-app.py`) | Marks the session cookie `Secure` — must be `true` once served over real HTTPS, `false` for plain local `http://` |
| `SKIP_LLM` | `false` | `true` = deterministic mode, skips LLMGateway deploy entirely |
| `MICRO_COSMOS_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` — see [Logging](#logging--micro_cosmos_log_level) below |

---

## Manual gcloud equivalents

If you prefer shell commands over the Python scripts:

### LM Studio engine (GPU)

```bash
gcloud run deploy micro-cosmos-llmgateway \
  --image=europe-west4-docker.pkg.dev/$PROJECT/micro-cosmos/lmstudio:latest \
  --region=europe-west4 \
  --allow-unauthenticated \
  --ingress=internal \
  --service-account=micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com \
  --port=1234 \
  --memory=32Gi \
  --cpu=8 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --no-cpu-throttling \
  --no-gpu-zonal-redundancy \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=3600 \
  --startup-probe=tcpSocket.port=1234,initialDelaySeconds=0,periodSeconds=10,failureThreshold=180 \
  --clear-volumes \
  --clear-volume-mounts \
  --add-volume=name=model-cache,type=cloud-storage,bucket=$PROJECT-lmstudio-models \
  --add-volume-mount=volume=model-cache,mount-path=/root/.lmstudio/models \
  --set-env-vars=MODEL_ID=google/gemma-4-e4b,MODEL_CONTEXT_LENGTH=131072,GPU_LAYERS=max,LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS=1500,LMSTUDIO_WATCHDOG_POLL_SECONDS=2
```

For `nvidia-rtx-pro-6000` instead of `nvidia-l4`: use `gcloud beta run deploy`
(preview GPU type), `--memory=80Gi --cpu=20`, and `--gpu-type=nvidia-rtx-pro-6000`
— see "GPU type" above.

### vLLM (GPU) — alternative to LM Studio, see [GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm)

```bash
gcloud beta run deploy micro-cosmos-llmgateway \
  --image=europe-west4-docker.pkg.dev/$PROJECT/micro-cosmos/vllm:latest \
  --region=europe-west4 \
  --allow-unauthenticated \
  --ingress=internal \
  --service-account=micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com \
  --port=8000 \
  --memory=80Gi \
  --cpu=20 \
  --gpu=1 \
  --gpu-type=nvidia-rtx-pro-6000 \
  --no-cpu-throttling \
  --no-gpu-zonal-redundancy \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=3600 \
  --startup-probe=tcpSocket.port=8000,initialDelaySeconds=0,periodSeconds=10,failureThreshold=180 \
  --clear-volumes \
  --clear-volume-mounts \
  --add-volume=name=model-cache,type=cloud-storage,bucket=$PROJECT-lmstudio-models \
  --add-volume-mount=volume=model-cache,mount-path=/root/.cache/huggingface \
  --set-env-vars=MODEL_ID=google/gemma-4-31B-it,MODEL_CONTEXT_LENGTH=65536,GPU_MEMORY_UTILIZATION=0.9,LMSTUDIO_REASONING_PARSER=gemma4,LMSTUDIO_TOOL_CALL_PARSER=gemma4,LMSTUDIO_CHAT_TEMPLATE=examples/tool_chat_template_gemma4.jinja,LMSTUDIO_WATCHDOG_TIMEOUT_SECONDS=1500,LMSTUDIO_WATCHDOG_POLL_SECONDS=10
```

Note the image path is `micro_cosmos/vllm`, not `micro_cosmos/lmstudio` — the two
engines build to separate Artifact Registry image names even though they
deploy the same Cloud Run **service** name. **Same
`MODEL_REASONING`/`MODEL_FAST` alignment caveat as the individual-deploy
section above applies here too** — this manual command doesn't update
`micro-cosmos-web`'s config for you. Add `,HF_TOKEN=<your-token>` to the
`--set-env-vars` list if you want one (optional — see the config reference
table above); the deploy script's automatic redaction-on-failure doesn't
apply to a manual `gcloud` command, so be extra mindful not to paste this
command with a real token value into a shared terminal/log.

### Micro-Cosmos web app

`GOOGLE_GENAI_USE_VERTEXAI=FALSE` below is intentionally hardcoded, not a placeholder —
Vertex AI is a planned third `LLM_ENGINE` option, not yet implemented (no `Settings` fields
read it today), so `GOOGLE_CLOUD_LOCATION` is deliberately omitted too. See
[`product-roadmap-markup/Micro-Cosmos-with-LLMGateway-for-VertexAI-GCP.md`](../product-roadmap-markup/Micro-Cosmos-with-LLMGateway-for-VertexAI-GCP.md).

```bash
gcloud storage rsync examples/ gs://$PROJECT-micro-cosmos-examples --recursive --project=$PROJECT

gcloud run deploy micro-cosmos-web \
  --image=europe-west4-docker.pkg.dev/$PROJECT/micro-cosmos/web:latest \
  --region=europe-west4 \
  --allow-unauthenticated \
  --ingress=internal-and-cloud-load-balancing \
  --set-env-vars=\
GOOGLE_GENAI_USE_VERTEXAI=FALSE,\
GOOGLE_CLOUD_PROJECT=$PROJECT,\
LLM_BASE_URL=https://micro-cosmos-llmgateway-xxxx.a.run.app/v1,\
LLM_API_KEY=lm-studio,\
MODEL_REASONING=google/gemma-4-e4b,\
MODEL_FAST=google/gemma-4-e4b,\
MODEL_CONTEXT_LENGTH=131072,\
LLM_ENGINE=lmstudio,\
MODEL_TEMPERATURE=0.2,\
LLM_TIMEOUT=28800,\
SKIP_LLM=false,\
RUNS_DIR=/app/runs,\
DEMO_USERNAME=<set-a-real-username>,\
DEMO_PASSWORD=<set-a-real-password>,\
SESSION_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))'),\
SESSION_HTTPS_ONLY=true \
  --service-account=micro-cosmos-runtime@$PROJECT.iam.gserviceaccount.com \
  --memory=5Gi \
  --cpu=4 \
  --concurrency=10 \
  --min-instances=1 \
  --max-instances=3 \
  --session-affinity \
  --timeout=3600 \
  --clear-volumes \
  --clear-volume-mounts \
  --add-volume=name=examples-data,type=cloud-storage,bucket=$PROJECT-micro-cosmos-examples \
  --add-volume-mount=volume=examples-data,mount-path=/app/examples \
  --add-volume=name=runs-data,type=cloud-storage,bucket=$PROJECT-micro-cosmos-runs \
  --add-volume-mount=volume=runs-data,mount-path=/app/runs
```

Both buckets must exist (`gcloud storage buckets create gs://$PROJECT-micro-cosmos-examples --location=europe-west4 --uniform-bucket-level-access`, and the same command with `gs://$PROJECT-micro-cosmos-runs`) and grant `micro-cosmos-runtime` `roles/storage.objectAdmin` on each before the first deploy — see [Examples gallery](#examples-gallery--mounted-matching-local-docker-compose) and [Run artifacts](#run-artifacts--mounted-matching-local-docker-compose) above.

**This example matches the LM Studio GPU service above.** If you deployed
the vLLM service instead, change `MODEL_REASONING`/`MODEL_FAST` to
`google/gemma-4-31B-it` (or whatever you set `MODEL_REASONING` to when
deploying vLLM) **and set `LLM_ENGINE=vllm`** — `micro_cosmos/settings.py`'s
`build_llm()` reads this to decide whether it's safe to send LM Studio's
`num_ctx` extra param (vLLM's stricter API rejects it outright). See
[GPU engine choice](#gpu-engine-choice--lm-studio-vs-vllm) for the full
reasoning.

`--ingress=internal-and-cloud-load-balancing` requires the external Load
Balancer from `setup_micro_cosmos_web_lb.py` to already exist (see "Web UI
access" above) — without an LB routing traffic to it, this ingress value
just means nothing external can reach the service (same as plain
`internal`, since there's no LB in the picture).

### External Load Balancer for `micro-cosmos-web`

```bash
gcloud compute addresses create micro-cosmos-web-lb-ip \
  --network-tier=PREMIUM --ip-version=IPV4 --global --project=$PROJECT

gcloud compute network-endpoint-groups create micro-cosmos-web-neg \
  --region=europe-west4 --network-endpoint-type=serverless \
  --cloud-run-service=micro-cosmos-web --project=$PROJECT

gcloud compute backend-services create micro-cosmos-web-backend \
  --load-balancing-scheme=EXTERNAL_MANAGED --global --project=$PROJECT

gcloud compute backend-services add-backend micro-cosmos-web-backend \
  --global --network-endpoint-group=micro-cosmos-web-neg \
  --network-endpoint-group-region=europe-west4 --project=$PROJECT

gcloud compute url-maps create micro-cosmos-web-urlmap \
  --default-service=micro-cosmos-web-backend --project=$PROJECT

gcloud compute ssl-certificates create micro-cosmos-web-cert \
  --domains=app.micro-cosmos.tools --global --project=$PROJECT

gcloud compute target-https-proxies create micro-cosmos-web-https-proxy \
  --ssl-certificates=micro-cosmos-web-cert --url-map=micro-cosmos-web-urlmap \
  --project=$PROJECT

gcloud compute forwarding-rules create micro-cosmos-web-https-rule \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM \
  --address=micro-cosmos-web-lb-ip --target-https-proxy=micro-cosmos-web-https-proxy \
  --global --ports=443 --project=$PROJECT
```

`setup_micro_cosmos_web_lb.py` runs all of the above (plus an HTTP→HTTPS
redirect on port 80) idempotently in one command — see "Web UI access"
above for the full walkthrough including the DNS and SSL cert steps this
can't do for you.

---

## Operational notes

- **GPU idle cost.** `LMSTUDIO_MIN_INSTANCES=0` (the default) scales the GPU
  service to zero when not in use — no GPU billing while idle, but the first
  request after a cold start waits for the container to boot, pull/verify the
  model, and load it onto the GPU (several minutes, since `lms load` itself
  takes time even with cached weights). Set `LMSTUDIO_MIN_INSTANCES=1` to keep
  one GPU instance warm if you're running the pipeline frequently — this bills
  continuously for GPU time.
- **Model persistence.** Model weights live in `gs://$PROJECT-lmstudio-models`,
  mounted at `/root/.lmstudio/models` via GCS FUSE. Redeploying the
  LLMGateway service or scaling to zero and back does not re-download the model.
- **Single-GPU concurrency.** `LMSTUDIO_CONCURRENCY=1` and
  `LMSTUDIO_MAX_INSTANCES=1` are intentional — one L4 GPU serves one
  generation at a time. Raise `LMSTUDIO_MAX_INSTANCES` only if you have GPU
  quota for multiple concurrent instances (each loads its own copy of the
  model into its own GPU).
- **Run state is in-memory.** If the `micro-cosmos-web` Cloud Run instance
  restarts, active runs are lost. For production persistence, back the `RUNS`
  dict with Firestore or Cloud SQL.
- **Swapping models.** Change `MODEL_REASONING` / `MODEL_FAST` and redeploy
  `micro-cosmos-llmgateway` — the container pulls the new model into the same
  mounted bucket on next cold start.
- **Logs:**
  ```bash
  gcloud run services logs read micro-cosmos-web --region=europe-west4 --limit=100
  gcloud run services logs read micro-cosmos-llmgateway --region=europe-west4 --limit=100
  ```

### Logging — `MICRO_COSMOS_LOG_LEVEL`

`micro-cosmos-web`'s Python logging is configured once, on import, in
`micro_cosmos/__init__.py` — a single handler on the `micro-cosmos` logger that every
module's own logger (`micro_cosmos.orchestration.driver`, `micro_cosmos.settings`,
`micro_cosmos.retrieval.embedder`, `micro_cosmos.retrieval.chat`, `micro_cosmos.diagnostics`,
etc.) inherits with no extra wiring. That handler writes to stderr, which
both `docker compose logs` and `gcloud run services logs read` capture
automatically — no separate log-shipping config needed in either
environment. Set the level with `MICRO_COSMOS_LOG_LEVEL` (docker-compose: add to
`.env`/`docker-compose.yml`; Cloud Run: `export MICRO_COSMOS_LOG_LEVEL=DEBUG`
before running `deploy.py`, or add it to `deploy_cloudrun-micro-cosmos-app.py`'s
`--set-env-vars`). Any standard Python `logging` level name works:

| Level | Default? | What you see |
|---|---|---|
| `DEBUG` | | Everything below, plus a line for every individual poll of the LM Studio/vLLM readiness check (`GET <url> -> <status>`) even when nothing changed — verbose, meant for actively debugging a stuck/slow run |
| `INFO` | **yes** | Composed URLs and `200 OK` responses for every place `micro-cosmos-web` talks to the GPU service: the readiness check's `native_url`/`openai_url` (`_wait_for_llm_ready()` in `driver.py`), each agent's real LLM calls (`build_llm()` in `settings.py`), embedding calls (`embedder.py`), and the ASK tab's completion calls (`chat.py`) — model, `api_base`, and whether an API key is configured (never the key value itself) |
| `WARNING` | | Non-fatal issues: 401s from a missing/wrong `LLM_API_KEY`, the readiness check timing out, gate retries, stale-doc flags — see `micro_cosmos/diagnostics.py`'s own severity tiers |
| `ERROR` | | Pipeline-halting failures only: agent crashes, missing credentials, hallucinated-reference rejections |

This is the same knob whether you're debugging a stuck run locally or one
on Cloud Run — a run that seems parked at "[LLMGateway] waiting for `<model>`
to load…" with no visible progress is exactly the case `INFO` was expanded
for (2026-07-13): a 401 there now surfaces as a `WARNING` line naming
`LLM_API_KEY` explicitly, instead of silently retrying until the full
`LMSTUDIO_READY_TIMEOUT_SECONDS` with nothing in the logs to explain why.

---

## Superseded

This replaces the previous Compute Engine + Cloud Run architecture documented
in `cloudrun-cloudcompute.md`. That doc is kept for reference only; do not use
it for new deployments.
