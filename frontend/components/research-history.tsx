"use client"

import { FileTextIcon, RefreshCwIcon } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

import { StatusBadge } from "@/components/research-status"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, api } from "@/lib/api"
import { isTerminal, relativeTime } from "@/lib/research"
import type { ResearchSummary } from "@/lib/types"

export function ResearchHistory() {
  const [items, setItems] = useState<ResearchSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await api.listResearch(20))
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load research history.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data fetch
    void load()
  }, [load])

  // Keep running tasks fresh without a websocket per row.
  const hasActive = items?.some((i) => !isTerminal(i.status)) ?? false
  useEffect(() => {
    if (!hasActive) return
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [hasActive, load])

  return (
    <section aria-labelledby="history-heading" className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 id="history-heading" className="text-sm font-medium text-muted-foreground">
          Recent research
        </h2>
        <Button variant="ghost" size="icon-sm" onClick={load} disabled={loading} aria-label="Refresh history">
          <RefreshCwIcon className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {items === null && !error && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {items?.length === 0 && (
        <div className="rounded-xl border border-dashed px-6 py-10 text-center">
          <FileTextIcon className="mx-auto mb-2 size-5 text-muted-foreground" />
          <p className="text-sm font-medium">No research yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Your reports will appear here once you start one.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <ul className="divide-y rounded-xl border bg-card">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/research/${item.id}`}
                className="flex flex-col gap-1.5 px-4 py-3 transition-colors outline-none hover:bg-muted/50 focus-visible:bg-muted/50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{item.title ?? item.question}</p>
                  {item.title && <p className="truncate text-xs text-muted-foreground">{item.question}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="tabular-nums">{item.source_count} sources</span>
                  <span className="capitalize">{item.depth}</span>
                  <span>{relativeTime(item.created_at)}</span>
                  <StatusBadge status={item.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
