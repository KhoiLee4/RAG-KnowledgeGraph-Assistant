/**
 * ChatInterface.jsx — Giao diện hội thoại chính của ứng dụng RAG.
 */

import { useState, useRef, useEffect } from 'react'
import {
  Send, Loader2, FileText, ExternalLink, AlertCircle,
  RotateCcw, Sparkles, Bot, User,
} from 'lucide-react'
import { sendChatStream, formatApiError } from '../api/client'
import { PageHeader } from './layout/PageHeader'
import { cn } from '../lib/utils'

const RETRIEVAL_MODES = [
  { id: 'rag', label: 'RAG', hint: 'Chỉ tìm trong nội dung tài liệu' },
  { id: 'graph_rag', label: 'GraphRAG', hint: 'Kết hợp đồ thị tri thức + tài liệu' },
]

function normalizeRetrievalMode(mode) {
  if (mode === 'graph_rag') return 'graph_rag'
  return 'rag'
}

const SUGGESTIONS = [
  'Tóm tắt nội dung báo cáo cuối kỳ',
  'GraphRAG hoạt động như thế nào?',
  'Liệt kê các thực thể chính trong tài liệu',
]

const WELCOME_MESSAGE = {
  id: 0,
  role: 'model',
  content: 'Xin chào! Tôi là trợ lý ảo của bạn. Hãy đặt câu hỏi về các tài liệu bạn đã lưu trữ.',
  citations: [],
}

const RESET_MESSAGE = {
  id: 0,
  role: 'model',
  content: 'Hội thoại đã được xóa. Hãy đặt câu hỏi mới!',
  citations: [],
}

function chatStorageKey(userId) {
  return `rag-chat:${userId || 'guest'}`
}

function loadChatFromStorage(userId) {
  try {
    const raw = localStorage.getItem(chatStorageKey(userId))
    if (!raw) return null
    const data = JSON.parse(raw)
    if (!Array.isArray(data.messages) || data.messages.length === 0) return null
    return {
      messages: data.messages,
      retrievalMode: normalizeRetrievalMode(data.retrievalMode),
    }
  } catch {
    return null
  }
}

function saveChatToStorage(userId, messages, retrievalMode) {
  try {
    const toSave = messages.filter(
      (m) => m.role === 'user' || (m.role === 'model' && m.content.trim()),
    )
    if (toSave.length === 0) return
    localStorage.setItem(
      chatStorageKey(userId),
      JSON.stringify({ messages: toSave, retrievalMode, savedAt: Date.now() }),
    )
  } catch {
    // Bỏ qua nếu localStorage đầy hoặc bị chặn
  }
}

function SourceBadge({ source, sourceLabel }) {
  const config = {
    vector: { label: 'Tài liệu', cls: 'bg-chart-4/20 text-chart-4' },
    graph: { label: 'Đồ thị', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
    hybrid: { label: 'Kết hợp', cls: 'bg-chart-2/20 text-chart-2' },
    community: { label: 'Tổng quan', cls: 'bg-violet-500/15 text-violet-600 dark:text-violet-400' },
  }
  const { label, cls } = config[source] || { label: sourceLabel || 'Nguồn', cls: 'bg-muted text-muted-foreground' }
  return (
    <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold', cls)}>
      {sourceLabel || label}
    </span>
  )
}

function CitationChip({ cite, index }) {
  const title = cite.label || cite.file_name || 'Nguồn'
  const location = cite.location || (cite.page ? `Trang ${cite.page}` : null)
  const link = cite.location_link || cite.drive_link
  const snippet = cite.snippet

  const content = (
    <>
      <FileText className="h-3 w-3 shrink-0" />
      <span className="min-w-0">
        <span className="font-semibold">[{index}]</span>{' '}
        <span className="truncate">{title}</span>
        {location && <span className="text-muted-foreground"> · {location}</span>}
      </span>
      {cite.source && <SourceBadge source={cite.source} sourceLabel={cite.source_label} />}
      {link && (
        <ExternalLink className="h-3 w-3 shrink-0 opacity-70" />
      )}
    </>
  )

  const className = cn(
    'inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border/60',
    'bg-accent/50 px-2.5 py-1.5 text-xs text-accent-foreground transition-colors',
    link && 'hover:bg-accent hover:border-primary/30',
  )

  if (link) {
    return (
      <a
        href={link}
        target="_blank"
        rel="noopener noreferrer"
        className={className}
        title={snippet || `Mở ${title}${location ? ` — ${location}` : ''}`}
      >
        {content}
      </a>
    )
  }

  return (
    <div className={className} title={snippet || title}>
      {content}
    </div>
  )
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold',
          isUser ? 'bg-secondary text-secondary-foreground' : 'bg-primary text-primary-foreground',
        )}
      >
        {isUser ? <User className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
      </div>
      <div className={cn('max-w-[85%]', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap',
            isUser
              ? 'rounded-tr-sm bg-primary text-primary-foreground'
              : 'rounded-tl-sm border border-border bg-card text-card-foreground shadow-sm',
          )}
        >
          {message.content}
        </div>
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Nguồn tham khảo
            </p>
            <div className="flex flex-wrap gap-2">
              {message.citations.map((cite, idx) => (
                <CitationChip key={idx} cite={cite} index={cite.index || idx + 1} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ChatInterface({ userId = 'guest' }) {
  const [messages, setMessages] = useState([WELCOME_MESSAGE])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [retrievalMode, setRetrievalMode] = useState('rag')

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    const saved = loadChatFromStorage(userId)
    if (saved) {
      setMessages(saved.messages)
      setRetrievalMode(saved.retrievalMode)
    } else {
      setMessages([WELCOME_MESSAGE])
      setRetrievalMode('rag')
    }
  }, [userId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (isLoading) return
    saveChatToStorage(userId, messages, retrievalMode)
  }, [messages, retrievalMode, isLoading, userId])

  const buildHistory = () =>
    messages.filter((m) => m.id !== 0).map((m) => ({ role: m.role, content: m.content }))

  const sendMessage = async (questionText) => {
    const question = (questionText ?? input).trim()
    if (!question || isLoading) return

    const userMsg = { id: Date.now(), role: 'user', content: question, citations: [] }
    const aiMsgId = Date.now() + 1

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: aiMsgId, role: 'model', content: '', citations: [] },
    ])
    setInput('')
    setIsLoading(true)
    setError('')

    await sendChatStream(
      question,
      buildHistory(),
      retrievalMode,
      (chunk) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + chunk } : m)),
        )
      },
      (citations) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, citations } : m)),
        )
      },
      () => {
        setIsLoading(false)
        inputRef.current?.focus()
      },
      (errMsg) => {
        setError(formatApiError({ message: errMsg }))
        setIsLoading(false)
      },
    )
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearChat = () => {
    try {
      localStorage.removeItem(chatStorageKey(userId))
    } catch {
      // ignore
    }
    setMessages([RESET_MESSAGE])
    setError('')
  }

  const userQuestionCount = messages.filter((m) => m.role === 'user').length
  const showSuggestions = messages.length === 1 && messages[0].id === 0

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Hỏi đáp tri thức"
        subtitle="Powered by Gemini 2.0 Flash + GraphRAG"
        icon={<Sparkles className="h-5 w-5" />}
        actions={
          <>
            <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-0.5">
              {RETRIEVAL_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  title={mode.hint}
                  onClick={() => setRetrievalMode(mode.id)}
                  className={cn(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                    retrievalMode === mode.id
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={clearChat}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              aria-label="Làm mới hội thoại"
              title="Xóa lịch sử hội thoại"
            >
              <RotateCcw className="h-4 w-4" />
            </button>
          </>
        }
      />

      <div className="chat-scroll flex-1 overflow-y-auto px-4 py-6 md:px-8">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {showSuggestions && (
            <div className="flex flex-wrap gap-2 pl-12">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => sendMessage(s)}
                  className="rounded-full border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {error && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive md:mx-8">
          <AlertCircle size={14} />
          {error}
          <button type="button" onClick={() => setError('')} className="ml-auto opacity-70 hover:opacity-100">
            ✕
          </button>
        </div>
      )}

      <div className="border-t border-border bg-background px-4 py-4 md:px-8">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            sendMessage()
          }}
          className="mx-auto flex max-w-3xl items-end gap-2"
        >
          <div className="flex flex-1 items-end rounded-2xl border border-border bg-card px-4 py-2 shadow-sm focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/20">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={isLoading}
              placeholder="Nhập câu hỏi về tài liệu của bạn... (Enter để gửi, Shift+Enter để xuống dòng)"
              className="max-h-32 flex-1 resize-none bg-transparent py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-60"
              onInput={(e) => {
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`
              }}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            aria-label="Gửi câu hỏi"
          >
            {isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
          </button>
        </form>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          {userQuestionCount} câu hỏi · lịch sử được lưu trên trình duyệt cho đến khi bạn reset
        </p>
      </div>
    </div>
  )
}
