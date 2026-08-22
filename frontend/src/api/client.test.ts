import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sends the API key header and parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.getStats()

    expect(result).toEqual({ status: 'ok' })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-API-Key']).toBeTruthy()
    expect(init.headers['Content-Type']).toBe('application/json')
    vi.unstubAllGlobals()
  })

  it('throws ApiError with backend detail on error responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'mission is failed' }, 409)),
    )
    await expect(api.getReport('m-1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      message: 'mission is failed',
    })
    vi.unstubAllGlobals()
  })

  it('falls back to status text when the body has no detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('', { status: 500, statusText: 'Boom' })),
    )
    const err = await api.getStats().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('Boom')
    vi.unstubAllGlobals()
  })

  it('wraps network failures in an ApiError with status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    const err = await api.getStats().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
    expect(err.message).toContain('Network error')
    vi.unstubAllGlobals()
  })

  it('serializes POST bodies correctly', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ mission_id: 'm-9', status: 'queued' }))
    vi.stubGlobal('fetch', fetchMock)

    await api.createMission('a question long enough')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url.endsWith('/v1/missions')).toBe(true)
    expect(JSON.parse(init.body)).toEqual({ question: 'a question long enough' })
    vi.unstubAllGlobals()
  })
})
