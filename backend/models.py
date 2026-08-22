"""Pydantic data models for the AI Video Clipping Laboratory.

All documents use a uuid string `id` and are stored in MongoDB with the `_id`
field ignored on read (see server.py). This keeps the data layer portable and
free of BSON ObjectId serialization concerns.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Content types (extensible - not hard-coded around podcasts)
# ---------------------------------------------------------------------------
CONTENT_TYPES = [
    "auto", "podcast", "interview", "gaming", "livestream",
    "vlog", "entertainment", "educational", "sports", "other",
]

# Pipeline stages surfaced to the UI as a terminal-style timeline.
JOB_STATUSES = [
    "uploaded", "extracting_audio", "transcribing",
    "analyzing", "scoring", "ready", "error",
]


class VideoMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    duration: float = 0.0            # seconds
    width: int = 0
    height: int = 0
    fps: float = 0.0
    size_bytes: int = 0
    container: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    has_audio: bool = True


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


class Word(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: float
    end: float
    word: str


class CaptionLine(BaseModel):
    """A burned-caption line on the CLIP-relative (output) timeline."""
    model_config = ConfigDict(extra="ignore")
    start: float
    end: float
    text: str
    words: List[Word] = Field(default_factory=list)


# Editing / post-production settings (separate from AI analysis).
ASPECT_RATIOS = ["9:16", "1:1", "original"]
CAPTION_PRESETS = ["clean", "bold", "highlight", "none"]
CAPTION_POSITIONS = ["bottom", "center", "top"]


class EditSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    aspect_ratio: str = "9:16"
    caption_preset: str = "clean"
    caption_position: str = "bottom"
    remove_pauses: bool = False
    dynamic_effects: bool = False
    reframe_mode: str = "face"        # "face" (track speaker) | "preserve" (pad, screen content)
    start: Optional[float] = None      # boundary override (source seconds)
    end: Optional[float] = None


class StepLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step: str
    status: str                      # running | done | error
    message: str = ""
    ts: str = Field(default_factory=_now)


class ClipScores(BaseModel):
    """The 8 modular sub-metrics (0-100). Overall is computed in scoring.py."""
    model_config = ConfigDict(extra="ignore")
    hook: float = 0
    standalone: float = 0
    payoff: float = 0
    info_value: float = 0
    emotional: float = 0
    curiosity: float = 0
    context: float = 0
    social_appeal: float = 0


class Clip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    title: str = ""
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    reason: str = ""                 # why the AI selected it
    hook: str = ""                   # first line / hook text
    category: str = ""
    confidence: float = 0.0          # AI raw confidence 0-1
    scores: ClipScores = Field(default_factory=ClipScores)
    overall_score: float = 0.0       # computed 0-100
    status: str = "candidate"        # candidate | generating | generated | error
    clip_path: Optional[str] = None
    error: Optional[str] = None
    # ---- Post-production (editing) state ----
    edit: Optional[EditSettings] = None
    captions: List[CaptionLine] = Field(default_factory=list)
    captions_ready: bool = False
    export_path: Optional[str] = None
    export_status: str = "none"      # none | rendering | done | error
    export_error: Optional[str] = None
    export_aspect: Optional[str] = None


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    filename: str
    content_type: str = "auto"           # user-selected
    detected_content_type: Optional[str] = None
    transcription_provider: str = "whisper_api"
    status: str = "uploaded"
    progress: int = 0
    error: Optional[str] = None
    video_path: str = ""
    audio_path: Optional[str] = None
    metadata: VideoMetadata = Field(default_factory=VideoMetadata)
    transcript: List[TranscriptSegment] = Field(default_factory=list)
    words: List[Word] = Field(default_factory=list)
    clips: List[Clip] = Field(default_factory=list)
    step_logs: List[StepLog] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class GenerateClipRequest(BaseModel):
    clip_ids: Optional[List[str]] = None   # None = all candidates


class BatchRenderRequest(BaseModel):
    clip_ids: List[str]
