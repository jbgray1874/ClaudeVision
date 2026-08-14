import sys
from pathlib import Path

# Tests import the project modules directly, mirroring how sync.py runs on the
# server (flat layout, no package install).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
