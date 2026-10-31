"""
CI helper: shows the end of a failed step's output as a GitHub annotation, so
the reason is visible on the run page without signing in to read the logs.

    python tests/ci_annotate.py "Unit tests" output.log
"""

import sys

LINES = 40


def annotate(title: str, text: str):
    tail = "\n".join(text.strip().splitlines()[-LINES:])
    # Annotations are one line: GitHub turns %0A back into line breaks
    body = tail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={title}::{body}", flush=True)


if __name__ == "__main__":
    with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
        annotate(sys.argv[1], f.read())
