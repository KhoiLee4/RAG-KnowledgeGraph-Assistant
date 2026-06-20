/**
 * ChatInterface.jsx — Giao diện hội thoại chính của ứng dụng RAG.
 */

import { useState, useRef, useEffect } from 'react'
import {
  Send, Loader2, FileText, ExternalLink, AlertCircle,
  RotateCcw, Sparkles, Bot, User,
} from 'lucide-react'
import { sendChat, sendChatStream, formatApiError } from '../api/client'
import { PageHeader } from './layout/PageHeader'
import { cn } from '../lib/utils'

const SUGGESTIONS = [
  'Tóm tắt nội dung báo cáo cuối kỳ',
  'GraphRAG hoạt động như thế nào?',
  'Liệt kê các thực thể chính trong tài liệu',
]

function SourceBadge({ source }) {
  const config = {
    vector: { label: 'Vector', cls: 'bg-chart-4/20 text-chart-4' },
    graph: { label: 'Graph', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
    hybrid: { label: 'Hybrid', cls: 'bg-chart-2/20 text-chart-2' },
  }
  const { label, cls } = config[source] || config.vector
  return (
    <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold', cls)}>
      {label}
    </span>
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
          <div className="mt-3 flex flex-wrap gap-2">
            {message.citations.map((cite, idx) => (
              <div
                key={idx}
                className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-accent px-2 py-1 text-xs font-medium text-accent-foreground"
              >
                <FileText className="h-3 w-3 shrink-0" />
                <span className="truncate">
                  [{idx + 1}] {cite.file_name}
                  {cite.page_estimate != null && ` · ~${cite.page_estimate}`}
                  {cite.chunk_index != null && ` · chunk ${cite.chunk_index}`}
                </span>
                {cite.source && <SourceBadge source={cite.source} />}
                {cite.drive_link && (
                  <a
                    href={cite.drive_link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 hover:opacity-80"
                    title="Mở trên Google Drive"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-5 w-5" />
      </div>
      <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-sm">
        <div className="flex h-4 items-center gap-1">
          {[0, 1, 2].map((i) => (
            <div key={i} className="typing-dot h-2 w-2 rounded-full bg-muted-foreground" />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function ChatInterface() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      role: 'model',
      content: 'Xin chào! Tôi là trợ lý ảo của bạn. Hãy đặt câu hỏi về các tài liệu bạn đã lưu trữ.',
      citations: [],
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [useStream, setUseStream] = useState(true)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const buildHistory = () =>
    messages.filter((m) => m.id !== 0).map((m) => ({ role: m.role, content: m.content }))

  const sendMessage = async (questionText) => {
    const question = (questionText ?? input).trim()
    if (!question || isLoading) return

    const userMsg = { id: Date.now(), role: 'user', content: question, citations: [] }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)
    setError('')

    try {
      const result = await sendChat(question, '', buildHistory())
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: 'model',
          content: result.answer,
          citations: result.citations || [],
        },
      ])
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  const sendMessageStream = async (questionText) => {
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

  const handleSend = (text) => {
    if (useStream) sendMessageStream(text)
    else sendMessage(text)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const clearChat = () => {
    setMessages([
      {
        id: 0,
        role: 'model',
        content: 'Hội thoại đã được xóa. Hãy đặt câu hỏi mới!',
        citations: [],
      },
    ])
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
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Stream</span>
              <button
                type="button"
                onClick={() => setUseStream(!useStream)}
                className={cn(
                  'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                  useStream ? 'bg-primary' : 'border border-border bg-secondary',
                )}
                aria-label="Bật/tắt stream"
              >
                <span
                  className={cn(
                    'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
                    useStream ? 'translate-x-6' : 'translate-x-1',
                  )}
                />
              </button>
            </label>
            <button
              type="button"
              onClick={clearChat}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              aria-label="Làm mới hội thoại"
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
          {isLoading && !useStream && <TypingIndicator />}
          {showSuggestions && (
            <div className="flex flex-wrap gap-2 pl-12">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => handleSend(s)}
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
            handleSend()
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
          {userQuestionCount} câu hỏi trong cuộc hội thoại này
        </p>
      </div>
    </div>
  )
}
