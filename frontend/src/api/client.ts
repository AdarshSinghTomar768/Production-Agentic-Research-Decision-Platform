import type {
  ApprovalDecisionBody,
  EvalRunSummary,
  IngestResponse,
  MissionCreated,
  MissionDetail,
  MissionUsage,
  PlatformStats,
  ReportResponse,
  ReviewPayload,
  SearchResponse,
} from '../types'

const BASE: string = import.meta.env.VITE_API_BASE_URL ?? '/api'
const API_KEY: string = import.meta.env.VITE_API_KEY ?? 'dev-key-change-me'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY,
        ...(options.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError(0, `Network error: could not reach the API at ${BASE}`)
  }
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.detail != null) {
        detail =
          typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail, null, 2)
      }
    } catch {
      // keep default detail
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const api = {
  getStats: () => request<PlatformStats>('/v1/missions/stats'),

  listMissions: (limit = 20) =>
    request<MissionDetail[]>(`/v1/missions?limit=${encodeURIComponent(limit)}`),

  createMission: (question: string) =>
    request<MissionCreated>('/v1/missions', {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),

  getMission: (id: string) => request<MissionDetail>(`/v1/missions/${id}`),

  getReview: (id: string) => request<ReviewPayload>(`/v1/missions/${id}/review`),

  decide: (id: string, body: ApprovalDecisionBody) =>
    request<MissionCreated>(`/v1/missions/${id}/decision`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getReport: (id: string) => request<ReportResponse>(`/v1/missions/${id}/report`),

  getUsage: (id: string) => request<MissionUsage>(`/v1/missions/${id}/usage`),

  searchKnowledge: (query: string, topK = 5) =>
    request<SearchResponse>('/v1/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK }),
    }),

  ingestDocument: (title: string, text: string) =>
    request<IngestResponse>('/v1/knowledge/ingest', {
      method: 'POST',
      body: JSON.stringify({ documents: [{ title, text, metadata: { source: 'frontend' } }] }),
    }),

  runEvals: (fakeLlm = true) =>
    request<EvalRunSummary>('/v1/evals/run', {
      method: 'POST',
      body: JSON.stringify({ fake_llm: fakeLlm }),
    }),
}
