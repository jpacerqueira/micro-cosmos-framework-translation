# 02-kubernetes-istio - Cluster manifests

Deploys the Customer-Application-Name workloads on AKS with Istio service mesh,
implementing the SAD's Application Architecture View: WebApp BFF (GraphQL/REST),
microservices for User Auth, Property Allocation/Valuation, VDR Ingestion,
Workflow, Search; the platform layer (NATS JetStream cluster, Axon Server),
the edge gateway, and the OpenTelemetry collector that ships traces/metrics/logs
to Azure Application Insights.

## Layout

```
02-kubernetes-istio/
├── 00-namespaces/   # Namespaces with Istio injection
├── 10-istio/        # IstioOperator + mTLS STRICT + edge gateway
├── 20-platform/     # NATS, Axon Server, KV CSI SecretProviderClass
├── 30-services/     # All Spring Boot services + UI
├── 40-observability/# OTel collector
├── 50-policies/     # Cluster-wide policies (Gatekeeper / Kyverno)
└── kustomization.yaml
```

## Apply

```bash
# 1. Connect kubectl to AKS
az aks get-credentials -g <rg-platform> -n aks-can-<env>-uks

# 2. Install Istio
istioctl install -f 10-istio/istio-operator.yaml -y

# 3. Apply everything else
kubectl apply -k .
```

## Mesh design

- **mTLS STRICT** mesh-wide. PeerAuthentication enforces it.
- **Default-deny** AuthorizationPolicies in every app namespace.
  Each service must opt-in with an explicit ALLOW policy.
- **Edge gateway** terminates TLS and validates Azure AD JWTs before
  forwarding to internal services.
- **DestinationRule** per service sets connection pools and outlier detection.
- **NetworkPolicy** as a second layer alongside Istio AuthZ.

## Substitutions

Replace these placeholders before applying (use `envsubst` or kustomize):

| Placeholder | Source |
|---|---|
| `<ACR_LOGIN_SERVER>` | `terraform output acr_login_server` |
| `<PG_FQDN>` | `terraform output postgres_fqdn` |
| `<TENANT_ID>` | Azure AD tenant ID |
| `<APP_CLIENT_ID>` | `terraform output azuread_app_client_id` |
| `<KEYVAULT_NAME>` | from KV URI |
| `<WORKLOAD_IDENTITY_CLIENT_ID>` | the user-assigned MI client ID |
| `<STORAGE_ACCOUNT_NAME>` | `terraform output storage_account_name` |
