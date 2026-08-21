import React, { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { Clapperboard, Cpu, RotateCw } from "lucide-react";
import {
  getConfig, listVideos, getVideo, deleteVideo, reprocessVideo,
  generateClip, generateAll, deleteClip,
} from "@/lib/studioApi";
import UploadPanel from "./UploadPanel";
import JobList from "./JobList";
import CenterStage from "./CenterStage";
import ClipResults from "./ClipResults";

const PROCESSING = ["uploaded", "extracting_audio", "transcribing", "analyzing", "scoring"];

export default function Studio() {
  const [config, setConfig] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [job, setJob] = useState(null);
  const pollRef = useRef(null);
  const centerRef = useRef(null);

  const shouldPoll = useCallback((j) => {
    if (!j) return false;
    if (PROCESSING.includes(j.status)) return true;
    return (j.clips || []).some((c) => c.status === "generating");
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await listVideos());
    } catch (e) { /* ignore */ }
  }, []);

  useEffect(() => {
    getConfig().then(setConfig).catch(() => toast.error("Failed to load config"));
    refreshJobs();
  }, [refreshJobs]);

  // Poll the selected job while it is processing / rendering.
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!selectedId) return;

    const tick = async () => {
      try {
        const j = await getVideo(selectedId);
        setJob(j);
        setJobs((prev) => prev.map((p) => (p.id === j.id ? { ...p, ...j, transcript: undefined } : p)));
        if (!shouldPoll(j)) clearInterval(pollRef.current);
      } catch (e) {
        clearInterval(pollRef.current);
      }
    };
    tick();
    pollRef.current = setInterval(tick, 2500);
    return () => clearInterval(pollRef.current);
  }, [selectedId, shouldPoll]);

  const onUploaded = (newJob) => {
    setJobs((prev) => [newJob, ...prev]);
    setSelectedId(newJob.id);
  };

  const handleDeleteJob = async (id) => {
    try {
      await deleteVideo(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
      if (selectedId === id) { setSelectedId(null); setJob(null); }
      toast.success("Video deleted");
    } catch (e) { toast.error("Delete failed"); }
  };

  const handleReprocess = async () => {
    if (!job) return;
    try {
      await reprocessVideo(job.id);
      toast.info("Reprocessing started");
      const j = await getVideo(job.id);
      setJob(j);
      clearInterval(pollRef.current);
      setSelectedId(null);
      setTimeout(() => setSelectedId(job.id), 50);
    } catch (e) { toast.error(e?.response?.data?.detail || "Reprocess failed"); }
  };

  const preview = (clip) => {
    centerRef.current?.seek(clip.start, clip.end);
    toast.message(`Previewing: ${clip.title}`);
  };

  const genOne = async (clip) => {
    setJob((j) => ({ ...j, clips: j.clips.map((c) => c.id === clip.id ? { ...c, status: "generating" } : c) }));
    try {
      const updated = await generateClip(job.id, clip.id);
      setJob((j) => ({ ...j, clips: j.clips.map((c) => c.id === clip.id ? updated : c) }));
      if (updated?.status === "generated") toast.success("Clip rendered");
      else toast.error(updated?.error || "Render failed");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Render failed");
      const j = await getVideo(job.id); setJob(j);
    }
  };

  const genAll = async () => {
    try {
      const res = await generateAll(job.id);
      toast.info(`Rendering ${res.generating} clip(s)…`);
      const j = await getVideo(job.id); setJob(j);
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        const fresh = await getVideo(job.id);
        setJob(fresh);
        if (!shouldPoll(fresh)) clearInterval(pollRef.current);
      }, 2500);
    } catch (e) { toast.error(e?.response?.data?.detail || "Generate all failed"); }
  };

  const delClip = async (clip) => {
    try {
      await deleteClip(job.id, clip.id);
      setJob((j) => ({ ...j, clips: j.clips.filter((c) => c.id !== clip.id) }));
      toast.success("Candidate removed");
    } catch (e) { toast.error("Delete failed"); }
  };

  return (
    <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
      {/* Top bar */}
      <header className="h-12 shrink-0 border-b border-[#2E2E32] flex items-center px-4 gap-3 bg-[#18181A]">
        <Clapperboard className="h-5 w-5 text-[#2D8CFF]" />
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tracking-tight">CLIP LAB</span>
          <span className="font-mono text-[10px] text-neutral-500">AI VIDEO CLIPPING LABORATORY</span>
        </div>
        <div className="ml-auto flex items-center gap-3 font-mono text-[10px] text-neutral-400">
          <span className="flex items-center gap-1.5">
            <Cpu className="h-3.5 w-3.5 text-[#2D8CFF]" />
            {config?.analysis_model || "…"}
          </span>
        </div>
      </header>

      {/* IDE 3-column layout */}
      <div className="flex-1 min-h-0 flex">
        {/* Left sidebar */}
        <aside className="w-80 shrink-0 border-r border-[#2E2E32] flex flex-col bg-[#18181A]">
          <UploadPanel config={config} onUploaded={onUploaded} />
          <JobList jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} onDelete={handleDeleteJob} />
        </aside>

        {/* Center */}
        <main className="flex-1 min-w-0 grid-noise">
          {job ? (
            <div className="h-full flex flex-col">
              {job.status === "ready" && (
                <div className="h-8 shrink-0 border-b border-[#2E2E32] flex items-center px-4 bg-[#141416]">
                  <button
                    onClick={handleReprocess}
                    className="flex items-center gap-1.5 font-mono text-[10px] text-neutral-400 hover:text-[#2D8CFF] transition-colors"
                    data-testid="reprocess-button"
                  >
                    <RotateCw className="h-3 w-3" /> RE-RUN ANALYSIS
                  </button>
                </div>
              )}
              <div className="flex-1 min-h-0">
                <CenterStage ref={centerRef} job={job} />
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center" data-testid="empty-stage">
              <div className="text-center max-w-sm px-6">
                <Clapperboard className="h-10 w-10 mx-auto text-neutral-700 mb-4" />
                <h2 className="text-xl tracking-tight font-medium text-neutral-300">
                  Upload a video to begin
                </h2>
                <p className="text-sm text-neutral-500 mt-2 leading-relaxed">
                  Extract audio, transcribe with timestamps, and let AI surface the
                  strongest standalone moments — then render clips with FFmpeg.
                </p>
              </div>
            </div>
          )}
        </main>

        {/* Right sidebar */}
        <aside className="w-[420px] shrink-0 border-l border-[#2E2E32] bg-[#141416]">
          {job ? (
            <ClipResults
              job={job}
              onPreview={preview}
              onGenerate={genOne}
              onGenerateAll={genAll}
              onDelete={delClip}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-neutral-600">
              No video selected
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
