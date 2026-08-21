"""Modular transcription layer.

Providers implement a common interface so the transcription engine can be
swapped without touching the pipeline or UI:

  - WhisperApiProvider  : OpenAI Whisper via Emergent universal key (accurate,
                          hosted, chunked to respect the 25MB limit).
  - FasterWhisperProvider: local faster-whisper (fully offline / portable,
                          no API needed, slower on CPU).

Add new providers (e.g. Deepgram, AssemblyAI) by subclassing
TranscriptionProvider and registering them in get_provider().
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from video_utils import split_audio, VideoProcessingError

ProgressCB = Optional[Callable[[int, str], None]]


class TranscriptionError(Exception):
    pass


class TranscriptionProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def transcribe(self, audio_path: str, total_duration: float,
                         workdir: str, progress_cb: ProgressCB = None) -> List[dict]:
        """Return list of {start, end, text} segments (seconds)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OpenAI Whisper (hosted, via Emergent universal key)
# ---------------------------------------------------------------------------
class WhisperApiProvider(TranscriptionProvider):
    name = "whisper_api"

    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.chunk_seconds = int(os.environ.get("CHUNK_SECONDS", "600"))
        if not self.api_key:
            raise TranscriptionError("EMERGENT_LLM_KEY not configured for whisper_api")

    async def transcribe(self, audio_path, total_duration, workdir, progress_cb=None):
        from emergentintegrations.llm.openai import OpenAISpeechToText

        stt = OpenAISpeechToText(api_key=self.api_key)
        chunks = split_audio(audio_path, os.path.join(workdir, "chunks"),
                             self.chunk_seconds, total_duration)

        segments: List[dict] = []
        total = len(chunks)
        for idx, (chunk_path, offset) in enumerate(chunks):
            if progress_cb:
                progress_cb(int(100 * idx / max(total, 1)),
                            f"Transcribing chunk {idx + 1}/{total}")
            try:
                with open(chunk_path, "rb") as fh:
                    resp = await stt.transcribe(
                        file=fh, model="whisper-1",
                        response_format="verbose_json",
                        timestamp_granularities=["segment"],
                    )
            except Exception as e:  # noqa: BLE001
                raise TranscriptionError(f"Whisper API failed on chunk {idx + 1}: {e}") from e

            raw_segments = getattr(resp, "segments", None) or []
            if not raw_segments and getattr(resp, "text", "").strip():
                # No segment timing returned; keep as one block for this chunk.
                raw_segments = [{"start": 0.0, "end": min(self.chunk_seconds, total_duration),
                                 "text": resp.text}]
            for seg in raw_segments:
                start = float(_attr(seg, "start", 0.0)) + offset
                end = float(_attr(seg, "end", 0.0)) + offset
                text = str(_attr(seg, "text", "")).strip()
                if text:
                    segments.append({"start": start, "end": end, "text": text})

        if not segments:
            raise TranscriptionError("Transcription returned no text")
        return segments


# ---------------------------------------------------------------------------
# faster-whisper (local, offline, portable)
# ---------------------------------------------------------------------------
class FasterWhisperProvider(TranscriptionProvider):
    name = "local_whisper"
    _model = None

    def __init__(self):
        self.model_size = os.environ.get("WHISPER_LOCAL_MODEL", "base")

    def _load(self):
        if FasterWhisperProvider._model is None:
            from faster_whisper import WhisperModel
            FasterWhisperProvider._model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8"
            )
        return FasterWhisperProvider._model

    async def transcribe(self, audio_path, total_duration, workdir, progress_cb=None):
        import asyncio

        def _work():
            model = self._load()
            seg_iter, _info = model.transcribe(audio_path, vad_filter=True)
            out = []
            for seg in seg_iter:
                text = (seg.text or "").strip()
                if text:
                    out.append({"start": float(seg.start), "end": float(seg.end), "text": text})
            return out

        if progress_cb:
            progress_cb(10, f"Running local whisper ({self.model_size})")
        try:
            segments = await asyncio.to_thread(_work)
        except Exception as e:  # noqa: BLE001
            raise TranscriptionError(f"Local whisper failed: {e}") from e
        if not segments:
            raise TranscriptionError("Local transcription returned no text")
        return segments


def _attr(obj, key, default):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


_PROVIDERS = {
    "whisper_api": WhisperApiProvider,
    "local_whisper": FasterWhisperProvider,
}


def available_providers() -> List[str]:
    return list(_PROVIDERS.keys())


def get_provider(name: str) -> TranscriptionProvider:
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise TranscriptionError(f"Unknown transcription provider: {name}")
    return cls()
