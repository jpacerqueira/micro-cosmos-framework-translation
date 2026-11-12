---
name: "micro-cosmos-terraform"
displayName: "Micro-Cosmos Terraform"
author: "Micro-Cosmos"
description: "Use when reviewing, writing, or validating Terraform HCL for Micro-Cosmos-translated microservices. Enforces modular microservice layout, security hygiene, and compatibility guards across the full Observer→Gate5 pipeline."
keywords: ["terraform", "hcl", "iac", "microservice", "module", "security", "micro-cosmos", "pipeline", "review", "state", "provider", "encryption", "least-privilege", "compatibility"]
---

# Micro-Cosmos Terraform Power

Diagnose-first Terraform review for Micro-Cosmos translated microservices. Applies the full terraform-skill discipline with Micro-Cosmos-specific conventions: modular microservice layout, security gate alignment, and pipeline-phase traceability.

## Response Contract

Every HCL review or generation must include:

1. **Execution context** — Terraform/OpenTofu version floor, provider(s), backend, CI path.
2. **Microservice module coverage** — **WARN** if the HCL does not follow a per-bounded-context module layout. Missing module separation is always flagged.
3. **Risk category addressed** — one or more of: identity churn, secret exposure, blast radius, CI drift, compliance gap, state corruption, provider upgrade risk.
4. **Validation plan** — exact commands: `terraform fmt -check`, `terraform validate`, `trivy config .`, `checkov -d .`.
5. **Rollback notes** — for any destructive or state-mutating change.

Never recommend direct production apply without a reviewed plan artifact and approval.

## Workflow

1. **Capture Micro-Cosmos context** — which pipeline phase produced or will use this HCL? (Observer infra, per-service module, composition layer.)
2. **Check microservice coverage** — each bounded context identified by the Cartographer MUST have its own Terraform module. Warn if flat resources are used instead.
3. **Diagnose failure mode** using the routing table below.
4. **Review or generate HCL** following module layout, variable contracts, and security rules.
5. **Emit Response Contract.**

## Microservice Module Coverage — MANDATORY CHECK

For every Micro-Cosmos run the Cartographer defines bounded contexts. Each context must map to a dedicated Terraform module:

```
modules/
├── <context-a>/          # one module per bounded context
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
├── <context-b>/
│   └── ...
environments/
├── prod/
│   ├── main.tf           # composes modules/
│   └── terraform.tfvars
└── staging/
    └── ...
```

**⚠ WARN** if any of the following are present:
- Resources defined directly in `environments/` without a module call
- A single monolithic `main.tf` containing resources for multiple bounded contexts
- Module directory names that do not correspond to a bounded context from `bounded_context_map.json`
- No `modules/` directory at all

Include this warning in the review findings with severity **MAJOR**.

## Diagnose Before You Generate

| Failure category | Symptoms | Action |
|---|---|---|
| **Microservice module missing** | Flat resources, no `modules/` dir, multi-context `main.tf` | WARN MAJOR — propose per-context module split |
| **Identity churn** | `count` index instability, missing `moved` blocks after rename | Add `moved` blocks; switch to `for_each` |
| **Secret exposure** | Hardcoded values, secrets in `.tfvars`, sensitive outputs unmarked | Source from secret manager; use `sensitive = true` and `write_only` on 1.11+ |
| **Blast radius** | Prod/staging in same state, oversized stacks | Split state per environment and per component |
| **CI drift** | No `.terraform.lock.hcl`, apply without plan artifact | Pin versions; commit lock file |
| **Compliance gap** | No `trivy config .` or `checkov -d .` stage | Add security policy gate before apply |
| **Encryption absent** | Storage without encryption, KMS key not specified | Enforce `encrypt = true`, specify KMS key ARN/ID |
| **Least-privilege violated** | IAM with `*` actions/resources, overly broad SGs | Scope to minimum actions and resources |
| **Provider upgrade risk** | Unpinned providers, breaking-change bump without lock | Pin to `~> MAJOR.0`; upgrade in separate PR |

## Module Conventions for Micro-Cosmos Microservices

Each translated bounded context gets a dedicated module with:

```hcl
# modules/<context>/versions.tf
terraform {
  required_version = "~> 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

# modules/<context>/variables.tf
variable "environment" {
  description = "Deployment environment (prod | staging | dev)"
  type        = string
  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "environment must be prod, staging, or dev."
  }
}

variable "context_name" {
  description = "Bounded context name from Micro-Cosmos Cartographer output"
  type        = string
}
```

**Variable contract rules:**
- Every variable has `description` and explicit `type`
- Secrets use `sensitive = true` (or `write_only` on 1.11+)
- No `map(any)` — use typed `object({})` with `optional()` on 1.3+

**Output contract rules:**
- Every output has `description`
- Sensitive outputs marked `sensitive = true`
- Expose stable subsets only — never expose whole provider objects

## Security Baseline

**Always enforce:**
- Remote state with encryption and locking (`encrypt = true`, `use_lockfile = true` on 1.10+)
- KMS-managed encryption keys for all storage resources
- Dedicated VPC per environment — never use default VPC
- Security groups: separate `aws_vpc_security_group_{ingress,egress}_rule` resources (not inline)
- No open `0.0.0.0/0` ingress except explicit load-balancer front ends
- Secrets sourced from AWS Secrets Manager / Azure Key Vault / GCP Secret Manager

**Pre-apply checks (embed in CI):**
```bash
terraform fmt -check -recursive
terraform validate
trivy config . --exit-code 1
checkov -d . --compact
```

## Pipeline Phase Traceability

Each Terraform module should carry tags/labels that trace back to the Micro-Cosmos run:

```hcl
# In modules/<context>/main.tf locals block
locals {
  common_tags = {
    micro_cosmos_run_id      = var.micro_cosmos_run_id
    bounded_context     = var.context_name
    source_language     = var.source_lang
    target_language     = var.target_lang
    environment         = var.environment
  }
}
```

Add `micro_cosmos_run_id` as a required variable in every module so cost attribution and drift investigation can always trace resources back to the originating Micro-Cosmos translation run.

## PR Gate Alignment (Gate 5)

Terraform HCL review is part of the Gate 5 PR review. For a PR to pass Gate 5 on the infrastructure side:

- [ ] Each bounded context has its own module under `modules/`
- [ ] No hardcoded secrets or sensitive defaults
- [ ] Encryption enabled on all storage and state backends
- [ ] IAM roles scoped to least-privilege
- [ ] Providers and runtime version-pinned in `versions.tf`
- [ ] `.terraform.lock.hcl` committed
- [ ] `trivy config .` and `checkov -d .` pass clean
- [ ] Plan artifact reviewed before apply

If any item is unchecked, the Gate 5 PR reviewer must mark it **BLOCKER** before merge.

## Common Workflows

### Review existing HCL for microservice coverage
1. Read all `.tf` files in the repository root and `environments/`
2. List bounded contexts from `bounded_context_map.json` (if available)
3. Check each context has a corresponding `modules/<context>/` directory
4. Report WARN MAJOR for any context without a dedicated module
5. Emit Response Contract with validation commands

### Generate a new bounded-context module
1. Identify context name from Cartographer output
2. Create `modules/<context-name>/` with: `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`
3. Add `micro_cosmos_run_id`, `context_name`, `environment` as required variables
4. Add `common_tags` local block
5. Write `examples/minimal/` and `examples/complete/` for documentation and test fixtures
6. Emit Response Contract

### Security review before apply
1. Run `terraform fmt -check -recursive`
2. Run `terraform validate`
3. Run `trivy config .` — fail on HIGH or CRITICAL
4. Run `checkov -d .` — fail on HIGH severity
5. Review plan artifact for destroy actions (`plan -destroy` first)
6. Emit Response Contract with every finding classified by risk category
