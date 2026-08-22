"""Background processing pipeline orchestration.

Runs the full job asynchronously so the UI never blocks:

  extract_audio -> transcribe -> diarize -> analyze -> score -> ready

Every stage updates the job document (status, progress, step_logs) in MongoDB
so the frontend can poll and render a live terminal-style timeline. Errors at
any stage are captured with a useful message and the job is marked "error".
"""
from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timezone

from analysis import analyze_transcript, snap_boundaries, AnalysisError
from diarization import diarize
from models import Clip, ClipScores
from scoring import compute_overall, normalize_scores
from transcription import get_provider, TranscriptionError
from video_utils import extract_audio, VideoProcessingError

logger = logging.getLogger("pipeline")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Pipeline:
    def __init__(self, db, storage_dir: str):
        self.db = db
        self.storage_dir = storage_dir

    async def _update(self, job_id: str, **fields):
        fields["updated_at"] = _now()
        await self.db.jobs.update_one({"id": job_id}, {"$set": fields})

    async def _log(self, job_id: str, step: str, status: str, message: str = ""):
        entry = {"step": step, "status": status, "message": message, "ts": _now()}
        await self.db.jobs.update_one(
            {"id": job_id},
            {"$push": {"step_logs": entry}, "$set": {"updated_at": _now()}},
        )

    async def run(self, job_id: str):
        try:
            job = await self.db.jobs.find_one({"id": job_id}, {"_id": 0})
            if not job:
                logger.error("Job %s not found", job_id)
                return

            video_path = job["video_path"]
            metadata = job.get("metadata", {})
            workdir = os.path.join(self.storage_dir, "work", job_id)
            os.makedirs(workdir, exist_ok=True)

            # ---- 1. Audio extraction ----------------------------------
            if not metadata.get("has_audio", True):
                raise VideoProcessingError("Video has no audio track to transcribe")
            await self._update(job_id, status="extracting_audio", progress=5)
            await self._log(job_id, "extract_audio", "running", "Extracting audio track")
            audio_path = os.path.join(workdir, "audio.mp3")
            await _to_thread(extract_audio, video_path, audio_path)
            await self._update(job_id, audio_path=audio_path, progress=15)
            await self._log(job_id, "extract_audio", "done", "Audio extracted (16kHz mono)")

            # ---- 2. Transcription -------------------------------------
            provider_name = job.get("transcription_provider", "whisper_api")
            await self._update(job_id, status="transcribing", progress=20)
            await self._log(job_id, "transcribe", "running",
                            f"Transcribing with '{provider_name}'")
            provider = get_provider(provider_name)

            segments = await provider.transcribe(
                audio_path, float(metadata.get("duration", 0) or 0), workdir,
                progress_cb=None,
            )
            words = []
            if isinstance(segments, dict):
                words = segments.get("words", [])
                segments = segments.get("segments", [])
            await self._log(job_id, "transcribe", "done",
                            f"{len(segments)} transcript segments · {len(words)} words")

            # ---- 3. Diarization (speaker labels) ----------------------
            await self._log(job_id, "diarize", "running", "Assigning speaker labels")
            segments = diarize(segments)
            await self._update(job_id, transcript=segments, words=words, progress=60)
            await self._log(job_id, "diarize", "done", "Speaker labels assigned (heuristic)")

            # ---- 4. AI analysis ---------------------------------------
            await self._update(job_id, status="analyzing", progress=65)
            await self._log(job_id, "analyze", "running",
                            "Finding clip-worthy moments with AI")
            result = await analyze_transcript(
                segments, job.get("content_type", "auto"), metadata,
            )
            detected = result.get("detected_content_type")
            await self._log(job_id, "analyze", "done",
                            f"{len(result['clips'])} candidate moments found")

            # ---- 5. Boundaries + scoring ------------------------------
            await self._update(job_id, status="scoring", progress=88)
            await self._log(job_id, "score", "running",
                            "Refining boundaries and scoring clips")
            duration = float(metadata.get("duration", 0) or 0)
            clips = []
            for c in result["clips"]:
                c = snap_boundaries(c, segments, duration)
                sub = normalize_scores(c.get("scores", {}))
                overall = compute_overall(sub)
                clip = Clip(
                    title=c["title"], start=c["start"], end=c["end"],
                    duration=c["duration"], reason=c["reason"], hook=c["hook"],
                    category=c["category"], confidence=c["confidence"],
                    scores=ClipScores(**sub), overall_score=overall,
                )
                clips.append(clip.model_dump())
            clips.sort(key=lambda x: x["overall_score"], reverse=True)

            await self._update(
                job_id, clips=clips, detected_content_type=detected,
                status="ready", progress=100,
            )
            await self._log(job_id, "score", "done",
                            f"{len(clips)} clips ready")
            await self._log(job_id, "ready", "done", "Pipeline complete")

        except (VideoProcessingError, TranscriptionError, AnalysisError) as e:
            await self._fail(job_id, str(e))
        except Exception as e:  # noqa: BLE001
            logger.error("Pipeline crash: %s", traceback.format_exc())
            await self._fail(job_id, f"Unexpected error: {e}")

    async def _fail(self, job_id: str, message: str):
        await self._update(job_id, status="error", error=message)
        await self._log(job_id, "error", "error", message)


async def _to_thread(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)
