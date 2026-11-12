###############################################################################
# AKS module - Workload Identity + OIDC, Azure CNI overlay, NAT egress,
# Log Analytics + Container Insights, system + autoscaling user node pool.
###############################################################################

variable "resource_group_name"             { type = string }
variable "location"                        { type = string }
variable "name_prefix"                     { type = string }
variable "kubernetes_version"              { type = string }
variable "vnet_subnet_id"                  { type = string }
variable "log_analytics_workspace_id"      { type = string }
variable "acr_id"                          { type = string }
variable "admin_group_object_ids"          { type = list(string) }
variable "system_node_count"               { type = number }
variable "system_node_size"                { type = string }
variable "user_node_min"                   { type = number }
variable "user_node_max"                   { type = number }
variable "user_node_size"                  { type = string }
variable "enable_workload_identity"        { type = bool   default = true }
variable "enable_oidc_issuer"              { type = bool   default = true }
variable "network_plugin_mode"             { type = string default = "overlay" }
variable "outbound_type"                   { type = string default = "userAssignedNATGateway" }
variable "user_assigned_nat_gateway_id"    { type = string default = null }
variable "tags"                            { type = map(string) }

resource "azurerm_user_assigned_identity" "aks" {
  name                = "id-${var.name_prefix}-aks"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

resource "azurerm_kubernetes_cluster" "this" {
  name                      = "aks-${var.name_prefix}"
  resource_group_name       = var.resource_group_name
  location                  = var.location
  dns_prefix                = "aks-${var.name_prefix}"
  kubernetes_version        = var.kubernetes_version
  automatic_channel_upgrade = "patch"
  sku_tier                  = "Standard"

  oidc_issuer_enabled       = var.enable_oidc_issuer
  workload_identity_enabled = var.enable_workload_identity
  azure_policy_enabled      = true
  local_account_disabled    = true
  role_based_access_control_enabled = true

  azure_active_directory_role_based_access_control {
    managed                = true
    azure_rbac_enabled     = true
    admin_group_object_ids = var.admin_group_object_ids
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks.id]
  }

  default_node_pool {
    name                = "system"
    node_count          = var.system_node_count
    vm_size             = var.system_node_size
    vnet_subnet_id      = var.vnet_subnet_id
    only_critical_addons_enabled = true
    type                = "VirtualMachineScaleSets"
    zones               = ["1", "2", "3"]
    os_disk_type        = "Ephemeral"
    os_disk_size_gb     = 128
    upgrade_settings { max_surge = "33%" }
    tags                = var.tags
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = var.network_plugin_mode
    network_policy      = "cilium"
    network_dataplane   = "cilium"
    outbound_type       = var.outbound_type
    load_balancer_sku   = "standard"
    pod_cidr            = "10.244.0.0/16"
    service_cidr        = "10.0.0.0/16"
    dns_service_ip      = "10.0.0.10"
  }

  oms_agent {
    log_analytics_workspace_id      = var.log_analytics_workspace_id
    msi_auth_for_monitoring_enabled = true
  }

  microsoft_defender {
    log_analytics_workspace_id = var.log_analytics_workspace_id
  }

  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "5m"
  }

  maintenance_window_auto_upgrade {
    frequency   = "Weekly"
    interval    = 1
    duration    = 4
    day_of_week = "Sunday"
    start_time  = "02:00"
    utc_offset  = "+00:00"
  }

  tags = var.tags
}

# User node pool - autoscaling, taints isolated workloads.
resource "azurerm_kubernetes_cluster_node_pool" "user" {
  name                  = "user"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.user_node_size
  vnet_subnet_id        = var.vnet_subnet_id
  enable_auto_scaling   = true
  min_count             = var.user_node_min
  max_count             = var.user_node_max
  zones                 = ["1", "2", "3"]
  os_disk_type          = "Ephemeral"
  os_disk_size_gb       = 128
  mode                  = "User"
  upgrade_settings { max_surge = "33%" }
  tags                  = var.tags
}

# Pull from ACR using kubelet identity.
resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

# Network Contributor on the cluster identity for the subnet.
resource "azurerm_role_assignment" "network_contributor" {
  scope                = var.vnet_subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id
}

output "cluster_name"               { value = azurerm_kubernetes_cluster.this.name }
output "resource_group_name"        { value = azurerm_kubernetes_cluster.this.resource_group_name }
output "kube_config_raw"            { value = azurerm_kubernetes_cluster.this.kube_config_raw  sensitive = true }
output "oidc_issuer_url"            { value = azurerm_kubernetes_cluster.this.oidc_issuer_url }
output "kubelet_identity_object_id" { value = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id }
output "host"                       { value = azurerm_kubernetes_cluster.this.kube_config[0].host  sensitive = true }
