# Dev environment - smaller footprint, single zone, no geo-replication.
environment        = "dev"
location           = "uksouth"
location_short     = "uks"
tenant_id          = "00000000-0000-0000-0000-000000000000" # populate via CI
owner_email        = "platform@example.com"
cost_centre        = "CC-1234"

vnet_cidr          = "10.40.0.0/16"

kubernetes_version = "1.29"
aks_admin_group_object_ids = [] # populate via CI
aks_system_node_count = 2
aks_system_node_size  = "Standard_D2ds_v5"
aks_user_node_min     = 1
aks_user_node_max     = 3
aks_user_node_size    = "Standard_D4ds_v5"

acr_sku            = "Standard"
acr_geo_replications = []

pg_sku_name        = "GP_Standard_D2ds_v5"
pg_storage_mb      = 65536
pg_ha_mode         = "Disabled"
pg_geo_backup      = false
pg_enable_citus    = true

log_retention_days = 30
