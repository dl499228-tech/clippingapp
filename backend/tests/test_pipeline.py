"""End-to-end backend tests for the AI Video Clipping Laboratory.

Covers:
- GET /api/config
- POST /api/videos/upload (valid + invalid types)
- Background pipeline progression to `ready` status
- Transcript segments, clip candidates, scores
- Clip generation, download, range streaming
- Delete clip / delete job
"""
from __future__ import annotations

import os
import time
import tempfile

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
TEST_VIDEO = "/app/backend/storage/test_video.mp4"


# Shared job id across pipeline tests
_shared = {}


# ------------------------- Config -------------------------
class TestConfig:
    def test_config_shape(self):
        r = requests.get(f"{API}/config", timeout=30)
        assert r.status_code == 200
        data = r.json()
        # required keys
        for k in ["content_types", "transcription_providers",
                  "default_provider", "analysis_model",
                  "score_metrics", "score_weights",
                  "clip_min_seconds", "clip_max_seconds"]:
            assert k in data, f"missing key: {k}"

        # content types include auto
        assert "auto" in data["content_types"]
        # both providers advertised
        providers = data["transcription_providers"]
        assert "whisper_api" in providers
        # local_whisper may not be enabled if faster-whisper not installed, but is expected here
        # We only require the API provider to be present.
        # Analysis model
        assert "gemini" in data["analysis_model"].lower()
        # 8 sub-metrics
        assert len(data["score_metrics"]) == 8
        expected = {"hook", "standalone", "payoff", "info_value",
                    "emotional", "curiosity", "context", "social_appeal"}
        assert set(data["score_metrics"]) == expected
        # weights present for each metric
        for m in data["score_metrics"]:
            assert m in data["score_weights"]


# ------------------------- Upload error handling -------------------------
class TestUploadErrors:
    def test_reject_non_video_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a video")
            path = f.name
        try:
            with open(path, "rb") as fh:
                r = requests.post(
                    f"{API}/videos/upload",
                    files={"file": ("fake.txt", fh, "text/plain")},
                    data={"content_type": "auto",
                          "transcription_provider": "whisper_api"},
                    timeout=60,
                )
            assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
            body = r.json()
            assert "detail" in body
            assert "unsupported" in body["detail"].lower() or "supported" in body["detail"].lower()
        finally:
            os.remove(path)

    def test_reject_corrupt_video_with_mp4_extension(self):
        """A .mp4 file with garbage bytes should fail probe with 400, not 500."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"not really an mp4 file, just garbage bytes" * 200)
            path = f.name
        try:
            with open(path, "rb") as fh:
                r = requests.post(
                    f"{API}/videos/upload",
                    files={"file": ("fake.mp4", fh, "video/mp4")},
                    data={"content_type": "auto",
                          "transcription_provider": "whisper_api"},
                    timeout=60,
                )
            # Should be 400 with useful message, NOT 500
            assert r.status_code == 400, f"expected 400 for corrupt video, got {r.status_code}: {r.text[:200]}"
        finally:
            os.remove(path)

    def test_reject_bad_provider(self):
        with open(TEST_VIDEO, "rb") as fh:
            r = requests.post(
                f"{API}/videos/upload",
                files={"file": ("test_video.mp4", fh, "video/mp4")},
                data={"content_type": "auto",
                      "transcription_provider": "bogus_provider"},
                timeout=60,
            )
        assert r.status_code == 400
        assert "provider" in r.json()["detail"].lower()


# ------------------------- Real pipeline (Whisper + Claude) -------------------------
# All pipeline lifecycle tests live in ONE class so pytest-xdist loadscope pins
# them to a single worker and they run sequentially, sharing state via `_shared`.
class TestPipelineLifecycle:
    def test_a_upload_video(self):
        assert os.path.exists(TEST_VIDEO), f"missing test video: {TEST_VIDEO}"
        with open(TEST_VIDEO, "rb") as fh:
            r = requests.post(
                f"{API}/videos/upload",
                files={"file": ("test_video.mp4", fh, "video/mp4")},
                data={"content_type": "auto",
                      "transcription_provider": "whisper_api"},
                timeout=120,
            )
        assert r.status_code == 200, f"upload failed: {r.status_code} {r.text[:300]}"
        job = r.json()
        assert "id" in job
        assert job["filename"] == "test_video.mp4"
        meta = job["metadata"]
        # Real metadata from ffprobe
        assert 40 < meta["duration"] < 45, f"expected ~42s, got {meta['duration']}"
        assert meta["width"] > 0 and meta["height"] > 0
        assert meta["fps"] > 0
        assert meta["size_bytes"] > 0
        assert meta["video_codec"], "video_codec should be populated"
        assert meta["has_audio"] is True
        _shared["job_id"] = job["id"]

    def test_b_pipeline_reaches_ready(self):
        job_id = _shared.get("job_id")
        if not job_id:
            pytest.skip("upload test did not run")

        seen_statuses = set()
        deadline = time.time() + 180  # generous
        final = None
        while time.time() < deadline:
            r = requests.get(f"{API}/videos/{job_id}", timeout=30)
            assert r.status_code == 200
            job = r.json()
            seen_statuses.add(job["status"])
            if job["status"] == "ready":
                final = job
                break
            if job["status"] == "error":
                pytest.fail(f"pipeline errored: {job.get('error')}\nlogs: {job.get('step_logs')}")
            time.sleep(3)

        assert final is not None, f"pipeline did not reach ready. saw: {seen_statuses}"
        # Should have transitioned through processing stages
        assert seen_statuses & {"extracting_audio", "transcribing", "analyzing", "scoring", "ready"}
        # step_logs populated
        assert isinstance(final.get("step_logs"), list)
        assert len(final["step_logs"]) >= 4
        # Transcript populated with real segments
        segs = final.get("transcript") or []
        assert len(segs) > 0, "expected non-empty transcript from Whisper"
        for s in segs:
            assert "start" in s and "end" in s and "text" in s
            assert s["end"] >= s["start"]
            assert isinstance(s["text"], str)
        # Speaker labels present (heuristic diarization)
        assert any(s.get("speaker") for s in segs), "expected speaker labels"

        _shared["final"] = final

    def test_c_clips_shape_and_scores(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("pipeline test did not finish")
        clips = final.get("clips") or []
        assert len(clips) > 0, "expected at least one clip candidate from Claude"

        duration = final["metadata"]["duration"]
        expected_metrics = {"hook", "standalone", "payoff", "info_value",
                            "emotional", "curiosity", "context", "social_appeal"}

        for c in clips:
            # Basic fields
            for k in ["id", "title", "start", "end", "duration", "reason",
                      "hook", "category", "confidence", "scores", "overall_score"]:
                assert k in c, f"clip missing field: {k}"
            # Bounds
            assert 0 <= c["start"] < duration + 0.5, f"start out of range: {c['start']} / {duration}"
            assert c["end"] > c["start"]
            assert c["end"] <= duration + 0.5, f"end past duration: {c['end']} / {duration}"
            # duration matches
            assert abs((c["end"] - c["start"]) - c["duration"]) < 0.6
            # scores
            scores = c["scores"]
            assert set(scores.keys()) == expected_metrics
            for m, v in scores.items():
                assert 0 <= v <= 100, f"{m} score out of 0-100: {v}"
            # overall
            assert 0 <= c["overall_score"] <= 100
            # status
            assert c["status"] == "candidate"

        # Not equal-length splits: check that at least some clips differ
        # (or that clips do not tile the video in equal chunks starting at 0)
        starts = sorted([c["start"] for c in clips])
        if len(starts) >= 2:
            gaps = [starts[i+1] - starts[i] for i in range(len(starts)-1)]
            # If all gaps are nearly identical AND equal to durations, that would be uniform split.
            # We just assert clips are non-trivial (not all starting at 0).
            assert not all(s == 0 for s in starts), "all clips start at 0 (looks like naive split)"


    def test_d_transcript_matches_known_script(self):
        """Real speech from the espeak audio - transcript should contain
        recognizable words from the known script."""
        final = _shared.get("final")
        if not final:
            pytest.skip("pipeline test did not finish")
        segs = final.get("transcript") or []
        full = " ".join(s["text"] for s in segs).lower()
        # words from /app/backend/storage/script.txt
        keywords = ["invest", "mistake", "market", "money", "time"]
        hits = [w for w in keywords if w in full]
        assert len(hits) >= 3, (
            f"transcript doesn't seem to reflect the speech. hits={hits} "
            f"transcript={full[:400]!r}"
        )

    def test_e_generate_single_clip(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("pipeline test did not finish")
        clip = final["clips"][0]
        r = requests.post(
            f"{API}/videos/{final['id']}/clips/{clip['id']}/generate",
            timeout=180,
        )
        assert r.status_code == 200, f"generate failed: {r.status_code} {r.text[:300]}"
        updated = r.json()
        assert updated["status"] == "generated", f"expected generated, got {updated['status']} err={updated.get('error')}"
        assert updated.get("clip_path")
        _shared["clip_id"] = clip["id"]

    def test_f_download_clip(self):
        final = _shared.get("final")
        clip_id = _shared.get("clip_id")
        if not final or not clip_id:
            pytest.skip("no rendered clip")
        r = requests.get(
            f"{API}/videos/{final['id']}/clips/{clip_id}/download",
            timeout=60,
            stream=True,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/")
        data = r.raw.read(65536)
        # MP4 files start with ftyp box at bytes 4-7
        assert b"ftyp" in data[:32], f"downloaded file is not mp4: header={data[:32]!r}"

    def test_g_range_stream_video(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        r = requests.get(
            f"{API}/videos/{final['id']}/stream",
            headers={"Range": "bytes=0-1023"},
            timeout=30,
        )
        assert r.status_code == 206, f"expected 206 partial, got {r.status_code}"
        assert "content-range" in {k.lower() for k in r.headers.keys()}
        assert r.headers.get("Accept-Ranges") == "bytes"
        assert len(r.content) == 1024

    def test_h_generate_all(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        r = requests.post(
            f"{API}/videos/{final['id']}/clips/generate-all",
            timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert "generating" in body

        # Poll until all clips generated (or timeout)
        deadline = time.time() + 180
        all_done = False
        while time.time() < deadline:
            j = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
            statuses = [c["status"] for c in j["clips"]]
            if all(s in ("generated", "error") for s in statuses):
                all_done = True
                break
            time.sleep(3)
        assert all_done, f"generate-all didn't finish. statuses: {statuses}"


    def test_i_delete_a_clip(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        # Re-fetch to get current clip list
        job = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        if len(job["clips"]) < 2:
            pytest.skip("need >=2 clips to safely delete one")
        target = job["clips"][-1]["id"]
        r = requests.delete(f"{API}/videos/{final['id']}/clips/{target}", timeout=30)
        assert r.status_code == 200
        assert r.json().get("deleted") is True
        # Verify removal
        job2 = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        assert target not in [c["id"] for c in job2["clips"]]

    # ------------------- Editing / post-production -------------------
    def test_j_config_has_editing_fields(self):
        r = requests.get(f"{API}/config", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("aspect_ratios") == ["9:16", "1:1", "original"]
        assert set(d.get("caption_presets", [])) == {"clean", "bold", "highlight", "none"}
        assert set(d.get("caption_positions", [])) == {"bottom", "center", "top"}

    def test_k_update_edit_settings(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        clip_id = final["clips"][0]["id"]
        payload = {
            "aspect_ratio": "9:16",
            "caption_preset": "bold",
            "caption_position": "bottom",
            "remove_pauses": False,
            "dynamic_effects": False,
            "reframe_mode": "face",
            "start": final["clips"][0]["start"],
            "end": final["clips"][0]["end"],
        }
        r = requests.put(f"{API}/videos/{final['id']}/clips/{clip_id}/edit",
                         json=payload, timeout=30)
        assert r.status_code == 200, r.text
        clip = r.json()
        assert clip["edit"]["aspect_ratio"] == "9:16"
        assert clip["edit"]["caption_preset"] == "bold"
        assert clip["edit"]["caption_position"] == "bottom"
        assert clip["edit"]["reframe_mode"] == "face"
        # Verify persistence via GET
        job = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        c = next(c for c in job["clips"] if c["id"] == clip_id)
        assert c["edit"]["caption_preset"] == "bold"
        _shared["edit_clip_id"] = clip_id

    def test_l_generate_and_save_captions(self):
        final = _shared.get("final")
        clip_id = _shared.get("edit_clip_id")
        if not final or not clip_id:
            pytest.skip("no clip")
        r = requests.post(f"{API}/videos/{final['id']}/clips/{clip_id}/captions",
                          timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("captions"), list)
        assert len(data["captions"]) > 0, "expected caption lines from word timings"
        for line in data["captions"]:
            assert "start" in line and "end" in line and "text" in line
            assert line["end"] >= line["start"]
            assert isinstance(line["text"], str)
        # Manually edit lines and save
        edited = data["captions"][:]
        edited[0] = {**edited[0], "text": "EDITED HEADLINE"}
        r2 = requests.put(f"{API}/videos/{final['id']}/clips/{clip_id}/captions",
                          json={"captions": edited}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["captions"][0]["text"] == "EDITED HEADLINE"
        # Persistence
        job = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        c = next(c for c in job["clips"] if c["id"] == clip_id)
        assert c["captions"][0]["text"] == "EDITED HEADLINE"
        assert c["captions_ready"] is True

    def test_m_editing_does_not_rerun_analysis(self):
        """Verify that setting edit / captions does not touch transcript,
        clips list identity, or step_logs (no new analysis stages)."""
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        job_before = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        # Snapshot invariants
        transcript_before = job_before["transcript"]
        clip_ids_before = sorted(c["id"] for c in job_before["clips"])
        step_logs_before = len(job_before["step_logs"])

        # Poke edit endpoint again
        clip_id = _shared.get("edit_clip_id")
        r = requests.put(f"{API}/videos/{final['id']}/clips/{clip_id}/edit",
                         json={"aspect_ratio": "1:1", "caption_preset": "clean",
                               "caption_position": "top", "remove_pauses": False,
                               "dynamic_effects": False, "reframe_mode": "preserve",
                               "start": None, "end": None},
                         timeout=30)
        assert r.status_code == 200

        job_after = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        assert job_after["transcript"] == transcript_before, "transcript changed on edit!"
        assert sorted(c["id"] for c in job_after["clips"]) == clip_ids_before
        assert len(job_after["step_logs"]) == step_logs_before, "step_logs grew - re-analysis?"

        # Reset back to 9:16 for the render tests
        requests.put(f"{API}/videos/{final['id']}/clips/{clip_id}/edit",
                     json={"aspect_ratio": "9:16", "caption_preset": "bold",
                           "caption_position": "bottom", "remove_pauses": False,
                           "dynamic_effects": False, "reframe_mode": "face",
                           "start": None, "end": None}, timeout=30)

    def test_n_render_export_916(self):
        final = _shared.get("final")
        clip_id = _shared.get("edit_clip_id")
        if not final or not clip_id:
            pytest.skip("no clip")
        r = requests.post(f"{API}/videos/{final['id']}/clips/{clip_id}/render", timeout=30)
        assert r.status_code == 200
        assert r.json().get("rendering") is True

        # Poll for export_status done - allow generous time (safe-render fallbacks)
        deadline = time.time() + 240
        seen = set()
        clip = None
        while time.time() < deadline:
            job = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
            c = next(c for c in job["clips"] if c["id"] == clip_id)
            seen.add(c["export_status"])
            if c["export_status"] == "done":
                clip = c
                break
            if c["export_status"] == "error":
                pytest.fail(f"render error: {c.get('export_error')}")
            time.sleep(3)
        assert clip is not None, f"render did not complete, saw: {seen}"
        assert "rendering" in seen, f"expected to observe rendering state, saw: {seen}"
        assert clip.get("export_path") and os.path.exists(clip["export_path"])
        _shared["export_ready_clip_id"] = clip_id

        # Download and check dims via ffprobe
        r = requests.get(f"{API}/videos/{final['id']}/clips/{clip_id}/export/download",
                         timeout=60, stream=True)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/")
        content = r.content
        assert b"ftyp" in content[:64], "not an mp4"
        # Save then ffprobe to check dims
        out = f"/tmp/export_{clip_id}.mp4"
        with open(out, "wb") as fh:
            fh.write(content)
        import json as _json
        import subprocess
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name",
             "-show_entries", "format=duration",
             "-of", "json", out],
            capture_output=True, text=True, timeout=30
        )
        info = _json.loads(p.stdout)
        w = info["streams"][0]["width"]
        h = info["streams"][0]["height"]
        codec = info["streams"][0]["codec_name"]
        dur = float(info["format"]["duration"])
        assert (w, h) == (1080, 1920), f"expected 1080x1920, got {w}x{h}"
        assert codec == "h264", f"expected h264, got {codec}"
        assert dur > 0.5, f"suspicious duration {dur}"
        # Audio track exists (aac)
        pa = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", out],
            capture_output=True, text=True, timeout=30
        )
        assert "aac" in pa.stdout.strip(), f"expected aac audio, got {pa.stdout!r}"

    def test_o_export_range_stream(self):
        final = _shared.get("final")
        clip_id = _shared.get("export_ready_clip_id")
        if not final or not clip_id:
            pytest.skip("no rendered export")
        r = requests.get(
            f"{API}/videos/{final['id']}/clips/{clip_id}/export/stream",
            headers={"Range": "bytes=0-2047"}, timeout=30,
        )
        assert r.status_code == 206
        assert r.headers.get("Accept-Ranges") == "bytes"
        assert "content-range" in {k.lower() for k in r.headers.keys()}
        assert len(r.content) == 2048

    def test_p_batch_render(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        job = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
        # pick up to 2 clips that are NOT already exported
        candidates = [c for c in job["clips"]
                      if c["export_status"] != "done"][:2]
        if len(candidates) < 2:
            # fall back: use any 2 clips (re-render is fine)
            candidates = job["clips"][:2]
        ids = [c["id"] for c in candidates]
        if len(ids) < 2:
            pytest.skip("need >=2 clips for batch")

        r = requests.post(f"{API}/videos/{final['id']}/clips/batch-render",
                          json={"clip_ids": ids}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rendering"] == len(ids)
        assert set(body["clip_ids"]) == set(ids)

        # Poll until all target clips leave 'rendering'
        deadline = time.time() + 360
        done_ids = set()
        errors = {}
        while time.time() < deadline:
            j = requests.get(f"{API}/videos/{final['id']}", timeout=30).json()
            for cid in ids:
                c = next(x for x in j["clips"] if x["id"] == cid)
                if c["export_status"] == "done":
                    done_ids.add(cid)
                elif c["export_status"] == "error":
                    errors[cid] = c.get("export_error")
            if len(done_ids) + len(errors) == len(ids):
                break
            time.sleep(3)

        # Independent export_status: one failure should not stop the rest.
        # We assert most clips finished with a terminal status.
        terminal = len(done_ids) + len(errors)
        assert terminal == len(ids), (
            f"batch did not reach terminal states: done={done_ids} errors={errors}"
        )
        # At least one clip should have rendered successfully.
        assert len(done_ids) >= 1, f"none of the batch clips rendered. errors={errors}"

    def test_zz_delete_job(self):
        final = _shared.get("final")
        if not final:
            pytest.skip("no job")
        r = requests.delete(f"{API}/videos/{final['id']}", timeout=60)
        assert r.status_code == 200
        # Verify gone
        r2 = requests.get(f"{API}/videos/{final['id']}", timeout=30)
        assert r2.status_code == 404
