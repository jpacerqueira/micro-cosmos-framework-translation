# Requirements — Micro-Cosmos Terraform Power

## REQ-1: Microservice Module Coverage Check
The power MUST warn when Terraform HCL does not define a dedicated module per Micro-Cosmos bounded context. The warning MUST be severity MAJOR and include the list of contexts without modules.

## REQ-2: Security Baseline Enforcement
The power MUST verify: remote state with encryption, no hardcoded secrets in variables or `.tfvars`, KMS-managed keys, dedicated VPC, and least-privilege IAM. Each violation MUST be classified with severity (BLOCKER / MAJOR / MINOR).

## REQ-3: Gate 5 PR Checklist
The power MUST emit the Gate 5 infrastructure checklist covering: module coverage, secrets, encryption, IAM, version pinning, `.terraform.lock.hcl`, policy scan results, and plan artifact review.

## REQ-4: Pipeline Phase Traceability
The power MUST recommend resource tagging with `alchemy_run_id`, `bounded_context`, `source_language`, `target_language`, `environment` for every module.

## REQ-5: Validation Plan
Every review MUST include exact CLI commands: `terraform fmt -check -recursive`, `terraform validate`, `trivy config .`, `checkov -d .`.

## REQ-6: Rollback Safety
For any destructive or state-mutating recommendation the power MUST include rollback instructions and require a `terraform plan -destroy` review before proceed.

## REQ-7: Module Layout Generation
The power MUST generate standard module layouts (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `examples/minimal/`, `examples/complete/`) for a given bounded context name.

## REQ-8: Version Pinning
The power MUST enforce `required_version = "~> 1.9"` (or higher) and provider version constraints in every module's `versions.tf`.

## REQ-9: Micro-Cosmos Context Awareness
The power MUST understand Micro-Cosmos pipeline phases (Observer, Cartographer, Architect, Security, Code Writer, Writer, PR Reviewer, Gate 5) and contextualise findings to the phase that generated or will consume the HCL.

## REQ-10: Diagnosable Failure Categories
The power MUST include the Terraform failure category routing table (identity churn, blast radius, CI drift, compliance gap, state corruption, provider upgrade risk) adapted for Micro-Cosmos microservice patterns.
