import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const getConfig = () => api.get("/config").then((r) => r.data);
export const listVideos = () => api.get("/videos").then((r) => r.data);
export const getVideo = (id) => api.get(`/videos/${id}`).then((r) => r.data);
export const deleteVideo = (id) => api.delete(`/videos/${id}`).then((r) => r.data);
export const reprocessVideo = (id) =>
  api.post(`/videos/${id}/reprocess`).then((r) => r.data);

export const uploadVideo = (formData, onProgress) =>
  api
    .post("/videos/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total));
      },
    })
    .then((r) => r.data);

export const generateClip = (jobId, clipId) =>
  api.post(`/videos/${jobId}/clips/${clipId}/generate`).then((r) => r.data);
export const generateAll = (jobId, clipIds) =>
  api.post(`/videos/${jobId}/clips/generate-all`, { clip_ids: clipIds || null }).then((r) => r.data);
export const deleteClip = (jobId, clipId) =>
  api.delete(`/videos/${jobId}/clips/${clipId}`).then((r) => r.data);

export const streamUrl = (jobId) => `${API}/videos/${jobId}/stream`;
export const clipStreamUrl = (jobId, clipId) =>
  `${API}/videos/${jobId}/clips/${clipId}/stream`;
export const clipDownloadUrl = (jobId, clipId) =>
  `${API}/videos/${jobId}/clips/${clipId}/download`;

// ---- formatting helpers ----
export const fmtTime = (s) => {
  if (s == null || isNaN(s)) return "00:00";
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
};

export const fmtDuration = (s) => {
  if (s == null || isNaN(s)) return "--";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}m ${sec}s`;
};

export const fmtBytes = (b) => {
  if (!b) return "--";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (b >= 1024 && i < units.length - 1) {
    b /= 1024;
    i++;
  }
  return `${b.toFixed(1)} ${units[i]}`;
};
