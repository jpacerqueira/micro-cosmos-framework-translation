# Micro-Cosmos Terraform Power

Kiro.dev Power for reviewing and generating Terraform HCL in the context of Micro-Cosmos translated microservices.

## What it does

- Reviews HCL modules for microservice coverage (one module per bounded context)
- Warns when flat-resource patterns replace proper module decomposition
- Enforces security baseline: encryption, least-privilege IAM, secret sourcing
- Aligns HCL review with Micro-Cosmos Gate 5 PR approval requirements
- Provides pipeline phase traceability via standard resource tags

## Installation in Kiro

Install this power from the Kiro.dev marketplace or copy the `POWER.md` file into your Kiro powers directory.

## When to activate

- You are reviewing or writing Terraform for a microservice translated by Micro-Cosmos
- You want to validate that each Cartographer bounded context has its own module
- You are running the Gate 5 infrastructure checklist
- You need to audit security posture before a production apply

## Microservice coverage check

This power always checks whether each bounded context from the Micro-Cosmos Cartographer output has a dedicated `modules/<context>/` directory. A missing module is always a **MAJOR** finding.

## Tests

```bash
npm install
npm test
```
