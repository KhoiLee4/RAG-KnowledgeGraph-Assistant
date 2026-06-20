/**
 * GraphStats.jsx — Trang hiển thị thống kê Knowledge Graph.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Network, RefreshCw, Loader2, AlertCircle,
  Tag, Link2, BarChart2, Users, Building2,
  Lightbulb, MapPin, Calendar, HelpCircle, Boxes, GitBranch, Layers,
} from 'lucide-react'
import { getGraphStats, isBackendUnreachable, BACKEND_UNREACHABLE_MSG } from '../api/client'
import { PageHeader } from './layout/PageHeader'
import { cn } from '../lib/utils'

function EntityTypeIcon({ type, size = 14 }) {
  const map = {
    PERSON: Users,
    ORGANIZATION: Building2,
    CONCEPT: Lightbulb,
    LOCATION: MapPin,
    DATE: Calendar,
    OTHER: HelpCircle,
  }
  const Icon = map[type] || HelpCircle
  return <Icon size={size} />
}

function typeColor(type) {
  const map = {
    PERSON: 'bg-chart-4/20 text-chart-4',
    ORGANIZATION: 'bg-chart-2/20 text-chart-2',
    CONCEPT: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    LOCATION: 'bg-orange-500/15 text-orange-600 dark:text-orange-400',
    DATE: 'bg-yellow-500/15 text-yellow-600 dark:text-yellow-400',
    OTHER: 'bg-muted text-muted-foreground',
  }
  return map[type] || 'bg-muted text-muted-foreground'
}

const typeColorBar = {
  PERSON: 'bg-chart-4',
  ORGANIZATION: 'bg-chart-2',
  CONCEPT: 'bg-emerald-500',
  LOCATION: 'bg-orange-500',
  DATE: 'bg-yellow-500',
  OTHER: 'bg-muted-foreground',
}

const chartColors = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']

function StatCard({ label, value, icon: Icon }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-accent-foreground">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <p className="text-2xl font-bold text-card-foreground">{value ?? '—'}</p>
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  )
}

function ProgressBar({ value, max, color = 'bg-primary' }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="h-1.5 w-full rounded-full bg-secondary">
      <div className={cn(color, 'h-1.5 rounded-full transition-all')} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function GraphStats() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedEntity, setSelectedEntity] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getGraphStats()
      setStats(data)
    } catch (err) {
      if (isBackendUnreachable(err)) {
        setError(BACKEND_UNREACHABLE_MSG)
      } else if (err?.response?.status === 401) {
        setError('Chưa đăng nhập. Hãy đăng nhập Google trước.')
      } else {
        setError(err?.response?.data?.detail || err.message || 'Lỗi không xác định')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const totalRelations = stats
    ? Object.values(stats.relations_by_type || {}).reduce((s, v) => s + v, 0)
    : 0

  const maxMentions = stats?.top_entities?.length
    ? Math.max(...stats.top_entities.map((e) => e.mentions))
    : 1

  const maxTypeCount = stats?.entity_types
    ? Math.max(...Object.values(stats.entity_types))
    : 1

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title="Knowledge Graph"
        subtitle="Đồ thị tri thức trích xuất từ tài liệu"
        icon={<Network className="h-5 w-5" />}
        actions={
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Làm mới
          </button>
        }
      />

      <div className="mx-auto w-full max-w-6xl px-6 py-6">
        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {loading && !stats && (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-2xl border border-border bg-card p-4">
                <div className="mb-2 h-4 w-1/3 rounded bg-muted" />
                <div className="h-6 w-1/4 rounded bg-muted" />
              </div>
            ))}
          </div>
        )}

        {stats && (
          <>
            {stats.total_entities === 0 && (
              <div className="rounded-2xl border border-primary/30 bg-primary/5 px-4 py-8 text-center">
                <Network size={32} className="mx-auto mb-2 text-primary/50" />
                <p className="text-sm font-medium text-foreground">Chưa có Knowledge Graph</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Đồng bộ tài liệu từ Google Drive để tự động xây dựng graph.
                </p>
              </div>
            )}

            {stats.total_entities > 0 && (
              <>
                <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <StatCard label="Thực thể (Entities)" value={stats.total_entities} icon={Boxes} />
                  <StatCard label="Quan hệ (Relations)" value={totalRelations} icon={GitBranch} />
                  <StatCard
                    label="Loại Entity"
                    value={Object.keys(stats.entity_types || {}).length}
                    icon={Layers}
                  />
                </div>

                <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_280px]">
                  <div className="space-y-4">
                    {Object.keys(stats.entity_types || {}).length > 0 && (
                      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
                        <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-card-foreground">
                          <BarChart2 size={15} />
                          Phân loại Entity
                        </h3>
                        <div className="space-y-2.5">
                          {Object.entries(stats.entity_types)
                            .sort((a, b) => b[1] - a[1])
                            .map(([type, count]) => (
                              <div key={type}>
                                <div className="mb-1 flex items-center justify-between">
                                  <span className={cn('flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium', typeColor(type))}>
                                    <EntityTypeIcon type={type} size={12} />
                                    {type}
                                  </span>
                                  <span className="text-xs font-medium text-muted-foreground">{count}</span>
                                </div>
                                <ProgressBar
                                  value={count}
                                  max={maxTypeCount}
                                  color={typeColorBar[type] || 'bg-muted-foreground'}
                                />
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                    {Object.keys(stats.relations_by_type || {}).length > 0 && (
                      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
                        <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-card-foreground">
                          <Link2 size={15} />
                          Loại Relation
                        </h3>
                        <div className="space-y-2">
                          {Object.entries(stats.relations_by_type)
                            .sort((a, b) => b[1] - a[1])
                            .map(([type, count]) => (
                              <div
                                key={type}
                                className="flex items-center justify-between border-b border-border/50 py-1 text-sm last:border-0"
                              >
                                <span className="rounded bg-secondary px-2 py-0.5 font-mono text-xs text-card-foreground">
                                  {type}
                                </span>
                                <span className="font-medium text-muted-foreground">{count}</span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                    {stats.top_entities?.length > 0 && (
                      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm lg:hidden">
                        <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-card-foreground">
                          <Users size={15} />
                          Entity xuất hiện nhiều nhất
                        </h3>
                        <div className="space-y-3">
                          {stats.top_entities.map((ent, i) => (
                            <div key={i}>
                              <div className="mb-1 flex items-center justify-between">
                                <div className="flex min-w-0 items-center gap-2">
                                  <span className="w-4 shrink-0 text-xs text-muted-foreground">{i + 1}.</span>
                                  <span className={cn('flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-xs', typeColor(ent.type))}>
                                    <EntityTypeIcon type={ent.type} size={11} />
                                  </span>
                                  <span className="truncate text-sm font-medium text-card-foreground">{ent.name}</span>
                                </div>
                                <span className="ml-2 shrink-0 text-xs text-muted-foreground">{ent.mentions} lần</span>
                              </div>
                              <ProgressBar value={ent.mentions} max={maxMentions} />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {stats.top_entities?.length > 0 && (
                    <div className="hidden rounded-2xl border border-border bg-card p-4 shadow-sm lg:block">
                      <h3 className="mb-3 text-sm font-bold text-card-foreground">Top thực thể</h3>
                      <ul className="flex flex-col gap-1">
                        {stats.top_entities.map((ent, i) => (
                          <li key={i}>
                            <button
                              type="button"
                              onClick={() => setSelectedEntity(ent.name)}
                              className={cn(
                                'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors',
                                selectedEntity === ent.name
                                  ? 'bg-accent font-medium text-accent-foreground'
                                  : 'text-muted-foreground hover:bg-secondary',
                              )}
                            >
                              <span
                                className="h-3 w-3 shrink-0 rounded-full"
                                style={{ background: chartColors[i % chartColors.length] }}
                              />
                              <span className="truncate">{ent.name}</span>
                              <span className="ml-auto shrink-0 text-xs text-muted-foreground">{ent.mentions}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                      {selectedEntity && (
                        <div className="mt-4 border-t border-border pt-4">
                          <p className="text-xs text-muted-foreground">Đang chọn</p>
                          <p className="mt-1 font-semibold text-card-foreground">{selectedEntity}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <p className="mt-6 text-center text-xs text-muted-foreground">
                  Knowledge Graph được xây dựng tự động khi đồng bộ tài liệu.
                  Dữ liệu trên chỉ tính cho tài khoản của bạn.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
