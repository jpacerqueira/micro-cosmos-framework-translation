"""Secret retrieval helpers — Azure Key Vault + Databricks secret scopes.

These references are surfaced by parsers/secrets.py → SecretRef entries in IRBundle.
The report emits SECRETS.md listing all secrets that need provisioning in Google Secret Manager.
"""

from __future__ import annotations


def get_sql_server_password(dbutils) -> str:
    return dbutils.secrets.get(scope="next-azure-kv", key="sql-server-sa-password")


def get_adls_sas_token(dbutils) -> str:
    return dbutils.secrets.get(scope="next-azure-kv", key="adls-gen2-sas-token")


def get_eventhub_connection_string(dbutils) -> str:
    return dbutils.secrets.get(scope="next-azure-kv", key="eventhub-connection-string")


def get_service_principal_secret(dbutils) -> str:
    return dbutils.secrets.get(scope="next-azure-kv", key="aad-sp-client-secret")
