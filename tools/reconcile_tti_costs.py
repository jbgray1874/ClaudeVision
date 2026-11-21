"""Standalone write-back only entry point. Never starts the pricer."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tti_cost_reconcile import main

if __name__ == '__main__':
    raise SystemExit(main())
