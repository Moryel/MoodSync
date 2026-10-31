"""
MoodSync optional camera tiredness detection (--camera).

Uses MediaPipe's face landmarker on the webcam image to watch three classic
drowsiness signs:

  eye closure:  share of time the eyes are closed (PERCLOS). Rested people
                are around 5% (normal blinking), drowsy people well above 15%.
  long blinks:  eye closures longer than 0.4 s
  yawns:        mouth wide open for more than 1.5 s

It also counts blinks: people blink about 15-20 times a minute, but often
less than half as much while looking at a screen, which dries the eyes. When
the rate stays low, MoodSync reminds you to blink (BlinkReminder).

Frames are processed in memory a few times a second and never saved. The face
model (about 4 MB) is downloaded once to ~/.moodsync/ on first use.
"""

import os
import threading
import time
import urllib.request
from collections import deque

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_FILE = os.path.join(os.path.expanduser("~"), ".moodsync", "face_landmarker.task")

FRAME_INTERVAL = 1 / 15     # Seconds between analysed frames (fast enough to see short blinks)
EYE_WINDOW = 60             # Eye closure is judged over the last minute
YAWN_WINDOW = 300           # Yawns are counted over the last 5 minutes
EYES_CLOSED = 0.5           # Blink blendshape above this = eyes closed
JAW_OPEN = 0.6              # Jaw blendshape above this = mouth wide open
LONG_BLINK = 0.4            # Closures longer than this (s) are long blinks
YAWN_SECONDS = 1.5          # Mouth open longer than this = a yawn
MIN_FACE_SHARE = 0.5        # Face must be seen at least this often to judge
MAX_BLINK = 1.0             # Closures longer than this are not blinks (looking down, eyes shut)
LOW_BLINK_RATE = 8          # Blinks per minute below this are too few
LOW_BLINK_SECONDS = 120     # ...for this long before reminding
BLINK_REMINDER_COOLDOWN = 600   # At most one reminder every 10 minutes


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class EyeTracker:
    """
    Turns per-frame face readings into a tiredness score. Pure logic, fed with
    (time, eyes closed score, jaw open score) so it can be tested without a camera.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.frames = deque()        # (time, face seen, eyes closed)
        self.long_blinks = deque()   # end times of long closures
        self.blinks = deque()        # end times of all blinks
        self.yawns = deque()         # end times of yawns
        self.closed_since = None
        self.open_mouth_since = None

    def add(self, now: float, eyes=None, jaw=None):
        """One analysed frame. eyes/jaw are 0-1 blendshape scores, None = no face."""
        with self.lock:
            face = eyes is not None
            closed = face and eyes >= EYES_CLOSED
            self.frames.append((now, face, closed))

            if closed and self.closed_since is None:
                self.closed_since = now
            elif not closed and self.closed_since is not None:
                closed_for = now - self.closed_since
                if face and closed_for <= MAX_BLINK:
                    self.blinks.append(now)
                if face and closed_for >= LONG_BLINK:
                    self.long_blinks.append(now)
                self.closed_since = None

            mouth_open = face and jaw is not None and jaw >= JAW_OPEN
            if mouth_open and self.open_mouth_since is None:
                self.open_mouth_since = now
            elif not mouth_open and self.open_mouth_since is not None:
                if now - self.open_mouth_since >= YAWN_SECONDS:
                    self.yawns.append(now)
                self.open_mouth_since = None

            while self.frames and self.frames[0][0] < now - EYE_WINDOW:
                self.frames.popleft()
            while self.long_blinks and self.long_blinks[0] < now - EYE_WINDOW:
                self.long_blinks.popleft()
            while self.blinks and self.blinks[0] < now - EYE_WINDOW:
                self.blinks.popleft()
            while self.yawns and self.yawns[0] < now - YAWN_WINDOW:
                self.yawns.popleft()

    def readings(self, now: float):
        """Returns (eye closure share, long blinks/min, yawns in 5 min) or None if the face was not seen enough."""
        with self.lock:
            frames = [f for f in self.frames if f[0] >= now - EYE_WINDOW]
            seen = [f for f in frames if f[1]]
            if len(frames) < 50 or len(seen) < MIN_FACE_SHARE * len(frames):
                return None
            closure = sum(1 for f in seen if f[2]) / len(seen)
            return closure, len(self.long_blinks), len(self.yawns)

    def blink_rate(self, now: float):
        """Blinks in the last minute, or None if the face was not seen for most of it."""
        with self.lock:
            frames = [f for f in self.frames if f[0] >= now - EYE_WINDOW]
            if not frames or frames[0][0] > now - EYE_WINDOW * 0.9:
                return None      # Less than a full minute watched yet
            seen = sum(1 for f in frames if f[1])
            if seen < 0.8 * len(frames):
                return None
            return len(self.blinks) * len(frames) / seen   # Scale up for moments the face was lost

    def score(self, now: float):
        """0 = alert, 1 = drowsy; None when the camera cannot tell (no face, too few frames)."""
        values = self.readings(now)
        if values is None:
            return None
        closure, long_blinks, yawns = values
        return (0.5 * clamp((closure - 0.08) / 0.12)
                + 0.25 * clamp(long_blinks / 3)
                + 0.25 * clamp(yawns / 2))


class BlinkReminder:
    """Decides when to remind about blinking: rate low for a while, not too often."""

    def __init__(self):
        self.low_since = None
        self.last = float("-inf")

    def update(self, now: float, rate) -> bool:
        if rate is None or rate >= LOW_BLINK_RATE:
            self.low_since = None
            return False
        if self.low_since is None:
            self.low_since = now
        if now - self.low_since >= LOW_BLINK_SECONDS and now - self.last >= BLINK_REMINDER_COOLDOWN:
            self.last = now
            self.low_since = None
            return True
        return False


def ensure_model() -> str:
    """Downloads the face model on first use and returns its path."""
    if not os.path.exists(MODEL_FILE):
        os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
        print("Downloading the face model (about 4 MB, only once)...")
        partial = MODEL_FILE + ".part"
        urllib.request.urlretrieve(MODEL_URL, partial)
        os.replace(partial, MODEL_FILE)
    return MODEL_FILE


class CameraWatcher:
    """Reads the webcam in a background thread and feeds an EyeTracker."""

    def __init__(self, index: int = 0):
        self.index = index
        self.tracker = EyeTracker()
        self.stopped = threading.Event()
        self.problem = None
        self.thread = None

    def start(self):
        """Opens the camera and the face model. Returns an error message, or None when it works."""
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError:
            return "mediapipe is not installed (pip install mediapipe)"

        try:
            model = ensure_model()
        except OSError as e:
            return f"the face model could not be downloaded ({e})"

        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
        )
        try:
            landmarker = vision.FaceLandmarker.create_from_options(options)
        except Exception as e:
            return f"the face model could not be loaded ({e})"

        capture = cv2.VideoCapture(self.index)
        if not capture.isOpened():
            landmarker.close()
            return (f"camera {self.index} could not be opened (on macOS allow your terminal under "
                    "System Settings -> Privacy & Security -> Camera)")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.thread = threading.Thread(target=self._run, args=(cv2, mp, capture, landmarker), daemon=True)
        self.thread.start()
        return None

    def _run(self, cv2, mp, capture, landmarker):
        started = time.monotonic()
        try:
            while not self.stopped.is_set():
                tick = time.monotonic()
                ok, frame = capture.read()
                if not ok:
                    self.problem = "the camera stopped sending images"
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, int((tick - started) * 1000))
                eyes = jaw = None
                if result.face_blendshapes:
                    shapes = {c.category_name: c.score for c in result.face_blendshapes[0]}
                    eyes = (shapes.get("eyeBlinkLeft", 0) + shapes.get("eyeBlinkRight", 0)) / 2
                    jaw = shapes.get("jawOpen", 0)
                self.tracker.add(tick, eyes, jaw)
                self.stopped.wait(max(0.0, FRAME_INTERVAL - (time.monotonic() - tick)))
        finally:
            capture.release()
            landmarker.close()

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
