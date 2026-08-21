"""FFmpeg / FFprobe based video utilities.

This module is the ONLY place that touches ffmpeg. It is intentionally
decoupled from the web/UI layer so it can be reused or run standalone
outside Emergent. All functions are plain (synchronous) and are called from
the pipeline via asyncio.to_thread.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from typing import List, Tuple


class VideoProcessingError(Exception):
    pass


def _run(cmd: List[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise VideoProcessingError(f"ffmpeg timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise VideoProcessingError("ffmpeg/ffprobe not found on PATH") from e


def probe_video(path: str) -> dict:
    """Return normalized metadata using ffprobe."""
    if not os.path.exists(path):
        raise VideoProcessingError("Video file not found")

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    res = _run(cmd, timeout=120)
    if res.returncode != 0:
        raise VideoProcessingError(f"Could not read video (unsupported or corrupt): {res.stderr[:300]}")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise VideoProcessingError("ffprobe returned invalid data") from e

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if vstream is None:
        raise VideoProcessingError("No video stream found in file")

    # frame rate can be "30000/1001"
    fps = 0.0
    rate = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "0/0"
    try:
        num, den = rate.split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    duration = 0.0
    for src in (fmt.get("duration"), vstream.get("duration")):
        if src:
            try:
                duration = float(src)
                break
            except ValueError:
                continue

    return {
        "duration": duration,
        "width": int(vstream.get("width", 0) or 0),
        "height": int(vstream.get("height", 0) or 0),
        "fps": fps,
        "size_bytes": int(fmt.get("size", 0) or 0),
        "container": (fmt.get("format_name", "") or "").split(",")[0],
        "video_codec": vstream.get("codec_name", ""),
        "audio_codec": astream.get("codec_name", "") if astream else "",
        "has_audio": astream is not None,
    }


def extract_audio(video_path: str, out_path: str) -> str:
    """Extract mono 16kHz mp3 (small, transcription-friendly, portable)."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "64k", "-f", "mp3", out_path,
    ]
    res = _run(cmd, timeout=3600)
    if res.returncode != 0 or not os.path.exists(out_path):
        raise VideoProcessingError(f"Audio extraction failed: {res.stderr[-300:]}")
    if os.path.getsize(out_path) == 0:
        raise VideoProcessingError("Extracted audio is empty (video may have no audio track)")
    return out_path


def split_audio(audio_path: str, chunk_dir: str, chunk_seconds: int,
                total_duration: float) -> List[Tuple[str, float]]:
    """Split audio into time chunks. Returns [(chunk_path, offset_seconds)].

    Chunking keeps each piece well under provider size limits (e.g. Whisper's
    25MB) and lets us stitch timestamps back together via the offset.
    """
    os.makedirs(chunk_dir, exist_ok=True)
    if total_duration <= chunk_seconds:
        return [(audio_path, 0.0)]

    n = int(math.ceil(total_duration / chunk_seconds))
    chunks: List[Tuple[str, float]] = []
    for i in range(n):
        offset = i * chunk_seconds
        out = os.path.join(chunk_dir, f"chunk_{i:04d}.mp3")
        cmd = [
            "ffmpeg", "-y", "-ss", str(offset), "-t", str(chunk_seconds),
            "-i", audio_path, "-ac", "1", "-ar", "16000",
            "-b:a", "64k", "-f", "mp3", out,
        ]
        res = _run(cmd, timeout=1800)
        if res.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            chunks.append((out, float(offset)))
    if not chunks:
        raise VideoProcessingError("Failed to split audio into chunks")
    return chunks


def generate_clip(video_path: str, out_path: str, start: float, end: float) -> dict:
    """Render a single clip with frame-accurate boundaries.

    We re-encode ONLY the short clip (never the whole source) at high quality
    (crf 18) which gives accurate start/end times while preserving quality.
    Falls back to stream-copy if re-encoding fails.
    """
    if end <= start:
        raise VideoProcessingError("Invalid timestamps: end must be greater than start")
    duration = round(end - start, 3)

    cmd = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", video_path,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", out_path,
    ]
    res = _run(cmd, timeout=1800)

    if res.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        # Fallback: stream copy (fast, keyframe-aligned, less precise)
        cmd_copy = [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", video_path,
            "-t", f"{duration:.3f}", "-c", "copy",
            "-movflags", "+faststart", out_path,
        ]
        res2 = _run(cmd_copy, timeout=600)
        if res2.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise VideoProcessingError(f"Clip rendering failed: {res.stderr[-300:]}")

    return {"path": out_path, "size_bytes": os.path.getsize(out_path), "duration": duration}
