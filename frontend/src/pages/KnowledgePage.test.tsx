import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import KnowledgePage from './KnowledgePage'
import { ApiError } from '../api/client'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      searchKnowledge: vi.fn(),
      ingestDocument: vi.fn(),
    },
  }
})

import { api } from '../api/client'
const mockedApi = vi.mocked(api)

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('performs a search and renders hits with scores', async () => {
    mockedApi.searchKnowledge.mockResolvedValue({
      query: 'vector db',
      hits: [
        { score: 0.9123, title: 'Qdrant guide', content: 'Filterable HNSW indexes…', metadata: {} },
      ],
    })

    const user = userEvent.setup()
    render(<KnowledgePage />)

    const searchBtn = screen.getByTestId('search-btn') as HTMLButtonElement
    expect(searchBtn).toBeDisabled()

    await user.type(screen.getByTestId('search-input'), 'vector db')
    expect(searchBtn).toBeEnabled()
    await user.click(searchBtn)

    expect(mockedApi.searchKnowledge).toHaveBeenCalledWith('vector db', 5)
    const results = await screen.findByTestId('search-results')
    expect(results).toHaveTextContent('Qdrant guide')
    expect(results).toHaveTextContent('0.912')
  })

  it('shows an empty-state message when there are no hits', async () => {
    mockedApi.searchKnowledge.mockResolvedValue({ query: 'zzz', hits: [] })
    const user = userEvent.setup()
    render(<KnowledgePage />)

    await user.type(screen.getByTestId('search-input'), 'zzz query')
    await user.click(screen.getByTestId('search-btn'))

    expect(await screen.findByText('No hits for this query.')).toBeInTheDocument()
  })

  it('surfaces API errors as alerts', async () => {
    mockedApi.searchKnowledge.mockRejectedValue(new ApiError(503, 'embedder down'))
    const user = userEvent.setup()
    render(<KnowledgePage />)

    await user.type(screen.getByTestId('search-input'), 'anything goes here')
    await user.click(screen.getByTestId('search-btn'))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/embedder down/),
    )
  })

  it('ingests a document and reports indexed chunks', async () => {
    mockedApi.ingestDocument.mockResolvedValue({
      documents_ingested: 1,
      chunks_indexed: 7,
      collection: 'kb_main',
    })

    const user = userEvent.setup()
    render(<KnowledgePage />)

    const ingestBtn = screen.getByTestId('ingest-btn') as HTMLButtonElement
    expect(ingestBtn).toBeDisabled()

    await user.type(screen.getByTestId('doc-title'), 'Runbook notes')
    await user.type(screen.getByTestId('doc-text'), 'Some long operational text for the index.')
    expect(ingestBtn).toBeEnabled()
    await user.click(ingestBtn)

    expect(await screen.findByTestId('ingest-result')).toHaveTextContent(
      /7 chunks.*kb_main/,
    )
  })
})
