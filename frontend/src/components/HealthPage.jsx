import { useState, useEffect } from 'react'
import { Activity, Database, Network, ServerCog, Cpu, Loader2 } from 'lucide-react'
import { PageHeader } from './layout/PageHeader'
import { getHealth } from '../api/client'
import { cn } from '../lib/utils'

function StatusBadge({ status }) {
  const online = status === 'ok'
  const degraded = status === 'degraded'
  const label = online ? 'Online' : degraded ? 'Degraded' : status === 'loading' ? '...' : 'Offline'

  if (status === 'loading') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Đang kiểm tra...
      </span>
    )
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
        online && 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
        degraded && 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400',
        !online && !degraded && 'bg-red-500/10 text-red-600 dark:text-red-400',
      )}
    >
      <span className="relative flex h-2 w-2">
        {online && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
        )}
        <span
          className={cn(
            'relative inline-flex h-2 w-2 rounded-full',
            online ? 'bg-emerald-500' : degraded ? 'bg-yellow-500' : 'bg-red-500',
          )}
        />
      </span>
      {label}
    </span>
  )
}

const serviceIcons = {
  chromadb: Database,
  neo4j: Network,
  gemini: Cpu,
}

export default function HealthPage() {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: 'error', services: {} }))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title="System Health"
        subtitle="Giám sát trạng thái các dịch vụ"
        icon={<Activity className="h-5 w-5" />}
      />

      <div className="mx-auto w-full max-w-3xl space-y-4 px-6 py-6">
        <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-accent-foreground">
                <ServerCog className="h-5 w-5" />
              </div>
              <h2 className="text-base font-bold text-card-foreground">Trạng thái tổng thể</h2>
            </div>
            <StatusBadge status={loading ? 'loading' : health?.status || 'error'} />
          </div>
        </div>

        {health &&
          Object.entries(health.services || {}).map(([name, info]) => {
            const Icon = serviceIcons[name.toLowerCase()] || Database
            return (
              <div key={name} className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-accent-foreground">
                      <Icon className="h-5 w-5" />
                    </div>
                    <h2 className="text-base font-bold capitalize text-card-foreground">{name}</h2>
                  </div>
                  <StatusBadge status={info.status} />
                </div>
                {(info.documents !== undefined ||
                  info.documents_indexed !== undefined ||
                  info.collection ||
                  info.detail) && (
                  <div className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-4">
                    {info.documents !== undefined && (
                      <div>
                        <p className="text-xs text-muted-foreground">Documents</p>
                        <p className="truncate font-mono text-sm font-semibold text-card-foreground">
                          {info.documents}
                        </p>
                      </div>
                    )}
                    {info.documents_indexed !== undefined && (
                      <div>
                        <p className="text-xs text-muted-foreground">Indexed</p>
                        <p className="truncate font-mono text-sm font-semibold text-card-foreground">
                          {info.documents_indexed}
                        </p>
                      </div>
                    )}
                    {info.collection && (
                      <div>
                        <p className="text-xs text-muted-foreground">Collection</p>
                        <p className="truncate font-mono text-sm font-semibold text-card-foreground">
                          {info.collection}
                        </p>
                      </div>
                    )}
                    {info.detail && (
                      <div className="col-span-2">
                        <p className="text-xs text-red-500">{info.detail}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
      </div>
    </div>
  )
}
