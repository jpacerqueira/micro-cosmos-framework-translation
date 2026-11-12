output "aks_cluster_name" {
  value = module.aks.cluster_name
}

output "aks_resource_group" {
  value = module.aks.resource_group_name
}

output "aks_oidc_issuer_url" {
  value = module.aks.oidc_issuer_url
}

output "acr_login_server" {
  value = module.acr.login_server
}

output "keyvault_uri" {
  value = module.keyvault.vault_uri
}

output "postgres_fqdn" {
  value     = module.postgres.fqdn
  sensitive = false
}

output "storage_account_name" {
  value = module.storage.account_name
}

output "log_analytics_workspace_id" {
  value = module.observability.log_analytics_workspace_id
}

output "eventhubs_namespace" {
  value = module.eventhubs.namespace
}

output "azuread_app_client_id" {
  value = module.azuread_app.client_id
}
