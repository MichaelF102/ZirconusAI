"use client"

import { ArrowLeftIcon, ClockIcon, RefreshCwIcon, SquareIcon, WifiOffIcon } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { EvidencePanel } from "@/components/evidence-panel"
import { IssueList, QualityPanel } from "@/components/quality-panel"
import { ReportViewer } from "@/components/report-viewer"
import { StatusBadge } from "@/components/research-status"
import { SourceContext } from "@/components/source-context"
import { SourceExplorer } from "@/components/source-explorer"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { WorkflowTimeline } from "@/components/workflow-timeline"
import { useResearchEvents } from "@/hooks/use-research-events"
import { ApiError, api } from "@/lib/api"
import { parseCitedIds } from "@/lib/citations"
import { formatDuration, isTerminal } from "@/lib/research"
import type { CriticIssue, ProgressEvent, ResearchDetail, ResearchReport, SourceRecord } from "@/lib/types"

type Tab = "progress" | "report" | "sources" | "evidence" | "quality"

const REFRESH_ON = new Set(["started", "plan", "sources", "extraction", "revision", "stage_started", "completed", "failed", "cancelled"])

export function ResearchWorkspace({ researchId }: { researchId: string }) {
  const [detail, setDetail] = useState<ResearchDetail | null>(null)
  const [loadError, setLoadError] = useState<{ message: string; status: number } | null>(null)
  const [report, setReport] = useState<ResearchReport | null>(null)
  const [sources, setSources] = useState<SourceRecord[]>([])
  const [tab, setTab] = useState<Tab>("progress")
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [fetchedAt, setFetchedAt] = useState(() => Date.now())
  const autoSwitched = useRef(false)

  const refreshDetail = useCallback(async () => {
    try {
      const d = await api.getResearch(researchId)
      setDetail(d)
      setFetchedAt(Date.now())
      setLoadError(null)
      return d
    } catch (e) {
      setLoadError(e instanceof ApiError ? { message: e.message, status: e.status } : { message: "Failed to load", status: 0 })
      return null
    }
  }, [researchId])

  const refreshSources = useCallback(async () => {
    try {
      setSources(await api.getSources(researchId))
    } catch {
      // Non-fatal: the sources tab shows what we have.
    }
  }, [researchId])

  const loadFinal = useCallback(async () => {
    const d = await refreshDetail()
    await refreshSources()
    if (d?.has_report) {
      try {
        const r = await api.getReport(researchId)
        setReport(r)
        setSources(r.sources)
        if (!autoSwitched.current) {
          autoSwitched.current = true
          setTab("report")
        }
      } catch (e) {
        toast.error("Could not load the report", { description: e instanceof Error ? e.message : undefined })
      }
    }
  }, [refreshDetail, refreshSources, researchId])

  useEffect(() => {
    let active = true
    void (async () => {
      const d = await refreshDetail()
      if (!active || !d) return
      if (isTerminal(d.status)) {
        await loadFinal()
      } else {
        await refreshSources()
      }
    })()
    return () => {
      active = false
    }
  }, [refreshDetail, refreshSources, loadFinal])

  const running = detail ? !isTerminal(detail.status) : false

  const { events, connection } = useResearchEvents(researchId, {
    enabled: detail !== null,
    onEvent: (event) => {
      if (!REFRESH_ON.has(event.type)) return
      void refreshDetail()
      if (event.type === "sources" || event.type === "extraction") void refreshSources()
    },
    onEnd: () => void loadFinal(),
    onReconnect: () => void refreshDetail(),
  })

  // Backend-measured elapsed time, advanced locally between refreshes while running.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const elapsed =
    detail?.elapsed_seconds != null
      ? detail.elapsed_seconds + (running ? Math.max(0, (now - fetchedAt) / 1000) : 0)
      : null

  const sourceMap = useMemo(() => new Map(sources.map((s) => [s.source_id, s])), [sources])
  const citedIds = useMemo(() => new Set(report ? parseCitedIds(report.report_markdown) : []), [report])
  const contextValue = useMemo(
    () => ({
      sources: sourceMap,
      showSource: (id: string) => {
        setSelectedSource(id)
        setTab("sources")
      },
    }),
    [sourceMap],
  )

  async function cancel() {
    setCancelling(true)
    try {
      setDetail(await api.cancelResearch(researchId))
      setFetchedAt(Date.now())
      toast("Research cancelled")
    } catch (e) {
      toast.error("Could not cancel", { description: e instanceof Error ? e.message : undefined })
    } finally {
      setCancelling(false)
    }
  }

  if (loadError && !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-16 sm:px-6">
        <Alert variant={loadError.status === 404 ? "default" : "destructive"}>
          <AlertTitle>{loadError.status === 404 ? "Research not found" : "Could not load research"}</AlertTitle>
          <AlertDescription>
            {loadError.status === 404 ? "This research task does not exist or was removed." : loadError.message}
          </AlertDescription>
        </Alert>
        <div className="mt-6 flex gap-2">
          <Button variant="outline" nativeButton={false} render={<Link href="/" />}>
            <ArrowLeftIcon /> Back to dashboard
          </Button>
          {loadError.status !== 404 && (
            <Button variant="ghost" onClick={() => void refreshDetail()}>
              <RefreshCwIcon /> Retry
            </Button>
          )}
        </div>
      </div>
    )
  }

  if (!detail) return <WorkspaceSkeleton />

  const criticEvents = events.filter((e) => e.type === "critic")
  const latestCritic = criticEvents.at(-1)
  const warnings = Array.from(
    new Set([...events.filter((e) => e.type === "warning").map((e) => e.message), ...detail.warnings]),
  )

  return (
    <SourceContext.Provider value={contextValue}>
      <div className="mx-auto w-full max-w-[1800px] px-4 py-8 sm:px-6 lg:px-10">
        <div className="mb-6 space-y-3">
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <Link href="/" className="inline-flex items-center gap-1 hover:text-foreground">
              <ArrowLeftIcon className="size-3.5" /> Dashboard
            </Link>
            <StatusBadge status={detail.status} />
            <span className="inline-flex items-center gap-1 tabular-nums">
              <ClockIcon className="size-3.5" /> {formatDuration(elapsed)}
            </span>
            <span>{detail.depth.charAt(0).toUpperCase() + detail.depth.slice(1)} depth</span>
            {running && connection === "reconnecting" && (
              <span className="inline-flex items-center gap-1 text-warning">
                <WifiOffIcon className="size-3.5" /> Reconnecting to live updates…
              </span>
            )}
            {running && (
              <Dialog>
                <DialogTrigger render={<Button variant="outline" size="sm" className="ml-auto" disabled={cancelling} />}>
                  <SquareIcon /> Stop research
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Stop this research?</DialogTitle>
                    <DialogDescription>
                      The workflow will be cancelled on the server. Sources collected so far are kept, but no report will
                      be produced.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Keep running</DialogClose>
                    <DialogClose render={<Button variant="destructive" onClick={cancel} />}>Stop research</DialogClose>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
          <h1 className="max-w-4xl font-serif text-2xl leading-snug tracking-tight text-balance sm:text-3xl">
            {detail.question}
          </h1>
        </div>

        {detail.status === "failed" && detail.error && (
          <Alert variant="destructive" className="mb-6">
            <AlertTitle>Research failed</AlertTitle>
            <AlertDescription>{detail.error}</AlertDescription>
          </Alert>
        )}
        {detail.status === "cancelled" && (
          <Alert className="mb-6">
            <AlertTitle>Research cancelled</AlertTitle>
            <AlertDescription>This task was stopped before a report was produced.</AlertDescription>
          </Alert>
        )}
        {detail.status === "completed_with_warnings" && report && (
          <Alert className="mb-6 border-warning/40">
            <AlertTitle>Completed with warnings</AlertTitle>
            <AlertDescription>
              Some quality checks did not pass. Review the Quality tab before relying on this report.
            </AlertDescription>
          </Alert>
        )}

        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <TabsList variant="line" className="mb-6">
              <TabsTrigger value="progress">Progress</TabsTrigger>
              <TabsTrigger value="report" disabled={!report}>
                Report
              </TabsTrigger>
              <TabsTrigger value="sources">
                Sources <span className="ml-1 text-xs text-muted-foreground tabular-nums">{sources.length}</span>
              </TabsTrigger>
              <TabsTrigger value="evidence" disabled={!report?.evidence_matrix}>
                Evidence
              </TabsTrigger>
              <TabsTrigger value="quality" disabled={!report}>
                Quality
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="progress">
            <ProgressView
              detail={detail}
              events={events}
              sources={sources}
              warnings={warnings}
              latestCritic={latestCritic}
              criticCount={criticEvents.length}
            />
          </TabsContent>
          <TabsContent value="report">{report && <ReportViewer report={report} />}</TabsContent>
          <TabsContent value="sources">
            <SourceExplorer
              sources={sources}
              claims={report?.evidence_matrix?.claims ?? []}
              citedIds={citedIds}
              selectedId={selectedSource}
              onSelect={setSelectedSource}
            />
          </TabsContent>
          <TabsContent value="evidence">
            {report?.evidence_matrix && <EvidencePanel evidence={report.evidence_matrix} plan={report.plan ?? detail.plan} />}
          </TabsContent>
          <TabsContent value="quality">
            {report && <QualityPanel report={report} plan={report.plan ?? detail.plan} usage={detail.usage} />}
          </TabsContent>
        </Tabs>
      </div>
    </SourceContext.Provider>
  )
}

function ProgressView({
  detail,
  events,
  sources,
  warnings,
  latestCritic,
  criticCount,
}: {
  detail: ResearchDetail
  events: ProgressEvent[]
  sources: SourceRecord[]
  warnings: string[]
  latestCritic: ProgressEvent | undefined
  criticCount: number
}) {
  const searches = events.filter((e) => e.type === "search").length
  const extracted = sources.filter((s) => s.extraction_status === "extracted").length
  const fallback = sources.filter((s) => s.extraction_status === "snippet_only" || s.extraction_status === "failed").length
  const criticIssues = (latestCritic?.data.issues as CriticIssue[] | undefined) ?? []
  const subquestions = detail.plan?.subquestions ?? []
  const sourcesPerSubq = (id: string) => sources.filter((s) => s.subquestion_ids.includes(id)).length

  return (
    <div className="grid gap-8 lg:grid-cols-[16rem_minmax(0,1fr)_20rem] 2xl:grid-cols-[19rem_minmax(0,1fr)_26rem]">
      <section aria-labelledby="stages-heading">
        <h2 id="stages-heading" className="mb-4 text-sm font-medium text-muted-foreground">
          Workflow
        </h2>
        <WorkflowTimeline events={events} status={detail.status} revisionCount={detail.revision_count} />
      </section>

      <div className="min-w-0 space-y-8">
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-4">
          <Metric label="Searches run" value={searches || detail.usage.search_calls} />
          <Metric label="Sources found" value={sources.length} />
          <Metric label="Pages extracted" value={extracted} />
          <Metric label="Fallback to snippet" value={fallback} />
        </dl>

        <section aria-labelledby="plan-heading" className="space-y-3">
          <h2 id="plan-heading" className="text-sm font-medium text-muted-foreground">
            Research plan
          </h2>
          {detail.plan ? (
            <>
              <p className="font-serif text-[1.0625rem] leading-relaxed">{detail.plan.objective}</p>
              <ol className="space-y-2">
                {subquestions.map((sq) => (
                  <li key={sq.id} className="flex gap-3 rounded-lg border bg-card p-3">
                    <span className="font-mono text-xs text-muted-foreground">{sq.id}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm">{sq.question}</p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {sq.search_queries.map((q) => `“${q}”`).join(" · ")}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{sourcesPerSubq(sq.id)} src</span>
                  </li>
                ))}
              </ol>
            </>
          ) : isTerminal(detail.status) ? (
            <p className="text-sm text-muted-foreground">No plan was produced.</p>
          ) : (
            <div className="space-y-2">
              <Skeleton className="h-5 w-3/4" />
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          )}
        </section>

        {criticCount > 0 && (
          <section aria-labelledby="critic-heading" className="space-y-3">
            <h2 id="critic-heading" className="text-sm font-medium text-muted-foreground">
              Critic feedback{criticCount > 1 ? ` (pass ${criticCount})` : ""}
            </h2>
            <p className="text-sm">{latestCritic?.message}</p>
            <IssueList issues={criticIssues.filter((i) => i.severity !== "low")} empty="No material issues." />
          </section>
        )}

        {warnings.length > 0 && (
          <Alert className="border-warning/40">
            <AlertTitle>Warnings</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </div>

      <section aria-labelledby="log-heading" className="min-w-0">
        <h2 id="log-heading" className="mb-4 text-sm font-medium text-muted-foreground">
          Activity
        </h2>
        <ScrollArea className="h-[28rem] rounded-xl border bg-card">
          <ol className="divide-y text-sm" aria-live="polite">
            {[...events].reverse().map((event) => (
              <li key={event.id} className="flex gap-3 px-3 py-2">
                <time className="shrink-0 pt-px font-mono text-[11px] text-muted-foreground tabular-nums">
                  {new Date(event.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </time>
                <span
                  className={
                    event.type === "warning"
                      ? "text-warning"
                      : event.type === "failed"
                        ? "text-destructive"
                        : event.type === "stage_started"
                          ? "font-medium"
                          : "text-muted-foreground"
                  }
                >
                  {event.message}
                </span>
              </li>
            ))}
            {events.length === 0 && <li className="px-3 py-6 text-center text-muted-foreground">Waiting for events…</li>}
          </ol>
        </ScrollArea>
      </section>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-card p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</dd>
    </div>
  )
}

export function WorkspaceSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1800px] space-y-6 px-4 py-8 sm:px-6 lg:px-10" aria-busy="true" aria-label="Loading research">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-9 w-80" />
      <div className="grid gap-8 lg:grid-cols-[16rem_1fr_20rem] 2xl:grid-cols-[19rem_1fr_26rem]">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  )
}
