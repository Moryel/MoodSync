"""
Start-up check used by CI: runs MoodSync in --dry-run mode, waits until its
loop has started, lets it run a few seconds and fails if it crashes, prints a
traceback or never gets going.

    python tests/smoke_run.py focus --camera
    python tests/smoke_run.py screen
"""

import os
import subprocess
import sys
import threading
import time

from ci_annotate import annotate

START_TIMEOUT = 180     # First runs can be slow (installing font caches, downloading the face model)
RUN_SECONDS = 8         # How long it must keep running once started
EXPECTED = {"focus": "Focus block 1/", "screen": "Press Ctrl+C to stop"}

# Never fail just because this console cannot show a character
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def run(program: str, extra: list) -> list:
    """Runs MoodSync and returns (problems, output)."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    cmd = [sys.executable, "main.py", program, "--dry-run", *extra]
    print("$", " ".join(cmd), flush=True)

    # Unbuffered, so start-up lines arrive as they are printed
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks = []
    reader = threading.Thread(target=lambda: chunks.extend(iter(proc.stdout.readline, b"")), daemon=True)
    reader.start()

    def output():
        return b"".join(chunks).decode("utf-8", "replace")

    deadline = time.monotonic() + START_TIMEOUT
    while EXPECTED[program] not in output() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.5)
    started = EXPECTED[program] in output()
    if started:
        time.sleep(RUN_SECONDS)

    crashed = proc.poll() is not None
    if not crashed:
        proc.terminate()
    proc.wait(timeout=30)
    reader.join(timeout=10)
    out = output()

    problems = []
    if crashed:
        problems.append(f"exited early with code {proc.returncode}")
    if "Traceback" in out:
        problems.append("printed a traceback")
    if not started:
        problems.append(f"never printed {EXPECTED[program]!r}")
    return problems, out


def main():
    program, extra = sys.argv[1], sys.argv[2:]
    try:
        problems, out = run(program, extra)
    except Exception as e:  # The check itself broke: still say why
        problems, out = [f"smoke test error: {e!r}"], ""
    print(out)
    if problems:
        print("SMOKE TEST FAILED: " + ", ".join(problems))
        if os.environ.get("GITHUB_ACTIONS"):
            annotate(f"{program} start-up: " + ", ".join(problems), out or problems[0])
        sys.exit(1)
    print("Smoke test passed.")


if __name__ == "__main__":
    main()
