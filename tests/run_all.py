"""Run every phase smoke test in order. Exit non-zero on the first failure.

    python tests/run_all.py
"""

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
scripts = sorted(HERE.glob("smoke_phase*.py"), key=lambda p: int(p.stem.split("phase")[1]))

failed = 0
for s in scripts:
    print(f"\n=== {s.name} " + "=" * (60 - len(s.name)))
    r = subprocess.run([sys.executable, str(s)])
    if r.returncode != 0:
        failed += 1
        print(f"!!! {s.name} FAILED")

print("\n" + "=" * 64)
if failed:
    print(f"{failed} suite(s) FAILED")
    sys.exit(1)
print(f"All {len(scripts)} smoke suites passed.")
