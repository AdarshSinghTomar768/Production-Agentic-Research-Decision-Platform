import type { MissionStatus } from '../types'

const STYLES: Record<MissionStatus, { label: string; className: string }> = {
  queued: {
    label: 'Queued',
    className: 'bg-slate-700/50 text-slate-300 ring-slate-500/40',
  },
  running: {
    label: 'Running',
    className: 'bg-blue-500/10 text-blue-300 ring-blue-400/40 animate-pulse',
  },
  pending_approval: {
    label: 'Awaiting approval',
    className: 'bg-amber-500/10 text-amber-300 ring-amber-400/40',
  },
  completed: {
    label: 'Completed',
    className: 'bg-emerald-500/10 text-emerald-300 ring-emerald-400/40',
  },
  failed: {
    label: 'Failed',
    className: 'bg-red-500/10 text-red-300 ring-red-400/40',
  },
  guardrail_blocked: {
    label: 'Guardrail blocked',
    className: 'bg-fuchsia-500/10 text-fuchsia-300 ring-fuchsia-400/40',
  },
}

export default function StatusBadge({ status }: { status: MissionStatus }) {
  const style = STYLES[status] ?? {
    label: status,
    className: 'bg-slate-700/50 text-slate-300 ring-slate-500/40',
  }
  return (
    <span
      data-testid="status-badge"
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  )
}
