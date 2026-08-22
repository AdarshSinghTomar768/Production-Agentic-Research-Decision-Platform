import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { IngestResponse, SearchResponse } from '../types'

export default function KnowledgePage() {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null)
  const [ingesting, setIngesting] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim().length < 2) return
    setSearching(true)
    setSearchError(null)
    try {
      setResult(await api.searchKnowledge(query.trim(), topK))
    } catch (err) {
      setSearchError(err instanceof ApiError ? err.message : 'Search failed')
    } finally {
      setSearching(false)
    }
  }

  async function handleIngest(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !text.trim()) return
    setIngesting(true)
    setIngestError(null)
    try {
      setIngestResult(await api.ingestDocument(title.trim(), text.trim()))
      setTitle('')
      setText('')
    } catch (err) {
      setIngestError(err instanceof ApiError ? err.message : 'Ingest failed')
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <section aria-label="Semantic search" className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-base font-semibold">Search the knowledge base</h2>
          <form onSubmit={handleSearch} className="mt-3 space-y-3">
            <input
              data-testid="search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Semantic query…"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-400">
                top_k
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
                >
                  {[1, 3, 5, 10, 20].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                data-testid="search-btn"
                disabled={searching || query.trim().length < 2}
                className="ml-auto rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
              >
                {searching ? 'Searching…' : 'Search'}
              </button>
            </div>
          </form>
        </div>

        {searchError && (
          <p role="alert" className="text-sm text-red-400">
            {searchError}
          </p>
        )}

        {result && (
          <ul className="space-y-3" data-testid="search-results">
            {result.hits.length === 0 && (
              <li className="text-sm text-slate-500">No hits for this query.</li>
            )}
            {result.hits.map((hit, i) => (
              <li key={i} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="truncate text-sm font-semibold text-slate-200">{hit.title}</h3>
                  <span className="shrink-0 rounded bg-slate-800 px-2 py-0.5 text-xs tabular-nums text-indigo-300">
                    {hit.score.toFixed(3)}
                  </span>
                </div>
                <p className="mt-2 line-clamp-6 whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
                  {hit.content}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Ingest document" className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-base font-semibold">Add a document</h2>
          <form onSubmit={handleIngest} className="mt-3 space-y-3">
            <input
              data-testid="doc-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Document title"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <textarea
              data-testid="doc-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              placeholder="Paste document text — it will be chunked, embedded and indexed."
              className="w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              type="submit"
              data-testid="ingest-btn"
              disabled={ingesting || !title.trim() || !text.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              {ingesting ? 'Ingesting…' : 'Ingest document'}
            </button>
            {ingestError && (
              <p role="alert" className="text-sm text-red-400">
                {ingestError}
              </p>
            )}
            {ingestResult && (
              <p className="text-sm text-emerald-400" data-testid="ingest-result">
                Indexed {ingestResult.chunks_indexed} chunks from{' '}
                {ingestResult.documents_ingested} document(s) into “{ingestResult.collection}”.
              </p>
            )}
          </form>
        </div>
      </section>
    </div>
  )
}
