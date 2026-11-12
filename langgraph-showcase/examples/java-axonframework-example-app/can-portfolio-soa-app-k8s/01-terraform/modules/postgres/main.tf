###############################################################################
# PostgreSQL Flexible Server - Citus extension where supported, private VNet
# integration, ZRS HA, automated backups, password sourced into Key Vault.
###############################################################################

variable "resource_group_name"        { type = string }
variable "location"                   { type = string }
variable "name_prefix"                { type = string }
variable "delegated_subnet_id"        { type = string }
variable "private_dns_zone_id"        { type = string }
variable "admin_login"                { type = string }
variable "sku_name"                   { type = string }
variable "storage_mb"                 { type = number }
variable "ha_mode"                    { type = string }
variable "geo_redundant_backup"       { type = bool }
variable "enable_citus"               { type = bool }
variable "databases"                  { type = list(string) }
variable "log_analytics_workspace_id" { type = string }
variable "keyvault_id"                { type = string }
variable "tags"                       { type = map(string) }

resource "random_password" "admin" {
  length           = 24
  special          = true
  override_special = "_-+=!@$%^&"
}

resource "azurerm_key_vault_secret" "admin" {
  name         = "pg-admin-password"
  value        = random_password.admin.result
  key_vault_id = var.keyvault_id
  content_type = "PostgreSQL admin password"
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "pg-${var.name_prefix}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = "15"
  administrator_login           = var.admin_login
  administrator_password        = random_password.admin.result
  zone                          = "1"

  delegated_subnet_id           = var.delegated_subnet_id
  private_dns_zone_id           = var.private_dns_zone_id
  public_network_access_enabled = false

  sku_name                      = var.sku_name
  storage_mb                    = var.storage_mb
  backup_retention_days         = 14
  geo_redundant_backup_enabled  = var.geo_redundant_backup
  auto_grow_enabled             = true

  high_availability {
    mode                      = var.ha_mode
    standby_availability_zone = "2"
  }

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}

data "azurerm_client_config" "current" {}

# Enable extensions including citus.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = var.enable_citus ? "CITUS,UUID-OSSP,PG_TRGM,BTREE_GIN,PGCRYPTO" : "UUID-OSSP,PG_TRGM,BTREE_GIN,PGCRYPTO"
}

resource "azurerm_postgresql_flexible_server_configuration" "shared_libs" {
  count     = var.enable_citus ? 1 : 0
  name      = "shared_preload_libraries"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "citus,pg_stat_statements"
}

resource "azurerm_postgresql_flexible_server_database" "dbs" {
  for_each  = toset(var.databases)
  name      = each.value
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# Diagnostic settings - all categories to LAW.
resource "azurerm_monitor_diagnostic_setting" "pg" {
  name                       = "diag-${var.name_prefix}-pg"
  target_resource_id         = azurerm_postgresql_flexible_server.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log { category = "PostgreSQLLogs" }
  enabled_log { category = "PostgreSQLFlexSessions" }
  enabled_log { category = "PostgreSQLFlexQueryStoreRuntime" }
  enabled_log { category = "PostgreSQLFlexQueryStoreWaitStats" }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

output "fqdn"     { value = azurerm_postgresql_flexible_server.this.fqdn }
output "id"       { value = azurerm_postgresql_flexible_server.this.id }
output "admin"    { value = var.admin_login }
output "secret"   { value = azurerm_key_vault_secret.admin.id }
