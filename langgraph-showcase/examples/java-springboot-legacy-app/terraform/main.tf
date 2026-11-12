terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 3.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.0" }
  }
  backend "azurerm" {
    resource_group_name  = "can-legacy-tfstate-rg"
    storage_account_name = "canlegacytfstate"
    container_name       = "tfstate"
    key                  = "can-legacy.terraform.tfstate"
  }
}

provider "azurerm" { features {} }

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
  tags     = { environment = "production", app = "can-legacy" }
}

module "networking" {
  source              = "./modules/networking"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  vnet_cidr           = var.vnet_cidr
  aks_subnet_cidr     = var.aks_subnet_cidr
  depends_on          = [azurerm_resource_group.rg]
}

module "acr" {
  source              = "./modules/acr"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  acr_name            = var.acr_name
  sku                 = "Standard"
  depends_on          = [azurerm_resource_group.rg]
}

module "aks" {
  source              = "./modules/aks"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  cluster_name        = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  subnet_id           = module.networking.aks_subnet_id
  acr_id              = module.acr.acr_id
  node_count          = var.node_count
  vm_size             = var.vm_size
  depends_on          = [module.networking, module.acr]
}
