###############################################################################
# Key Vault - private-endpoint, RBAC mode, federated identity for AKS workloads.
###############################################################################

variable "resource_group_name"            { type = string }
variable "location"                       { type = string }
variable "name_prefix"                    { type = string }
variable "tenant_id"                      { type = string }
variable "aks_kubelet_identity_object_id" { type = string }
variable "aks_oidc_issuer_url"            { type = string }
variable "workload_identity_namespace"    { type = string }
variable "workload_identity_sa"           { type = string }
variable "private_endpoint_subnet_id"     { type = string }
variable "tags"                           { type = map(string) }

resource "azurerm_key_vault" "this" {
  name                          = "kv-${substr(replace(var.name_prefix, "-", ""), 0, 18)}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  enable_rbac_authorization     = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = false

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
  }

  tags = var.tags
}

# AKS kubelet identity gets read access to secrets via CSI driver.
resource "azurerm_role_assignment" "aks_kvsec_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.aks_kubelet_identity_object_id
}

# Dedicated workload identity used by Spring Boot pods through federated credential.
resource "azurerm_user_assigned_identity" "workload" {
  name                = "id-${var.name_prefix}-workload"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_role_assignment" "workload_kvsec_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

resource "azurerm_federated_identity_credential" "workload" {
  name                = "fic-${var.name_prefix}-workload"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.workload.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.aks_oidc_issuer_url
  subject             = "system:serviceaccount:${var.workload_identity_namespace}:${var.workload_identity_sa}"
}

resource "azurerm_private_endpoint" "this" {
  name                = "pe-${var.name_prefix}-kv"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-kv"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  tags = var.tags
}

output "keyvault_id"         { value = azurerm_key_vault.this.id }
output "vault_uri"           { value = azurerm_key_vault.this.vault_uri }
output "workload_client_id"  { value = azurerm_user_assigned_identity.workload.client_id }
output "workload_object_id"  { value = azurerm_user_assigned_identity.workload.principal_id }
