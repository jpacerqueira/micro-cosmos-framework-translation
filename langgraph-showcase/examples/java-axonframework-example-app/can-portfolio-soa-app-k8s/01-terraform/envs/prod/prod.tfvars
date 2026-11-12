# Prod - HA, ZRS, geo-redundant backups, autoscaling user pool.
environment        = "prod"
location           = "uksouth"
location_short     = "uks"
tenant_id          = "00000000-0000-0000-0000-000000000000"
owner_email        = "platform@example.com"
cost_centre        = "CC-1234"

vnet_cidr          = "10.50.0.0/16"

kubernetes_version = "1.29"
aks_admin_group_object_ids = []
aks_system_node_count = 3
aks_system_node_size  = "Standard_D4ds_v5"
aks_user_node_min     = 3
aks_user_node_max     = 12
aks_user_node_size    = "Standard_D8ds_v5"

acr_sku            = "Premium"
acr_geo_replications = ["northeurope"]

pg_sku_name        = "GP_Standard_D8ds_v5"
pg_storage_mb      = 524288
pg_ha_mode         = "ZoneRedundant"
pg_geo_backup      = true
pg_enable_citus    = true

log_retention_days = 365
