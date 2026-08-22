import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EvalsPage from './EvalsPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      runEvals: vi.fn(),
    },
  }
})

import { api } from '../api/client'
const mockedApi = vi.mocked(api)

describe('EvalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('warns about quota usage only when fake mode is off', async () => {
    const user = userEvent.setup()
    render(<EvalsPage />)

    expect(screen.queryByTestId('real-llm-warning')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('fake-llm-checkbox'))
    expect(screen.getByTestId('real-llm-warning')).toHaveTextContent(/free-tier/i)

    await user.click(screen.getByTestId('fake-llm-checkbox'))
    expect(screen.queryByTestId('real-llm-warning')).not.toBeInTheDocument()
  })

  it('sends the selected mode and renders a passing summary', async () => {
    mockedApi.runEvals.mockResolvedValue({
      run_id: 'eval-1',
      mean_overall: 8.0,
      mean_pass_rate: 1.0,
      fake_llm: true,
      cases: [
        {
          case_id: 'case-a',
          question: 'Q?',
          overall_score: 8.0,
          passed_judge: true,
          dimensions: { coverage: 8 },
          notes: [],
        },
      ],
    })

    const user = userEvent.setup()
    render(<EvalsPage />)
    await user.click(screen.getByTestId('run-evals-btn'))

    await waitFor(() => expect(mockedApi.runEvals).toHaveBeenCalledWith(true))
    const summary = await screen.findByTestId('eval-summary')
    expect(summary).toHaveTextContent('8.00')
    expect(screen.getByText('case-a')).toBeInTheDocument()
    expect(screen.getByText(/PASS/)).toBeInTheDocument()
  })
})
