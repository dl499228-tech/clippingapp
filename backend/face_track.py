"""Subject detection + virtual-camera path for professional vertical reframing.

- Samples faces (OpenCV YuNet) across a clip; returns ALL faces per sample.
- Builds a smooth "virtual camera" path (crop top-left x/y over time) that HOLDS
  on a subject and only GLIDES (eased) when the subject meaningfully moves.
- Detects a stable two-speaker arrangement (for optional split layouts).
- Motion-saliency fallback (frame differencing) to follow the action when no
  faces are present (UGC / product / gameplay-with-no-face).

Nothing here ever changes the source proportions; it only decides crop windows.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import cv2
import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), "assets", "face_detection_yunet.onnx")


def _detector(w, h):
    return cv2.FaceDetectorYN.create(MODEL_PATH, "", (w, h), 0.6, 0.3, 5000)


def sample_faces(video_path: str, start: float, end: float,
                 sample_fps: float = 4.0, max_samples: int = 400) -> List[dict]:
    """Return [{t, faces:[(cx,cy,w,h) normalized, area-desc]}] over [start,end]."""
    if not os.path.exists(MODEL_PATH):
        return []
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        det = _detector(vw, vh)
        det.setInputSize((vw, vh))
        dur = max(0.1, end - start)
        step = 1.0 / max(0.5, sample_fps)
        out, t = [], 0.0
        while t <= dur and len(out) < max_samples:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                fh, fw = frame.shape[:2]
                if (fw, fh) != (vw, vh):
                    det.setInputSize((fw, fh))
                try:
                    _, faces = det.detect(frame)
                except cv2.error:
                    faces = None
                fl = []
                if faces is not None:
                    for f in faces:
                        x, y, w, h = float(f[0]), float(f[1]), float(f[2]), float(f[3])
                        if w <= 0 or h <= 0:
                            continue
                        fl.append((float(np.clip((x + w / 2) / fw, 0, 1)),
                                   float(np.clip((y + h / 2) / fh, 0, 1)),
                                   float(np.clip(w / fw, 0, 1)),
                                   float(np.clip(h / fh, 0, 1))))
                fl.sort(key=lambda z: z[2] * z[3], reverse=True)
                out.append({"t": t, "faces": fl})
            t += step
        cap.release()
        return out
    except Exception:  # noqa: BLE001
        return []


def sample_motion_centers(video_path: str, start: float, end: float,
                          sample_fps: float = 4.0, max_samples: int = 400) -> List[Tuple[float, float]]:
    """Return [(t, cx_norm)] of the horizontal centre of motion (frame diff)."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        dur = max(0.1, end - start)
        step = 1.0 / max(0.5, sample_fps)
        out, t, prev = [], 0.0, None
        while t <= dur and len(out) < max_samples:
            cap.set(cv2.CAP_PROP_POS_MSEC, (start + t) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
                if prev is not None:
                    diff = cv2.absdiff(small, prev)
                    col = diff.sum(axis=0).astype(np.float64)
                    total = col.sum()
                    if total > 1e-3:
                        cx = float((col * np.arange(col.size)).sum() / total / col.size)
                        out.append((t, float(np.clip(cx, 0, 1))))
                prev = small
            t += step
        cap.release()
        return out
    except Exception:  # noqa: BLE001
        return []


def detect_two_speakers(samples: List[dict], min_support: float = 0.4
                        ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """If two horizontally-separated faces persist, return ((lx,ly),(rx,ry))."""
    two = [s for s in samples if len(s["faces"]) >= 2]
    if not samples or len(two) < len(samples) * min_support:
        return None
    lefts, rights = [], []
    for s in two:
        top2 = sorted(s["faces"][:2], key=lambda z: z[0])
        lefts.append((top2[0][0], top2[0][1]))
        rights.append((top2[1][0], top2[1][1]))
    lx = float(np.median([p[0] for p in lefts]))
    ly = float(np.median([p[1] for p in lefts]))
    rx = float(np.median([p[0] for p in rights]))
    ry = float(np.median([p[1] for p in rights]))
    if abs(rx - lx) < 0.22:   # too close together -> a single crop is better
        return None
    return ((lx, ly), (rx, ry))


def _pick_active(faces, prev_cx):
    """Choose the subject face: largest, with hysteresis toward the previous one."""
    if not faces:
        return None
    if prev_cx is None:
        return faces[0]
    best, score = faces[0], -1.0
    for f in faces:
        cx, cy, w, h = f
        area = w * h
        proximity = 1.0 - min(1.0, abs(cx - prev_cx) / 0.5)
        s = area * (0.6 + 0.4 * proximity)
        if s > score:
            best, score = f, s
    return best


def _smooth(series: List[Optional[float]], times: List[float], win: float = 0.8) -> List[float]:
    """Forward-fill Nones then time-window moving average."""
    filled, last = [], None
    for v in series:
        if v is None:
            v = last
        filled.append(v if v is not None else 0.5)
        if v is not None:
            last = v
    # back-fill leading Nones
    firstval = next((v for v in filled if v is not None), 0.5)
    filled = [firstval if v is None else v for v in filled]
    out = []
    for i, t in enumerate(times):
        lo = hi = i
        while lo > 0 and t - times[lo - 1] <= win:
            lo -= 1
        while hi < len(times) - 1 and times[hi + 1] - t <= win:
            hi += 1
        out.append(sum(filled[lo:hi + 1]) / (hi - lo + 1))
    return out


def _camera_1d(times, vals, lo, hi, deadband, trans=0.6, min_hold=0.7, duration=0.0):
    """Hold-and-ease keyframe path in [lo,hi]. Returns [(t, value)]."""
    sm = _smooth(vals, times)
    sm = [float(np.clip(v, lo, hi)) for v in sm]
    if not sm:
        return [(0.0, (lo + hi) / 2), (duration, (lo + hi) / 2)]
    held = sm[0]
    kf = [(0.0, held)]
    last_move = -min_hold
    for i in range(1, len(sm)):
        t = times[i]
        if abs(sm[i] - held) > deadband and (t - last_move) >= min_hold:
            kf.append((t, held))
            kf.append((min(t + trans, duration or t + trans), sm[i]))
            held = sm[i]
            last_move = t + trans
    kf.append((duration or times[-1], held))
    # de-dup times
    dedup = []
    for t, v in kf:
        if dedup and abs(dedup[-1][0] - t) < 1e-3:
            dedup[-1] = (t, v)
        else:
            dedup.append((t, v))
    return dedup


def build_camera_path(samples: List[dict], duration: float, in_w: int, in_h: int,
                      crop_w: int, crop_h: int, headroom: float = 0.30
                      ) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Return (x_keyframes, y_keyframes) for the crop TOP-LEFT in source pixels."""
    max_x = max(0, in_w - crop_w)
    max_y = max(0, in_h - crop_h)
    times, xs, ys = [], [], []
    prev_cx = None
    for s in samples:
        times.append(s["t"])
        face = _pick_active(s["faces"], prev_cx)
        if face is None:
            xs.append(None)
            ys.append(None)
            continue
        cx, cy, fw, fh = face
        prev_cx = cx
        # horizontal: centre the face
        x = cx * in_w - crop_w / 2.0
        # vertical: leave headroom so the face sits in the upper third
        face_top = (cy - fh / 2.0) * in_h
        y = face_top - headroom * crop_h
        xs.append(float(np.clip(x, 0, max_x)))
        ys.append(float(np.clip(y, 0, max_y)))
    if not times:
        return ([(0.0, max_x / 2), (duration, max_x / 2)],
                [(0.0, max_y / 2), (duration, max_y / 2)])
    xkf = _camera_1d(times, xs, 0, max_x, deadband=max(8.0, in_w * 0.045), duration=duration)
    ykf = _camera_1d(times, ys, 0, max_y, deadband=max(8.0, in_h * 0.06),
                     trans=0.8, min_hold=1.0, duration=duration)
    return xkf, ykf


def motion_camera_path(motion, duration, in_w, in_h, crop_w, crop_h):
    max_x = max(0, in_w - crop_w)
    max_y = max(0, in_h - crop_h)
    if not motion:
        return ([(0.0, max_x / 2), (duration, max_x / 2)],
                [(0.0, max_y / 2), (duration, max_y / 2)])
    times = [t for t, _ in motion]
    xs = [float(np.clip(cx * in_w - crop_w / 2.0, 0, max_x)) for _, cx in motion]
    xkf = _camera_1d(times, xs, 0, max_x, deadband=max(8.0, in_w * 0.06),
                     trans=0.8, min_hold=1.2, duration=duration)
    ykf = [(0.0, max_y / 2), (duration, max_y / 2)]
    return xkf, ykf
