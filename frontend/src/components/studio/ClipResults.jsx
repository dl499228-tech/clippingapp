import React, { useState } from "react";
import {
  Play, Download, Trash2, Loader2, ChevronDown, ChevronUp,
  Sparkles, Clapperboard, CheckCircle2, AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScoreBar, OverallScore } from "./ScoreBar";
import { fmtTime, fmtDuration, clipDownloadUrl } from "@/lib/studioApi";

const CATEGORY_COLORS = {
  hook: "#2D8CFF", story: "#A78BFA", insight: "#10B981", emotional: "#F472B6",
  humor: "#F59E0B", conflict: "#EF4444", opinion: "#60A5FA", surprise: "#FBBF24",
  educational: "#34D399", highlight: "#9CA3AF",
};

const METRICS = ["hook", "standalone", "payoff", "info_value", "emotional", "curiosity", "context", "social_appeal"];

function ClipCard({ clip, index, jobId, onPreview, onGenerate, onDelete }) {
  const [open, setOpen] = useState(false);
  const catColor = CATEGORY_COLORS[clip.category] || "#9CA3AF";
  const generating = clip.status === "generating";
  const generated = clip.status === "generated";

  return (
    <div className="border border-[#2E2E32] bg-[#18181A] rounded-sm" data-testid={`clip-card-${clip.id}`}>
      <div className="p-3">
        <div className="flex gap-3">
          <OverallScore value={clip.overall_score} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-neutral-500">#{index + 1}</span>
              <span
                className="text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 border rounded-sm"
                style={{ color: catColor, borderColor: `${catColor}55` }}
              >
                {clip.category}
              </span>
              {generated && <CheckCircle2 className="h-3 w-3 text-[#10B981]" />}
              {clip.status === "error" && <AlertTriangle className="h-3 w-3 text-[#EF4444]" />}
            </div>
            <p className="text-sm text-neutral-100 font-medium leading-snug mt-1 truncate" title={clip.title}>
              {clip.title}
            </p>
            <div className="flex items-center gap-3 mt-1 font-mono text-[10px] text-neutral-400">
              <span data-testid={`clip-range-${clip.id}`}>
                {fmtTime(clip.start)} → {fmtTime(clip.end)}
              </span>
              <span className="text-neutral-500">{fmtDuration(clip.duration)}</span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 mt-3">
          <Button
            size="sm" variant="secondary"
            className="h-7 px-2 text-xs rounded-sm bg-[#222224] hover:bg-white/10 border border-[#2E2E32]"
            onClick={() => onPreview(clip)}
            data-testid={`preview-clip-${clip.id}`}
          >
            <Play className="h-3 w-3 mr-1" /> Preview
          </Button>
          {generated ? (
            <a href={clipDownloadUrl(jobId, clip.id)} data-testid={`download-clip-${clip.id}`}>
              <Button size="sm" className="h-7 px-2 text-xs rounded-sm bg-[#2D8CFF] hover:bg-[#1A73E8]">
                <Download className="h-3 w-3 mr-1" /> Download
              </Button>
            </a>
          ) : (
            <Button
              size="sm"
              className="h-7 px-2 text-xs rounded-sm bg-[#2D8CFF] hover:bg-[#1A73E8]"
              disabled={generating}
              onClick={() => onGenerate(clip)}
              data-testid={`generate-clip-${clip.id}`}
            >
              {generating ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Clapperboard className="h-3 w-3 mr-1" />}
              {generating ? "Rendering" : "Generate"}
            </Button>
          )}
          <button
            onClick={() => onDelete(clip)}
            className="h-7 w-7 flex items-center justify-center rounded-sm text-neutral-500 hover:text-[#EF4444] hover:bg-white/5 transition-colors"
            data-testid={`delete-clip-${clip.id}`}
            title="Delete candidate"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setOpen((o) => !o)}
            className="ml-auto h-7 px-2 flex items-center gap-1 rounded-sm text-neutral-400 hover:text-neutral-200 text-[10px] font-mono"
            data-testid={`expand-clip-${clip.id}`}
          >
            {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            SCORES
          </button>
        </div>

        {clip.status === "error" && clip.error && (
          <p className="mt-2 text-[10px] font-mono text-[#EF4444]">{clip.error}</p>
        )}
      </div>

      {open && (
        <div className="border-t border-[#2E2E32] p-3 space-y-3 bg-[#141416]">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">Hook</p>
            <p className="text-xs text-neutral-300 italic">"{clip.hook}"</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">Why selected</p>
            <p className="text-xs text-neutral-300 leading-relaxed">{clip.reason}</p>
          </div>
          <div className="space-y-1.5 pt-1">
            {METRICS.map((mk) => (
              <ScoreBar key={mk} metric={mk} value={clip.scores?.[mk]} />
            ))}
          </div>
          <div className="flex items-center justify-between pt-1 font-mono text-[10px] text-neutral-500">
            <span>AI confidence: {Math.round((clip.confidence || 0) * 100)}%</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ClipResults({ job, onPreview, onGenerate, onGenerateAll, onDelete }) {
  const clips = job?.clips || [];
  const anyGenerating = clips.some((c) => c.status === "generating");
  const pendingCount = clips.filter((c) => c.status !== "generated").length;

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="clip-results">
      <div className="px-4 py-2.5 border-b border-[#2E2E32] flex items-center justify-between bg-[#18181A]">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[#2D8CFF]" />
          <span className="text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-300">
            Candidate Clips · {clips.length}
          </span>
        </div>
        {clips.length > 0 && (
          <Button
            size="sm"
            className="h-7 px-2.5 text-xs rounded-sm bg-[#2D8CFF] hover:bg-[#1A73E8]"
            disabled={anyGenerating || pendingCount === 0}
            onClick={onGenerateAll}
            data-testid="generate-all-button"
          >
            {anyGenerating ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Clapperboard className="h-3 w-3 mr-1" />}
            Generate All
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {clips.length === 0 ? (
          <div className="text-center py-10 text-xs text-neutral-500" data-testid="clips-empty">
            {job?.status === "ready"
              ? "No clip candidates were found."
              : "Clips will appear here once analysis completes."}
          </div>
        ) : (
          clips.map((clip, i) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              index={i}
              jobId={job.id}
              onPreview={onPreview}
              onGenerate={onGenerate}
              onDelete={onDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}
