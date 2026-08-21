import React, { useRef, useState } from "react";
import { UploadCloud, Loader2, FileVideo } from "lucide-react";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { uploadVideo, fmtBytes } from "@/lib/studioApi";

const CONTENT_LABELS = {
  auto: "Auto Detect", podcast: "Podcast", interview: "Interview",
  gaming: "Gaming", livestream: "Livestream", vlog: "Vlog",
  entertainment: "Entertainment", educational: "Educational",
  sports: "Sports", other: "Other",
};
const PROVIDER_LABELS = {
  whisper_api: "Whisper (Hosted)",
  local_whisper: "Local Whisper (Offline)",
};

export default function UploadPanel({ config, onUploaded }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [contentType, setContentType] = useState("auto");
  const [provider, setProvider] = useState(config?.default_provider || "whisper_api");
  const [pending, setPending] = useState(null);

  const doUpload = async (file) => {
    if (!file) return;
    setPending({ name: file.name, size: file.size });
    setUploading(true);
    setProgress(0);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("content_type", contentType);
    fd.append("transcription_provider", provider);
    try {
      const job = await uploadVideo(fd, setProgress);
      toast.success("Upload complete — processing started");
      onUploaded(job);
    } catch (e) {
      const msg = e?.response?.data?.detail || "Upload failed";
      toast.error(msg);
    } finally {
      setUploading(false);
      setProgress(0);
      setPending(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (uploading) return;
    const file = e.dataTransfer.files?.[0];
    if (file) doUpload(file);
  };

  return (
    <div className="p-4 border-b border-[#2E2E32] space-y-3" data-testid="upload-panel">
      <div className="space-y-2">
        <label className="text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-400">
          Content Type
        </label>
        <Select value={contentType} onValueChange={setContentType} disabled={uploading}>
          <SelectTrigger className="h-8 text-xs rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="content-type-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#222224] border-[#2E2E32]">
            {(config?.content_types || []).map((ct) => (
              <SelectItem key={ct} value={ct} className="text-xs" data-testid={`content-type-option-${ct}`}>
                {CONTENT_LABELS[ct] || ct}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] uppercase tracking-[0.1em] font-bold text-neutral-400">
          Transcription
        </label>
        <Select value={provider} onValueChange={setProvider} disabled={uploading}>
          <SelectTrigger className="h-8 text-xs rounded-sm bg-[#0F0F11] border-[#2E2E32]" data-testid="provider-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#222224] border-[#2E2E32]">
            {(config?.transcription_providers || []).map((p) => (
              <SelectItem key={p} value={p} className="text-xs" data-testid={`provider-option-${p}`}>
                {PROVIDER_LABELS[p] || p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.webm,.avi,.m4v,.flv"
        className="hidden"
        data-testid="file-input"
        onChange={(e) => doUpload(e.target.files?.[0])}
      />

      <div
        onClick={() => !uploading && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={`cursor-pointer border border-dashed rounded-sm p-5 text-center transition-colors duration-150 ${
          dragging ? "border-[#2D8CFF] bg-[#2D8CFF]/5" : "border-neutral-600 hover:border-neutral-500"
        } ${uploading ? "opacity-70 pointer-events-none" : ""}`}
      >
        {uploading ? (
          <div className="space-y-2">
            <Loader2 className="h-5 w-5 mx-auto animate-spin text-[#2D8CFF]" />
            <div className="flex items-center justify-center gap-1.5 text-xs text-neutral-300 truncate">
              <FileVideo className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate max-w-[140px]">{pending?.name}</span>
            </div>
            <div className="h-1.5 bg-[#0F0F11] border border-[#2E2E32]">
              <div className="h-full bg-[#2D8CFF] transition-[width] duration-200" style={{ width: `${progress}%` }} />
            </div>
            <p className="font-mono text-[10px] text-neutral-400">
              {progress}% · {fmtBytes(pending?.size)}
            </p>
          </div>
        ) : (
          <div className="space-y-1.5">
            <UploadCloud className="h-6 w-6 mx-auto text-neutral-500" />
            <p className="text-xs text-neutral-300 font-medium">Drop video or click to upload</p>
            <p className="font-mono text-[10px] text-neutral-500">MP4 · MOV · MKV · WEBM · AVI</p>
          </div>
        )}
      </div>
    </div>
  );
}
