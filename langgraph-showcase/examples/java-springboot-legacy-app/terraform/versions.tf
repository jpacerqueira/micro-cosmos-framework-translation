terraform {
  required_version = ">= 1.3.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }
  backend "azurerm" {
    resource_group_name  = "can-legacy-tfstate-rg"
    storage_account_name = "canlegacytfstate"
    container_name       = "tfstate"
    key                  = "can-legacy.terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}
