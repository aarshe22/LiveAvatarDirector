#!/usr/bin/env bash
set -euo pipefail
mkdir -p data models cache
docker compose up --build -d api worker
docker compose ps
