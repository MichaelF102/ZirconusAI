import type { ResearchStatus } from "@/lib/types"

export const STAGES = [
  { id: "planner", label: "Plan", description: "Break the question into subquestions" },
  { id: "researcher", label: "Search", description: "Query the web for each subquestion" },
  { id: "extractor", label: "Extract", description: "Fetch pages and extract readable text" },
  { id: "analyst", label: "Analyse", description: "Build the evidence matrix" },
  { id: "writer", label: "Write", description: "Draft the cited report" },
  { id: "critic", label: "Critique", description: "Verify claims and citations" },
  { id: "finalizer", label: "Finalise", description: "Validate citations and save" },
] as const

export type StageId = (typeof STAGES)[number]["id"] | "revise"

export const STATUS_LABEL: Record<ResearchStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  cancelled: "Cancelled",
}

export function isTerminal(status: ResearchStatus | undefined): boolean {
  return status === "completed" || status === "completed_with_warnings" || status === "failed" || status === "cancelled"
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—"
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${String(s % 60).padStart(2, "0")}s`
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  })
}

export function relativeTime(value: string, now = Date.now()): string {
  const diff = Math.round((now - new Date(value).getTime()) / 1000)
  if (diff < 60) return "just now"
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return formatDate(value)
}
