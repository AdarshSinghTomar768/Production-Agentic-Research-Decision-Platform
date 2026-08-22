import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MissionDetailPage from './MissionDetailPage'
import type { FinalReport, MissionDetail, ReportResponse, ReviewPayload } from '../types'

const REPORT: FinalReport = {
  mission_id: 'm-1',
  question: 'Evaluate migration to Postgres 17',
  title: 'Postgres 17 Migration Assessment',
  executive_summary: 'Upgrade is low risk with the right checklist.',
  sections: [{ heading: 'Findings', body: 'Benchmarks show 20% gains [ev-rag-001].', citations: ['ev-rag-001'] }],
  recommendation: 'Proceed behind a read replica.',
  confidence: 'medium',
  open_questions: ['Replication lag under load?'],
  sources: [{ evidence_id: 'ev-rag-001', title: 'Release notes', url: null, source: 'rag' }],
  review_history: [],
  generated_at: '2026-08-01T10:04:00Z',
}

const REPORT_RESPONSE: ReportResponse = {
  mission_id: 'm-1',
  question: 'Evaluate migration to Postgres 17',
  report: REPORT,
}

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getMission: vi.fn(),
      getReview: vi.fn(),
      decide: vi.fn(),
      getReport: vi.fn(),
      getUsage: vi.fn(),
    },
  }
})

import { api } from '../api/client'
const mockedApi = vi.mocked(api)

function missionWith(status: MissionDetail['status']): MissionDetail {
  return {
    mission_id: 'm-1',
    question: 'Evaluate migration to Postgres 17',
    status,
    plan: { objective: 'Assess upgrade risks', steps: [{ id: 's1', title: 'Benchmark' }] },
    revision_count: 0,
    error: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:02:00Z',
  }
}

const REVIEW: ReviewPayload = {
  mission_id: 'm-1',
  status: 'pending_approval',
  review: { plan: { objective: 'Assess upgrade risks' }, message: 'approve to continue' },
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/missions/m-1']}>
      <Routes>
        <Route path="/missions/:id" element={<MissionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MissionDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.getReport.mockResolvedValue(REPORT_RESPONSE)
    mockedApi.getUsage.mockResolvedValue({ mission_id: 'm-1', rows: [], totals: {} })
  })

  it('shows the review panel and submits an approval', async () => {
    mockedApi.getMission.mockResolvedValue(missionWith('pending_approval'))
    mockedApi.getReview.mockResolvedValue(REVIEW)
    mockedApi.decide.mockResolvedValue({ mission_id: 'm-1', status: 'running' })

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByTestId('review-panel')).toBeInTheDocument()
    expect(screen.getByTestId('review-panel')).toHaveTextContent(/approve to continue/)

    await user.type(screen.getByTestId('feedback-input'), 'looks good, proceed')
    await user.click(screen.getByTestId('approve-btn'))

    expect(mockedApi.decide).toHaveBeenCalledWith('m-1', {
      approved: true,
      feedback: null,
    })
  })

  it('requires feedback before allowing a rejection', async () => {
    mockedApi.getMission.mockResolvedValue(missionWith('pending_approval'))
    mockedApi.getReview.mockResolvedValue(REVIEW)

    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('review-panel')

    const rejectBtn = screen.getByTestId('reject-btn') as HTMLButtonElement
    expect(rejectBtn).toBeDisabled()

    await user.type(screen.getByTestId('feedback-input'), 'plan misses cost analysis')
    expect(rejectBtn).toBeEnabled()

    mockedApi.decide.mockResolvedValue({ mission_id: 'm-1', status: 'running' })
    await user.click(rejectBtn)
    expect(mockedApi.decide).toHaveBeenCalledWith('m-1', {
      approved: false,
      feedback: 'plan misses cost analysis',
    })
  })

  it('shows a polling note while the mission is running and no review', async () => {
    mockedApi.getMission.mockResolvedValue(missionWith('running'))
    renderPage()

    expect(await screen.findByTestId('polling-note')).toBeInTheDocument()
    expect(screen.queryByTestId('review-panel')).not.toBeInTheDocument()
  })

  it('renders the plan panel when a plan is attached', async () => {
    mockedApi.getMission.mockResolvedValue(missionWith('completed'))
    renderPage()

    expect(await screen.findByTestId('plan-panel')).toHaveTextContent('Assess upgrade risks')
  })
})
