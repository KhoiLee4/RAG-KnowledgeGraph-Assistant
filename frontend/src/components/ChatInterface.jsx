/**
 * ChatInterface.jsx — Giao diện hội thoại chính của ứng dụng RAG.
 *
 * Tính năng:
 *   - Input câu hỏi + gửi bằng Enter hoặc button
 *   - Hiển thị answer từ Gemini
 *   - Hiển thị citations dạng card (tên file + link Drive)
 *   - Loading state (typing indicator)
 *   - Lịch sử hội thoại multi-turn
 *   - Hỗ trợ streaming response (toggle)
 */

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, BookOpen, ExternalLink, AlertCircle, RefreshCw } from 'lucide-react'
import { sendChat, sendChatStream, formatApiError } from '../api/client'

/** Component hiển thị một bong bóng tin nhắn */
function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {/* Avatar trợ lý */}
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold mr-2 flex-shrink-0 mt-1">
          AI
        </div>
      )}

      <div className={`max-w-[75%] ${isUser ? 'order-1' : ''}`}>
        {/* Nội dung tin nhắn */}
        <div
          className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-blue-500 text-white rounded-br-sm'
              : 'bg-white text-gray-800 shadow-sm border border-gray-100 rounded-bl-sm'
          }`}
        >
          {message.content}
        </div>

        {/* Citations cards — chỉ hiển thị cho tin nhắn AI có citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-2 space-y-1">
            <p className="text-xs text-gray-400 px-1 flex items-center gap-1">
              <BookOpen size={12} />
              Nguồn tham khảo ({message.citations.length}):
            </p>
            {message.citations.map((cite, idx) => (
              <CitationCard key={idx} citation={cite} index={idx + 1} />
            ))}
          </div>
        )}
      </div>

      {/* Avatar người dùng */}
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-gray-600 text-xs font-bold ml-2 flex-shrink-0 mt-1">
          You
        </div>
      )}
    </div>
  )
}

/** Card hiển thị thông tin citation */
function CitationCard({ citation, index }) {
  return (
    <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-blue-700 truncate">
          [{index}] {citation.file_name}
        </p>
        <p className="text-xs text-blue-500">
          Trang ~{citation.page_estimate} · Chunk {citation.chunk_index}
          {citation.score && ` · Độ liên quan: ${(parseFloat(citation.score) * 100).toFixed(0)}%`}
        </p>
      </div>
      {citation.drive_link && (
        <a
          href={citation.drive_link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-500 hover:text-blue-700 flex-shrink-0"
          title="Mở trên Google Drive"
        >
          <ExternalLink size={14} />
        </a>
      )}
    </div>
  )
}

/** Typing indicator animation */
function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4">
      <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold mr-2 flex-shrink-0">
        AI
      </div>
      <div className="bg-white shadow-sm border border-gray-100 rounded-2xl rounded-bl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-2 h-2 rounded-full bg-gray-400 typing-dot"
              style={{ animationDelay: `${i * 0.16}s` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

/** Component chính */
export default function ChatInterface() {
  // Danh sách tin nhắn trong cuộc hội thoại
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
  const [useStream, setUseStream] = useState(false)  // Toggle streaming

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Tự động scroll xuống khi có tin nhắn mới
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  /** Tạo history format cho backend từ messages state */
  const buildHistory = () => {
    return messages
      .filter((m) => m.id !== 0) // Bỏ tin nhắn chào mừng
      .map((m) => ({ role: m.role, content: m.content }))
  }

  /** Gửi câu hỏi (non-streaming) */
  const sendMessage = async () => {
    const question = input.trim()
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

  /** Gửi câu hỏi (streaming) */
  const sendMessageStream = async () => {
    const question = input.trim()
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
      // onChunk: cập nhật từng đoạn văn bản
      (chunk) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId ? { ...m, content: m.content + chunk } : m,
          ),
        )
      },
      // onCitations: nhận citations cuối cùng
      (citations) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsgId ? { ...m, citations } : m)),
        )
      },
      // onDone
      () => {
        setIsLoading(false)
        inputRef.current?.focus()
      },
      // onError
      (errMsg) => {
        setError(formatApiError({ message: errMsg }))
        setIsLoading(false)
      },
    )
  }

  /** Handler gửi (chọn streaming hay không) */
  const handleSend = () => {
    if (useStream) sendMessageStream()
    else sendMessage()
  }

  /** Gửi bằng Enter (Shift+Enter = xuống dòng) */
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  /** Xóa hội thoại */
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

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-800">Hỏi đáp tri thức</h2>
          <p className="text-xs text-gray-500">Powered by Gemini 2.0 Flash + GraphRAG</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Toggle streaming */}
          <label className="flex items-center gap-1.5 cursor-pointer">
            <span className="text-xs text-gray-500">Stream</span>
            <div
              onClick={() => setUseStream(!useStream)}
              className={`w-8 h-4 rounded-full transition-colors ${
                useStream ? 'bg-blue-500' : 'bg-gray-300'
              } relative`}
            >
              <div
                className={`w-3 h-3 rounded-full bg-white absolute top-0.5 transition-transform ${
                  useStream ? 'translate-x-4' : 'translate-x-0.5'
                }`}
              />
            </div>
          </label>
          {/* Clear button */}
          <button
            onClick={clearChat}
            className="text-gray-400 hover:text-gray-600 p-1 rounded"
            title="Xóa hội thoại"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isLoading && !useStream && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mb-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-sm text-red-600">
          <AlertCircle size={14} />
          {error}
          <button onClick={() => setError('')} className="ml-auto text-red-400 hover:text-red-600">
            ✕
          </button>
        </div>
      )}

      {/* Input area */}
      <div className="bg-white border-t border-gray-200 px-4 py-3">
        <div className="flex items-end gap-2 max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Nhập câu hỏi về tài liệu của bạn... (Enter để gửi, Shift+Enter để xuống dòng)"
            rows={1}
            disabled={isLoading}
            className="flex-1 resize-none border border-gray-200 rounded-xl px-4 py-2.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-transparent
                       disabled:opacity-60 disabled:bg-gray-50 max-h-32 overflow-y-auto"
            style={{
              height: 'auto',
              minHeight: '42px',
            }}
            onInput={(e) => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px'
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="p-2.5 bg-blue-500 text-white rounded-xl hover:bg-blue-600
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors
                       flex-shrink-0"
            title="Gửi câu hỏi"
          >
            {isLoading ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Send size={18} />
            )}
          </button>
        </div>
        <p className="text-xs text-gray-400 text-center mt-1.5">
          {messages.filter((m) => m.role === 'user').length} câu hỏi trong cuộc hội thoại này
        </p>
      </div>
    </div>
  )
}
