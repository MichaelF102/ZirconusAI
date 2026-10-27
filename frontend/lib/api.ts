import type {
  ResearchDetail,
  ResearchReport,
  ResearchRequest,
  ResearchSummary,
  SourceRecord,
} from "@/lib/types"

// Only the backend URL is public. API keys live exclusively in the backend environment.
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "")

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    })
  } catch {
    throw new ApiError(`Cannot reach the research backend at ${API_BASE_URL}. Is it running?`, 0)
  }
  if (!response.ok) {
    let detail = response.statusText || "Request failed"
    try {
      const body = await response.json()
      if (typeof body?.detail === "string") detail = body.detail
    } catch {
      // non-JSON error body; keep status text
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

export const api = {
  createResearch: (body: Partial<ResearchRequest> & { question: string }) =>
    request<{ id: string; status: string }>("/api/research", { method: "POST", body: JSON.stringify(body) }),
  listResearch: (limit = 20) => request<ResearchSummary[]>(`/api/research?limit=${limit}`),
  getResearch: (id: string) => request<ResearchDetail>(`/api/research/${encodeURIComponent(id)}`),
  getReport: (id: string) => request<ResearchReport>(`/api/research/${encodeURIComponent(id)}/report`),
  getSources: (id: string) => request<SourceRecord[]>(`/api/research/${encodeURIComponent(id)}/sources`),
  cancelResearch: (id: string) =>
    request<ResearchDetail>(`/api/research/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  eventsUrl: (id: string, after = 0) =>
    `${API_BASE_URL}/api/research/${encodeURIComponent(id)}/events${after ? `?after=${after}` : ""}`,
}
