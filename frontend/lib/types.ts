// Types mirroring the FastAPI/Pydantic schemas in backend/app/schemas.

export type ResearchDepth = "quick" | "standard" | "deep"

export type ResearchStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled"

export const TERMINAL_STATUSES: ResearchStatus[] = [
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
]

export interface ResearchRequest {
  question: string
  depth: ResearchDepth
  include_domains: string[]
  exclude_domains: string[]
  start_date: string | null
  end_date: string | null
  max_sources_per_subquestion: number | null
}

export interface SubQuestion {
  id: string
  question: string
  search_queries: string[]
  evidence_needed: string
}

export interface ResearchPlan {
  objective: string
  subquestions: SubQuestion[]
  search_strategy: string
  methodology: string
  scope: string
  limitations: string[]
}

export interface UsageStats {
  llm_calls: number
  input_tokens: number
  output_tokens: number
  search_calls: number
  pages_fetched: number
  fetch_failures: number
}

export interface ResearchSummary {
  id: string
  question: string
  title: string | null
  status: ResearchStatus
  depth: ResearchDepth
  current_stage: string | null
  source_count: number
  revision_count: number
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface ResearchDetail extends ResearchSummary {
  request: ResearchRequest
  plan: ResearchPlan | null
  error: string | null
  warnings: string[]
  usage: UsageStats
  elapsed_seconds: number | null
  has_report: boolean
}

export type ExtractionStatus = "pending" | "extracted" | "snippet_only" | "failed"

export interface SourceRecord {
  source_id: string
  title: string
  url: string
  domain: string
  published_at: string | null
  retrieved_at: string
  snippet: string
  extracted_content: string
  extraction_status: ExtractionStatus
  extraction_error: string | null
  source_type: string
  search_query: string
  subquestion_ids: string[]
  search_score: number | null
}

export type Severity = "low" | "medium" | "high"

export interface EvidenceClaim {
  claim_id: string
  claim_text: string
  subquestion_id: string | null
  source_ids: string[]
  supporting_evidence: string[]
  contradicting_evidence: { source_id: string; text: string }[]
  assessment: "established" | "reported" | "estimate" | "interpretation" | "contested" | "uncertain"
  limitations: string
}

export interface EvidenceMatrix {
  claims: EvidenceClaim[]
  conflicts: string[]
  gaps: string[]
  dropped_claims: number
}

export interface CriticIssue {
  type: string
  severity: Severity
  description: string
  claim_text: string
  source_ids: string[]
  recommendation: string
  origin: "deterministic" | "llm"
}

export interface CriticResult {
  overall_assessment: string
  issues: CriticIssue[]
  unsupported_claims: string[]
  invalid_citations: string[]
  missing_coverage: string[]
  requires_revision: boolean
  requires_more_research: boolean
  follow_up_queries: string[]
  summary: string
}

export interface QualityAssessment {
  status: "passed" | "passed_with_warnings" | "failed"
  citation_count: number
  valid_citation_count: number
  invalid_citations_removed: string[]
  cited_source_count: number
  distinct_cited_domains: number
  uncited_factual_sentences: number
  revision_cycles: number
  unresolved_issues: CriticIssue[]
  subquestion_coverage: Record<string, boolean>
  notes: string[]
}

export interface ResearchReport {
  research_id: string
  title: string
  question: string
  status: ResearchStatus
  executive_summary: string
  report_markdown: string
  sources: SourceRecord[]
  evidence_matrix: EvidenceMatrix | null
  critic: CriticResult | null
  quality_assessment: QualityAssessment
  plan: ResearchPlan | null
  created_at: string
  completed_at: string
}

export interface ProgressEvent {
  id: number
  research_id: string
  type: string
  node: string | null
  message: string
  data: Record<string, unknown>
  timestamp: string
}
