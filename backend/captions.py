"""Word-timed burned-in captions.

- Obtains word timings for a clip (from the job's stored words when available,
  otherwise by transcribing the short clip locally with faster-whisper).
- Groups words into short, readable caption lines.
- Renders an ASS subtitle file with 3 presets (clean / bold / highlight) and
  configurable position, sized for the target resolution and kept inside
  social-media safe margins.

All timings are CLIP-RELATIVE (seconds from clip start). The renderer remaps
them if pauses are removed.
"""
from __future__ import annotations

import os
import re
from typing import List

import video_utils

_FW_MODEL = None


def _fw_model():
    global _FW_MODEL
    if _FW_MODEL is None:
        from faster_whisper import WhisperModel
        _FW_MODEL = WhisperModel(os.environ.get("WHISPER_LOCAL_MODEL", "base"),
                                 device="cpu", compute_type="int8")
    return _FW_MODEL


def extract_clip_words(job: dict, start: float, end: float, workdir: str) -> List[dict]:
    """Return [{start,end,word}] clip-relative for [start,end]."""
    duration = max(0.1, end - start)
    words = job.get("words") or []
    sliced = []
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        if we <= start or ws >= end:
            continue
        sliced.append({
            "start": max(0.0, ws - start),
            "end": min(duration, we - start),
            "word": str(w["word"]).strip(),
        })
    if sliced:
        return [w for w in sliced if w["word"]]

    # Fallback: transcribe just this clip locally with word timestamps.
    os.makedirs(workdir, exist_ok=True)
    wav = os.path.join(workdir, "cap_audio.wav")
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", job["video_path"],
         "-t", f"{duration:.3f}", "-vn", "-ac", "1", "-ar", "16000", wav],
        capture_output=True, timeout=600,
    )
    if not os.path.exists(wav) or os.path.getsize(wav) == 0:
        return []
    model = _fw_model()
    seg_iter, _ = model.transcribe(wav, word_timestamps=True, vad_filter=False)
    out = []
    for seg in seg_iter:
        for w in (seg.words or []):
            token = (w.word or "").strip()
            if token:
                out.append({"start": float(w.start), "end": float(w.end), "word": token})
    return out


def group_words_to_lines(words: List[dict], max_chars: int = 30, max_words: int = 6,
                         max_gap: float = 0.8) -> List[dict]:
    """Group words into short caption lines with sensible breaks."""
    lines: List[dict] = []
    cur: List[dict] = []
    cur_chars = 0
    for i, w in enumerate(words):
        token = w["word"]
        gap = 0.0 if not cur else w["start"] - cur[-1]["end"]
        would = cur_chars + len(token) + (1 if cur else 0)
        if cur and (would > max_chars or len(cur) >= max_words or gap > max_gap):
            lines.append(_finalize_line(cur))
            cur, cur_chars = [], 0
        cur.append(w)
        cur_chars += len(token) + 1
        # Break after sentence-ending punctuation.
        if re.search(r"[.!?]$", token) and len(cur) >= 2:
            lines.append(_finalize_line(cur))
            cur, cur_chars = [], 0
    if cur:
        lines.append(_finalize_line(cur))
    return lines


def _finalize_line(words: List[dict]) -> dict:
    text = " ".join(w["word"] for w in words).strip()
    return {
        "start": round(words[0]["start"], 3),
        "end": round(words[-1]["end"], 3),
        "text": text,
        "words": [{"start": round(w["start"], 3), "end": round(w["end"], 3), "word": w["word"]} for w in words],
    }


# ---------------------------------------------------------------------------
# ASS generation
# ---------------------------------------------------------------------------
def _ass_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap(text: str, max_chars: int = 24) -> str:
    """Wrap into at most 2 balanced lines using \\N."""
    words = text.split()
    if not words:
        return text
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines[:2]) if len(lines) <= 2 else "\\N".join([" ".join(lines[:1]), " ".join(lines[1:])])


def _preset_style(preset: str, tw: int, th: int, position: str) -> tuple:
    """Return (style_line, alignment, margin_v)."""
    align = {"bottom": 2, "center": 5, "top": 8}.get(position, 2)
    margin_v = int(th * 0.13) if position in ("bottom", "top") else 0

    if preset == "bold":
        fs = int(tw * 0.070)
        style = (f"Style: Default,Liberation Sans,{fs},&H00FFFFFF,&H000000FF,"
                 f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(3,int(tw*0.006))},"
                 f"{max(2,int(tw*0.003))},{align},60,60,{margin_v},1")
    elif preset == "highlight":
        fs = int(tw * 0.068)
        style = (f"Style: Default,Liberation Sans,{fs},&H00FFFFFF,&H000000FF,"
                 f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(3,int(tw*0.006))},"
                 f"{max(2,int(tw*0.003))},{align},60,60,{margin_v},1")
    else:  # clean
        fs = int(tw * 0.058)
        style = (f"Style: Default,Liberation Sans,{fs},&H00FFFFFF,&H000000FF,"
                 f"&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{max(2,int(tw*0.004))},"
                 f"0,{align},60,60,{margin_v},1")
    return style, align, margin_v


def build_ass(lines: List[dict], preset: str, position: str, tw: int, th: int) -> str:
    style, _align, _mv = _preset_style(preset, tw, th, position)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\n"
        f"PlayResX: {tw}\nPlayResY: {th}\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"{style}\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )

    events = []
    HL = "&H0000E5FF"  # amber highlight (ASS BGR)
    WHITE = "&H00FFFFFF"

    for ln in lines:
        if preset == "highlight" and ln.get("words"):
            words = ln["words"]
            for i, w in enumerate(words):
                w_start = w["start"]
                w_end = words[i + 1]["start"] if i + 1 < len(words) else ln["end"]
                parts = []
                for j, ww in enumerate(words):
                    tok = _strip_ass(ww["word"])
                    if j == i:
                        parts.append(f"{{\\c{HL}}}{tok}{{\\c{WHITE}}}")
                    else:
                        parts.append(tok)
                events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Default,,0,0,0,,{' '.join(parts)}")
        else:
            text = _wrap(_strip_ass(ln["text"]))
            events.append(f"Dialogue: 0,{_ass_time(ln['start'])},{_ass_time(ln['end'])},Default,,0,0,0,,{text}")

    return header + "\n".join(events) + "\n"


def _strip_ass(text: str) -> str:
    return text.replace("{", "").replace("}", "")
