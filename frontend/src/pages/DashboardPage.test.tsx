import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from './DashboardPage'
import { ApiError } from '../api/client'
import type { MissionDetail, PlatformStats } from '../types'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getStats: vi.fn(),
      listMissions: vi.fn(),
      createMission: vi.fn(),
    },
  }
})

import { api } from '../api/client'
const mockedApi = vi.mocked(api)

const STATS: PlatformStats = {
  missions: { total: 12, by_status: { completed: 10, running: 2 }, completion_rate: 0.833, avg_revisions: 0.4 },
  llm: { calls: 340, prompt_tokens: 120000, completion_tokens: 45000, cost_usd: 1.2345 },
  quality: { avg_judge_score: 8.2, judged_reports: 9 },
  avg_node_latency_ms: { planner: 900, researcher: 2100, synthesizer: 1500 },
}

const MISSIONS: MissionDetail[] = [
  {
    mission_id: 'm-abc',
    question: 'Should we adopt Postgres for vector workloads?',
    status: 'completed',
    plan: null,
    revision_count: 1,
    error: null,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:05:00Z',
  },
]

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.getStats.mockResolvedValue(STATS)
    mockedApi.listMissions.mockResolvedValue(MISSIONS)
    mockedApi.createMission.mockResolvedValue({ mission_id: 'm-new', status: 'queued' })
  })

  it('renders scoreboard stats and the missions list', async () => {
    renderPage()

    expect(await screen.findByTestId('stat-Missions')).toHaveTextContent('12')
    expect(screen.getByTestId('stat-Spend')).toHaveTextContent('$1.23')
    expect(screen.getByText('Completion')).toBeInTheDocument()
    expect(await screen.findByText(/adopt Postgres/)).toBeInTheDocument()
  })

  it('disables launch until the question is long enough', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('stat-Missions')

    const input = screen.getByTestId('question-input')
    const button = screen.getByTestId('submit-mission') as HTMLButtonElement
    expect(button).toBeDisabled()

    await user.type(input, 'too short')
    expect(button).toBeDisabled()

    await user.clear(input)
    await user.type(input, 'a perfectly reasonable research question')
    expect(button).toBeEnabled()
  })

  it('submits a new mission and shows the confirmation link', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByTestId('stat-Missions')

    await user.type(
      screen.getByTestId('question-input'),
      'Compare qdrant vs pgvector for our stack',
    )
    await user.click(screen.getByTestId('submit-mission'))

    await waitFor(() => {
      expect(mockedApi.createMission).toHaveBeenCalledWith(
        'Compare qdrant vs pgvector for our stack',
      )
    })
    expect(await screen.findByTestId('mission-created')).toHaveTextContent(/Mission queued/)
    expect(screen.getByText('view progress').closest('a')).toHaveAttribute(
      'href',
      '/missions/m-new',
    )
    expect(mockedApi.getStats).toHaveBeenCalledTimes(2)
  })

  it('shows an alert when stats fail to load', async () => {
    mockedApi.getStats.mockRejectedValue(new ApiError(500, 'Network down'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/Network down/)
  })
})
