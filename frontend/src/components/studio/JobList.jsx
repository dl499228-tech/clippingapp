import React from "react";
import { Trash2, Film, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { fmtDuration, fmtBytes } from "@/lib/studioApi";

const STATUS_META = {
  uploaded: { label: "QUEUED", color: "#9CA3AF" },
  extracting_audio: { label: "AUDIO", color: "#F59E0B" },
  transcribing: { label: "TRANSCRIBE", color: "#F59E0B" },
  analyzing: { label: "ANALYZE", color: "#F59E0B" },
  scoring: { label: "SCORING", color: "#F59E0B" },
  ready: { label: "READY", color: "#10B981" },
  error: { label: "ERROR", color: "#EF4444" },
};

const StatusIcon = ({ status }) => {
  if (status === "ready") return <CheckCircle2 className="h-3.5 w-3.5" style={{ color: "#10B981" }} />;
  if (status === "error") return <AlertTriangle className="h-3.5 w-3.5" style={{ color: "#EF4444" }} />;
  return <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "#F59E0B" }} />;
};

export default function JobList({ jobs, selectedId, onSelect, onDelete }) {
  return (
    <div className="flex-1 overflow-y-auto" data-testid="job-list">
      <div className="px-4 py-2 text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-400 sticky top-0 bg-[#18181A] border-b border-[#2E2E32]">
        Library · {jobs.length}
      </div>
      {jobs.length === 0 && (
        <p className="px-4 py-6 text-xs text-neutral-500 text-center">No videos yet.</p>
      )}
      {jobs.map((j) => {
        const meta = STATUS_META[j.status] || STATUS_META.uploaded;
        const active = j.id === selectedId;
        return (
          <div
            key={j.id}
            onClick={() => onSelect(j.id)}
            data-testid={`job-item-${j.id}`}
            className={`group px-4 py-2.5 border-b border-[#232326] cursor-pointer transition-colors duration-150 ${
              active ? "bg-[#222224] border-l-2 border-l-[#2D8CFF]" : "hover:bg-white/[0.03] border-l-2 border-l-transparent"
            }`}
          >
            <div className="flex items-start gap-2">
              <Film className="h-3.5 w-3.5 mt-0.5 text-neutral-500 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-neutral-200 truncate font-medium" title={j.filename}>
                  {j.filename}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="flex items-center gap-1">
                    <StatusIcon status={j.status} />
                    <span className="font-mono text-[9px] tracking-wider" style={{ color: meta.color }}>
                      {meta.label}
                    </span>
                  </span>
                  <span className="font-mono text-[9px] text-neutral-500">
                    {fmtDuration(j.metadata?.duration)} · {fmtBytes(j.metadata?.size_bytes)}
                  </span>
                </div>
                {j.status !== "ready" && j.status !== "error" && (
                  <div className="h-1 mt-1.5 bg-[#0F0F11] border border-[#2E2E32]">
                    <div className="h-full bg-[#F59E0B] transition-[width] duration-500" style={{ width: `${j.progress || 0}%` }} />
                  </div>
                )}
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(j.id); }}
                data-testid={`delete-job-${j.id}`}
                className="opacity-0 group-hover:opacity-100 text-neutral-500 hover:text-[#EF4444] transition-colors"
                title="Delete video"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
