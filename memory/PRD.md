# Clip Lab — AI Video Clipping Laboratory (PRD)

## Original Problem Statement
Personal-use (single-user, no auth/payments/teams) AI video clipping laboratory. Upload long-form video → extract audio → timestamped transcription (with speaker labels) → LLM analysis to find standalone clip-worthy moments → natural clip boundaries → FFmpeg clip rendering → results dashboard with 0–100 scoring across 8 sub-metrics. Must be a real end-to-end pipeline (no fake AI), modular/extensible, portable (runnable outside Emergent), and prioritize video processing correctness > timestamps > candidate selection > boundaries > rendering > UI.

## User Choices
- Transcription: BOTH Whisper (hosted) + local faster-whisper, switchable per upload.
- AI analysis model: Claude `claude-sonnet-4-6` (via EMERGENT_LLM_KEY).
- Basic speaker diarization: yes (heuristic v1).
- UI: dark "editing studio" aesthetic (DaVinci/Premiere-like).
- Test video length: short/medium/long.

## Architecture (modular, portable)
Frontend (React) → `/api` (FastAPI) → background Pipeline → { video_utils (ffmpeg), transcription (pluggable providers), diarization, analysis (LLM), scoring } → MongoDB job store → local filesystem storage (uploads/clips/work).
- `video_utils.py` — only place touching ffmpeg/ffprobe (probe, extract audio, split, render clip).
- `transcription.py` — `TranscriptionProvider` interface + `whisper_api` (chunked for 25MB limit) + `local_whisper`; add providers via `get_provider()`.
- `diarization.py` — swappable speaker labeler (pause-gap heuristic v1; replace with pyannote later).
- `analysis.py` — Claude call + strict-JSON parsing + `snap_boundaries()` (natural cuts, lead-in/tail).
- `scoring.py` — configurable weighted overall from 8 sub-metrics.
- `pipeline.py` — async orchestration, per-stage status/progress/step_logs.
- No Emergent-specific lock-in beyond EMERGENT_LLM_KEY (swap key/provider anytime).

## Implemented (2026-06)
- Upload with metadata (duration/resolution/fps/size/codecs), progress, format validation (mp4/mov/mkv/webm/avi/m4v/flv).
- Content-type selector (auto + 9 types); provider selector.
- Background pipeline: audio extract → transcribe (real Whisper, now with word-level timestamps) → diarize → Claude analysis → boundary snap + scoring → ready; live status timeline.
- Candidate clips: title, start/end, duration, reason, hook, category, confidence, 8 sub-scores + overall 0–100.
- Clip rendering via FFmpeg (frame-accurate re-encode of only the clip, crf 18; stream-copy fallback).
- Results dashboard: expandable score cards, Preview (player seek + auto-stop), Delete, batch-select.
- Video streaming with HTTP Range (206) for seeking; transcript viewer with clickable timestamps + speaker pills.
- Graceful errors with useful messages.

## Post-Production Upgrade (2026-06) — short-form editor
- Per-clip Editor (modal): live preview (source range play + rendered result), all controls, Render/Download.
- 9:16 / 1:1 / Original reframing. Face-aware speaker tracking via OpenCV YuNet (`face_track.py`) with smoothed keyframes; "preserve" letterbox mode for gaming/screen; static-center fallback when no face.
- Word-timed burned-in captions (`captions.py`): 3 presets (clean/bold/highlight) + none, positions (bottom/center/top), safe-area margins, manual line editing. Words sourced from stored transcript words (no re-transcribe); local faster-whisper fallback per-clip.
- Optional smart pause/silence trimming (ffmpeg silencedetect + select/concat, conservative, default off) with caption/keyframe remap.
- Optional subtle dynamic motion (gentle zoompan), default off.
- Manual start/end boundary override — no AI re-analysis.
- Content-aware defaults per content type (`reframe.default_edit_settings`).
- Batch export: multi-select → Render Selected (sequential, independent failures) → Download All.
- Export MP4 1080×1920 (9:16) / 1080×1080 (1:1) / source AR (original), H.264 + AAC 48k, +faststart.
- Layered render fallbacks (full → no-motion → no-captions → safe letterbox) so a clip always renders.
- Editing/rendering fully decoupled from analysis (`render.py`, `reframe.py`, `captions.py`, `face_track.py`).
- Verified: 20/21 backend pytest (1 pre-existing flaky assertion in the QA harness, unrelated) + 100% frontend; real renders confirmed at all three aspect ratios with burned captions and pause-removal path.

## Extensibility Hooks (not yet built, no rewrite needed)
Visual/scene analysis, face/speaker tracking, 9:16 reframing, captions, B-roll, gaming/livestream-specific detectors, better ranking, campaign scoring — all pluggable behind provider/analyzer/scorer interfaces.

## Backlog / Next
- P1: Real diarization (pyannote) behind existing `diarize()` interface.
- P1: Word-level timestamps option for tighter boundaries.
- P2: Auto 9:16 reframing + burned-in captions on render.
- P2: Scene/visual analysis to complement transcript signals.
- P2: Adjustable clip scoring weights from the UI.
