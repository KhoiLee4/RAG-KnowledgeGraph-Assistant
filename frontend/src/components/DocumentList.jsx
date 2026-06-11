/**
 * DocumentList.jsx — Hiển thị danh sách tài liệu đã index vào knowledge base.
 *
 * Tính năng:
 *   - Liệt kê tài liệu từ API /documents
 *   - Hiển thị tên file, số chunk, link Drive
 *   - Nút xóa tài liệu khỏi knowledge base
 *   - Nút đồng bộ Drive (sync tất cả hoặc nhập file ID)
 *   - Loading/error state
 */

import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  FileText, Trash2, RefreshCw, ExternalLink,
  Plus, AlertCircle, CheckCircle2, Loader2, Database, LogOut
} from 'lucide-react'
import {
  getDocuments,
  deleteDocument,
  syncDrive,
  getDriveStatus,
  loginDrive,
  logoutAuth,
  getAuthConfig,
  syncAllDrive,
  previewDriveFiles,
  isBackendUnreachable,
  BACKEND_UNREACHABLE_MSG,
  summarizeSyncErrors,
} from '../api/client'

/** Badge màu theo MIME type */
function MimeBadge({ mimeType }) {
  const config = {
    'application/pdf': { label: 'PDF', color: 'bg-red-100 text-red-700' },
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': { label: 'DOCX', color: 'bg-blue-100 text-blue-700' },
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': { label: 'XLSX', color: 'bg-green-100 text-green-700' },
    'text/plain': { label: 'TXT', color: 'bg-gray-100 text-gray-700' },
    'image/jpeg': { label: 'JPEG', color: 'bg-yellow-100 text-yellow-700' },
    'image/png': { label: 'PNG', color: 'bg-yellow-100 text-yellow-700' },
  }
  const { label = 'FILE', color = 'bg-gray-100 text-gray-600' } =
    config[mimeType] || {}
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${color}`}>
      {label}
    </span>
  )
}

/** Card đại diện một tài liệu */
function DocumentCard({ doc, onDelete }) {
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async () => {
    if (!confirm(`Xóa tài liệu "${doc.file_name}" khỏi knowledge base?`)) return
    setDeleting(true)
    try {
      await onDelete(doc.id)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-start gap-3 hover:shadow-sm transition-shadow">
      {/* Icon file */}
      <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center flex-shrink-0">
        <FileText size={20} className="text-blue-500" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <p className="font-medium text-sm text-gray-800 truncate" title={doc.file_name}>
            {doc.file_name || doc.id}
          </p>
          <MimeBadge mimeType={doc.mime_type} />
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <Database size={11} />
            {doc.chunk_count ?? '?'} chunks
          </span>
          {doc.drive_link && (
            <a
              href={doc.drive_link}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-blue-500 hover:text-blue-700"
            >
              <ExternalLink size={11} />
              Xem Drive
            </a>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-0.5 font-mono truncate" title={doc.id}>
          ID: {doc.id}
        </p>
      </div>

      {/* Delete button */}
      <button
        onClick={handleDelete}
        disabled={deleting}
        className="text-gray-300 hover:text-red-500 p-1 rounded transition-colors disabled:opacity-50"
        title="Xóa tài liệu"
      >
        {deleting ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
      </button>
    </div>
  )
}

/** Panel đăng nhập Google Drive + đồng bộ toàn bộ */
function DriveAuthPanel({ onSynced }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState(null)
  const [oauthConfigured, setOauthConfigured] = useState(true)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [loggingOut, setLoggingOut] = useState(false)
  const [syncingAll, setSyncingAll] = useState(false)
  const [syncProgress, setSyncProgress] = useState('')
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [backendDown, setBackendDown] = useState(false)

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true)
    try {
      const [s, cfg] = await Promise.all([getDriveStatus(), getAuthConfig()])
      setStatus(s)
      setOauthConfigured(cfg.oauth_configured !== false)
      setBackendDown(false)
      setError('')
    } catch (err) {
      if (isBackendUnreachable(err)) {
        setBackendDown(true)
        setStatus(null)
        setError(BACKEND_UNREACHABLE_MSG)
      } else {
        setBackendDown(false)
        setError(err.response?.data?.detail || 'Không kiểm tra được trạng thái Drive.')
      }
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  useEffect(() => {
    const loginResult = searchParams.get('login')
    if (!loginResult) return

    if (loginResult === 'success') {
      loadStatus().then(() => {
        alert('Đăng nhập Google thành công! Bạn có thể đồng bộ Drive của mình.')
      })
    } else if (loginResult === 'error') {
      const reason = searchParams.get('reason') || 'unknown'
      setError(`Đăng nhập thất bại (${reason}). Thử lại hoặc kiểm tra OAuth config trên backend.`)
    }

    searchParams.delete('login')
    searchParams.delete('reason')
    setSearchParams(searchParams, { replace: true })
  }, [searchParams, setSearchParams, loadStatus])

  const handleLogin = () => {
    loginDrive()
  }

  const handleLogout = async () => {
    setLoggingOut(true)
    setError('')
    try {
      await logoutAuth()
      setPreview(null)
      await loadStatus()
    } catch (err) {
      setError(err.response?.data?.detail || 'Không đăng xuất được.')
    } finally {
      setLoggingOut(false)
    }
  }

  const handlePreview = async () => {
    setError('')
    try {
      const data = await previewDriveFiles()
      setPreview(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Không lấy được danh sách file.')
    }
  }

  const handleSyncAll = async () => {
    if (
      !confirm(
        'Đồng bộ TOÀN BỘ file được hỗ trợ trên Google Drive?\n\n' +
          'PDF, Word, Excel, TXT, ảnh, Google Docs...\n' +
        'Quá trình có thể mất 15–30+ phút tùy số file (chạy nền, không bị timeout).',
      )
    ) {
      return
    }
    setSyncingAll(true)
    setSyncProgress('Đang bắt đầu...')
    setError('')
    try {
      const result = await syncAllDrive(false, null, {
        onProgress: (job) => {
          if (job?.total > 0) {
            setSyncProgress(`${job.processed}/${job.total} — ${job.message || ''}`)
          } else {
            setSyncProgress(job?.message || 'Đang đồng bộ...')
          }
        },
      })
      setPreview(null)
      await loadStatus()
      onSynced?.(result)
      const errSummary = summarizeSyncErrors(result.details)
      alert(
        `Hoàn tất đồng bộ Drive!\n\n` +
          `Tài khoản: ${result.account_email || '?'}\n` +
          `Tìm thấy: ${result.files_found} file\n` +
          `Thành công: ${result.success}\n` +
          `Bỏ qua (đã index): ${result.skipped}\n` +
          `Lỗi: ${result.failed}` +
          (errSummary ? `\n\nNguyên nhân lỗi phổ biến:\n${errSummary}` : '') +
          (result.failed > 0
            ? '\n\nGợi ý: đợi 2–3 phút (quota Gemini) rồi sync lại — file đã index sẽ được bỏ qua.'
            : ''),
      )
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      setError(detail)
      alert(`Lỗi đồng bộ:\n${detail}`)
    } finally {
      setSyncingAll(false)
      setSyncProgress('')
    }
  }

  return (
    <div className="mb-4 bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold text-gray-800 text-sm">Google Drive</h3>
          {loadingStatus ? (
            <p className="text-xs text-gray-400 mt-1">Đang kiểm tra...</p>
          ) : status?.logged_in && status?.authenticated ? (
            <p className="text-xs text-green-600 mt-1 flex items-center gap-1">
              <CheckCircle2 size={12} />
              Đã đăng nhập: {status.email || status.session_email || status.display_name}
            </p>
          ) : status?.logged_in ? (
            <p className="text-xs text-amber-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} />
              Đã đăng nhập app nhưng chưa kết nối Drive — thử đăng nhập lại.
            </p>
          ) : (
            <p className="text-xs text-amber-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} />
              {status?.message || 'Chưa đăng nhập — mỗi tài khoản Google có Drive riêng.'}
            </p>
          )}
          {backendDown && (
            <p className="text-xs text-red-600 mt-2 bg-red-50 border border-red-100 rounded-lg p-2">
              {BACKEND_UNREACHABLE_MSG}
            </p>
          )}
          {!backendDown && !loadingStatus && !oauthConfigured && (
            <div className="text-xs text-red-500 mt-2 space-y-1">
              <p>
                OAuth Web chưa cấu hình. Tạo OAuth Client loại <strong>Web application</strong>{' '}
                trên Google Cloud Console, thêm redirect URI:
              </p>
              <p className="font-mono text-[11px] bg-red-50 p-2 rounded break-all text-red-700">
                http://localhost:3000/api/v1/auth/google/callback
              </p>
              <p className="text-gray-500">
                Rồi set <code className="bg-gray-100 px-1">GOOGLE_CLIENT_ID</code>,{' '}
                <code className="bg-gray-100 px-1">GOOGLE_CLIENT_SECRET</code> trong backend/.env
              </p>
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {!status?.logged_in ? (
            <button
              onClick={handleLogin}
              disabled={!oauthConfigured}
              className="px-3 py-1.5 text-sm border border-blue-200 text-blue-600 rounded-lg
                         hover:bg-blue-50 disabled:opacity-50 flex items-center gap-1.5"
            >
              Đăng nhập Google
            </button>
          ) : (
            <>
              <button
                onClick={handleLogout}
                disabled={loggingOut}
                className="px-3 py-1.5 text-sm border border-gray-200 text-gray-600 rounded-lg
                           hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1.5"
              >
                {loggingOut ? <Loader2 size={14} className="animate-spin" /> : <LogOut size={14} />}
                Đăng xuất
              </button>
              <button
                onClick={handleLogin}
                disabled={!oauthConfigured}
                title="Đăng nhập tài khoản Google khác"
                className="px-3 py-1.5 text-sm border border-blue-100 text-blue-500 rounded-lg
                           hover:bg-blue-50 disabled:opacity-50"
              >
                Đổi tài khoản
              </button>
            </>
          )}
          <button
            onClick={handlePreview}
            disabled={!status?.authenticated}
            className="px-3 py-1.5 text-sm border border-gray-200 text-gray-600 rounded-lg
                       hover:bg-gray-50 disabled:opacity-50"
          >
            Xem file trên Drive
          </button>
          <button
            onClick={handleSyncAll}
            disabled={syncingAll || !status?.authenticated}
            className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded-lg hover:bg-blue-600
                       disabled:opacity-50 flex items-center gap-1.5"
          >
            {syncingAll ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {syncingAll ? 'Đang đồng bộ...' : 'Đồng bộ toàn bộ Drive'}
          </button>
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-500 mt-2">{error}</p>
      )}

      {syncingAll && syncProgress && (
        <p className="text-xs text-blue-600 mt-2 flex items-center gap-1">
          <Loader2 size={12} className="animate-spin flex-shrink-0" />
          {syncProgress}
        </p>
      )}

      {preview && (
        <div className="mt-3 p-3 bg-gray-50 rounded-lg text-xs">
          <p className="font-medium text-gray-700 mb-2">
            {preview.total} file được hỗ trợ trên Drive
            {preview.account_email ? ` (${preview.account_email})` : ''}
          </p>
          <ul className="space-y-1 max-h-32 overflow-y-auto">
            {preview.files?.map((f) => (
              <li key={f.id} className="text-gray-600 truncate">
                [{f.type_label}] {f.name}
              </li>
            ))}
          </ul>
          {preview.total > preview.showing && (
            <p className="text-gray-400 mt-1">... và {preview.total - preview.showing} file khác</p>
          )}
        </div>
      )}
    </div>
  )
}

/** Modal nhập file ID để sync */
function SyncModal({ onClose, onSync }) {
  const [fileIds, setFileIds] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [result, setResult] = useState(null)

  const handleSync = async () => {
    setSyncing(true)
    setResult(null)
    try {
      const ids = fileIds
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
      const res = await onSync(ids)
      setResult(res)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <h3 className="font-semibold text-gray-800 mb-1">Đồng bộ Google Drive</h3>
        <p className="text-sm text-gray-500 mb-4">
          Nhập danh sách Google Drive file ID (mỗi dòng một ID).<br />
          Để trống = đồng bộ toàn bộ Drive.
        </p>

        <textarea
          value={fileIds}
          onChange={(e) => setFileIds(e.target.value)}
          placeholder={'1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms\n1a2b3c4d5e6f...'}
          rows={5}
          className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm font-mono
                     focus:outline-none focus:ring-2 focus:ring-blue-300 resize-none"
        />

        {/* Kết quả sync */}
        {result && (
          <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
            <p className="font-medium text-gray-700 mb-1">Kết quả đồng bộ:</p>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-green-50 rounded p-2">
                <p className="text-green-600 font-bold">{result.success}</p>
                <p className="text-xs text-green-500">Thành công</p>
              </div>
              <div className="bg-yellow-50 rounded p-2">
                <p className="text-yellow-600 font-bold">{result.skipped}</p>
                <p className="text-xs text-yellow-500">Bỏ qua</p>
              </div>
              <div className="bg-red-50 rounded p-2">
                <p className="text-red-600 font-bold">{result.failed}</p>
                <p className="text-xs text-red-500">Lỗi</p>
              </div>
            </div>
          </div>
        )}

        <div className="flex gap-2 mt-4">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 border border-gray-200 rounded-xl text-sm text-gray-600
                       hover:bg-gray-50 transition-colors"
          >
            Đóng
          </button>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex-1 px-4 py-2 bg-blue-500 text-white rounded-xl text-sm
                       hover:bg-blue-600 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
          >
            {syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {syncing ? 'Đang đồng bộ...' : 'Bắt đầu sync'}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Component chính */
export default function DocumentList() {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showSyncModal, setShowSyncModal] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  /** Tải danh sách tài liệu từ API */
  const loadDocuments = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getDocuments(100)
      setDocuments(data)
    } catch (err) {
      setError(
        isBackendUnreachable(err)
          ? BACKEND_UNREACHABLE_MSG
          : err.response?.data?.detail || 'Không thể tải danh sách tài liệu.',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  /** Xóa tài liệu và reload list */
  const handleDelete = async (fileId) => {
    try {
      await deleteDocument(fileId)
      setDocuments((prev) => prev.filter((d) => d.id !== fileId))
      showSuccess('Đã xóa tài liệu thành công.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Không thể xóa tài liệu.')
    }
  }

  /** Sync Drive và reload list */
  const handleSync = async (fileIds) => {
    const result = await syncDrive(fileIds)
    if (result.success > 0) {
      await loadDocuments()
      showSuccess(`Đã index ${result.success} tài liệu mới.`)
    }
    return result
  }

  /** Sau khi đồng bộ toàn bộ Drive từ panel */
  const handleDriveSynced = async (result) => {
    if (result?.success > 0 || result?.skipped > 0) {
      await loadDocuments()
      showSuccess(
        `Drive: ${result.success} file mới, ${result.skipped} đã có, ${result.failed} lỗi.`,
      )
    }
  }

  const showSuccess = (msg) => {
    setSuccessMsg(msg)
    setTimeout(() => setSuccessMsg(''), 4000)
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-800">Tài liệu đã index</h2>
          <p className="text-xs text-gray-500">
            {loading ? 'Đang tải...' : `${documents.length} tài liệu trong knowledge base`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadDocuments}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
            title="Tải lại"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => setShowSyncModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500 text-white text-sm
                       rounded-lg hover:bg-blue-600 transition-colors"
          >
            <Plus size={14} />
            Sync Drive
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        <DriveAuthPanel onSynced={handleDriveSynced} />

        {/* Success message */}
        {successMsg && (
          <div className="mb-3 px-3 py-2 bg-green-50 border border-green-200 rounded-lg
                          flex items-center gap-2 text-sm text-green-600">
            <CheckCircle2 size={14} />
            {successMsg}
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg
                          flex items-center gap-2 text-sm text-red-600">
            <AlertCircle size={14} />
            {error}
            <button onClick={() => setError('')} className="ml-auto">✕</button>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 animate-pulse">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 bg-gray-200 rounded-lg" />
                  <div className="flex-1">
                    <div className="h-4 bg-gray-200 rounded w-3/4 mb-2" />
                    <div className="h-3 bg-gray-200 rounded w-1/2" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && documents.length === 0 && (
          <div className="text-center py-16">
            <Database size={48} className="text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">Chưa có tài liệu nào</p>
            <p className="text-gray-400 text-sm mt-1">
              Nhấn "Sync Drive" để index tài liệu từ Google Drive
            </p>
            <button
              onClick={() => setShowSyncModal(true)}
              className="mt-4 px-4 py-2 bg-blue-500 text-white text-sm rounded-lg hover:bg-blue-600"
            >
              Sync Drive ngay
            </button>
          </div>
        )}

        {/* Document cards */}
        {!loading && documents.length > 0 && (
          <div className="space-y-2">
            {documents.map((doc) => (
              <DocumentCard key={doc.id} doc={doc} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>

      {/* Sync modal */}
      {showSyncModal && (
        <SyncModal onClose={() => setShowSyncModal(false)} onSync={handleSync} />
      )}
    </div>
  )
}
