"use client"

import { CheckIcon, CircleIcon, Loader2Icon, RotateCcwIcon, XIcon } from "lucide-react"

import { STAGES } from "@/lib/research"
import type { ProgressEvent, ResearchStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

export type StageState = "pending" | "active" | "done" | "failed" | "skipped"

export interface StageView {
  id: string
  label: string
  description: string
  state: StageState
  visits: number
  lastMessage?: string
}

/** Derive per-stage state purely from persisted backend events (no simulated progress). */
export function deriveStages(events: ProgressEvent[], status: ResearchStatus | undefined): StageView[] {
  const visits = new Map<string, number>()
  const messages = new Map<string, string>()
  let current: string | null = null
  const done = new Set<string>()

  for (const event of events) {
    if (event.type === "stage_started" && event.node) {
      if (current && current !== event.node) done.add(current)
      current = event.node
      visits.set(event.node, (visits.get(event.node) ?? 0) + 1)
      done.delete(event.node)
    }
    if (event.node && event.type !== "stage_started") messages.set(event.node, event.message)
  }

  const terminal = status && !["queued", "running"].includes(status)
  return STAGES.map((stage) => {
    let state: StageState = "pending"
    if (done.has(stage.id)) state = "done"
    if (current === stage.id) {
      if (!terminal) state = "active"
      else if (status === "completed" || status === "completed_with_warnings") state = "done"
      else state = "failed"
    }
    if (state === "pending" && terminal) state = "skipped"
    return { ...stage, state, visits: visits.get(stage.id) ?? 0, lastMessage: messages.get(stage.id) }
  })
}

const ICON: Record<StageState, React.ReactNode> = {
  pending: <CircleIcon className="size-3 text-muted-foreground/50" />,
  skipped: <CircleIcon className="size-3 text-muted-foreground/30" />,
  active: <Loader2Icon className="size-3.5 animate-spin text-info" />,
  done: <CheckIcon className="size-3.5 text-success" />,
  failed: <XIcon className="size-3.5 text-destructive" />,
}

export function WorkflowTimeline({
  events,
  status,
  revisionCount,
}: {
  events: ProgressEvent[]
  status: ResearchStatus | undefined
  revisionCount: number
}) {
  const stages = deriveStages(events, status)
  return (
    <ol className="relative space-y-0" aria-label="Workflow stages">
      {stages.map((stage, index) => (
        <li key={stage.id} className="relative flex gap-3 pb-5 last:pb-0" data-state={stage.state}>
          {index < stages.length - 1 && (
            <span
              aria-hidden
              className={cn(
                "absolute top-6 left-[11px] h-[calc(100%-1.25rem)] w-px",
                stage.state === "done" ? "bg-success/40" : "bg-border",
              )}
            />
          )}
          <span
            className={cn(
              "relative z-10 grid size-6 shrink-0 place-items-center rounded-full border bg-background",
              stage.state === "active" && "border-info/50 ring-3 ring-info/15",
              stage.state === "done" && "border-success/40",
              stage.state === "failed" && "border-destructive/50",
            )}
          >
            {ICON[stage.state]}
          </span>
          <div className="min-w-0 pt-0.5">
            <p
              className={cn(
                "flex items-center gap-2 text-sm font-medium",
                (stage.state === "pending" || stage.state === "skipped") && "text-muted-foreground",
              )}
            >
              {stage.label}
              {stage.visits > 1 && (
                <span className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 text-[11px] font-normal text-muted-foreground">
                  <RotateCcwIcon className="size-2.5" />×{stage.visits}
                </span>
              )}
              <span className="sr-only">({stage.state})</span>
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {stage.state === "pending" || stage.state === "skipped" ? stage.description : (stage.lastMessage ?? stage.description)}
            </p>
          </div>
        </li>
      ))}
      {revisionCount > 0 && (
        <li className="mt-4 text-xs text-muted-foreground">
          {revisionCount} revision cycle{revisionCount === 1 ? "" : "s"} triggered by the critic
        </li>
      )}
    </ol>
  )
}
