import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { formatCost, formatNumber, formatPercent } from '../lib/format'
import type { MissionDetail, PlatformStats } from '../types'

const QUESTION_MIN = 10
const QUESTION_MAX = 4000

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-100" data-testid={`stat-${label}`}>
        {value}
      </p>
    </div>
  )
}

export default function DashboardPage() {
  const [stats, setStats] = useState<PlatformStats | null>(null)
  const [missions, setMissions] = useState<MissionDetail[]>([])
  const [question, setQuestion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([api.getStats(), api.listMissions(20)])
      setStats(s)
      setMissions(m)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load dashboard')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const created = await api.createMission(question.trim())
      setCreatedId(created.mission_id)
      setQuestion('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create mission')
    } finally {
      setSubmitting(false)
    }
  }

  const questionInvalid = question.length > 0 && question.trim().length < QUESTION_MIN

  return (
    <div className="space-y-8">
      <section aria-label="Platform stats">
        <h1 className="mb-4 text-lg font-semibold">Platform scoreboard</h1>
        {stats ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            <StatCard label="Missions" value={formatNumber(stats.missions.total)} />
            <StatCard label="Completion" value={formatPercent(stats.missions.completion_rate)} />
            <StatCard
              label="Avg judge"
              value={stats.quality.avg_judge_score?.toFixed(2) ?? '—'}
            />
            <StatCard label="LLM calls" value={formatNumber(stats.llm.calls)} />
            <StatCard label="Spend" value={formatCost(stats.llm.cost_usd)} />
          </div>
        ) : (
          <p className="text-sm text-slate-500">{error ?? 'Loading stats…'}</p>
        )}
        {stats && Object.keys(stats.avg_node_latency_ms).length > 0 && (
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Avg node latency
            </p>
            <ul className="mt-3 space-y-2">
              {Object.entries(stats.avg_node_latency_ms).map(([node, ms]) => (
                <li key={node} className="flex items-center gap-3 text-sm">
                  <span className="w-28 shrink-0 truncate text-slate-400">{node}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full bg-indigo-500/70"
                      style={{
                        width: `${Math.min(
                          100,
                          (ms /
                            Math.max(...Object.values(stats.avg_node_latency_ms), 1)) *
                            100,
                        )}%`,
                      }}
                    />
                  </div>
                  <span className="w-16 text-right tabular-nums text-slate-300">
                    {Math.round(ms)}ms
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section aria-label="New mission" className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-base font-semibold">Launch a research mission</h2>
        <form onSubmit={handleSubmit} className="mt-3 space-y-3">
          <textarea
            data-testid="question-input"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            maxLength={QUESTION_MAX}
            placeholder="e.g. What are the trade-offs between vector databases for a RAG pipeline at 10M documents?"
            className="w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-slate-500">
              {question.trim().length}/{QUESTION_MIN} min characters · max {QUESTION_MAX}
            </p>
            <button
              type="submit"
              data-testid="submit-mission"
              disabled={submitting || questionInvalid || question.trim().length < QUESTION_MIN}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? 'Launching…' : 'Launch mission'}
            </button>
          </div>
          {questionInvalid && (
            <p className="text-xs text-amber-400">
              Question must be at least {QUESTION_MIN} characters.
            </p>
          )}
          {createdId && (
            <p className="text-sm text-emerald-400" data-testid="mission-created">
              Mission queued —{' '}
              <Link to={`/missions/${createdId}`} className="underline hover:text-emerald-300">
                view progress
              </Link>
            </p>
          )}
        </form>
      </section>

      <section aria-label="Recent missions">
        <h2 className="mb-3 text-base font-semibold">Recent missions</h2>
        {missions.length === 0 ? (
          <p className="text-sm text-slate-500">No missions yet. Launch one above.</p>
        ) : (
          <ul className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            {missions.map((m) => (
              <li key={m.mission_id}>
                <Link
                  to={`/missions/${m.mission_id}`}
                  className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-slate-800/40"
                >
                  <StatusBadge status={m.status} />
                  <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                    {m.question}
                  </span>
                  <span className="hidden shrink-0 text-xs text-slate-500 sm:block">
                    rev {m.revision_count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
