#!/bin/bash
set -e
MARK_PACKAGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec /usr/bin/python3 -B "$MARK_PACKAGE_DIR/mark.py" --gui launch --switch
