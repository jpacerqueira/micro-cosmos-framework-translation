variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "cluster_name" { type = string }
variable "kubernetes_version" { type = string; default = "1.28" }
variable "subnet_id" { type = string }
variable "acr_id" { type = string }
variable "node_count" { type = number; default = 3 }
variable "vm_size" { type = string; default = "Standard_D4s_v3" }
