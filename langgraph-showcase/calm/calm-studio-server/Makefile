SHELL := /bin/bash

SCRIPT_DIR := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)
INSTALL_SCRIPT := $(SCRIPT_DIR)/install-calm-studio.sh
LOG_FILE := $(SCRIPT_DIR)/calm-studio.log

GIT_HOME ?= $(HOME)/Documents/GitHub
REPO_DIR := $(GIT_HOME)/architecture-as-code
CALM_CORE_DIST := $(REPO_DIR)/calm-studio/packages/calm-core/dist/index.js

PORT := 5173

.PHONY: install start stop

# Clones/pulls architecture-as-code, npm installs, and builds the calm-models/calm-core
# workspaces that CALM Studio needs — does NOT start the dev server (see `start`).
install:
	@RUN_DEV=false GIT_HOME="$(GIT_HOME)" "$(INSTALL_SCRIPT)"

# Installs first only if not already installed, then starts the dev server. Once installed,
# repeat `make start` calls skip straight to `npm run dev` instead of redoing install/build.
start:
	@if lsof -ti :$(PORT) >/dev/null 2>&1; then \
		echo "CALM Studio already running at http://localhost:$(PORT)"; \
		exit 0; \
	fi; \
	if [ ! -f "$(CALM_CORE_DIST)" ]; then \
		echo "CALM Studio not installed yet — running install ..."; \
		$(MAKE) --no-print-directory install; \
	fi; \
	echo "Starting CALM Studio (logs: $(LOG_FILE)) ..."; \
	cd "$(REPO_DIR)" && nohup npm run dev --workspace=@calmstudio/studio > "$(LOG_FILE)" 2>&1 & \
	for i in $$(seq 1 60); do \
		if curl -sf http://localhost:$(PORT) >/dev/null 2>&1; then \
			echo "CALM Studio is up at http://localhost:$(PORT)"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Timed out waiting for CALM Studio to start — check $(LOG_FILE)"; \
	exit 1

stop:
	@if lsof -ti :$(PORT) >/dev/null 2>&1; then \
		lsof -ti :$(PORT) | xargs kill -9; \
		echo "CALM Studio stopped (port $(PORT) freed)"; \
	else \
		echo "CALM Studio is not running"; \
	fi
