###############################################################################
# Inputs - Root Module
###############################################################################

variable "environment" {
  description = "Environment name: dev | test | uat | preprod | prod"
  type        = string
  validation {
    condition     = contains(["dev", "test", "uat", "preprod", "prod"], var.environment)
    error_message = "environment must be one of dev|test|uat|preprod|prod."
  }
}

variable "location" {
  description = "Azure region (e.g. uksouth, westeurope)"
  type        = string
  default     = "uksouth"
}

variable "location_short" {
  description = "Short region code used in resource names (e.g. uks, weu)"
  type        = string
  default     = "uks"
}

variable "tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
}

variable "owner_email" {
  description = "Owner email for tagging"
  type        = string
}

variable "cost_centre" {
  description = "Cost-centre code for tagging"
  type        = string
}

variable "extra_tags" {
  description = "Additional tags merged into the base tag set"
  type        = map(string)
  default     = {}
}

# Networking
variable "vnet_cidr" {
  description = "CIDR for the VNet"
  type        = string
  default     = "10.40.0.0/16"
}

# AKS
variable "kubernetes_version" {
  description = "AKS Kubernetes version"
  type        = string
  default     = "1.29"
}

variable "aks_admin_group_object_ids" {
  description = "AAD group object IDs that get cluster-admin"
  type        = list(string)
  default     = []
}

variable "aks_system_node_count" {
  type    = number
  default = 2
}

variable "aks_system_node_size" {
  type    = string
  default = "Standard_D4ds_v5"
}

variable "aks_user_node_min" {
  type    = number
  default = 2
}

variable "aks_user_node_max" {
  type    = number
  default = 6
}

variable "aks_user_node_size" {
  type    = string
  default = "Standard_D4ds_v5"
}

# ACR
variable "acr_sku" {
  type    = string
  default = "Premium"
}

variable "acr_geo_replications" {
  type    = list(string)
  default = []
}

# Postgres
variable "pg_admin_login" {
  type    = string
  default = "canadmin"
}

variable "pg_sku_name" {
  type    = string
  default = "GP_Standard_D4ds_v5"
}

variable "pg_storage_mb" {
  type    = number
  default = 131072 # 128 GiB
}

variable "pg_ha_mode" {
  type    = string
  default = "ZoneRedundant"
}

variable "pg_geo_backup" {
  type    = bool
  default = true
}

variable "pg_enable_citus" {
  description = "Enable the citus extension on the flexible server"
  type        = bool
  default     = true
}

# Observability
variable "log_retention_days" {
  type    = number
  default = 90
}

# AAD application
variable "app_redirect_uris" {
  type    = list(string)
  default = []
}

variable "app_homepage_url" {
  type    = string
  default = ""
}
