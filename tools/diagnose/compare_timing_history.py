"""Compare the two latest saved timing snapshots of a job from the timing history (D-581):

    python tools/diagnose/compare_timing_history.py output/timing_history.csv --job <stem>

Prints every run of the job and the latest pair's wall-time saving with per-stage deltas.
Stage deltas are inclusive and never sum to wall time. No model, supplier or Excel call.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from timing_comparison import runs_from_history, compare

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history")
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    runs = runs_from_history(args.history, args.job)
    if len(runs) < 2:
        parser.error("Two saved runs are required")
    print(json.dumps({"runs": runs, "latest_pair": compare(*runs[-2:])}, indent=2))
