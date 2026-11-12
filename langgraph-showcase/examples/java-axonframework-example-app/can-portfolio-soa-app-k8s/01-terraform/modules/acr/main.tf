###############################################################################
# Azure Container Registry - Premium for replication, content trust, retention.
###############################################################################

variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "name_prefix"         { type = string }
variable "sku"                 { type = string  default = "Premium" }
variable "geo_replications"    { type = list(string)  default = [] }
variable "tags"                { type = map(string) }

resource "azurerm_container_registry" "this" {
  name                          = replace("acr${var.name_prefix}", "-", "")
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = var.sku
  admin_enabled                 = false
  public_network_access_enabled = false
  zone_redundancy_enabled       = true
  anonymous_pull_enabled        = false
  data_endpoint_enabled         = true

  retention_policy {
    days    = 30
    enabled = true
  }

  trust_policy {
    enabled = true
  }

  dynamic "georeplications" {
    for_each = var.sku == "Premium" ? var.geo_replications : []
    content {
      location                = georeplications.value
      zone_redundancy_enabled = true
    }
  }

  tags = var.tags
}

output "acr_id"       { value = azurerm_container_registry.this.id }
output "login_server" { value = azurerm_container_registry.this.login_server }
output "name"         { value = azurerm_container_registry.this.name }
