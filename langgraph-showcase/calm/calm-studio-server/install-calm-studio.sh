#!/usr/bin/env bash
# Installs and starts FINOS CALM Studio (https://calm.finos.org/working-with-calm/calm-studio/)
# CALM Studio is a workspace (@calmstudio/studio) inside the finos/architecture-as-code monorepo,
# on the `main` branch — it does not exist as a standalone npm package, and it is NOT present on
# the release-1.2-revised branch (that branch predates CalmStudio's addition to the monorepo).
set -euo pipefail

# GIT_HOME is where this machine keeps its GitHub clones. Override it (e.g. `GIT_HOME=/some/path
# ./install-calm-studio.sh`) to relocate the checkout without editing this script.
GIT_HOME="${GIT_HOME:-$HOME/Documents/GitHub}"
REPO_DIR="$GIT_HOME/architecture-as-code"
REPO_URL="https://github.com/finos/architecture-as-code"
BRANCH="main"
# Set RUN_DEV=false to only clone/install/build (used by `make install`) without starting the
# dev server — `make start` starts it separately so repeat starts don't redo the install.
RUN_DEV="${RUN_DEV:-true}"

# CALM Studio requires Node.js 22+
required_major=22
node_major="$(node -v | sed 's/^v//' | cut -d. -f1)"
if [ "$node_major" -lt "$required_major" ]; then
    echo "CALM Studio requires Node.js >= $required_major (found $(node -v))" >&2
    exit 1
fi

mkdir -p "$GIT_HOME"

if [ -d "$REPO_DIR/.git" ]; then
    echo "architecture-as-code already cloned at $REPO_DIR — switching to $BRANCH and pulling latest"
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" pull --ff-only
else
    echo "Cloning $REPO_URL @ $BRANCH into $REPO_DIR (CALM Studio lives at workspace @calmstudio/studio)"
    git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
npm install

# @calmstudio/studio imports @calmstudio/calm-core, whose package.json `exports` point at a
# ./dist build output. `npm install` does not build workspace packages, so without this step
# vite fails dependency pre-bundling with "Failed to run dependency scan" and can serve a broken
# app. calm-core itself depends on @finos/calm-models, which also needs a build.
npm run build --workspace=@finos/calm-models
npm run build --workspace=@calmstudio/calm-core

if [ "$RUN_DEV" = "true" ]; then
    npm run dev --workspace=@calmstudio/studio
fi
