###############################################################################
# Observability - Log Analytics workspace + App Insights + base alerts.
# Drives the SAD's Centralised Logging & Monitoring section.
###############################################################################

variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "name_prefix"         { type = string }
variable "retention_in_days"   { type = number  default = 90 }
variable "tags"                { type = map(string) }

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${var.name_prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = "appi-${var.name_prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  application_type    = "java"
  workspace_id        = azurerm_log_analytics_workspace.this.id
  retention_in_days   = var.retention_in_days
  tags                = var.tags
}

resource "azurerm_monitor_action_group" "ops" {
  name                = "ag-${var.name_prefix}-ops"
  resource_group_name = var.resource_group_name
  short_name          = "canops"
  tags                = var.tags
}

# Baseline alert: high 5xx rate from API gateway / ingress.
resource "azurerm_monitor_metric_alert" "high_5xx" {
  name                = "alert-${var.name_prefix}-high-5xx"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_application_insights.this.id]
  description         = "5xx rate above 5% over 5 minutes"
  severity            = 2
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 50
  }

  action { action_group_id = azurerm_monitor_action_group.ops.id }
  tags = var.tags
}

output "log_analytics_workspace_id" { value = azurerm_log_analytics_workspace.this.id }
output "app_insights_id"            { value = azurerm_application_insights.this.id }
output "app_insights_connection"    { value = azurerm_application_insights.this.connection_string  sensitive = true }
output "app_insights_ikey"          { value = azurerm_application_insights.this.instrumentation_key  sensitive = true }
output "action_group_id"            { value = azurerm_monitor_action_group.ops.id }
