# 01-terraform - Infrastructure as Code

Implements the Azure footprint described in the Solution Architecture
Document: AKS (Workload Identity, OIDC, Cilium dataplane), ACR, Key Vault,
PostgreSQL Flexible Server with the Citus extension, GPv2 storage with
lifecycle management, Log Analytics + Application Insights, Event Hubs
(Kafka-compatible) for the ULI durable bridge, and an Azure AD app
registration for the WebApp/API.

## Layout

```
01-terraform/
├── main.tf            # Root module - composes everything
├── variables.tf
├── outputs.tf
├── modules/
│   ├── network/       # VNet, subnets, NAT, private DNS
│   ├── aks/           # AKS cluster + node pools
│   ├── acr/           # Premium ACR
│   ├── keyvault/      # Key Vault + workload identity federation
│   ├── postgres/      # PG Flexible Server + Citus
│   ├── storage/       # GPv2 + lifecycle
│   ├── observability/ # LAW + AppInsights + alerts
│   ├── eventhubs/     # Kafka-compatible namespace
│   └── azuread_app/   # AAD app registration
└── envs/
    ├── dev/           # dev.tfvars + backend.hcl
    ├── test/
    └── prod/
```

## Usage

```bash
cd 01-terraform
terraform init -backend-config=envs/dev/backend.hcl
terraform plan  -var-file=envs/dev/dev.tfvars
terraform apply -var-file=envs/dev/dev.tfvars
```

## Conventions

- All resources tagged with `application`, `environment`, `owner`, `cost_centre`.
- Naming follows `<resource>-<app>-<env>-<region>` (e.g. `aks-can-dev-uks`).
- Public network access disabled where the resource supports private endpoints.
- TLS 1.2 minimum, public access deny-by-default, OAuth-only on storage.
- Diagnostic settings stream all resource logs to the central Log Analytics workspace.
