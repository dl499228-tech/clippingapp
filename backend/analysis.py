"""AI content analysis via Claude (Emergent universal key).

Sends the timestamped transcript + metadata to the LLM and asks it to identify
standalone clip-worthy moments with natural boundaries and 8 sub-scores. The
model/provider is configurable through the ANALYSIS_MODEL env var.

Returns a dict: {"detected_content_type": str|None, "clips": [ ... ]}.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from scoring import SUB_METRICS


class AnalysisError(Exception):
    pass


SYSTEM_PROMPT = """You are an expert short-form video editor and producer. \
Your job is to analyze a timestamped transcript of a long-form video and find \
the strongest STANDALONE moments that would make great short clips.

You must think like a viral clip editor, not a text summarizer. Do NOT split \
the video into equal sections. Only surface genuinely compelling moments.

Look for: strong hooks, surprising statements, interesting stories, useful \
information, emotional moments, humor, conflict/disagreement, curiosity gaps, \
unexpected information, strong opinions, memorable statements, and clear \
beginning/middle/end arcs with social-media appeal.

CLIP BOUNDARY RULES:
- Begin slightly BEFORE the important statement if context is needed.
- End AFTER the payoff / punchline lands.
- Never cut a speaker off mid-sentence.
- Avoid long dead air at the start or end.
- Preserve enough context for the clip to make sense on its own.
- Target roughly {min_s}-{max_s} seconds, but choose a different length when \
the content genuinely requires it.

Return STRICT JSON only (no prose, no markdown fences) in this exact shape:
{{
  "detected_content_type": "podcast|interview|gaming|livestream|vlog|entertainment|educational|sports|other",
  "clips": [
    {{
      "title": "punchy clip title",
      "start": <seconds float>,
      "end": <seconds float>,
      "hook": "the first spoken line / attention grabber",
      "reason": "1-2 sentences on why this moment is compelling",
      "category": "hook|story|insight|emotional|humor|conflict|opinion|surprise|educational|highlight",
      "confidence": <0.0-1.0>,
      "scores": {{
        "hook": <0-100>,
        "standalone": <0-100>,
        "payoff": <0-100>,
        "info_value": <0-100>,
        "emotional": <0-100>,
        "curiosity": <0-100>,
        "context": <0-100>,
        "social_appeal": <0-100>
      }}
    }}
  ]
}}

Guidance: return between 3 and 12 of the BEST candidates ordered by quality. \
All timestamps must fall within the video duration. Scores must honestly \
reflect each dimension (a weak hook gets a low hook score)."""


def _build_transcript_block(segments: List[dict], max_chars: int = 120000) -> str:
    lines = []
    used = 0
    for seg in segments:
        spk = seg.get("speaker") or "Speaker"
        line = f"[{seg['start']:.1f}-{seg['end']:.1f}] {spk}: {seg['text']}"
        used += len(line)
        if used > max_chars:
            lines.append("... (transcript truncated for length) ...")
            break
        lines.append(line)
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Grab the outermost {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


async def analyze_transcript(segments: List[dict], content_type: str,
                             metadata: Dict) -> Dict:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise AnalysisError("GEMINI_API_KEY not configured")

    model = os.environ.get("ANALYSIS_MODEL", "gemini-2.5-flash")
    min_s = int(os.environ.get("CLIP_MIN_SECONDS", "20"))
    max_s = int(os.environ.get("CLIP_MAX_SECONDS", "90"))
    duration = float(metadata.get("duration", 0) or 0)

    system = SYSTEM_PROMPT.format(min_s=min_s, max_s=max_s)
    transcript_block = _build_transcript_block(segments)

    hint = "auto-detect the content type" if content_type in ("auto", "", None) \
        else f"the user says this is a '{content_type}' video"

    user_text = (
        f"Video duration: {duration:.1f} seconds. The user says: {hint}.\n\n"
        f"TRANSCRIPT (timestamps in seconds):\n{transcript_block}\n\n"
        "Return the JSON now."
    )

    try:
        client = genai.Client(api_key=api_key)

        response = await client.aio.models.generate_content(
            model=model,
            contents=user_text,
            config={
                "system_instruction": system,
                "response_mime_type": "application/json",
            },
        )

        raw = response.text or ""
    except Exception as e:  # noqa: BLE001
        raise AnalysisError(f"Gemini analysis request failed: {e}") from e

    try:
        data = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise AnalysisError(f"Could not parse AI response as JSON: {e}") from e

    clips_raw = data.get("clips", [])
    if not isinstance(clips_raw, list):
        raise AnalysisError("AI response missing 'clips' array")

    cleaned = []
    for c in clips_raw:
        try:
            start = max(0.0, float(c.get("start", 0)))
            end = float(c.get("end", 0))
        except (TypeError, ValueError):
            continue

        if duration:
            end = min(end, duration)
            start = min(start, max(0.0, duration - 1))

        if end <= start:
            continue

        scores = c.get("scores", {}) if isinstance(c.get("scores"), dict) else {}

        cleaned.append({
            "title": str(c.get("title", "Untitled clip"))[:200],
            "start": round(start, 2),
            "end": round(end, 2),
            "hook": str(c.get("hook", ""))[:500],
            "reason": str(c.get("reason", ""))[:1000],
            "category": str(c.get("category", "highlight"))[:50],
            "confidence": max(
                0.0,
                min(1.0, float(c.get("confidence", 0.5) or 0.5))
            ),
            "scores": {m: scores.get(m, 0) for m in SUB_METRICS},
        })

    return {
        "detected_content_type": data.get("detected_content_type"),
        "clips": cleaned,
    }


def snap_boundaries(clip: Dict, segments: List[dict], duration: float,
                    lead_in: float = 0.4, tail: float = 0.5) -> Dict:
    """Snap clip start/end to natural transcript segment edges to avoid
    cutting speakers mid-sentence, with a small lead-in and tail."""
    if not segments:
        return clip
    start, end = clip["start"], clip["end"]

    # Snap start to the start of the segment that contains it (or nearest before).
    start_seg = None
    for seg in segments:
        if seg["start"] <= start <= seg["end"]:
            start_seg = seg
            break
        if seg["start"] > start:
            break
        start_seg = seg
    if start_seg:
        start = start_seg["start"]

    # Snap end to the end of the segment that contains it (or nearest after).
    end_seg = None
    for seg in segments:
        if seg["start"] <= end <= seg["end"]:
            end_seg = seg
            break
        if seg["end"] >= end:
            end_seg = seg
            break
        end_seg = seg
    if end_seg:
        end = end_seg["end"]

    start = max(0.0, start - lead_in)
    end = end + tail
    if duration:
        end = min(end, duration)
    if end <= start:
        end = min(start + 1.0, duration or (start + 1.0))

    clip["start"] = round(start, 2)
    clip["end"] = round(end, 2)
    clip["duration"] = round(end - start, 2)
    return clip
