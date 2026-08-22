import React, { useEffect, useRef, useState } from "react";
import {
  X, Play, Clapperboard, Download, Loader2, Type, Copy, Check,
  Crop, Captions, Scissors, Sparkles, RefreshCw, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  streamUrl, exportStreamUrl, exportDownloadUrl,
  updateEdit, buildCaptions, saveCaptions, renderExport, fmtTime,
} from "@/lib/studioApi";

const ASPECTS = [
  { v: "9:16", label: "9:16" },
  { v: "1:1", label: "1:1" },
  { v: "original", label: "Original" },
];

function Section({ icon: Icon, title, children }) {
  return (
    <div className="border border-[#2E2E32] rounded-sm">
      <div className="px-3 py-2 border-b border-[#2E2E32] flex items-center gap-2 bg-[#18181A]">
        <Icon className="h-3.5 w-3.5 text-[#2D8CFF]" />
        <span className="text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-300">{title}</span>
      </div>
      <div className="p-3 space-y-3">{children}</div>
    </div>
  );
}

const CopyBtn = ({ text, testid }) => {
  const [done, setDone] = useState(false);
  return (
    <button
      data-testid={testid}
      onClick={() => { navigator.clipboard?.writeText(text || ""); setDone(true); setTimeout(() => setDone(false), 1200); }}
      className="text-neutral-500 hover:text-[#2D8CFF] transition-colors"
      title="Copy"
    >
      {done ? <Check className="h-3.5 w-3.5 text-[#10B981]" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
};

export default function Editor({ jobId, clip, contentType, onClose, onRenderStart }) {
  const videoRef = useRef(null);
  const stopRef = useRef(null);
  const defaults = clip.edit || {
    aspect_ratio: "9:16", caption_preset: "clean", caption_position: "bottom",
    remove_pauses: false, dynamic_effects: false, reframe_mode: "face",
    start: null, end: null,
  };
  const [s, setS] = useState({
    aspect_ratio: defaults.aspect_ratio || "9:16",
    caption_preset: defaults.caption_preset || "clean",
    caption_position: defaults.caption_position || "bottom",
    remove_pauses: !!defaults.remove_pauses,
    dynamic_effects: !!defaults.dynamic_effects,
    reframe_mode: defaults.reframe_mode || "face",
  });
  const [start, setStart] = useState(defaults.start ?? clip.start);
  const [end, setEnd] = useState(defaults.end ?? clip.end);
  const [captions, setCaptions] = useState(clip.captions || []);
  const [capLoading, setCapLoading] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [previewMode, setPreviewMode] = useState(clip.export_status === "done" ? "rendered" : "source");

  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));

  // React to render completion coming from parent polling.
  useEffect(() => {
    if (clip.export_status === "done") {
      setRendering(false);
      setPreviewMode("rendered");
    } else if (clip.export_status === "error") {
      setRendering(false);
    } else if (clip.export_status === "rendering") {
      setRendering(true);
    }
  }, [clip.export_status]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (previewMode === "rendered") { v.currentTime = 0; }
    else { v.currentTime = start || 0; }
  }, [previewMode]); // eslint-disable-line

  const onTimeUpdate = (e) => {
    if (previewMode === "source" && stopRef.current != null && e.target.currentTime >= stopRef.current) {
      e.target.pause(); stopRef.current = null;
    }
  };

  const previewSource = () => {
    setPreviewMode("source");
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = start || 0;
    stopRef.current = end;
    v.play().catch(() => {});
  };

  const genCaptions = async () => {
    setCapLoading(true);
    try {
      await updateEdit(jobId, clip.id, { ...s, start, end });
      const res = await buildCaptions(jobId, clip.id);
      setCaptions(res.captions || []);
      toast.success(`Generated ${res.captions?.length || 0} caption lines`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Caption generation failed"); }
    finally { setCapLoading(false); }
  };

  const doRender = async () => {
    setRendering(true);
    try {
      await updateEdit(jobId, clip.id, { ...s, start, end });
      if (captions.length) await saveCaptions(jobId, clip.id, captions);
      await renderExport(jobId, clip.id);
      onRenderStart?.();
      toast.info("Rendering final short…");
    } catch (e) {
      setRendering(false);
      toast.error(e?.response?.data?.detail || "Render failed to start");
    }
  };

  const updateCaptionText = (i, text) =>
    setCaptions((prev) => prev.map((l, idx) => (idx === i ? { ...l, text } : l)));

  const isVertical = s.aspect_ratio === "9:16";
  const exportReady = clip.export_status === "done";

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" data-testid="clip-editor">
      <div className="bg-[#141416] border border-[#2E2E32] rounded-sm w-full max-w-6xl h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="h-12 shrink-0 border-b border-[#2E2E32] flex items-center px-4 gap-3 bg-[#18181A]">
          <Clapperboard className="h-4 w-4 text-[#2D8CFF]" />
          <span className="text-sm font-medium truncate">{clip.title}</span>
          <span className="font-mono text-[10px] text-neutral-500 ml-2">
            {fmtTime(start)} → {fmtTime(end)}
          </span>
          <button onClick={onClose} className="ml-auto text-neutral-400 hover:text-neutral-100" data-testid="editor-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 flex">
          {/* Preview */}
          <div className="flex-1 min-w-0 bg-black flex flex-col">
            <div className="h-9 shrink-0 flex items-center gap-1 px-3 border-b border-[#2E2E32] bg-[#0F0F11]">
              <button
                onClick={() => setPreviewMode("source")}
                className={`text-[10px] font-mono px-2 py-1 rounded-sm ${previewMode === "source" ? "bg-[#222224] text-neutral-100" : "text-neutral-500"}`}
                data-testid="preview-mode-source"
              >SOURCE</button>
              <button
                onClick={() => exportReady && setPreviewMode("rendered")}
                disabled={!exportReady}
                className={`text-[10px] font-mono px-2 py-1 rounded-sm disabled:opacity-40 ${previewMode === "rendered" ? "bg-[#222224] text-neutral-100" : "text-neutral-500"}`}
                data-testid="preview-mode-rendered"
              >RENDERED {exportReady ? "" : "(none)"}</button>
              <Button size="sm" className="h-6 px-2 text-[10px] rounded-sm ml-auto bg-[#222224] hover:bg-white/10 border border-[#2E2E32]" onClick={previewSource} data-testid="editor-preview-btn">
                <Play className="h-3 w-3 mr-1" /> Play range
              </Button>
            </div>
            <div className="flex-1 min-h-0 flex items-center justify-center p-4">
              <video
                key={previewMode + (clip.export_path || "")}
                ref={videoRef}
                src={previewMode === "rendered" && exportReady ? exportStreamUrl(jobId, clip.id) : streamUrl(jobId)}
                controls
                onTimeUpdate={onTimeUpdate}
                className={`bg-black ${previewMode === "rendered" && isVertical ? "h-full" : "max-h-full max-w-full"}`}
                style={previewMode === "rendered" && isVertical ? { aspectRatio: "9/16" } : {}}
                data-testid="editor-video"
              />
            </div>
          </div>

          {/* Controls */}
          <div className="w-[380px] shrink-0 border-l border-[#2E2E32] overflow-y-auto p-3 space-y-3">
            <Section icon={Crop} title="Aspect & Reframe">
              <div className="flex gap-1.5">
                {ASPECTS.map((a) => (
                  <button
                    key={a.v}
                    onClick={() => set("aspect_ratio", a.v)}
                    data-testid={`aspect-${a.v}`}
                    className={`flex-1 h-8 text-xs rounded-sm border transition-colors ${s.aspect_ratio === a.v ? "bg-[#2D8CFF] border-[#2D8CFF] text-white" : "bg-[#0F0F11] border-[#2E2E32] text-neutral-300 hover:border-neutral-500"}`}
                  >{a.label}</button>
                ))}
              </div>
              {s.aspect_ratio !== "original" && (
                <div className="flex gap-1.5">
                  <button onClick={() => set("reframe_mode", "face")} data-testid="reframe-face"
                    className={`flex-1 h-7 text-[11px] rounded-sm border ${s.reframe_mode === "face" ? "bg-[#222224] border-[#2D8CFF] text-neutral-100" : "bg-[#0F0F11] border-[#2E2E32] text-neutral-400"}`}>
                    Track Speaker
                  </button>
                  <button onClick={() => set("reframe_mode", "preserve")} data-testid="reframe-preserve"
                    className={`flex-1 h-7 text-[11px] rounded-sm border ${s.reframe_mode === "preserve" ? "bg-[#222224] border-[#2D8CFF] text-neutral-100" : "bg-[#0F0F11] border-[#2E2E32] text-neutral-400"}`}>
                    Preserve Screen
                  </button>
                </div>
              )}
            </Section>

            <Section icon={Captions} title="Captions">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-neutral-500">Style</label>
                  <Select value={s.caption_preset} onValueChange={(v) => set("caption_preset", v)}>
                    <SelectTrigger className="h-8 text-xs rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="caption-preset-select"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[#222224] border-[#2E2E32]">
                      {["clean", "bold", "highlight", "none"].map((p) => (
                        <SelectItem key={p} value={p} className="text-xs capitalize" data-testid={`caption-preset-${p}`}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-[10px] text-neutral-500">Position</label>
                  <Select value={s.caption_position} onValueChange={(v) => set("caption_position", v)}>
                    <SelectTrigger className="h-8 text-xs rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="caption-position-select"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-[#222224] border-[#2E2E32]">
                      {["bottom", "center", "top"].map((p) => (
                        <SelectItem key={p} value={p} className="text-xs capitalize" data-testid={`caption-position-${p}`}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button size="sm" variant="secondary" className="w-full h-7 text-xs rounded-sm bg-[#222224] hover:bg-white/10 border border-[#2E2E32]" onClick={genCaptions} disabled={capLoading} data-testid="generate-captions-btn">
                {capLoading ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Type className="h-3 w-3 mr-1" />}
                {captions.length ? "Regenerate captions" : "Generate captions"}
              </Button>
              {captions.length > 0 && (
                <div className="max-h-40 overflow-y-auto space-y-1 pt-1" data-testid="caption-editor-list">
                  {captions.map((l, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <span className="font-mono text-[9px] text-neutral-500 w-9 shrink-0">{fmtTime(l.start)}</span>
                      <Input
                        value={l.text}
                        onChange={(e) => updateCaptionText(i, e.target.value)}
                        className="h-6 text-[11px] rounded-sm bg-[#0F0F11] border-[#2E2E32] px-1.5"
                        data-testid={`caption-line-${i}`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={Scissors} title="Pacing & Motion">
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-300">Remove unnecessary pauses</span>
                <Switch checked={s.remove_pauses} onCheckedChange={(v) => set("remove_pauses", v)} data-testid="remove-pauses-switch" />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-300">Subtle dynamic motion</span>
                <Switch checked={s.dynamic_effects} onCheckedChange={(v) => set("dynamic_effects", v)} data-testid="dynamic-effects-switch" />
              </div>
            </Section>

            <Section icon={Scissors} title="Boundaries">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-neutral-500">Start (s)</label>
                  <Input type="number" step="0.1" value={start} onChange={(e) => setStart(parseFloat(e.target.value) || 0)}
                    className="h-8 text-xs font-mono rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="start-input" />
                </div>
                <div>
                  <label className="text-[10px] text-neutral-500">End (s)</label>
                  <Input type="number" step="0.1" value={end} onChange={(e) => setEnd(parseFloat(e.target.value) || 0)}
                    className="h-8 text-xs font-mono rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="end-input" />
                </div>
              </div>
              <button onClick={() => { setStart(clip.start); setEnd(clip.end); }} className="text-[10px] font-mono text-neutral-500 hover:text-[#2D8CFF] flex items-center gap-1" data-testid="reset-boundaries">
                <RefreshCw className="h-3 w-3" /> Reset to AI boundaries
              </button>
            </Section>

            <Section icon={Sparkles} title="Suggestions">
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[10px] text-neutral-500 uppercase tracking-wider">Title</p>
                    <p className="text-xs text-neutral-200">{clip.title}</p>
                  </div>
                  <CopyBtn text={clip.title} testid="copy-title" />
                </div>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[10px] text-neutral-500 uppercase tracking-wider">Hook</p>
                    <p className="text-xs text-neutral-300 italic">"{clip.hook}"</p>
                  </div>
                  <CopyBtn text={clip.hook} testid="copy-hook" />
                </div>
                <div>
                  <p className="text-[10px] text-neutral-500 uppercase tracking-wider">Why it works</p>
                  <p className="text-xs text-neutral-300 leading-relaxed">{clip.reason}</p>
                </div>
              </div>
            </Section>
          </div>
        </div>

        {/* Footer actions */}
        <div className="h-14 shrink-0 border-t border-[#2E2E32] flex items-center px-4 gap-2 bg-[#18181A]">
          {clip.export_status === "error" && (
            <span className="flex items-center gap-1.5 text-[11px] text-[#EF4444] font-mono" data-testid="export-error">
              <AlertTriangle className="h-3.5 w-3.5" /> {clip.export_error}
            </span>
          )}
          {clip.export_status === "done" && (
            <span className="text-[11px] text-[#10B981] font-mono">Export ready · {clip.export_aspect}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <Button onClick={doRender} disabled={rendering} className="h-9 px-4 text-sm rounded-sm bg-[#2D8CFF] hover:bg-[#1A73E8]" data-testid="render-btn">
              {rendering ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Clapperboard className="h-4 w-4 mr-1.5" />}
              {rendering ? "Rendering…" : "Render"}
            </Button>
            {exportReady ? (
              <a href={exportDownloadUrl(jobId, clip.id)} data-testid="editor-download">
                <Button className="h-9 px-4 text-sm rounded-sm bg-[#10B981] hover:bg-[#0e9f70]">
                  <Download className="h-4 w-4 mr-1.5" /> Download MP4
                </Button>
              </a>
            ) : (
              <Button disabled className="h-9 px-4 text-sm rounded-sm bg-[#222224] text-neutral-500 border border-[#2E2E32]">
                <Download className="h-4 w-4 mr-1.5" /> Download MP4
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
