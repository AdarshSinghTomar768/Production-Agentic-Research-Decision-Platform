export type MissionStatus =
  | 'queued'
  | 'running'
  | 'pending_approval'
  | 'completed'
  | 'failed'
  | 'guardrail_blocked'

export interface ResearchPlanStep {
  id?: string
  title?: string
  description?: string
  [key: string]: unknown
}

export interface ResearchPlan {
  objective?: string
  steps?: ResearchPlanStep[]
  [key: string]: unknown
}

export interface MissionDetail {
  mission_id: string
  question: string
  status: MissionStatus
  plan?: ResearchPlan | null
  revision_count: number
  error?: string | null
  created_at: string
  updated_at: string
}

export interface MissionCreated {
  mission_id: string
  status: MissionStatus
}

export interface PlatformStats {
  missions: {
    total: number
    by_status: Record<string, number>
    completion_rate: number
    avg_revisions: number
  }
  llm: {
    calls: number
    prompt_tokens: number
    completion_tokens: number
    cost_usd: number
  }
  quality: {
    avg_judge_score: number | null
    judged_reports: number
  }
  avg_node_latency_ms: Record<string, number>
}

export interface ReviewPayload {
  mission_id: string
  status: MissionStatus
  review: unknown
}

export interface ApprovalDecisionBody {
  approved: boolean
  feedback?: string | null
}

export interface ReportSection {
  heading: string
  body: string
  citations: string[]
}

export interface Citation {
  evidence_id: string
  title: string
  url: string | null
  source: string
}

export interface FinalReport {
  mission_id: string
  question: string
  title: string
  executive_summary: string
  sections: ReportSection[]
  recommendation: string
  confidence: 'low' | 'medium' | 'high'
  open_questions: string[]
  sources: Citation[]
  review_history: Record<string, unknown>[]
  generated_at: string
}

export interface ReportResponse {
  mission_id: string
  question: string
  report: FinalReport
}

export interface UsageRow {
  node: string
  model: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  total_latency_ms: number
}

export interface MissionUsage {
  mission_id: string
  rows: UsageRow[]
  totals: Record<string, number>
}

export interface SearchHit {
  score: number
  title: string
  content: string
  metadata: Record<string, unknown>
}

export interface SearchResponse {
  query: string
  hits: SearchHit[]
}

export interface IngestResponse {
  documents_ingested: number
  chunks_indexed: number
  collection: string
}

export interface EvalCaseResult {
  case_id: string
  question: string
  overall_score: number
  passed_judge: boolean
  dimensions: Record<string, number>
  notes: string[]
}

export interface EvalRunSummary {
  run_id: string
  cases: EvalCaseResult[]
  mean_overall: number
  mean_pass_rate: number
  fake_llm: boolean
}
