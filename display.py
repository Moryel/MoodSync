"""
MoodSync platform code for the screen guard (guard.py):

  gamma:      dims the whole screen     macOS Quartz, Windows gdi32, Linux X11 RandR
  foreground: notices app/window/Space  macOS Quartz window list, Windows user32,
              switches                  Linux X11 _NET_ACTIVE_WINDOW
  overlay:    click-through dark        macOS AppKit, Windows layered windows,
              windows over white areas  Linux X11 (needs a compositor)

Wayland has no common way to do any of this, so the guard reports it and
stays off there. Every opener returns (object, None) or (None, reason).
"""

import ctypes
import json
import os
import sys
import time

BACKUP_FILE = os.path.join(os.path.expanduser("~"), ".moodsync", "gamma_backup.json")
FADE_SECONDS = 0.6          # Overlays fade in and out instead of popping


def _wayland() -> bool:
    return sys.platform.startswith("linux") and (
        os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland")


def _linux_problem():
    if _wayland():
        return "Wayland does not let programs change the screen this way (works on X11)"
    if not os.environ.get("DISPLAY"):
        return "no X11 display"
    try:
        import Xlib.display  # noqa: F401  (comes with pynput)
    except ImportError:
        return "python-xlib is not installed (pip install -r requirements.txt)"
    return None


# ----- gamma ---------------------------------------------------------------------

class _Gamma:
    """Scales the display's gamma curves by a factor (1 = normal)."""

    def __init__(self):
        self.factor = 1.0

    def set(self, factor: float):
        factor = max(0.0, min(1.0, factor))
        if abs(factor - self.factor) < 1e-3:
            return
        try:
            self._apply(factor)
            self.factor = factor
        except Exception:
            pass    # A refused ramp (e.g. Windows limits) just leaves the screen as it is

    def restore(self):
        if self.factor != 1.0:
            try:
                self._restore()
            except Exception:
                pass
            self.factor = 1.0
        _drop_backup()


def _save_backup(data):
    """Keeps the original curves on disk until restored, in case MoodSync is killed while dimmed."""
    try:
        os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)
        with open(BACKUP_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_backup():
    try:
        with open(BACKUP_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _drop_backup():
    try:
        os.remove(BACKUP_FILE)
    except OSError:
        pass


class _MacGamma(_Gamma):
    def __init__(self):
        super().__init__()
        import Quartz
        self.q = Quartz
        err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
        self.tables = {}
        for display in ids[:count]:
            capacity = Quartz.CGDisplayGammaTableCapacity(display)
            err, r, g, b, n = Quartz.CGGetDisplayTransferByTable(display, capacity, None, None, None, None)
            if err == 0 and n:
                self.tables[display] = (list(r[:n]), list(g[:n]), list(b[:n]))
        if not self.tables:
            raise RuntimeError("no display gamma tables")

    def _apply(self, f):
        for display, (r, g, b) in self.tables.items():
            self.q.CGSetDisplayTransferByTable(display, len(r), [v * f for v in r],
                                               [v * f for v in g], [v * f for v in b])

    def _restore(self):
        # Brings back the system's own curves (colour profile, Night Shift)
        self.q.CGDisplayRestoreColorSyncSettings()


class _WindowsGamma(_Gamma):
    def __init__(self):
        super().__init__()
        self.gdi = ctypes.windll.gdi32
        self.user = ctypes.windll.user32
        self.user.GetDC.restype = ctypes.c_void_p
        self.gdi.GetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi.SetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.dc = self.user.GetDC(None)
        backup = _load_backup()
        if backup and backup.get("platform") == "win32":
            # A previous run was killed while dimmed: put the screen back first
            self._write(backup["ramp"])
        self.ramp = self._read()
        if self.ramp is None:
            raise RuntimeError("the display driver does not allow gamma changes")
        if not self._write(self.ramp):
            raise RuntimeError("the display driver does not allow gamma changes")
        _save_backup({"platform": "win32", "ramp": self.ramp})

    def _read(self):
        ramp = (ctypes.c_ushort * 768)()
        if not self.gdi.GetDeviceGammaRamp(self.dc, ctypes.byref(ramp)):
            return None
        return list(ramp)

    def _write(self, values) -> bool:
        ramp = (ctypes.c_ushort * 768)(*[int(max(0, min(65535, v))) for v in values])
        return bool(self.gdi.SetDeviceGammaRamp(self.dc, ctypes.byref(ramp)))

    def _apply(self, f):
        # Windows refuses ramps far from normal; then the screen just is not dimmed as much
        if not self._write([v * f for v in self.ramp]):
            self._write([v * max(f, 0.5) for v in self.ramp])

    def _restore(self):
        self._write(self.ramp)


class _LinuxGamma(_Gamma):
    def __init__(self):
        super().__init__()
        from Xlib import display as xdisplay
        self.d = xdisplay.Display()
        if not self.d.has_extension("RANDR"):
            raise RuntimeError("the X server has no RandR extension")
        res = self.d.screen().root.xrandr_get_screen_resources()
        self.curves = {}
        backup = _load_backup()
        saved = {int(k): v for k, v in backup["curves"].items()} if backup and backup.get("platform") == "linux" else {}
        for crtc in res.crtcs:
            if self.d.xrandr_get_crtc_info(crtc, res.config_timestamp).mode == 0:
                continue    # Not driving a monitor
            if crtc in saved:
                self._write(crtc, saved[crtc])
            gamma = self.d.xrandr_get_crtc_gamma(crtc)
            if len(gamma.red):
                self.curves[crtc] = (list(gamma.red), list(gamma.green), list(gamma.blue))
        if not self.curves:
            raise RuntimeError("no monitor with an adjustable gamma curve")
        _save_backup({"platform": "linux", "curves": {str(k): v for k, v in self.curves.items()}})

    def _write(self, crtc, curves):
        r, g, b = ([int(max(0, min(65535, v))) for v in c] for c in curves)
        self.d.xrandr_set_crtc_gamma(crtc, len(r), r, g, b)
        self.d.sync()

    def _apply(self, f):
        for crtc, curves in self.curves.items():
            self._write(crtc, [[v * f for v in c] for c in curves])

    def _restore(self):
        for crtc, curves in self.curves.items():
            self._write(crtc, curves)


def open_gamma():
    try:
        if sys.platform == "darwin":
            return _MacGamma(), None
        if sys.platform == "win32":
            return _WindowsGamma(), None
        problem = _linux_problem()
        if problem:
            return None, problem
        return _LinuxGamma(), None
    except ImportError:
        return None, "pyobjc is not installed (pip install -r requirements.txt)"
    except Exception as e:
        return None, f"the screen brightness cannot be changed ({e})"


# ----- foreground window ------------------------------------------------------------

class ForegroundWatcher:
    """changed() is True when another app or window came to the front (or the Space changed)."""

    def __init__(self):
        self.last = None
        self.read = self._reader()

    def _reader(self):
        try:
            if sys.platform == "darwin":
                import Quartz
                opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
                me = os.getpid()

                def front():
                    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
                        if w.get("kCGWindowLayer") == 0 and w.get("kCGWindowOwnerPID") != me:
                            return w.get("kCGWindowNumber")
                    return None
                return front
            if sys.platform == "win32":
                user32 = ctypes.windll.user32
                user32.GetForegroundWindow.restype = ctypes.c_void_p
                return user32.GetForegroundWindow
            if _linux_problem():
                return lambda: None
            from Xlib import X, display as xdisplay
            d = xdisplay.Display()
            root = d.screen().root
            atom = d.intern_atom("_NET_ACTIVE_WINDOW")

            def active():
                prop = root.get_full_property(atom, X.AnyPropertyType)
                return prop.value[0] if prop and len(prop.value) else None
            return active
        except Exception:
            return lambda: None

    def changed(self) -> bool:
        try:
            current = self.read()
        except Exception:
            return False
        before, self.last = self.last, current
        return before is not None and current is not None and current != before


# ----- overlay windows ------------------------------------------------------------------

class _Overlay:
    """
    A pool of borderless, click-through black windows with a shared opacity.
    Subclasses create, place, fade, hide and destroy the actual windows.
    """

    def __init__(self):
        self.windows = []
        self.rects = []         # What is shown right now (screen fractions)
        self.alpha = 0.0        # Current opacity
        self.tick = None

    def current_alpha(self) -> float:
        return self.alpha

    def show(self, rects: list, alpha: float, bounds: dict):
        now = time.monotonic()
        dt, self.tick = (0.0 if self.tick is None else now - self.tick), now
        target = alpha if rects else 0.0

        if rects and rects != self.rects:
            # Place one window per area; keep spare windows hidden
            while len(self.windows) < len(rects):
                self.windows.append(self._create())
            for win, (x, y, w, h) in zip(self.windows, rects):
                self._place(win, bounds["left"] + x * bounds["width"], bounds["top"] + y * bounds["height"],
                            w * bounds["width"], h * bounds["height"])
            for win in self.windows[len(rects):]:
                self._hide(win)
            self.rects = list(rects)

        # Fade towards the target darkness
        step = dt / FADE_SECONDS * 0.5
        new = self.alpha + max(-step, min(step, target - self.alpha))
        if new != self.alpha:
            self.alpha = new
            for win in self.windows[:len(self.rects)]:
                self._set_alpha(win, self.alpha)
        if self.alpha <= 0 and self.rects and not rects:
            for win in self.windows:
                self._hide(win)
            self.rects = []

    def close(self):
        for win in self.windows:
            try:
                self._destroy(win)
            except Exception:
                pass
        self.windows = []
        self.rects = []
        self.pump()

    def pump(self):
        pass


class _MacOverlay(_Overlay):
    def __init__(self):
        super().__init__()
        import AppKit
        import Quartz
        self.ak = AppKit
        self.app = AppKit.NSApplication.sharedApplication()
        # No Dock icon, never takes focus away from your app
        self.app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        self.app.finishLaunching()
        self.main_height = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.height

    def _create(self):
        ak = self.ak
        win = ak.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ak.NSMakeRect(0, 0, 10, 10), ak.NSWindowStyleMaskBorderless, ak.NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(ak.NSColor.blackColor())
        win.setAlphaValue_(0.0)
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(False)
        win.setReleasedWhenClosed_(False)
        win.setLevel_(ak.NSStatusWindowLevel)
        win.setCollectionBehavior_(ak.NSWindowCollectionBehaviorCanJoinAllSpaces
                                   | ak.NSWindowCollectionBehaviorStationary
                                   | ak.NSWindowCollectionBehaviorIgnoresCycle
                                   | ak.NSWindowCollectionBehaviorFullScreenAuxiliary)
        return win

    def _place(self, win, x, y, w, h):
        # AppKit counts from the bottom of the main screen
        win.setFrame_display_(self.ak.NSMakeRect(x, self.main_height - y - h, w, h), True)
        win.orderFrontRegardless()

    def _set_alpha(self, win, a):
        win.setAlphaValue_(a)

    def _hide(self, win):
        win.orderOut_(None)

    def _destroy(self, win):
        win.orderOut_(None)
        win.close()

    def pump(self):
        ak = self.ak
        while True:
            event = self.app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                ak.NSEventMaskAny, ak.NSDate.distantPast(), ak.NSDefaultRunLoopMode, True)
            if event is None:
                break
            self.app.sendEvent_(event)


class _WindowsOverlay(_Overlay):
    WS_POPUP = 0x80000000
    WS_EX = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
    # layered | transparent (click-through) | topmost | tool window (no taskbar) | no activate

    def __init__(self):
        super().__init__()
        from ctypes import wintypes
        self.u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        g = ctypes.windll.gdi32
        u = self.u
        LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        g.GetStockObject.restype = wintypes.HGDIOBJ
        k.GetModuleHandleW.restype = wintypes.HMODULE

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        self.proc = self.WNDPROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))   # Kept alive here
        self.hinst = k.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self.proc, hInstance=self.hinst,
                       hbrBackground=g.GetStockObject(4),   # BLACK_BRUSH
                       lpszClassName="MoodSyncDim")
        u.RegisterClassW(ctypes.byref(wc))
        self.msg = wintypes.MSG()

    def _create(self):
        hwnd = self.u.CreateWindowExW(self.WS_EX, "MoodSyncDim", "MoodSync", self.WS_POPUP,
                                      0, 0, 10, 10, None, None, self.hinst, None)
        if not hwnd:
            raise OSError("CreateWindowExW failed")
        self.u.SetLayeredWindowAttributes(hwnd, 0, 0, 2)   # LWA_ALPHA, start invisible
        return hwnd

    def _place(self, hwnd, x, y, w, h):
        # HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW
        self.u.SetWindowPos(hwnd, ctypes.c_void_p(-1), int(x), int(y), int(w), int(h), 0x0010 | 0x0040)

    def _set_alpha(self, hwnd, a):
        self.u.SetLayeredWindowAttributes(hwnd, 0, int(a * 255), 2)

    def _hide(self, hwnd):
        self.u.ShowWindow(hwnd, 0)

    def _destroy(self, hwnd):
        self.u.DestroyWindow(hwnd)

    def pump(self):
        msg = ctypes.byref(self.msg)
        while self.u.PeekMessageW(msg, None, 0, 0, 1):   # PM_REMOVE
            self.u.TranslateMessage(msg)
            self.u.DispatchMessageW(msg)


class _LinuxOverlay(_Overlay):
    def __init__(self):
        super().__init__()
        from Xlib import X, Xatom, display as xdisplay
        self.X, self.Xatom = X, Xatom
        self.d = xdisplay.Display()
        screen = self.d.screen()
        self.screen = screen
        owner = self.d.get_selection_owner(self.d.intern_atom(f"_NET_WM_CM_S{self.d.get_default_screen()}"))
        if not owner or owner == X.NONE:
            raise RuntimeError("no compositor is running, see-through windows are not possible")
        if not self.d.has_extension("SHAPE"):
            raise RuntimeError("the X server has no SHAPE extension")
        self.opacity = self.d.intern_atom("_NET_WM_WINDOW_OPACITY")

    def _create(self):
        from Xlib.ext import shape
        X = self.X
        win = self.screen.root.create_window(0, 0, 10, 10, 0, self.screen.root_depth, X.InputOutput,
                                             X.CopyFromParent, background_pixel=self.screen.black_pixel,
                                             override_redirect=True)
        win.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])   # Clicks pass through
        self._set_alpha(win, 0.0)
        return win

    def _place(self, win, x, y, w, h):
        win.configure(x=int(x), y=int(y), width=max(1, int(w)), height=max(1, int(h)), stack_mode=self.X.Above)
        win.map()
        self.d.flush()

    def _set_alpha(self, win, a):
        win.change_property(self.opacity, self.Xatom.CARDINAL, 32, [int(a * 0xFFFFFFFF)])
        self.d.flush()

    def _hide(self, win):
        win.unmap()
        self.d.flush()

    def _destroy(self, win):
        win.destroy()
        self.d.flush()

    def pump(self):
        while self.d.pending_events():
            self.d.next_event()


def open_overlay():
    try:
        if sys.platform == "darwin":
            return _MacOverlay(), None
        if sys.platform == "win32":
            return _WindowsOverlay(), None
        problem = _linux_problem()
        if problem:
            return None, problem
        return _LinuxOverlay(), None
    except ImportError:
        return None, "pyobjc is not installed (pip install -r requirements.txt)"
    except Exception as e:
        return None, f"see-through windows cannot be created ({e})"
