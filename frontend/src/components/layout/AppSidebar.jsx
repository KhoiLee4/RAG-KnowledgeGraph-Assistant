import { NavLink } from 'react-router-dom'
import { MessageSquare, FolderOpen, Network, Activity, Database } from 'lucide-react'
import { cn } from '../../lib/utils'
import { ThemeToggle } from './ThemeToggle'

const navItems = [
  { to: '/', label: 'Hỏi đáp AI', icon: MessageSquare },
  { to: '/docs', label: 'Tài liệu', icon: FolderOpen },
  { to: '/graph', label: 'Knowledge Graph', icon: Network },
  { to: '/health', label: 'System Status', icon: Activity },
]

function StatusDot({ status }) {
  const online = status === 'ok'
  const degraded = status === 'degraded'
  const color = online ? 'bg-emerald-500' : degraded ? 'bg-yellow-500' : status === 'loading' ? 'bg-muted-foreground' : 'bg-red-500'
  const label = online ? 'Online' : degraded ? 'Degraded' : status === 'loading' ? '...' : 'Offline'
  const textColor = online
    ? 'text-emerald-600 dark:text-emerald-400'
    : degraded
      ? 'text-yellow-600 dark:text-yellow-400'
      : 'text-muted-foreground'

  return (
    <div className="flex items-center gap-2">
      <span className="relative flex h-2 w-2">
        {online && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
        )}
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', color)} />
      </span>
      <span className={cn('text-xs font-medium', textColor)}>{label}</span>
    </div>
  )
}

export function AppSidebar({ systemStatus, authUser, onNavigate }) {
  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <Database className="h-5 w-5" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-bold text-sidebar-foreground">Knowledge</span>
          <span className="text-sm font-bold text-sidebar-foreground">Assistant</span>
        </div>
      </div>

      <div className="mx-5 mb-4 rounded-xl border border-sidebar-border bg-secondary/50 px-4 py-3">
        <StatusDot status={systemStatus} />
        {authUser?.email && (
          <p className="mt-1.5 truncate text-sm font-medium text-sidebar-foreground" title={authUser.email}>
            {authUser.display_name || authUser.email}
          </p>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                )
              }
            >
              <Icon className="h-[18px] w-[18px]" />
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="border-t border-sidebar-border px-5 py-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">Giao diện</span>
          <ThemeToggle />
        </div>
        <p className="text-xs font-semibold text-sidebar-foreground/80">GraphRAG + Gemini 2.0</p>
        <p className="text-[11px] text-muted-foreground">v1.0.0 — Đồ án tốt nghiệp</p>
      </div>
    </aside>
  )
}
