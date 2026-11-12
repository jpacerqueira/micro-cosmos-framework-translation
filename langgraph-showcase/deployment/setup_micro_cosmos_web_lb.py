"""Provision an external Application Load Balancer in front of micro-cosmos-web.

This project's org policy (constraints/run.allowedIngress) blocks Cloud
Run's default public "all" ingress value, and a per-project exception for
it was declined. The org-compliant way to make micro-cosmos-web
internet-reachable is `--ingress=internal-and-cloud-load-balancing` (see
deploy_cloudrun-micro-cosmos-app.py) plus a real external Application Load
Balancer using a serverless NEG — that's what this script provisions.

This is create-once infrastructure (a static IP, NEG, backend service, URL
map, SSL certificate, two proxies, two forwarding rules) — unlike the two
deploy_cloudrun-*.py scripts, it is NOT meant to run on every app deploy.
Run it once per environment; every step is idempotent (create-if-missing),
so re-running is safe if a later step failed partway through.

Usage:
    export PROJECT_ID=my-project-id
    export PROJECT=$PROJECT_ID
    export MICRO_COSMOS_LB_DOMAIN=app.micro-cosmos.tools   # required — the domain
                                                   # you'll point at the LB
    python deployment/setup_micro_cosmos_web_lb.py

Prerequisites:
    - micro-cosmos-web already deployed at least once (the serverless NEG needs
      an existing Cloud Run service to point at)
    - You control DNS for MICRO_COSMOS_LB_DOMAIN. This script cannot create the
      DNS record for you — it has no access to your domain's DNS provider
      (unless it's Google Cloud DNS; this script doesn't assume that). It
      prints the reserved static IP and the exact A record to create.
    - The Google-managed SSL certificate only provisions (reaches ACTIVE)
      after that DNS record resolves and Google validates it — this can
      take up to ~60 minutes after the record propagates. Check status:
        gcloud compute ssl-certificates describe micro-cosmos-web-cert \\
          --global --project=$PROJECT --format="value(managed.status)"
    - After the certificate is ACTIVE, redeploy micro-cosmos-web
      (deploy_cloudrun-micro-cosmos-app.py) so it picks up
      --ingress=internal-and-cloud-load-balancing.

Not yet exercised against a live deploy — flag syntax is based on Google's
current load-balancing documentation, not verified against this project.
If a step errors on flag syntax, check `gcloud compute <resource> create
--help` for the current exact syntax rather than assuming the whole
approach is wrong.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_REGION = "europe-west4"     # must match micro-cosmos-web's region
SERVICE_NAME = "micro-cosmos-web"

IP_NAME = "micro-cosmos-web-lb-ip"
NEG_NAME = "micro-cosmos-web-neg"
BACKEND_NAME = "micro-cosmos-web-backend"
URL_MAP_NAME = "micro-cosmos-web-urlmap"
CERT_NAME = "micro-cosmos-web-cert"
HTTPS_PROXY_NAME = "micro-cosmos-web-https-proxy"
HTTPS_RULE_NAME = "micro-cosmos-web-https-rule"
HTTP_REDIRECT_URL_MAP_NAME = "micro-cosmos-web-http-redirect"
HTTP_PROXY_NAME = "micro-cosmos-web-http-proxy"
HTTP_RULE_NAME = "micro-cosmos-web-http-rule"


# ── helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], **kwargs) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"\n  Command failed: {' '.join(cmd)}", file=sys.stderr)
        if result.stdout.strip():
            print(f"  --- stdout ---\n{result.stdout}", file=sys.stderr)
        if result.stderr.strip():
            print(f"  --- stderr ---\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result.stdout.strip()


def _ensure(create_cmd: list[str], label: str) -> None:
    try:
        run(create_cmd)
        print(f"  {label} created.")
    except subprocess.CalledProcessError:
        print(f"  {label} already exists — skipping.")


def ensure_static_ip(project: str) -> None:
    _ensure([
        "gcloud", "compute", "addresses", "create", IP_NAME,
        "--network-tier=PREMIUM",
        "--ip-version=IPV4",
        "--global",
        f"--project={project}",
    ], f"Static IP '{IP_NAME}'")


def ensure_serverless_neg(project: str, region: str) -> None:
    _ensure([
        "gcloud", "compute", "network-endpoint-groups", "create", NEG_NAME,
        f"--region={region}",
        "--network-endpoint-type=serverless",
        f"--cloud-run-service={SERVICE_NAME}",
        f"--project={project}",
    ], f"Serverless NEG '{NEG_NAME}'")


def ensure_backend_service(project: str, region: str) -> None:
    _ensure([
        "gcloud", "compute", "backend-services", "create", BACKEND_NAME,
        "--load-balancing-scheme=EXTERNAL_MANAGED",
        "--global",
        f"--project={project}",
    ], f"Backend service '{BACKEND_NAME}'")

    # Adding the same backend twice is an error, not idempotent — check first.
    existing = run([
        "gcloud", "compute", "backend-services", "describe", BACKEND_NAME,
        "--global", f"--project={project}", "--format=value(backends[].group)",
    ])
    if NEG_NAME in existing:
        print(f"  NEG '{NEG_NAME}' already attached to '{BACKEND_NAME}' — skipping.")
        return
    run([
        "gcloud", "compute", "backend-services", "add-backend", BACKEND_NAME,
        "--global",
        f"--network-endpoint-group={NEG_NAME}",
        f"--network-endpoint-group-region={region}",
        f"--project={project}",
    ])
    print(f"  NEG '{NEG_NAME}' attached to backend service '{BACKEND_NAME}'.")


def ensure_url_map(project: str) -> None:
    _ensure([
        "gcloud", "compute", "url-maps", "create", URL_MAP_NAME,
        f"--default-service={BACKEND_NAME}",
        f"--project={project}",
    ], f"URL map '{URL_MAP_NAME}'")


def ensure_ssl_certificate(project: str, domain: str) -> None:
    _ensure([
        "gcloud", "compute", "ssl-certificates", "create", CERT_NAME,
        f"--domains={domain}",
        "--global",
        f"--project={project}",
    ], f"Google-managed SSL certificate '{CERT_NAME}' for {domain}")


def ensure_https_proxy(project: str) -> None:
    _ensure([
        "gcloud", "compute", "target-https-proxies", "create", HTTPS_PROXY_NAME,
        f"--ssl-certificates={CERT_NAME}",
        f"--url-map={URL_MAP_NAME}",
        f"--project={project}",
    ], f"Target HTTPS proxy '{HTTPS_PROXY_NAME}'")


def ensure_https_forwarding_rule(project: str) -> None:
    _ensure([
        "gcloud", "compute", "forwarding-rules", "create", HTTPS_RULE_NAME,
        "--load-balancing-scheme=EXTERNAL_MANAGED",
        "--network-tier=PREMIUM",
        f"--address={IP_NAME}",
        f"--target-https-proxy={HTTPS_PROXY_NAME}",
        "--global",
        "--ports=443",
        f"--project={project}",
    ], f"Global forwarding rule '{HTTPS_RULE_NAME}' (port 443)")


def ensure_http_redirect(project: str) -> None:
    """So http://<domain> redirects to https:// instead of just failing —
    standard practice, shares the same static IP as the HTTPS rule. There is
    no direct gcloud flag for this (confirmed against Google's docs) — a
    URL map redirect is only configurable via YAML import."""
    redirect_yaml = (
        f"name: {HTTP_REDIRECT_URL_MAP_NAME}\n"
        "defaultUrlRedirect:\n"
        "  httpsRedirect: True\n"
        "  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT\n"
        "  stripQuery: False\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "redirect.yaml"
        yaml_path.write_text(redirect_yaml)
        _ensure([
            "gcloud", "compute", "url-maps", "import", HTTP_REDIRECT_URL_MAP_NAME,
            f"--source={yaml_path}",
            "--global",
            f"--project={project}",
            "--quiet",
        ], f"HTTP→HTTPS redirect URL map '{HTTP_REDIRECT_URL_MAP_NAME}'")

    _ensure([
        "gcloud", "compute", "target-http-proxies", "create", HTTP_PROXY_NAME,
        f"--url-map={HTTP_REDIRECT_URL_MAP_NAME}",
        f"--project={project}",
    ], f"Target HTTP proxy '{HTTP_PROXY_NAME}'")

    _ensure([
        "gcloud", "compute", "forwarding-rules", "create", HTTP_RULE_NAME,
        "--load-balancing-scheme=EXTERNAL_MANAGED",
        "--network-tier=PREMIUM",
        f"--address={IP_NAME}",
        f"--target-http-proxy={HTTP_PROXY_NAME}",
        "--global",
        "--ports=80",
        f"--project={project}",
    ], f"Global forwarding rule '{HTTP_RULE_NAME}' (port 80, redirects to HTTPS)")


# ── reusable entry point (called directly or imported) ──────────────────────

def setup_load_balancer(*, project: str, region: str | None = None, domain: str | None = None) -> str:
    """Provision the external Application Load Balancer for micro-cosmos-web.
    Returns the reserved static IP address."""
    region = region or os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_REGION)
    domain = domain or os.environ.get("MICRO_COSMOS_LB_DOMAIN")
    if not domain:
        print("Set MICRO_COSMOS_LB_DOMAIN to the domain you'll point at the load "
              "balancer (e.g. app.micro-cosmos.tools).", file=sys.stderr)
        sys.exit(1)

    print(f"[1/8] Reserving static IP '{IP_NAME}'…")
    ensure_static_ip(project)

    print(f"[2/8] Ensuring serverless NEG for '{SERVICE_NAME}' in {region}…")
    ensure_serverless_neg(project, region)

    print(f"[3/8] Ensuring backend service '{BACKEND_NAME}'…")
    ensure_backend_service(project, region)

    print(f"[4/8] Ensuring URL map '{URL_MAP_NAME}'…")
    ensure_url_map(project)

    print(f"[5/8] Ensuring Google-managed SSL certificate for {domain}…")
    ensure_ssl_certificate(project, domain)

    print(f"[6/8] Ensuring target HTTPS proxy '{HTTPS_PROXY_NAME}'…")
    ensure_https_proxy(project)

    print("[7/8] Ensuring HTTPS forwarding rule (port 443)…")
    ensure_https_forwarding_rule(project)

    print("[8/8] Ensuring HTTP→HTTPS redirect (port 80)…")
    ensure_http_redirect(project)

    ip_address = run([
        "gcloud", "compute", "addresses", "describe", IP_NAME,
        "--global", f"--project={project}", "--format=value(address)",
    ])

    print(f"\n  Load Balancer static IP: {ip_address}")
    print(f"  Create this DNS record with your domain's DNS provider:")
    print(f"    {domain}.  A  {ip_address}")
    print(
        "\n  The SSL certificate will not become ACTIVE until that record\n"
        "  resolves and Google validates it (can take up to ~60 minutes\n"
        "  after DNS propagates). Check status:\n"
        f"    gcloud compute ssl-certificates describe {CERT_NAME} --global "
        f"--project={project} --format='value(managed.status)'\n"
        "\n  Once ACTIVE, redeploy micro-cosmos-web so it picks up\n"
        "  --ingress=internal-and-cloud-load-balancing:\n"
        "    python deployment/deploy_cloudrun-micro-cosmos-app.py"
    )
    return ip_address


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    project = (
        os.environ.get("PROJECT")
        or os.environ.get("PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    if not project:
        print("Set PROJECT_ID (or PROJECT, or GOOGLE_CLOUD_PROJECT) to your GCP project ID", file=sys.stderr)
        sys.exit(1)

    setup_load_balancer(project=project)


if __name__ == "__main__":
    main()
