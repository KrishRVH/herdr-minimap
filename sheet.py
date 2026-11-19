#!/usr/bin/env python3
"""Export the standalone bonsai's contact sheets from a minimap checkout."""
import os
import sys
from pathlib import Path


if __name__ == "__main__":
    bundle = Path(__file__).resolve().parent / "vendor" / "pixel-bonsai.pyz"
    os.execv(sys.executable, [sys.executable, bundle, "sheet", *sys.argv[1:]])
