#!/usr/bin/env python3
"""Maintainer tool: refresh the package inventory after reviewing all changes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mark
mark.atomic_json(mark.ROOT / 'SHA256SUMS.json', mark.inventory())
print(mark.verify_package())
