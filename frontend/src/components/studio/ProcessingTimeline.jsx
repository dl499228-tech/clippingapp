import React from "react";
import { Loader2, CheckCircle2, XCircle, Circle } from "lucide-react";

const STEP_ORDER = [
  { key: "extract_audio", label: "Extract audio" },
  { key: "transcribe", label: "Transcribe" },
  { key: "diarize", label: "Speaker labels" },
  { key: "analyze", label: "AI analysis" },
  { key: "score", label: "Score & boundaries" },
  { key: "ready", label: "Complete" },
];

export default function ProcessingTimeline({ job }) {
  const logs = job?.step_logs || [];
  const byStep = {};
  logs.forEach((l) => { byStep[l.step] = l; });
  const errored = job?.status === "error";

  const renderIcon = (state) => {
    if (state === "done") return <CheckCircle2 className="h-4 w-4" style={{ color: "#10B981" }} />;
    if (state === "running") return <Loader2 className="h-4 w-4 animate-spin" style={{ color: "#F59E0B" }} />;
    if (state === "error") return <XCircle className="h-4 w-4" style={{ color: "#EF4444" }} />;
    return <Circle className="h-4 w-4 text-neutral-600" />;
  };

  return (
    <div className="bg-[#0F0F11] border border-[#2E2E32] rounded-sm p-4" data-testid="processing-timeline">
      <div className="text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-400 mb-3">
        Pipeline
      </div>
      <div className="space-y-2 font-mono text-xs">
        {STEP_ORDER.map((step) => {
          const log = byStep[step.key];
          const state = log?.status || "pending";
          const running = state === "running" && !errored;
          return (
            <div key={step.key} className="flex items-start gap-2.5">
              <div className="mt-0.5">{renderIcon(errored && running ? "error" : state)}</div>
              <div className="min-w-0 flex-1">
                <span className={running ? "text-neutral-100 blink-cursor" : state === "done" ? "text-neutral-300" : "text-neutral-500"}>
                  {step.label}
                </span>
                {log?.message && (
                  <p className="text-[10px] text-neutral-500 truncate">{log.message}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {errored && (
        <div className="mt-3 p-2 border border-[#EF4444]/40 bg-[#EF4444]/10 rounded-sm">
          <p className="text-[10px] font-mono text-[#EF4444] break-words" data-testid="job-error">
            {job.error || "Processing failed"}
          </p>
        </div>
      )}
    </div>
  );
}
