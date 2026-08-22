import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { EvalRunSummary } from '../types'

export default function EvalsPage() {
  const [fakeLlm, setFakeLlm] = useState(true)
  const [summary, setSummary] = useState<EvalRunSummary | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setSummary(await api.runEvals(fakeLlm))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Eval run failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-6">
      <section aria-label="Run evals" className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="text-base font-semibold">Golden-set evals</h2>
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              data-testid="fake-llm-checkbox"
              checked={fakeLlm}
              onChange={(e) => setFakeLlm(e.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-950"
            />
            Use fake LLM (deterministic, offline)
          </label>
          <button
            type="button"
            onClick={run}
            data-testid="run-evals-btn"
            disabled={running}
            className="ml-auto rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
          >
            {running ? 'Running…' : 'Run evals'}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Runs every golden case through the full graph and reports judge scores. Pass/fail is
          enforced in code (threshold {7.0}).
        </p>
        {!fakeLlm && (
          <p
            role="note"
            data-testid="real-llm-warning"
            className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-300"
          >
            Real mode: each case makes ~6+ live provider calls (~25 per suite). On a free-tier key
            (e.g. Gemini, 20 requests/day) this will hit rate limits — use fake mode for demos.
          </p>
        )}
      </section>

      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}

      {summary && (
        <>
          <section aria-label="Eval summary" className="grid grid-cols-3 gap-4" data-testid="eval-summary">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Mean overall</p>
              <p className="mt-1 text-2xl font-semibold">{summary.mean_overall.toFixed(2)}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Pass rate</p>
              <p className="mt-1 text-2xl font-semibold">{(summary.mean_pass_rate * 100).toFixed(0)}%</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">Cases</p>
              <p className="mt-1 text-2xl font-semibold">{summary.cases.length}</p>
            </div>
          </section>

          <ul className="space-y-3">
            {summary.cases.map((c) => (
              <li key={c.case_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-slate-500">{c.case_id}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      c.passed_judge
                        ? 'bg-emerald-500/10 text-emerald-300'
                        : 'bg-red-500/10 text-red-300'
                    }`}
                  >
                    {c.passed_judge ? 'PASS' : 'FAIL'} · {c.overall_score.toFixed(1)}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-300">{c.question}</p>
                {Object.keys(c.dimensions).length > 0 && (
                  <p className="mt-2 text-xs tabular-nums text-slate-500">
                    {Object.entries(c.dimensions)
                      .map(([k, v]) => `${k}: ${v.toFixed(1)}`)
                      .join('  ·  ')}
                  </p>
                )}
                {c.notes.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-400/80">
                    {c.notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
