###############################################################################
# Network module - VNet, subnets, NAT gateway, private DNS for Postgres.
###############################################################################

variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "name_prefix"         { type = string }
variable "vnet_cidr"           { type = string }
variable "tags"                { type = map(string) }

locals {
  # Carve the /16 into stable /22 subnets.
  aks_cidr = cidrsubnet(var.vnet_cidr,  6,  0) # x.x.0.0/22
  pg_cidr  = cidrsubnet(var.vnet_cidr,  6,  4) # x.x.16.0/22
  pe_cidr  = cidrsubnet(var.vnet_cidr,  6,  8) # x.x.32.0/22
  ag_cidr  = cidrsubnet(var.vnet_cidr,  6, 12) # x.x.48.0/22
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${var.name_prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.vnet_cidr]
  tags                = var.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [local.aks_cidr]
}

resource "azurerm_subnet" "pg" {
  name                 = "snet-pg"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [local.pg_cidr]
  service_endpoints    = ["Microsoft.Storage"]
  delegation {
    name = "fs"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "pe" {
  name                              = "snet-pe"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.this.name
  address_prefixes                  = [local.pe_cidr]
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_subnet" "ag" {
  name                 = "snet-ag"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [local.ag_cidr]
}

# NAT gateway gives AKS deterministic egress IPs (auditable, allow-list-friendly).
resource "azurerm_public_ip" "nat" {
  name                = "pip-${var.name_prefix}-nat"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  name                    = "ng-${var.name_prefix}"
  resource_group_name     = var.resource_group_name
  location                = var.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  nat_gateway_id       = azurerm_nat_gateway.this.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "aks" {
  subnet_id      = azurerm_subnet.aks.id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Private DNS zone for Postgres flexible server.
resource "azurerm_private_dns_zone" "pg" {
  name                = "${var.name_prefix}.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "pg" {
  name                  = "pg-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.pg.name
  virtual_network_id    = azurerm_virtual_network.this.id
  tags                  = var.tags
}

output "vnet_id"          { value = azurerm_virtual_network.this.id }
output "aks_subnet_id"    { value = azurerm_subnet.aks.id }
output "pg_subnet_id"     { value = azurerm_subnet.pg.id }
output "pe_subnet_id"     { value = azurerm_subnet.pe.id }
output "ag_subnet_id"     { value = azurerm_subnet.ag.id }
output "pg_dns_zone_id"   { value = azurerm_private_dns_zone.pg.id }
output "nat_gateway_id"   { value = azurerm_nat_gateway.this.id }
