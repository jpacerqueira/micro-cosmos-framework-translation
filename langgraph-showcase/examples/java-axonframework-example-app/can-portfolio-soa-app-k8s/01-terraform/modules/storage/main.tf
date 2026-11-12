###############################################################################
# Storage Account (GPv2) with lifecycle: hot -> cool (30d) -> archive (180d).
###############################################################################

variable "resource_group_name"        { type = string }
variable "location"                   { type = string }
variable "name_prefix"                { type = string }
variable "containers"                 { type = list(string) }
variable "enable_lifecycle"           { type = bool   default = true }
variable "private_endpoint_subnet_id" { type = string }
variable "tags"                       { type = map(string) }

resource "azurerm_storage_account" "this" {
  name                          = substr(replace("st${var.name_prefix}", "-", ""), 0, 24)
  resource_group_name           = var.resource_group_name
  location                      = var.location
  account_tier                  = "Standard"
  account_replication_type      = "ZRS"
  account_kind                  = "StorageV2"
  is_hns_enabled                = true
  min_tls_version               = "TLS1_2"
  public_network_access_enabled = false
  enable_https_traffic_only     = true
  shared_access_key_enabled     = false
  default_to_oauth_authentication = true

  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = true
    last_access_time_enabled = true
    delete_retention_policy { days = 30 }
    container_delete_retention_policy { days = 30 }
  }

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  tags = var.tags
}

resource "azurerm_storage_container" "containers" {
  for_each              = toset(var.containers)
  name                  = each.value
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "this" {
  count              = var.enable_lifecycle ? 1 : 0
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "tier-down"
    enabled = true
    filters {
      blob_types = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than    = 30
        tier_to_archive_after_days_since_modification_greater_than = 180
        delete_after_days_since_modification_greater_than          = 2555 # 7y
      }
      snapshot {
        delete_after_days_since_creation_greater_than = 90
      }
    }
  }
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-${var.name_prefix}-st-blob"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint_subnet_id

  private_service_connection {
    name                           = "psc-blob"
    private_connection_resource_id = azurerm_storage_account.this.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  tags = var.tags
}

output "account_name" { value = azurerm_storage_account.this.name }
output "account_id"   { value = azurerm_storage_account.this.id }
