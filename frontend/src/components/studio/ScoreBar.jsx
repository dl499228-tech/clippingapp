import React from "react";

const colorFor = (v) => {
  if (v >= 80) return "#10B981";
  if (v >= 60) return "#2D8CFF";
  if (v >= 40) return "#F59E0B";
  return "#EF4444";
};

export const METRIC_LABELS = {
  hook: "Hook",
  standalone: "Standalone",
  payoff: "Payoff",
  info_value: "Info Value",
  emotional: "Emotional",
  curiosity: "Curiosity",
  context: "Context",
  social_appeal: "Social Appeal",
};

export const ScoreBar = ({ metric, value }) => {
  const v = Math.round(value || 0);
  return (
    <div className="flex items-center gap-2" data-testid={`score-metric-${metric}`}>
      <span className="text-[10px] uppercase tracking-wider text-neutral-400 w-[86px] shrink-0">
        {METRIC_LABELS[metric] || metric}
      </span>
      <div className="flex-1 h-1.5 bg-[#0F0F11] border border-[#2E2E32]">
        <div
          className="h-full transition-[width] duration-500"
          style={{ width: `${v}%`, backgroundColor: colorFor(v) }}
        />
      </div>
      <span className="font-mono text-[10px] w-6 text-right" style={{ color: colorFor(v) }}>
        {v}
      </span>
    </div>
  );
};

export const OverallScore = ({ value, size = "md" }) => {
  const v = Math.round(value || 0);
  const dim = size === "lg" ? "h-14 w-14 text-lg" : "h-11 w-11 text-sm";
  return (
    <div
      className={`${dim} shrink-0 flex flex-col items-center justify-center border font-mono font-semibold`}
      style={{ borderColor: colorFor(v), color: colorFor(v) }}
      data-testid="clip-overall-score"
    >
      {v}
      <span className="text-[7px] tracking-widest text-neutral-500 -mt-0.5">SCORE</span>
    </div>
  );
};

export default ScoreBar;
