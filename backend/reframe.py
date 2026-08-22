"""Aspect-ratio reframing (9:16 / 1:1 / original).

Builds the FFmpeg video-filter chain that turns a landscape (or any) source
into the target aspect. For talking-head content it uses smoothed face
keyframes to keep the speaker in frame with gentle motion; for screen/gaming
content it pads (letterboxes) so nothing important is cropped away.
"""
from __future__ import annotations

from typing import List, Tuple


# Content-aware editing defaults. Reframe mode "preserve" = pad (screen/gaming).
_CONTENT_DEFAULTS = {
    "podcast":       {"reframe_mode": "face", "caption_preset": "clean"},
    "interview":     {"reframe_mode": "face", "caption_preset": "clean"},
    "vlog":          {"reframe_mode": "face", "caption_preset": "bold"},
    "entertainment": {"reframe_mode": "face", "caption_preset": "bold"},
    "educational":   {"reframe_mode": "face", "caption_preset": "clean"},
    "gaming":        {"reframe_mode": "preserve", "caption_preset": "clean"},
    "livestream":    {"reframe_mode": "preserve", "caption_preset": "clean"},
    "sports":        {"reframe_mode": "preserve", "caption_preset": "bold"},
    "other":         {"reframe_mode": "face", "caption_preset": "clean"},
    "auto":          {"reframe_mode": "face", "caption_preset": "clean"},
}


def default_edit_settings(content_type: str) -> dict:
    d = _CONTENT_DEFAULTS.get(content_type or "auto", _CONTENT_DEFAULTS["auto"])
    return {
        "aspect_ratio": "9:16",
        "caption_preset": d["caption_preset"],
        "caption_position": "bottom",
        "remove_pauses": False,       # conservative default
        "dynamic_effects": False,     # off by default (quality over effects)
        "reframe_mode": d["reframe_mode"],
        "start": None,
        "end": None,
    }


def target_dims(aspect: str, in_w: int, in_h: int) -> Tuple[int, int]:
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "1:1":
        return 1080, 1080
    # original: cap long side at 1920, keep even dims
    long_side = max(in_w, in_h)
    scale = min(1.0, 1920.0 / long_side) if long_side else 1.0
    tw = int(round(in_w * scale / 2) * 2) or 2
    th = int(round(in_h * scale / 2) * 2) or 2
    return tw, th


def _even(n: int) -> int:
    n = int(round(n))
    return n - (n % 2)


def _piecewise_x(kf: List[Tuple[float, float]], in_w: int, crop_w: int) -> str:
    """Build an FFmpeg crop-x expression (in source pixels) from (t, cx_norm)."""
    max_x = max(0, in_w - crop_w)

    def x_of(cx):
        return max(0.0, min(float(max_x), cx * in_w - crop_w / 2.0))

    if not kf:
        return f"{_even(max_x // 2)}"
    if len(kf) == 1:
        return f"{x_of(kf[0][1]):.1f}"

    expr = f"{x_of(kf[-1][1]):.1f}"
    for i in range(len(kf) - 2, -1, -1):
        t0, c0 = kf[i]
        t1, c1 = kf[i + 1]
        x0, x1 = x_of(c0), x_of(c1)
        dt = max(t1 - t0, 0.001)
        seg = f"({x0:.1f}+({x1 - x0:.3f})*(t-{t0:.3f})/{dt:.3f})"
        expr = f"if(lt(t\\,{t1:.3f})\\,{seg}\\,{expr})"
    expr = f"if(lt(t\\,{kf[0][0]:.3f})\\,{x_of(kf[0][1]):.1f}\\,{expr})"
    return expr


def build_reframe_filter(aspect: str, reframe_mode: str, in_w: int, in_h: int,
                         face_kf: List[Tuple[float, float]]) -> str:
    """Return an FFmpeg -vf chain (string) producing target-sized frames.

    Does NOT include captions or dynamic zoom (added by the renderer).
    """
    tw, th = target_dims(aspect, in_w, in_h)

    if aspect == "original":
        return f"scale={tw}:{th}:flags=lanczos,setsar=1"

    target_ar = tw / th

    # "preserve": letterbox the whole frame (screen/gaming) - lose nothing.
    if reframe_mode == "preserve":
        return (f"scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")

    # "face"/crop: crop a target-AR window, follow the speaker horizontally.
    crop_h = in_h
    crop_w = _even(in_h * target_ar)
    if crop_w > in_w:
        crop_w = in_w
        crop_h = _even(in_w / target_ar)
    crop_h = min(crop_h, in_h)
    y = _even(max(0, (in_h - crop_h) / 2))
    xexpr = _piecewise_x(face_kf, in_w, crop_w)
    return (f"crop={crop_w}:{crop_h}:{xexpr}:{y},"
            f"scale={tw}:{th}:flags=lanczos,setsar=1")


def zoom_filter(tw: int, th: int) -> str:
    """A subtle, professional slow oscillating punch-in (optional)."""
    return (f"zoompan=z='1.04+0.03*sin(on/60)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={tw}x{th}:fps=30")
