#!/bin/bash
# Creates the two auxiliary databases. can_app is already created by POSTGRES_DB.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE can_axon_event;
    CREATE DATABASE can_uli;
EOSQL
