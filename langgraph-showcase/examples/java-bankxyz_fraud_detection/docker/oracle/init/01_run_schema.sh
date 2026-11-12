#!/usr/bin/env bash
# Runs the BankXYZ fraud DDL against XEPDB1.
# Executed by the gvenzl oracle-xe entrypoint after FDADMIN is created.
# APP_USER and APP_USER_PASSWORD are injected by docker-compose environment.
set -euo pipefail

echo "[init] Installing BankXYZ fraud schema as ${APP_USER} in XEPDB1..."

# install_all.sql uses @-includes so sqlplus must run from the scripts directory
cd /oracle-scripts
sqlplus -S "${APP_USER}/${APP_USER_PASSWORD}@//localhost:1521/XEPDB1" @install_all.sql

echo "[init] Schema installation complete."
