import React, {
  forwardRef, useImperativeHandle, useRef, useState, useEffect,
} from "react";
import { Film } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { streamUrl, fmtTime, fmtDuration } from "@/lib/studioApi";
import ProcessingTimeline from "./ProcessingTimeline";
import TranscriptViewer from "./TranscriptViewer";

const CenterStage = forwardRef(({ job }, ref) => {
  const videoRef = useRef(null);
  const stopAtRef = useRef(null);
  const [currentTime, setCurrentTime] = useState(0);

  useImperativeHandle(ref, () => ({
    seek: (t, playUntil = null) => {
      const v = videoRef.current;
      if (!v) return;
      stopAtRef.current = playUntil;
      v.currentTime = t;
      v.play().catch(() => {});
    },
  }));

  useEffect(() => {
    setCurrentTime(0);
    stopAtRef.current = null;
  }, [job?.id]);

  const onTimeUpdate = (e) => {
    const t = e.target.currentTime;
    setCurrentTime(t);
    if (stopAtRef.current != null && t >= stopAtRef.current) {
      e.target.pause();
      stopAtRef.current = null;
    }
  };

  const ready = job?.status === "ready";
  const m = job?.metadata || {};

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="center-stage">
      {/* Metadata bar */}
      <div className="px-4 py-2.5 border-b border-[#2E2E32] flex items-center gap-4 flex-wrap bg-[#18181A]">
        <div className="flex items-center gap-2 min-w-0">
          <Film className="h-4 w-4 text-[#2D8CFF] shrink-0" />
          <span className="text-sm text-neutral-100 font-medium truncate max-w-[280px]" title={job?.filename}>
            {job?.filename}
          </span>
        </div>
        <div className="flex items-center gap-4 font-mono text-[11px] text-neutral-400 ml-auto">
          <span data-testid="meta-duration">{fmtDuration(m.duration)}</span>
          <span data-testid="meta-resolution">{m.width}×{m.height}</span>
          <span>{m.fps ? `${m.fps}fps` : "--"}</span>
          <span className="uppercase">{m.video_codec || "--"}</span>
          {job?.detected_content_type && (
            <span className="px-1.5 py-0.5 border border-[#2D8CFF]/40 text-[#2D8CFF] rounded-sm uppercase tracking-wider" data-testid="detected-type">
              {job.detected_content_type}
            </span>
          )}
        </div>
      </div>

      {/* Video */}
      <div className="bg-black flex items-center justify-center border-b border-[#2E2E32]" style={{ height: "42%" }}>
        {job?.video_path ? (
          <video
            ref={videoRef}
            src={streamUrl(job.id)}
            controls
            onTimeUpdate={onTimeUpdate}
            className="h-full max-w-full"
            data-testid="main-video"
          />
        ) : (
          <div className="text-neutral-600 text-sm">No preview</div>
        )}
      </div>

      {/* Tabs: Transcript / Pipeline */}
      <div className="flex-1 min-h-0 flex flex-col">
        <Tabs defaultValue={ready ? "transcript" : "pipeline"} className="flex-1 min-h-0 flex flex-col">
          <TabsList className="rounded-none bg-[#18181A] border-b border-[#2E2E32] justify-start h-9 px-2">
            <TabsTrigger value="transcript" className="text-xs data-[state=active]:bg-[#222224] rounded-sm" data-testid="tab-transcript">
              Transcript
            </TabsTrigger>
            <TabsTrigger value="pipeline" className="text-xs data-[state=active]:bg-[#222224] rounded-sm" data-testid="tab-pipeline">
              Pipeline
            </TabsTrigger>
          </TabsList>
          <TabsContent value="transcript" className="flex-1 min-h-0 overflow-y-auto m-0">
            <TranscriptViewer
              transcript={job?.transcript}
              onSeek={(t) => ref.current?.seek(t)}
              activeTime={currentTime}
            />
          </TabsContent>
          <TabsContent value="pipeline" className="flex-1 min-h-0 overflow-y-auto m-0 p-4">
            <ProcessingTimeline job={job} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
});

export default CenterStage;
