"""
CI helper: tries the real screen guard parts on this machine (gamma dimming,
see-through windows, foreground window) and reports what works. Fails only if
something crashes; "not available" with a reason is fine.
"""

import os
import platform
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import display  # noqa: E402

BOUNDS = {"left": 0, "top": 0, "width": 800, "height": 600}


def check():
    results = []

    gamma, problem = display.open_gamma()
    if gamma:
        gamma.set(0.8)
        time.sleep(0.2)
        gamma.restore()
        results.append("gamma dimming: ok")
    else:
        results.append(f"gamma dimming: not available ({problem})")

    overlay, problem = display.open_overlay()
    if overlay:
        for _ in range(10):
            overlay.show([(0.1, 0.1, 0.4, 0.4)], 0.3, BOUNDS)
            overlay.pump()
            time.sleep(0.1)
        shown = overlay.current_alpha()
        overlay.close()
        results.append(f"see-through windows: ok (faded to {shown:.2f})")
    else:
        results.append(f"see-through windows: not available ({problem})")

    watcher = display.ForegroundWatcher()
    watcher.changed()
    results.append(f"foreground window: {'readable' if watcher.read() is not None else 'not readable'}")
    return results


if __name__ == "__main__":
    lines = check()
    print("\n".join(lines))
    if os.environ.get("GITHUB_ACTIONS"):
        title = f"Screen guard on {platform.system()} {os.environ.get('GUARD_ENV', '')}".strip()
        print(f"::notice title={title}::" + "%0A".join(lines))
