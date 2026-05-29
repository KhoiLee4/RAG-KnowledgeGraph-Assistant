/**
 * client.js — Axios HTTP client giao tiếp với FastAPI backend.
 *
 * Tất cả API call đều đi qua file này để dễ bảo trì
 * và tập trung xử lý lỗi/loading tại một nơi.
 */

import axios from "axios";

// Base URL của backend FastAPI
// Khi dev với Vite proxy → dùng /api (proxy tới localhost:8081)
// Khi deploy tách riêng → set VITE_API_BASE_URL trong .env
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

/** Axios instance cho chat (Gemini có thể chậm khi retry quota) */
const chatApi = axios.create({
  baseURL: BASE_URL,
  timeout: 180000, // 3 phút
  headers: {
    "Content-Type": "application/json",
  },
});

/** Axios instance dùng chung cho toàn bộ ứng dụng */
const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
  },
});

/** Client sync Drive — không giới hạn thời gian chờ */
const syncApi = axios.create({
  baseURL: BASE_URL,
  timeout: 0,
  headers: { "Content-Type": "application/json" },
});

/** Chuẩn hóa response sync (API: indexed/total_found/errors) */
export function normalizeSyncResult(data) {
  if (!data) return data;
  return {
    ...data,
    success: data.indexed ?? data.success ?? 0,
    files_found: data.total_found ?? data.files_found ?? 0,
    failed: data.errors ?? data.failed ?? 0,
    skipped: data.skipped ?? 0,
    account_email: data.account_email ?? null,
  };
}

export function formatApiError(err) {
  const detail = err?.response?.data?.detail || err?.message || "";
  if (
    err?.code === "ECONNABORTED" ||
    String(detail).toLowerCase().includes("timeout")
  ) {
    return (
      "Phản hồi quá lâu (timeout). Thử lại sau vài phút hoặc hỏi câu ngắn hơn. " +
      "Câu 'tôi có gì' / 'hỏi được chủ đề gì' trả lời ngay, không cần Gemini."
    );
  }
  if (
    String(detail).toLowerCase().includes("429") ||
    String(detail).toLowerCase().includes("quota") ||
    String(detail).toLowerCase().includes("resource_exhausted")
  ) {
    return (
      "Đã vượt quota Gemini API (free tier). Đợi 1–2 phút rồi thử lại, " +
      "hoặc đổi API key / bật billing. Câu hỏi 'tôi có những gì' vẫn trả lời được không cần quota."
    );
  }
  if (typeof detail === "string" && detail.length > 300) {
    return detail.slice(0, 300) + "...";
  }
  return detail || "Lỗi không xác định";
}

/** Tóm tắt lỗi đồng bộ từ details[] */
export function summarizeSyncErrors(details = []) {
  const counts = {};
  for (const d of details) {
    if (d.status !== "error") continue;
    const reason = (d.reason || "Không rõ").slice(0, 80);
    counts[reason] = (counts[reason] || 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([reason, n]) => `• ${n}× ${reason}`)
    .join("\n");
}

/** True khi Vite proxy / backend không phản hồi (ECONNREFUSED, v.v.) */
export function isBackendUnreachable(err) {
  if (err?.response) return false;
  const msg = String(err?.message || "");
  return (
    err?.code === "ERR_NETWORK" ||
    msg.includes("Network Error") ||
    msg.includes("ECONNREFUSED")
  );
}

export const BACKEND_UNREACHABLE_MSG =
  "Không kết nối được backend (http://localhost:8081). " +
  "Chạy: cd backend → .\\start.ps1";

// ── Interceptor log lỗi ──────────────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg =
      error.response?.data?.detail || error.message || "Lỗi không xác định";
    console.error(`[API Error] ${error.config?.url}: ${msg}`);
    return Promise.reject(error);
  },
);

// ════════════════════════════════════════════════════════════
// Chat API
// ════════════════════════════════════════════════════════════

/**
 * Gửi câu hỏi và nhận câu trả lời từ backend RAG.
 *
 * @param {string} question - Câu hỏi của người dùng
 * @param {string} collectionName - Tên ChromaDB collection (để trống = mặc định)
 * @param {Array}  history - Lịch sử hội thoại [{role, content}]
 * @returns {Promise<{answer, citations, sources_count}>}
 */
export async function sendChat(question, collectionName = "", history = []) {
  const response = await chatApi.post("/chat", {
    question,
    collection_name: collectionName,
    history,
    stream: false,
  });
  return response.data;
}

/**
 * Lấy URL cho streaming chat (Server-Sent Events).
 * Dùng với EventSource hoặc fetch() stream.
 *
 * @param {string} question - Câu hỏi
 * @returns {string} URL endpoint stream
 */
export function getChatStreamUrl() {
  return `${BASE_URL}/chat`;
}

/**
 * Gửi câu hỏi và nhận streaming response qua fetch API.
 * Gọi onChunk(text) cho mỗi đoạn văn bản nhận được.
 * Gọi onCitations(citations) khi stream kết thúc.
 * Gọi onDone() khi hoàn tất.
 *
 * @param {string} question
 * @param {Function} onChunk - Callback nhận từng chunk text
 * @param {Function} onCitations - Callback nhận danh sách citations
 * @param {Function} onDone - Callback khi hoàn tất
 * @param {Function} onError - Callback khi lỗi
 */
export async function sendChatStream(
  question,
  onChunk,
  onCitations,
  onDone,
  onError,
) {
  try {
    const response = await fetch(`${BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, stream: true }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value, { stream: true });
      const lines = text.split("\n");

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);

        if (data === "[DONE]") {
          onDone?.();
        } else if (data.startsWith("[CITATIONS]")) {
          try {
            const citations = JSON.parse(data.slice(11));
            onCitations?.(citations);
          } catch {}
        } else if (data.startsWith("[ERROR]")) {
          onError?.(data.slice(7));
        } else {
          // Đổi \\n về \n để hiển thị đúng
          onChunk?.(data.replace(/\\n/g, "\n"));
        }
      }
    }
  } catch (err) {
    onError?.(err.message);
  }
}

// ════════════════════════════════════════════════════════════
// Documents API
// ════════════════════════════════════════════════════════════

/**
 * Lấy danh sách tài liệu đã index.
 *
 * @param {number} limit - Số lượng tối đa (mặc định 50)
 * @returns {Promise<Array<{id, file_name, mime_type, chunk_count, drive_link}>>}
 */
export async function getDocuments(limit = 50) {
  const response = await api.get("/documents", { params: { limit } });
  return response.data;
}

/**
 * Xóa tài liệu khỏi knowledge base.
 *
 * @param {string} fileId - Google Drive file ID
 * @returns {Promise<{status, message}>}
 */
export async function deleteDocument(fileId) {
  const response = await api.delete(`/documents/${fileId}`);
  return response.data;
}

// ════════════════════════════════════════════════════════════
// Google Drive API
// ════════════════════════════════════════════════════════════

/**
 * Kiểm tra trạng thái đăng nhập Google Drive.
 * @returns {Promise<{authenticated, has_credentials, has_token, email, message}>}
 */
export async function getDriveStatus() {
  const response = await api.get("/drive/status");
  return response.data;
}

/**
 * Đăng nhập Google Drive (mở browser trên máy chạy backend).
 * @returns {Promise<{authenticated, email, message}>}
 */
export async function loginDrive() {
  const response = await api.post("/drive/login");
  return response.data;
}

/**
 * Xem trước file được hỗ trợ trên Drive.
 */
export async function previewDriveFiles(folderId = null, limit = 20) {
  const response = await api.get("/drive/files", {
    params: { folder_id: folderId, limit },
  });
  return response.data;
}

/**
 * Đồng bộ TOÀN BỘ Drive (chạy nền + poll — không timeout 10 phút).
 * @param {function} [options.onProgress] - (job) => void mỗi lần poll
 */
export async function syncAllDrive(
  forceReindex = false,
  folderId = null,
  { onProgress } = {},
) {
  const start = await syncApi.post("/drive/sync-all/async", null, {
    params: { force_reindex: forceReindex, folder_id: folderId },
  });
  const jobId = start.data.job_id;
  const pollMs = 2500;

  for (;;) {
    await new Promise((r) => setTimeout(r, pollMs));
    const { data: job } = await api.get(`/drive/sync-all/jobs/${jobId}`);
    onProgress?.(job);

    if (job.status === "completed") {
      return normalizeSyncResult(job.result);
    }
    if (job.status === "failed") {
      throw new Error(job.error || job.message || "Đồng bộ thất bại.");
    }
  }
}

/** Trạng thái job đồng bộ (dùng khi cần hiển thị progress tùy chỉnh). */
export async function getSyncJobStatus(jobId) {
  const { data } = await api.get(`/drive/sync-all/jobs/${jobId}`);
  return data;
}

/**
 * Đồng bộ theo danh sách file ID (hoặc toàn Drive nếu fileIds rỗng).
 */
export async function syncDrive(
  fileIds = [],
  folderId = null,
  forceReindex = false,
) {
  const response = await syncApi.post("/sync-drive", {
    file_ids: fileIds,
    folder_id: folderId,
    force_reindex: forceReindex,
  });
  return normalizeSyncResult(response.data);
}

// ════════════════════════════════════════════════════════════
// Health Check
// ════════════════════════════════════════════════════════════

/**
 * Kiểm tra trạng thái hệ thống (ChromaDB + Neo4j).
 *
 * @returns {Promise<{status, services: {chromadb, neo4j}}>}
 */
export async function getHealth() {
  const response = await api.get("/health");
  return response.data;
}

export default api;
