#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
docker compose --profile cpa pull cpa
docker compose --profile cpa up -d --no-deps cpa
