###############################################################################
# Customer-Application-Name (CAN) - Root Module
# Implements the SAD: AKS + Istio-ready, ACR, Key Vault, PostgreSQL (Citus-ready),
# General Purpose v2 storage, Azure Monitor / Log Analytics, Azure AD B2B/B2C app
# registration, and Event Hubs (Kafka-compatible) for ULI/NATS bridge.
###############################################################################

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm    = { source = "hashicorp/azurerm",    version = "~> 3.110" }
    azuread    = { source = "hashicorp/azuread",    version = "~> 2.50" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
    helm       = { source = "hashicorp/helm",       version = "~> 2.13" }
    random     = { source = "hashicorp/random",     version = "~> 3.6" }
  }

  backend "azurerm" {
    # Configured per environment via -backend-config=envs/<env>/backend.hcl
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "azuread" {}

locals {
  app_short = "can" # Customer-Application-Name
  base_tags = merge(
    {
      application = "customer-application-name"
      environment = var.environment
      managed_by  = "terraform"
      owner       = var.owner_email
      cost_centre = var.cost_centre
    },
    var.extra_tags,
  )

  name_prefix = "${local.app_short}-${var.environment}-${var.location_short}"
}

# Resource groups - separated per the SAD's Resource Group strategy.
resource "azurerm_resource_group" "platform" {
  name     = "rg-${local.name_prefix}-platform"
  location = var.location
  tags     = local.base_tags
}

resource "azurerm_resource_group" "data" {
  name     = "rg-${local.name_prefix}-data"
  location = var.location
  tags     = local.base_tags
}

resource "azurerm_resource_group" "observability" {
  name     = "rg-${local.name_prefix}-obs"
  location = var.location
  tags     = local.base_tags
}

# Networking - explicit address space, dedicated subnets for AKS, DB, PE.
module "network" {
  source              = "./modules/network"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  name_prefix         = local.name_prefix
  vnet_cidr           = var.vnet_cidr
  tags                = local.base_tags
}

# Observability first - the AKS module needs the workspace ID.
module "observability" {
  source              = "./modules/observability"
  resource_group_name = azurerm_resource_group.observability.name
  location            = azurerm_resource_group.observability.location
  name_prefix         = local.name_prefix
  retention_in_days   = var.log_retention_days
  tags                = local.base_tags
}

# Container Registry - private, with geo-replication optional.
module "acr" {
  source              = "./modules/acr"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  name_prefix         = local.name_prefix
  sku                 = var.acr_sku
  geo_replications    = var.acr_geo_replications
  tags                = local.base_tags
}

# AKS - system + user node pools, workload identity, OIDC, Azure CNI overlay.
# Istio is installed via Helm in 02-kubernetes-istio after the cluster is up.
module "aks" {
  source                          = "./modules/aks"
  resource_group_name             = azurerm_resource_group.platform.name
  location                        = azurerm_resource_group.platform.location
  name_prefix                     = local.name_prefix
  kubernetes_version              = var.kubernetes_version
  vnet_subnet_id                  = module.network.aks_subnet_id
  log_analytics_workspace_id      = module.observability.log_analytics_workspace_id
  acr_id                          = module.acr.acr_id
  admin_group_object_ids          = var.aks_admin_group_object_ids
  system_node_count               = var.aks_system_node_count
  system_node_size                = var.aks_system_node_size
  user_node_min                   = var.aks_user_node_min
  user_node_max                   = var.aks_user_node_max
  user_node_size                  = var.aks_user_node_size
  enable_workload_identity        = true
  enable_oidc_issuer              = true
  network_plugin_mode             = "overlay"
  outbound_type                   = "userAssignedNATGateway"
  user_assigned_nat_gateway_id    = module.network.nat_gateway_id
  tags                            = local.base_tags
}

# Key Vault - secrets and key management for the Spring Boot apps via CSI driver.
module "keyvault" {
  source              = "./modules/keyvault"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  name_prefix         = local.name_prefix
  tenant_id           = var.tenant_id
  aks_kubelet_identity_object_id = module.aks.kubelet_identity_object_id
  aks_oidc_issuer_url            = module.aks.oidc_issuer_url
  workload_identity_namespace    = "can-system"
  workload_identity_sa           = "can-workload-sa"
  private_endpoint_subnet_id     = module.network.pe_subnet_id
  tags                = local.base_tags
}

# PostgreSQL Flexible Server - Citus-ready (use hyperscale/Cosmos for Citus mode).
# Default uses Flexible Server with the citus extension enabled where supported.
module "postgres" {
  source              = "./modules/postgres"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  name_prefix         = local.name_prefix
  delegated_subnet_id = module.network.pg_subnet_id
  private_dns_zone_id = module.network.pg_dns_zone_id
  admin_login         = var.pg_admin_login
  sku_name            = var.pg_sku_name
  storage_mb          = var.pg_storage_mb
  ha_mode             = var.pg_ha_mode
  geo_redundant_backup = var.pg_geo_backup
  enable_citus        = var.pg_enable_citus
  databases           = ["can_app", "can_axon_event", "can_uli"]
  log_analytics_workspace_id = module.observability.log_analytics_workspace_id
  keyvault_id         = module.keyvault.keyvault_id
  tags                = local.base_tags
}

# Storage Account (GPv2) - lifecycle policies for hot -> cool -> archive.
module "storage" {
  source              = "./modules/storage"
  resource_group_name = azurerm_resource_group.data.name
  location            = azurerm_resource_group.data.location
  name_prefix         = local.name_prefix
  containers          = ["vdr-raw", "vdr-clean", "exports", "audit"]
  enable_lifecycle    = true
  private_endpoint_subnet_id = module.network.pe_subnet_id
  tags                = local.base_tags
}

# Event Hubs (Kafka-compatible) - bridges to NATS for ULI durable backplane.
module "eventhubs" {
  source              = "./modules/eventhubs"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  name_prefix         = local.name_prefix
  sku                 = "Standard"
  capacity            = 1
  hubs                = ["uli.commands", "uli.events", "uli.dlq"]
  tags                = local.base_tags
}

# Azure AD application registration for the WebApp + API (B2B/B2C delegated).
module "azuread_app" {
  source           = "./modules/azuread_app"
  display_name     = "${local.name_prefix}-app"
  redirect_uris    = var.app_redirect_uris
  identifier_uris  = ["api://${local.name_prefix}"]
  tenant_id        = var.tenant_id
  reply_homepage   = var.app_homepage_url
}
