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
  AlertCircle, CheckCircle2, Loader2, Database, LogOut,
  FolderOpen, CloudUpload, Layers, UserCog,
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
import { PageHeader } from './layout/PageHeader'
import { cn } from '../lib/utils'

/** Badge màu theo MIME type */
function MimeBadge({ mimeType }) {
  const config = {
    'application/pdf': { label: 'PDF', color: 'bg-red-500/15 text-red-600 dark:text-red-400' },
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': { label: 'DOCX', color: 'bg-primary/15 text-primary' },
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': { label: 'XLSX', color: 'bg-emerald-500/15 text-emerald-600' },
    'text/plain': { label: 'TXT', color: 'bg-muted text-muted-foreground' },
    'image/jpeg': { label: 'JPEG', color: 'bg-yellow-500/15 text-yellow-600' },
    'image/png': { label: 'PNG', color: 'bg-yellow-500/15 text-yellow-600' },
  }
  const { label = 'FILE', color = 'bg-muted text-muted-foreground' } =
    config[mimeType] || {}
  return (
    <span className={cn('rounded-md px-2 py-0.5 text-xs font-bold', color)}>
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
    <div className="group flex items-center gap-4 rounded-2xl border border-border bg-card p-4 shadow-sm transition-colors hover:border-primary/40">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground">
        <FileText className="h-6 w-6" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate font-semibold text-card-foreground" title={doc.file_name}>
            {doc.file_name || doc.id}
          </h3>
          <MimeBadge mimeType={doc.mime_type} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" />
            {doc.chunk_count ?? '?'} chunks
          </span>
          {doc.drive_link && (
            <a
              href={doc.drive_link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-primary hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Xem Drive
            </a>
          )}
        </div>
        <p className="mt-1 truncate font-mono text-xs text-muted-foreground/70" title={doc.id}>
          ID: {doc.id}
        </p>
      </div>

      <button
        onClick={handleDelete}
        disabled={deleting}
        className="rounded-lg p-2 text-muted-foreground opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 disabled:opacity-50"
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
      const messages = {
        token_exchange: 'Lỗi đổi token OAuth — restart backend, xóa cookie localhost rồi đăng nhập lại.',
        invalid_state: 'Phiên OAuth hết hạn — đăng nhập lại (mở http://localhost:3000, không dùng 127.0.0.1).',
        access_denied: 'Bạn đã từ chối quyền truy cập Google Drive.',
      }
      setError(messages[reason] || `Đăng nhập thất bại (${reason}).`)
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
        'Đồng bộ TOÀN BỘ file PDF được hỗ trợ trên Google Drive?\n\n' +
          'Chỉ: .pdf\n' +
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
    <div className="mb-6 rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-card-foreground">Google Drive</h2>
          {loadingStatus ? (
            <p className="mt-1 text-sm text-muted-foreground">Đang kiểm tra...</p>
          ) : status?.logged_in && status?.authenticated ? (
            <p className="mt-1 flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              Đã đăng nhập: {status.email || status.session_email || status.display_name}
            </p>
          ) : status?.logged_in ? (
            <p className="mt-1 flex items-center gap-1.5 text-sm text-yellow-600 dark:text-yellow-400">
              <AlertCircle className="h-4 w-4" />
              Đã đăng nhập app nhưng chưa kết nối Drive — thử đăng nhập lại.
            </p>
          ) : (
            <p className="mt-1 flex items-center gap-1.5 text-sm text-yellow-600 dark:text-yellow-400">
              <AlertCircle className="h-4 w-4" />
              {status?.message || 'Chưa đăng nhập — mỗi tài khoản Google có Drive riêng.'}
            </p>
          )}
          {backendDown && (
            <p className="mt-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
              {BACKEND_UNREACHABLE_MSG}
            </p>
          )}
          {!backendDown && !loadingStatus && !oauthConfigured && (
            <div className="mt-2 space-y-1 text-xs text-destructive">
              <p>
                OAuth Web chưa cấu hình. Tạo OAuth Client loại <strong>Web application</strong>{' '}
                trên Google Cloud Console, thêm redirect URI:
              </p>
              <p className="break-all rounded bg-destructive/10 p-2 font-mono text-[11px]">
                http://localhost:3000/api/v1/auth/google/callback
              </p>
              <p className="text-muted-foreground">
                Rồi set <code className="rounded bg-muted px-1">GOOGLE_CLIENT_ID</code>,{' '}
                <code className="rounded bg-muted px-1">GOOGLE_CLIENT_SECRET</code> trong file{' '}
                <code className="rounded bg-muted px-1">.env</code> (thư mục gốc repo)
              </p>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!status?.logged_in ? (
            <button
              onClick={handleLogin}
              disabled={!oauthConfigured}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              Đăng nhập Google
            </button>
          ) : (
            <>
              <button
                onClick={handleLogout}
                disabled={loggingOut}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
              >
                {loggingOut ? <Loader2 size={14} className="animate-spin" /> : <LogOut size={14} />}
                Đăng xuất
              </button>
              <button
                onClick={handleLogin}
                disabled={!oauthConfigured}
                title="Đăng nhập tài khoản Google khác"
                className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
              >
                <UserCog className="h-4 w-4" />
                Đổi tài khoản
              </button>
            </>
          )}
          <button
            onClick={handlePreview}
            disabled={!status?.authenticated}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            <ExternalLink className="h-4 w-4" />
            Xem file trên Drive
          </button>
          <button
            onClick={handleSyncAll}
            disabled={syncingAll || !status?.authenticated}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {syncingAll ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {syncingAll ? 'Đang đồng bộ...' : 'Đồng bộ toàn bộ Drive'}
          </button>
        </div>
      </div>

      {error && <p className="mt-3 text-xs text-destructive">{error}</p>}

      {syncingAll && syncProgress && (
        <p className="mt-3 flex items-center gap-1 text-xs text-primary">
          <Loader2 size={12} className="shrink-0 animate-spin" />
          {syncProgress}
        </p>
      )}

      {preview && (
        <div className="mt-4 rounded-lg bg-secondary/50 p-3 text-xs">
          <p className="mb-2 font-medium text-card-foreground">
            {preview.total} file được hỗ trợ trên Drive
            {preview.account_email ? ` (${preview.account_email})` : ''}
          </p>
          <ul className="max-h-32 space-y-1 overflow-y-auto">
            {preview.files?.map((f) => (
              <li key={f.id} className="truncate text-muted-foreground">
                [{f.type_label}] {f.name}
              </li>
            ))}
          </ul>
          {preview.total > preview.showing && (
            <p className="mt-1 text-muted-foreground">... và {preview.total - preview.showing} file khác</p>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-xl">
        <h3 className="mb-1 font-semibold text-card-foreground">Đồng bộ Google Drive</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          Nhập danh sách Google Drive file ID (mỗi dòng một ID).<br />
          Để trống = đồng bộ toàn bộ Drive.
        </p>

        <textarea
          value={fileIds}
          onChange={(e) => setFileIds(e.target.value)}
          placeholder={'1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms\n1a2b3c4d5e6f...'}
          rows={5}
          className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2 font-mono text-sm focus:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/20"
        />

        {result && (
          <div className="mt-3 rounded-lg bg-secondary/50 p-3 text-sm">
            <p className="mb-1 font-medium text-card-foreground">Kết quả đồng bộ:</p>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded bg-emerald-500/10 p-2">
                <p className="font-bold text-emerald-600 dark:text-emerald-400">{result.success}</p>
                <p className="text-xs text-muted-foreground">Thành công</p>
              </div>
              <div className="rounded bg-yellow-500/10 p-2">
                <p className="font-bold text-yellow-600 dark:text-yellow-400">{result.skipped}</p>
                <p className="text-xs text-muted-foreground">Bỏ qua</p>
              </div>
              <div className="rounded bg-destructive/10 p-2">
                <p className="font-bold text-destructive">{result.failed}</p>
                <p className="text-xs text-muted-foreground">Lỗi</p>
              </div>
            </div>
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent"
          >
            Đóng
          </button>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
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
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title="Tài liệu đã index"
        subtitle={loading ? 'Đang tải...' : `${documents.length} tài liệu trong knowledge base`}
        icon={<FolderOpen className="h-5 w-5" />}
        actions={
          <>
            <button
              type="button"
              onClick={loadDocuments}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              title="Tải lại"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              type="button"
              onClick={() => setShowSyncModal(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-opacity hover:opacity-90"
            >
              <CloudUpload className="h-4 w-4" />
              Sync Drive
            </button>
          </>
        }
      />

      <div className="chat-scroll mx-auto w-full max-w-5xl flex-1 space-y-6 px-6 py-6">
        <DriveAuthPanel onSynced={handleDriveSynced} />

        {successMsg && (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 size={14} />
            {successMsg}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle size={14} />
            {error}
            <button type="button" onClick={() => setError('')} className="ml-auto opacity-70 hover:opacity-100">
              ✕
            </button>
          </div>
        )}

        {loading && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-2xl border border-border bg-card p-4">
                <div className="flex items-start gap-3">
                  <div className="h-12 w-12 rounded-xl bg-muted" />
                  <div className="flex-1">
                    <div className="mb-2 h-4 w-3/4 rounded bg-muted" />
                    <div className="h-3 w-1/2 rounded bg-muted" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && documents.length === 0 && (
          <div className="py-16 text-center">
            <Database size={48} className="mx-auto mb-3 text-muted-foreground/40" />
            <p className="font-medium text-muted-foreground">Chưa có tài liệu nào</p>
            <p className="mt-1 text-sm text-muted-foreground/70">
              Nhấn &quot;Sync Drive&quot; để index tài liệu từ Google Drive
            </p>
            <button
              type="button"
              onClick={() => setShowSyncModal(true)}
              className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground transition-opacity hover:opacity-90"
            >
              Sync Drive ngay
            </button>
          </div>
        )}

        {!loading && documents.length > 0 && (
          <section className="space-y-3">
            {documents.map((doc) => (
              <DocumentCard key={doc.id} doc={doc} onDelete={handleDelete} />
            ))}
          </section>
        )}
      </div>

      {showSyncModal && (
        <SyncModal onClose={() => setShowSyncModal(false)} onSync={handleSync} />
      )}
    </div>
  )
}
