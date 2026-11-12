###############################################################################
# Event Hubs - Kafka-compatible namespace, used as durable backplane bridged
# to NATS for ULI events that must escape the cluster.
###############################################################################

variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "name_prefix"         { type = string }
variable "sku"                 { type = string }
variable "capacity"            { type = number }
variable "hubs"                { type = list(string) }
variable "tags"                { type = map(string) }

resource "azurerm_eventhub_namespace" "this" {
  name                          = "evhns-${var.name_prefix}"
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = var.sku
  capacity                      = var.capacity
  auto_inflate_enabled          = true
  maximum_throughput_units      = 10
  zone_redundant                = true
  public_network_access_enabled = false
  minimum_tls_version           = "1.2"
  local_authentication_enabled  = false
  tags                          = var.tags
}

resource "azurerm_eventhub" "hubs" {
  for_each            = toset(var.hubs)
  name                = each.value
  namespace_name      = azurerm_eventhub_namespace.this.name
  resource_group_name = var.resource_group_name
  partition_count     = 4
  message_retention   = 7
}

output "namespace" { value = azurerm_eventhub_namespace.this.name }
output "fqdn"      { value = "${azurerm_eventhub_namespace.this.name}.servicebus.windows.net" }
