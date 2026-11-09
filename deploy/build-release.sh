#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: sh deploy/build-release.sh NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi

mkdir -- "$1"
output_dir=$(CDPATH= cd -- "$1" && pwd)
cd -- "$(dirname -- "$0")/.."

uv export --locked --no-dev --no-emit-project --no-cache -o "$output_dir/requirements.lock.txt" >/dev/null
uv build --wheel --no-cache --out-dir "$output_dir"
cp deploy/decision-service.service deploy/caddy-route.example deploy/config.example.json \
    deploy/install-provider-key.py "$output_dir/"
