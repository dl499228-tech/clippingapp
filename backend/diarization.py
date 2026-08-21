"""Lightweight, modular speaker diarization.

v1 uses a pause-gap heuristic: when the silence between two consecutive
transcript segments exceeds a threshold, a speaker turn is assumed. Labels
alternate between a small set of speakers. This is APPROXIMATE and intended as
a placeholder that can be swapped for a real diarizer (e.g. pyannote.audio)
without changing the pipeline or UI — just implement `diarize()` and return the
segments with a `speaker` field populated.
"""
from __future__ import annotations

from typing import List

GAP_THRESHOLD = 1.2  # seconds of silence that suggests a possible speaker change


def diarize(segments: List[dict], max_speakers: int = 2) -> List[dict]:
    """Assign a `speaker` label to each segment. Mutates and returns list."""
    if not segments:
        return segments

    speaker_idx = 0
    prev_end = None
    for seg in segments:
        if prev_end is not None:
            gap = seg["start"] - prev_end
            # Toggle speaker on a clear pause that ends a sentence.
            if gap >= GAP_THRESHOLD:
                speaker_idx = (speaker_idx + 1) % max_speakers
        seg["speaker"] = f"Speaker {speaker_idx + 1}"
        prev_end = seg["end"]
    return segments
