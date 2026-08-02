#!/usr/bin/env bash
# Unpacks data/pigeon_raw_human.tar.gz into the external raw-data directory
# that pathDefaults.RAW_DATA_DIR expects (../Data/Raw/Human relative to this
# project's root). Idempotent: safe to re-run, skips if already unpacked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ARCHIVE="$PROJECT_ROOT/data/pigeon_raw_human.tar.gz"
DEST="$PROJECT_ROOT/../Data/Raw/Human"

if [ -d "$DEST/MX" ] && [ -d "$DEST/OL" ] && [ -d "$DEST/PD" ] && [ -d "$DEST/MXSC" ]; then
    echo "Raw data already unpacked at $DEST -- nothing to do."
    exit 0
fi

mkdir -p "$DEST"
echo "Unpacking $ARCHIVE to $DEST ..."
tar -xzf "$ARCHIVE" -C "$DEST"
echo "Done. $(find "$DEST" -name '*.csv' | wc -l | tr -d ' ') CSV files unpacked."
