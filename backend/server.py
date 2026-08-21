"""AI Video Clipping Laboratory - FastAPI application.

Thin web layer. All heavy lifting lives in the modular components:
  video_utils (ffmpeg), transcription, diarization, analysis (LLM),
  scoring, pipeline (orchestration).

The web layer only handles HTTP, file storage, job persistence and streaming.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

from models import Job, VideoMetadata, CONTENT_TYPES, GenerateClipRequest
from video_utils import probe_video, generate_clip, VideoProcessingError
from transcription import available_providers
from scoring import DEFAULT_WEIGHTS, SUB_METRICS
from pipeline import Pipeline

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

STORAGE_DIR = os.environ.get("STORAGE_DIR", str(ROOT_DIR / "storage"))
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
CLIP_DIR = os.path.join(STORAGE_DIR, "clips")
for d in (UPLOAD_DIR, CLIP_DIR, os.path.join(STORAGE_DIR, "work")):
    os.makedirs(d, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv"}
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024 * 1024)))

app = FastAPI(title="AI Video Clipping Laboratory")
api_router = APIRouter(prefix="/api")
pipeline = Pipeline(db, STORAGE_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_job_or_404(job_id: str) -> dict:
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _range_response(path: str, request: Request, content_type: str = None):
    """Serve a file with HTTP Range support (needed for video seeking)."""
    file_size = os.path.getsize(path)
    content_type = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if range_header is None:
        return FileResponse(path, media_type=content_type)

    try:
        units, rng = range_header.split("=")
        start_s, end_s = rng.split("-")
        start = int(start_s)
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return FileResponse(path, media_type=content_type)

    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable")
    length = end - start + 1

    def _iter():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk = 1024 * 1024
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(_iter(), status_code=206, media_type=content_type, headers=headers)


# ---------------------------------------------------------------------------
# Config / meta
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "AI Video Clipping Laboratory API"}


@api_router.get("/config")
async def get_config():
    return {
        "content_types": CONTENT_TYPES,
        "transcription_providers": available_providers(),
        "default_provider": os.environ.get("TRANSCRIPTION_PROVIDER", "whisper_api"),
        "analysis_model": os.environ.get("ANALYSIS_MODEL", "claude-sonnet-4-6"),
        "clip_min_seconds": int(os.environ.get("CLIP_MIN_SECONDS", "20")),
        "clip_max_seconds": int(os.environ.get("CLIP_MAX_SECONDS", "90")),
        "score_metrics": SUB_METRICS,
        "score_weights": DEFAULT_WEIGHTS,
    }


# ---------------------------------------------------------------------------
# Upload + jobs
# ---------------------------------------------------------------------------
@api_router.post("/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    content_type: str = Form("auto"),
    transcription_provider: str = Form(None),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Supported: "
                   + ", ".join(sorted(ALLOWED_EXT)),
        )
    if content_type not in CONTENT_TYPES:
        content_type = "auto"
    provider = transcription_provider or os.environ.get("TRANSCRIPTION_PROVIDER", "whisper_api")
    if provider not in available_providers():
        raise HTTPException(status_code=400, detail=f"Unknown transcription provider '{provider}'")

    job = Job(filename=file.filename, content_type=content_type,
              transcription_provider=provider)
    dest = os.path.join(UPLOAD_DIR, f"{job.id}{ext}")

    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    os.remove(dest)
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    if size == 0:
        os.remove(dest)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    job.video_path = dest

    # Probe metadata (fast). If it fails, the file is unsupported/corrupt.
    try:
        meta = await asyncio.to_thread(probe_video, dest)
        job.metadata = VideoMetadata(**meta)
    except VideoProcessingError as e:
        os.remove(dest)
        raise HTTPException(status_code=400, detail=str(e))

    await db.jobs.insert_one(job.model_dump())

    # Kick off the background pipeline (non-blocking).
    asyncio.create_task(pipeline.run(job.id))

    return job.model_dump()


@api_router.get("/videos")
async def list_videos():
    jobs = await db.jobs.find({}, {"_id": 0, "transcript": 0}).sort("created_at", -1).to_list(500)
    return jobs


@api_router.get("/videos/{job_id}")
async def get_video(job_id: str):
    return await _get_job_or_404(job_id)


@api_router.delete("/videos/{job_id}")
async def delete_video(job_id: str):
    job = await _get_job_or_404(job_id)
    # Remove files
    for p in [job.get("video_path"), job.get("audio_path")]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    for clip in job.get("clips", []):
        cp = clip.get("clip_path")
        if cp and os.path.exists(cp):
            try:
                os.remove(cp)
            except OSError:
                pass
    shutil.rmtree(os.path.join(STORAGE_DIR, "work", job_id), ignore_errors=True)
    await db.jobs.delete_one({"id": job_id})
    return {"deleted": True}


@api_router.post("/videos/{job_id}/reprocess")
async def reprocess_video(job_id: str):
    job = await _get_job_or_404(job_id)
    if not os.path.exists(job.get("video_path", "")):
        raise HTTPException(status_code=400, detail="Source video no longer available")
    await db.jobs.update_one({"id": job_id}, {"$set": {
        "status": "uploaded", "progress": 0, "error": None,
        "clips": [], "transcript": [], "step_logs": [],
    }})
    asyncio.create_task(pipeline.run(job_id))
    return {"reprocessing": True}


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
@api_router.get("/videos/{job_id}/stream")
async def stream_video(job_id: str, request: Request):
    job = await _get_job_or_404(job_id)
    path = job.get("video_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    return _range_response(path, request)


@api_router.get("/videos/{job_id}/clips/{clip_id}/stream")
async def stream_clip(job_id: str, clip_id: str, request: Request):
    job = await _get_job_or_404(job_id)
    clip = next((c for c in job.get("clips", []) if c["id"] == clip_id), None)
    if not clip or not clip.get("clip_path") or not os.path.exists(clip["clip_path"]):
        raise HTTPException(status_code=404, detail="Clip not generated yet")
    return _range_response(clip["clip_path"], request, "video/mp4")


@api_router.get("/videos/{job_id}/clips/{clip_id}/download")
async def download_clip(job_id: str, clip_id: str):
    job = await _get_job_or_404(job_id)
    clip = next((c for c in job.get("clips", []) if c["id"] == clip_id), None)
    if not clip or not clip.get("clip_path") or not os.path.exists(clip["clip_path"]):
        raise HTTPException(status_code=404, detail="Clip not generated yet")
    safe = "".join(ch for ch in clip.get("title", "clip") if ch.isalnum() or ch in " -_")[:60].strip()
    return FileResponse(clip["clip_path"], media_type="video/mp4",
                        filename=f"{safe or 'clip'}.mp4")


# ---------------------------------------------------------------------------
# Clip generation / management
# ---------------------------------------------------------------------------
async def _set_clip(job_id: str, clip_id: str, **fields):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0, "clips": 1})
    if not job:
        return
    clips = job.get("clips", [])
    for c in clips:
        if c["id"] == clip_id:
            c.update(fields)
            break
    await db.jobs.update_one({"id": job_id}, {"$set": {"clips": clips}})


async def _render_one(job: dict, clip: dict):
    job_id = job["id"]
    out = os.path.join(CLIP_DIR, f"{job_id}_{clip['id']}.mp4")
    await _set_clip(job_id, clip["id"], status="generating", error=None)
    try:
        await asyncio.to_thread(
            generate_clip, job["video_path"], out, clip["start"], clip["end"]
        )
        await _set_clip(job_id, clip["id"], status="generated", clip_path=out, error=None)
    except VideoProcessingError as e:
        await _set_clip(job_id, clip["id"], status="error", error=str(e))
    except Exception as e:  # noqa: BLE001
        await _set_clip(job_id, clip["id"], status="error", error=f"Render failed: {e}")


@api_router.post("/videos/{job_id}/clips/{clip_id}/generate")
async def generate_single(job_id: str, clip_id: str):
    job = await _get_job_or_404(job_id)
    clip = next((c for c in job.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not os.path.exists(job.get("video_path", "")):
        raise HTTPException(status_code=400, detail="Source video no longer available")
    await _render_one(job, clip)
    updated = await _get_job_or_404(job_id)
    return next((c for c in updated["clips"] if c["id"] == clip_id), None)


@api_router.post("/videos/{job_id}/clips/generate-all")
async def generate_all(job_id: str, body: GenerateClipRequest = None):
    job = await _get_job_or_404(job_id)
    if not os.path.exists(job.get("video_path", "")):
        raise HTTPException(status_code=400, detail="Source video no longer available")
    ids = body.clip_ids if body and body.clip_ids else None
    targets = [c for c in job.get("clips", [])
               if (ids is None or c["id"] in ids) and c.get("status") != "generated"]

    async def _run_all():
        # Render sequentially to avoid overloading CPU with parallel ffmpeg.
        for clip in targets:
            fresh = await db.jobs.find_one({"id": job_id}, {"_id": 0})
            cur = next((c for c in fresh.get("clips", []) if c["id"] == clip["id"]), None)
            if cur:
                await _render_one(fresh, cur)

    asyncio.create_task(_run_all())
    return {"generating": len(targets)}


@api_router.delete("/videos/{job_id}/clips/{clip_id}")
async def delete_clip(job_id: str, clip_id: str):
    job = await _get_job_or_404(job_id)
    clips = job.get("clips", [])
    clip = next((c for c in clips if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    cp = clip.get("clip_path")
    if cp and os.path.exists(cp):
        try:
            os.remove(cp)
        except OSError:
            pass
    clips = [c for c in clips if c["id"] != clip_id]
    await db.jobs.update_one({"id": job_id}, {"$set": {"clips": clips}})
    return {"deleted": True}


app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
