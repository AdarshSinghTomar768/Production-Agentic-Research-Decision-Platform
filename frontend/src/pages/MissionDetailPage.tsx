import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { formatCost, formatMs, formatNumber } from '../lib/format'
import type { MissionDetail, MissionUsage, ReportResponse, ReviewPayload } from '../types'

const POLL_MS = 2500
const ACTIVE_STATUSES = new Set(['queued', 'running'])

function Panel({
  title,
  children,
  testid,
}: {
  title: string
  children: React.ReactNode
  testid?: string
}) {
  return (
    <section aria-label={title} className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
      {testid ? (
        <div data-testid={testid}>
          {children}
        </div>
      ) : (
        children
      )}
    </section>
  )
}

export default function MissionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [mission, setMission] = useState<MissionDetail | null>(null)
  const [review, setReview] = useState<ReviewPayload | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [usage, setUsage] = useState<MissionUsage | null>(null)
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [deciding, setDeciding] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    try {
      const m = await api.getMission(id)
      setMission(m)
      setError(null)
      return m
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load mission')
      return null
    }
  }, [id])

  useEffect(() => {
    let cancelled = false
    async function poll() {
      const m = await refresh()
      if (cancelled) return
      if (m && ACTIVE_STATUSES.has(m.status)) {
        timerRef.current = setTimeout(poll, POLL_MS)
      }
      if (m?.status === 'pending_approval') {
        try {
          setReview(await api.getReview(m.mission_id))
        } catch {
          setReview(null)
        }
      }
      if (m?.status === 'completed' && !report) {
        try {
          setReport(await api.getReport(m.mission_id))
          setUsage(await api.getUsage(m.mission_id))
        } catch {
          // report may not be indexed yet; next poll retries via status change
        }
      }
    }
    poll()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, refresh])

  async function decide(approved: boolean) {
    if (!id) return
    if (!approved && !feedback.trim()) {
      setError('Rejection requires feedback for the synthesizer.')
      return
    }
    setDeciding(true)
    setError(null)
    try {
      await api.decide(id, { approved, feedback: approved ? null : feedback.trim() })
      setReview(null)
      setFeedback('')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to submit decision')
    } finally {
      setDeciding(false)
    }
  }

  if (!mission && error) {
    return (
      <div className="space-y-3">
        <Link to="/" className="text-sm text-indigo-400 hover:text-indigo-300">
          ← Back to dashboard
        </Link>
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      </div>
    )
  }

  if (!mission) {
    return <p className="text-sm text-slate-500">Loading mission…</p>
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-indigo-400 hover:text-indigo-300">
          ← Back to dashboard
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <StatusBadge status={mission.status} />
          <span className="font-mono text-xs text-slate-500">{mission.mission_id}</span>
          {mission.revision_count > 0 && (
            <span className="text-xs text-slate-500">revisions: {mission.revision_count}</span>
          )}
        </div>
        <h1 className="mt-2 text-xl font-semibold leading-snug">{mission.question}</h1>
        {mission.error && <p className="mt-2 text-sm text-red-400">Error: {mission.error}</p>}
      </div>

      {review && mission.status === 'pending_approval' && (
        <Panel title="Human review required" testid="review-panel">
          <pre className="max-h-80 overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-relaxed text-slate-300">
            {JSON.stringify(review.review, null, 2)}
          </pre>
          <textarea
            data-testid="feedback-input"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            placeholder={approvedPlaceholder()}
            className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <p className="mt-1 text-xs text-slate-500">
            Feedback is optional when approving and required when rejecting.
          </p>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              data-testid="approve-btn"
              disabled={deciding}
              onClick={() => decide(true)}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
            >
              Approve plan
            </button>
            <button
              type="button"
              data-testid="reject-btn"
              disabled={deciding || !feedback.trim()}
              onClick={() => decide(false)}
              title="Requires feedback"
              className="rounded-lg bg-red-600/90 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Reject with feedback
            </button>
          </div>
        </Panel>
      )}

      {mission.plan && (
        <Panel title="Plan" testid="plan-panel">
          <pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-relaxed text-slate-300">
            {JSON.stringify(mission.plan, null, 2)}
          </pre>
        </Panel>
      )}

      {report && (
        <article className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-6" data-testid="report-panel">
          <div>
            <h2 className="text-lg font-semibold">{report.report.title}</h2>
            <p className="mt-1 inline-flex items-center gap-2 text-xs text-slate-500">
              confidence:
              <span className="rounded bg-slate-800 px-2 py-0.5 font-medium text-slate-300">
                {report.report.confidence}
              </span>
            </p>
          </div>
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Executive summary
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-200">
              {report.report.executive_summary}
            </p>
          </div>
          {report &&
            (report.report.sections ?? []).map((s) => (
              <div key={s.heading}>
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                  {s.heading}
                </h3>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                  {s.body}
                </p>
              </div>
            ))}
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Recommendation
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-emerald-300">
              {report.report.recommendation}
            </p>
          </div>
          {(report?.report.open_questions ?? []).length > 0 && (
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                Open questions
              </h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-300">
                {report!.report.open_questions!.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Sources
            </h3>
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-xs text-slate-400">
              {(report?.report.sources ?? []).map((c) => (
                <li key={c.evidence_id}>
                  [{c.evidence_id}] {c.title}{' '}
                  {c.url && (
                    <a href={c.url} target="_blank" rel="noreferrer" className="text-indigo-400 underline">
                      link
                    </a>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </article>
      )}

      {usage && usage.rows.length > 0 && (
        <Panel title="Usage & cost" testid="usage-panel">
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="pb-2 pr-4 font-medium">Node</th>
                <th className="pb-2 pr-4 font-medium">Model</th>
                <th className="pb-2 pr-4 text-right font-medium">Calls</th>
                <th className="pb-2 pr-4 text-right font-medium">Tokens</th>
                <th className="pb-2 pr-4 text-right font-medium">Latency</th>
                <th className="pb-2 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 tabular-nums text-slate-300">
              {usage.rows.map((r) => (
                <tr key={`${r.node}-${r.model}`}>
                  <td className="py-1.5 pr-4">{r.node}</td>
                  <td className="py-1.5 pr-4 font-mono">{r.model}</td>
                  <td className="py-1.5 pr-4 text-right">{r.calls}</td>
                  <td className="py-1.5 pr-4 text-right">
                    {formatNumber(r.prompt_tokens + r.completion_tokens)}
                  </td>
                  <td className="py-1.5 pr-4 text-right">{formatMs(r.total_latency_ms)}</td>
                  <td className="py-1.5 text-right">{formatCost(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {!report && mission.status === 'completed' && (
        <p className="text-sm text-slate-500">Report not available yet — retrying…</p>
      )}

      {ACTIVE_STATUSES.has(mission.status) && (
        <p className="flex items-center gap-2 text-sm text-slate-500" data-testid="polling-note">
          <span className="inline-block h-2 w-2 animate-ping rounded-full bg-indigo-400" />
          Mission in progress — polling every {POLL_MS / 1000}s…
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}

function approvedPlaceholder(): string {
  return 'Optional feedback for the agents…'
}
