"""Final render orchestration (post-production).

Takes a candidate clip + edit settings and produces a polished, social-ready
MP4 using FFmpeg. Combines: boundary trim, optional silence removal, aspect
reframing (face-tracked crop or letterbox), optional subtle motion, and burned
word-timed captions.

Layered fallbacks keep a render usable even when a feature fails:
  full -> without motion -> without captions -> plain reframe.

Analysis/transcription are NEVER re-run here; only ffmpeg + local caption
timing are used, so re-rendering with new settings is cheap.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Tuple

import captions as caps
from face_track import sample_face_centers, smooth_keyframes
from reframe import build_reframe_filter, zoom_filter, target_dims


class RenderError(Exception):
    pass


def _run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Silence / pause handling
# ---------------------------------------------------------------------------
def detect_silences(src: str, start: float, dur: float,
                    noise_db: int = -30, min_sil: float = 0.6) -> List[Tuple[float, float]]:
    cmd = ["ffmpeg", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_sil}", "-f", "null", "-"]
    res = _run(cmd, timeout=600)
    text = res.stderr or ""
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    pairs = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else dur
        pairs.append((max(0.0, s), min(dur, e)))
    return pairs


def build_keep_ranges(silences, dur, pad: float = 0.15) -> List[Tuple[float, float]]:
    removed = []
    for (s, e) in silences:
        a, b = s + pad, e - pad
        if b - a > 0.05:
            removed.append((a, b))
    keep, cur = [], 0.0
    for (a, b) in sorted(removed):
        if a > cur:
            keep.append((cur, a))
        cur = max(cur, b)
    if cur < dur:
        keep.append((cur, dur))
    return keep or [(0.0, dur)]


def remap(t: float, keep) -> float:
    acc = 0.0
    for (a, b) in keep:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


def _desilence(src, start, dur, keep, workdir) -> Tuple[str, float]:
    """Produce an intermediate clip with long pauses removed. Returns (path, out_dur)."""
    out = os.path.join(workdir, "desilenced.mp4")
    vexpr = "+".join([f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in keep])
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src,
           "-vf", f"select={vexpr},setpts=N/FRAME_RATE/TB",
           "-af", f"aselect={vexpr},asetpts=N/SR/TB",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-c:a", "aac", "-b:a", "192k", out]
    res = _run(cmd)
    if res.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        raise RenderError(f"Pause removal failed: {res.stderr[-200:]}")
    out_dur = sum(b - a for a, b in keep)
    return out, out_dur


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------
def build_caption_lines(job: dict, start: float, end: float, workdir: str) -> List[dict]:
    words = caps.extract_clip_words(job, start, end, workdir)
    return caps.group_words_to_lines(words)


def _remap_lines(lines, keep) -> List[dict]:
    out = []
    for ln in lines:
        s = remap(ln["start"], keep)
        e = remap(ln["end"], keep)
        if e - s < 0.05:
            continue
        rwords = []
        for w in ln.get("words", []):
            ws, we = remap(w["start"], keep), remap(w["end"], keep)
            if we - ws > 0.01:
                rwords.append({"start": ws, "end": we, "word": w["word"]})
        out.append({"start": s, "end": e, "text": ln["text"], "words": rwords})
    return out


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
def render_clip(job: dict, clip: dict, out_path: str, workdir: str) -> dict:
    os.makedirs(workdir, exist_ok=True)
    edit = clip.get("edit") or {}
    src = job["video_path"]
    meta = job.get("metadata", {})
    in_w = int(meta.get("width") or 1280)
    in_h = int(meta.get("height") or 720)

    start = edit.get("start")
    end = edit.get("end")
    start = clip["start"] if start is None else float(start)
    end = clip["end"] if end is None else float(end)
    if end <= start:
        raise RenderError("Invalid boundaries: end must be after start")
    dur = end - start

    aspect = edit.get("aspect_ratio", "9:16")
    mode = edit.get("reframe_mode", "face")
    preset = edit.get("caption_preset", "clean")
    position = edit.get("caption_position", "bottom")
    remove_pauses = bool(edit.get("remove_pauses"))
    dynamic = bool(edit.get("dynamic_effects"))

    # 1) Pauses -> optional intermediate
    keep = [(0.0, dur)]
    base_video, base_ss, out_dur = src, start, dur
    if remove_pauses:
        sil = detect_silences(src, start, dur)
        keep = build_keep_ranges(sil, dur)
        kept_dur = sum(b - a for a, b in keep)
        if keep != [(0.0, dur)] and kept_dur < dur - 0.2:
            try:
                base_video, out_dur = _desilence(src, start, dur, keep, workdir)
                base_ss = 0.0
            except RenderError:
                keep = [(0.0, dur)]  # fall back to no trimming
        else:
            keep = [(0.0, dur)]

    # 2) Captions (word-timed), remapped onto the output timeline
    lines = clip.get("captions") or build_caption_lines(job, start, end, workdir)
    rlines = _remap_lines(lines, keep)
    tw, th = target_dims(aspect, in_w, in_h)
    ass_path = None
    if preset != "none" and rlines:
        try:
            ass = caps.build_ass(rlines, preset, position, tw, th)
            ass_path = os.path.join(workdir, "captions.ass")
            with open(ass_path, "w") as f:
                f.write(ass)
        except Exception:  # noqa: BLE001
            ass_path = None

    # 3) Face keyframes for reframing (best-effort)
    kf = []
    if aspect != "original" and mode == "face":
        samples = sample_face_centers(base_video, base_ss, base_ss + out_dur)
        kf = smooth_keyframes(samples, out_dur)

    reframe_vf = build_reframe_filter(aspect, mode, in_w, in_h, kf)

    # 4) Assemble filter variants (progressive fallback)
    variants = []
    def compose(rf, use_zoom, use_caps):
        parts = [rf]
        if use_zoom:
            parts.append(zoom_filter(tw, th))
        if use_caps and ass_path:
            parts.append(f"subtitles={ass_path}")
        return ",".join(parts)

    variants.append(("full", compose(reframe_vf, dynamic, True)))
    if dynamic:
        variants.append(("no-motion", compose(reframe_vf, False, True)))
    if ass_path:
        variants.append(("no-captions", compose(reframe_vf, False, False)))
    # last resort: safe letterbox with no crop expression
    safe_rf = build_reframe_filter(aspect, "preserve", in_w, in_h, [])
    variants.append(("safe", compose(safe_rf, False, False)))

    last_err = ""
    for name, vf in variants:
        cmd = ["ffmpeg", "-y", "-ss", f"{base_ss:.3f}", "-i", base_video]
        if base_video == src:
            cmd += ["-t", f"{out_dur:.3f}"]
        cmd += ["-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", out_path]
        res = _run(cmd)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return {
                "path": out_path, "aspect": aspect, "variant": name,
                "captions_used": bool(ass_path) and name in ("full", "no-motion"),
                "pauses_removed": base_video != src,
                "duration": round(out_dur, 2),
                "size_bytes": os.path.getsize(out_path),
            }
        last_err = res.stderr[-300:] if res.stderr else "unknown ffmpeg error"

    raise RenderError(f"Render failed: {last_err}")
