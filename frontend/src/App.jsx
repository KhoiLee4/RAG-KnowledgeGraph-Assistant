/**
 * App.jsx — Root component với React Router layout.
 *
 * Layout: Sidebar navigation | Main content area
 *   - /       → Chat Interface
 *   - /docs   → Document List
 */

import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { MessageSquare, FolderOpen, Activity, Menu, X, Database } from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import DocumentList from './components/DocumentList'
import { getHealth, getAuthMe } from './api/client'

/** Badge trạng thái hệ thống */
function StatusBadge({ status }) {
  const config = {
    ok: { label: 'Online', color: 'bg-green-400', text: 'text-green-600' },
    degraded: { label: 'Degraded', color: 'bg-yellow-400', text: 'text-yellow-600' },
    error: { label: 'Offline', color: 'bg-red-400', text: 'text-red-600' },
    loading: { label: '...', color: 'bg-gray-300', text: 'text-gray-500' },
  }
  const { label, color, text } = config[status] || config.loading
  return (
    <span className={`flex items-center gap-1 text-xs ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
      {label}
    </span>
  )
}

/** Sidebar navigation item */
function NavItem({ to, icon: Icon, label, onClick }) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
          isActive
            ? 'bg-blue-500 text-white'
            : 'text-gray-600 hover:bg-gray-100'
        }`
      }
    >
      <Icon size={18} />
      {label}
    </NavLink>
  )
}

/** Health check page */
function HealthPage() {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: 'error', services: {} }))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-6 max-w-lg mx-auto">
      <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
        <Activity size={18} />
        System Health
      </h2>

      {loading && <p className="text-gray-400 text-sm">Đang kiểm tra...</p>}

      {health && (
        <div className="space-y-3">
          {/* Overall status */}
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium text-gray-700">Trạng thái tổng thể</span>
              <StatusBadge status={health.status} />
            </div>
          </div>

          {/* Services */}
          {Object.entries(health.services || {}).map(([name, info]) => (
            <div key={name} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-gray-700 capitalize">{name}</span>
                <StatusBadge status={info.status} />
              </div>
              <div className="text-xs text-gray-500 space-y-0.5">
                {info.documents !== undefined && (
                  <p><span className="font-medium">Documents:</span> {info.documents}</p>
                )}
                {info.documents_indexed !== undefined && (
                  <p><span className="font-medium">Indexed:</span> {info.documents_indexed}</p>
                )}
                {info.collection && (
                  <p><span className="font-medium">Collection:</span> {info.collection}</p>
                )}
                {info.detail && (
                  <p className="text-red-500">{info.detail}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Root App component */
export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [systemStatus, setSystemStatus] = useState('loading')
  const [authUser, setAuthUser] = useState(null)
  const location = useLocation()

  // Lấy system status khi load
  useEffect(() => {
    getHealth()
      .then((data) => setSystemStatus(data.status || 'ok'))
      .catch(() => setSystemStatus('error'))
  }, [])

  useEffect(() => {
    getAuthMe()
      .then((data) => setAuthUser(data.logged_in ? data : null))
      .catch(() => setAuthUser(null))
  }, [location.pathname])

  // Đóng sidebar khi chuyển route (mobile)
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  return (
    <div className="flex h-screen bg-gray-100 font-sans">
      {/* ── Overlay (mobile) ─────────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Sidebar ──────────────────────────────────────── */}
      <aside
        className={`
          fixed md:static inset-y-0 left-0 z-40
          w-64 bg-white border-r border-gray-200
          flex flex-col transition-transform duration-200
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
        `}
      >
        {/* Logo */}
        <div className="px-4 py-5 border-b border-gray-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center">
              <Database size={16} className="text-white" />
            </div>
            <div>
              <p className="font-bold text-gray-800 text-sm leading-tight">Knowledge</p>
              <p className="font-bold text-blue-500 text-sm leading-tight">Assistant</p>
            </div>
          </div>
          <div className="mt-2">
            <StatusBadge status={systemStatus} />
          </div>
          {authUser?.email && (
            <p className="text-xs text-gray-500 mt-2 truncate" title={authUser.email}>
              {authUser.display_name || authUser.email}
            </p>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          <NavItem
            to="/"
            icon={MessageSquare}
            label="Hỏi đáp AI"
            onClick={() => setSidebarOpen(false)}
          />
          <NavItem
            to="/docs"
            icon={FolderOpen}
            label="Tài liệu"
            onClick={() => setSidebarOpen(false)}
          />
          <NavItem
            to="/health"
            icon={Activity}
            label="System Status"
            onClick={() => setSidebarOpen(false)}
          />
        </nav>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-100">
          <p className="text-xs text-gray-400">GraphRAG + Gemini 2.0</p>
          <p className="text-xs text-gray-300">v1.0.0 — Đồ án tốt nghiệp</p>
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <header className="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="text-gray-500 hover:text-gray-700"
          >
            <Menu size={20} />
          </button>
          <span className="font-semibold text-gray-700">Knowledge Assistant</span>
        </header>

        {/* Routes */}
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<ChatInterface />} />
            <Route path="/docs" element={<DocumentList />} />
            <Route path="/health" element={<HealthPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
