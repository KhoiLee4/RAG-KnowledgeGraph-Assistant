/**
 * App.jsx — Root layout với sidebar navigation và routing.
 */

import { useState, useEffect } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { Menu } from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import DocumentList from './components/DocumentList'
import GraphStats from './components/GraphStats'
import HealthPage from './components/HealthPage'
import { AppSidebar } from './components/layout/AppSidebar'
import { getHealth, getAuthMe } from './api/client'

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [systemStatus, setSystemStatus] = useState('loading')
  const [authUser, setAuthUser] = useState(null)
  const location = useLocation()

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

  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  return (
    <div className="flex h-screen bg-background">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden
        />
      )}

      <div
        className={`fixed inset-y-0 left-0 z-40 transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <AppSidebar
          systemStatus={systemStatus}
          authUser={authUser}
          onNavigate={() => setSidebarOpen(false)}
        />
      </div>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center gap-3 border-b border-border bg-background px-4 py-3 md:hidden">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Mở menu"
          >
            <Menu size={20} />
          </button>
          <span className="font-semibold text-foreground">Knowledge Assistant</span>
        </header>

        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<ChatInterface />} />
            <Route path="/docs" element={<DocumentList />} />
            <Route path="/graph" element={<GraphStats />} />
            <Route path="/health" element={<HealthPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
