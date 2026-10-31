"""
Start-up check used by CI: runs MoodSync for a few seconds in --dry-run mode
and fails if it crashes, prints a traceback or never starts its loop.

    python tests/smoke_run.py focus --camera
    python tests/smoke_run.py screen
"""

import os
import subprocess
import sys
import time

from ci_annotate import annotate

RUN_SECONDS = 15
EXPECTED = {"focus": "Focus block 1/", "screen": "Press Ctrl+C to stop"}


def main():
    program, extra = sys.argv[1], sys.argv[2:]
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    cmd = [sys.executable, "main.py", program, "--dry-run", *extra]
    print("$", " ".join(cmd), flush=True)

    proc = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(RUN_SECONDS)
    crashed = proc.poll() is not None
    if not crashed:
        proc.terminate()
    out = proc.communicate(timeout=30)[0].decode("utf-8", "replace")
    print(out)

    problems = []
    if crashed:
        problems.append(f"exited early with code {proc.returncode}")
    if "Traceback" in out:
        problems.append("printed a traceback")
    if EXPECTED[program] not in out:
        problems.append(f"never printed {EXPECTED[program]!r}")
    if problems:
        print("SMOKE TEST FAILED: " + ", ".join(problems))
        if os.environ.get("GITHUB_ACTIONS"):
            annotate(f"{program} start-up: " + ", ".join(problems), out)
        sys.exit(1)
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
