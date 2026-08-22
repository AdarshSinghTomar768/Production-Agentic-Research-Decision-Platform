import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatusBadge from './StatusBadge'
import type { MissionStatus } from '../types'

describe('StatusBadge', () => {
  it.each([
    ['queued', 'Queued'],
    ['running', 'Running'],
    ['pending_approval', 'Awaiting approval'],
    ['completed', 'Completed'],
    ['failed', 'Failed'],
    ['guardrail_blocked', 'Guardrail blocked'],
  ] as [MissionStatus, string][])('renders %s with a human label', (status, label) => {
    render(<StatusBadge status={status} />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent(label)
  })
})
