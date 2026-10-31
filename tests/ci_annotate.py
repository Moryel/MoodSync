"""
CI helper: shows the end of a failed step's output as a GitHub annotation, so
the reason is visible on the run page without signing in to read the logs.

    python tests/ci_annotate.py "Unit tests" output.log
"""

import sys

LINES = 40


def annotate(title: str, text: str):
    lines = text.strip().splitlines()
    # unittest prints the failures after a "=====" line: show those, not just the end
    first = next((i for i, line in enumerate(lines) if line.startswith("=" * 20)), None)
    if first is not None:
        lines = lines[first:]
    tail = "\n".join(lines[:LINES * 2] if first is not None else lines[-LINES:])
    # Annotations are one line: GitHub turns %0A back into line breaks
    body = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={title}::{body}", flush=True)


if __name__ == "__main__":
    with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
        annotate(sys.argv[1], f.read())
