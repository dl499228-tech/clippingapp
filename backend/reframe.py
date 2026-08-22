"""Aspect-ratio reframing graphs (distortion-free).

Produces FFmpeg filter_complex chains that reframe a source into the target
aspect WITHOUT ever stretching it: we crop a window whose aspect already
matches the target, then scale uniformly. Supports:
  - face/crop mode with an eased virtual-camera path (x & y over time)
  - preserve mode (letterbox) for screen / gaming content
  - two-speaker split layouts (stacked / side-by-side)
  - original aspect (uniform scale only)
"""
from __future__ import annotations

from typing import List, Tuple


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
        "caption_preset": "none",         # captions OFF by default
        "caption_style": d["caption_preset"],  # remembered style when turned ON
        "caption_position": "bottom",
        "remove_pauses": False,
        "dynamic_effects": False,
        "reframe_mode": d["reframe_mode"],
        "two_speaker_layout": "off",      # off | stacked | sidebyside
        "start": None,
        "end": None,
    }


def _even(n) -> int:
    n = int(round(n))
    return n - (n % 2)


def target_dims(aspect: str, in_w: int, in_h: int) -> Tuple[int, int]:
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "1:1":
        return 1080, 1080
    long_side = max(in_w, in_h)
    scale = min(1.0, 1920.0 / long_side) if long_side else 1.0
    return _even(in_w * scale) or 2, _even(in_h * scale) or 2


def crop_window(aspect: str, in_w: int, in_h: int) -> Tuple[int, int]:
    """Largest window of the TARGET aspect that fits in the source."""
    tw, th = target_dims(aspect, in_w, in_h)
    ar = tw / th
    cw, ch = _even(in_h * ar), in_h
    if cw > in_w:
        cw, ch = in_w, _even(in_w / ar)
    return cw, min(ch, in_h)


def _panel_crop(in_w, in_h, panel_ar, cx, cy, headroom=0.28):
    cw, ch = _even(in_h * panel_ar), in_h
    if cw > in_w:
        cw, ch = in_w, _even(in_w / panel_ar)
    ch = min(ch, in_h)
    x = min(max(cx * in_w - cw / 2.0, 0), in_w - cw)
    y = min(max((cy - 0.5 * (ch / in_h)) * in_h - headroom * ch + ch * 0.5, 0), in_h - ch)
    y = min(max(cy * in_h - ch * (0.5 - headroom / 2), 0), in_h - ch)
    return cw, ch, _even(x), _even(y)


def _smoothstep_expr(kf: List[Tuple[float, float]]) -> str:
    """Piecewise smoothstep expression in `t`. Commas escaped for filtergraph."""
    if not kf:
        return "0"
    if len(kf) == 1:
        return f"{kf[0][1]:.1f}"
    expr = f"{kf[-1][1]:.1f}"
    for i in range(len(kf) - 2, -1, -1):
        t0, v0 = kf[i]
        t1, v1 = kf[i + 1]
        dt = t1 - t0
        if dt <= 1e-3:
            seg = f"{v1:.1f}"
        else:
            p = f"((t-{t0:.3f})/{dt:.3f})"
            ss = f"({p}*{p}*(3-2*{p}))"
            seg = f"({v0:.1f}+({v1 - v0:.1f})*{ss})"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    expr = f"if(lt(t,{kf[0][0]:.3f}),{kf[0][1]:.1f},{expr})"
    return expr.replace(",", "\\,")


def reframe_graph(aspect, mode, in_w, in_h, xkf, ykf) -> str:
    """filter_complex chain from [0:v] -> [vr] (target-sized, no distortion)."""
    tw, th = target_dims(aspect, in_w, in_h)
    if aspect == "original":
        return f"[0:v]scale={tw}:{th}:flags=lanczos,setsar=1[vr]"
    if mode == "preserve":
        return (f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[vr]")
    cw, ch = crop_window(aspect, in_w, in_h)
    xexpr = _smoothstep_expr(xkf) if xkf else str(_even((in_w - cw) / 2))
    yexpr = _smoothstep_expr(ykf) if ykf else str(_even((in_h - ch) / 2))
    return (f"[0:v]crop={cw}:{ch}:{xexpr}:{yexpr},"
            f"scale={tw}:{th}:flags=lanczos,setsar=1[vr]")


def split_graph(layout, aspect, in_w, in_h, left, right) -> str:
    """Two-speaker stacked / side-by-side layout (static, no distortion)."""
    tw, th = target_dims(aspect, in_w, in_h)
    if layout == "sidebyside":
        pw, ph, stack = tw // 2, th, "hstack=inputs=2"
        a, b = (left, right)                    # left speaker on the left
    else:  # stacked
        pw, ph, stack = tw, th // 2, "vstack=inputs=2"
        a, b = (left, right)                    # left speaker on top
    par = pw / ph
    cwa, cha, xa, ya = _panel_crop(in_w, in_h, par, a[0], a[1])
    cwb, chb, xb, yb = _panel_crop(in_w, in_h, par, b[0], b[1])
    return (
        f"[0:v]split=2[s0][s1];"
        f"[s0]crop={cwa}:{cha}:{xa}:{ya},scale={pw}:{ph}:flags=lanczos,setsar=1[p0];"
        f"[s1]crop={cwb}:{chb}:{xb}:{yb},scale={pw}:{ph}:flags=lanczos,setsar=1[p1];"
        f"[p0][p1]{stack},scale={tw}:{th},setsar=1[vr]"
    )


def zoom_chain(in_label, out_label, tw, th) -> str:
    """A single subtle push-in (1.00 -> 1.05 over ~1s, then held). Not oscillating."""
    return (f"{in_label}zoompan=z='min(1.05,1.0+0.05*on/30)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={tw}x{th}:fps=30{out_label}")
