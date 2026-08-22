"""Active-speaker face sampling using OpenCV YuNet.

Samples faces across a clip's time range and produces smoothed horizontal
keyframes used to build a 9:16 reframe that keeps the speaker in frame.
Pure best-effort: if detection fails or finds nothing, callers fall back to a
static center crop.
"""
from __future__ import annotations

import os
from typing import List, Tuple

import cv2
import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), "assets", "face_detection_yunet.onnx")


def _load_detector(w: int, h: int):
    det = cv2.FaceDetectorYN.create(MODEL_PATH, "", (w, h), 0.6, 0.3, 5000)
    return det


def sample_face_centers(video_path: str, start: float, end: float,
                        sample_fps: float = 2.0, max_samples: int = 240
                        ) -> List[Tuple[float, float, float]]:
    """Return [(t_rel, cx_norm, cy_norm)] samples where a face was found.

    t_rel is seconds relative to `start`; cx/cy are normalized 0..1 centers.
    Returns [] on any failure (caller falls back to static crop).
    """
    if not os.path.exists(MODEL_PATH):
        return []
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        detector = _load_detector(vw, vh)
        detector.setInputSize((vw, vh))

        duration = max(0.1, end - start)
        step = 1.0 / max(0.5, sample_fps)
        times = []
        t = 0.0
        while t <= duration and len(times) < max_samples:
            times.append(t)
            t += step

        out: List[Tuple[float, float, float]] = []
        for tr in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + tr) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            fh, fw = frame.shape[:2]
            if (fw, fh) != (vw, vh):
                detector.setInputSize((fw, fh))
            try:
                _, faces = detector.detect(frame)
            except cv2.error:
                continue
            if faces is None or len(faces) == 0:
                continue
            # Choose the largest (most prominent) face as the active speaker.
            best = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = best[0], best[1], best[2], best[3]
            cx = (x + w / 2.0) / fw
            cy = (y + h / 2.0) / fh
            out.append((tr, float(np.clip(cx, 0, 1)), float(np.clip(cy, 0, 1))))
        cap.release()
        return out
    except Exception:  # noqa: BLE001
        return []


def smooth_keyframes(samples: List[Tuple[float, float, float]], duration: float,
                     max_keyframes: int = 20, move_threshold: float = 0.04
                     ) -> List[Tuple[float, float]]:
    """Turn raw samples into a few smoothed (t, cx_norm) keyframes.

    Applies a moving average, then only emits a keyframe when the smoothed
    center moves more than `move_threshold` -> gentle motion, no jitter.
    Returns [] if there is nothing usable.
    """
    if not samples:
        return []
    xs = [s[1] for s in samples]
    ts = [s[0] for s in samples]
    # moving average window 3
    sm = []
    for i in range(len(xs)):
        lo = max(0, i - 2)
        sm.append(sum(xs[lo:i + 1]) / (i - lo + 1))

    kf: List[Tuple[float, float]] = [(0.0, sm[0])]
    for i in range(1, len(sm)):
        if abs(sm[i] - kf[-1][1]) >= move_threshold:
            kf.append((ts[i], sm[i]))
    kf.append((duration, sm[-1]))

    # Downsample if too many keyframes.
    if len(kf) > max_keyframes:
        idx = np.linspace(0, len(kf) - 1, max_keyframes).astype(int)
        kf = [kf[i] for i in sorted(set(idx))]
    return kf
