import React from "react";
import { fmtTime } from "@/lib/studioApi";

const SPEAKER_COLORS = {
  "Speaker 1": "#2D8CFF",
  "Speaker 2": "#F59E0B",
  "Speaker 3": "#10B981",
  "Speaker 4": "#A78BFA",
};

export default function TranscriptViewer({ transcript, onSeek, activeTime }) {
  if (!transcript || transcript.length === 0) {
    return (
      <div className="p-6 text-center text-xs text-neutral-500" data-testid="transcript-empty">
        No transcript available.
      </div>
    );
  }
  return (
    <div className="divide-y divide-[#1f1f22]" data-testid="transcript-viewer">
      {transcript.map((seg, i) => {
        const color = SPEAKER_COLORS[seg.speaker] || "#9CA3AF";
        const isActive = activeTime != null && activeTime >= seg.start && activeTime < seg.end;
        return (
          <div
            key={i}
            className={`px-4 py-2 flex gap-3 hover:bg-white/[0.03] transition-colors duration-150 ${isActive ? "bg-[#2D8CFF]/10" : ""}`}
            data-testid={`transcript-segment-${i}`}
          >
            <button
              onClick={() => onSeek(seg.start)}
              className="font-mono text-[11px] text-[#2D8CFF] hover:underline shrink-0 pt-0.5"
              data-testid={`transcript-ts-${i}`}
            >
              {fmtTime(seg.start)}
            </button>
            <div className="min-w-0">
              {seg.speaker && (
                <span
                  className="inline-block text-[9px] font-mono px-1.5 py-0.5 mr-2 rounded-sm border align-middle"
                  style={{ color, borderColor: `${color}55` }}
                >
                  {seg.speaker}
                </span>
              )}
              <span className="text-xs text-neutral-300 leading-relaxed">{seg.text}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
