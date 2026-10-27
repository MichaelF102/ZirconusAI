"use client"

import { CheckCircle2Icon, CircleAlertIcon, CircleXIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import type { CriticIssue, ResearchPlan, ResearchReport, UsageStats } from "@/lib/types"
import { cn } from "@/lib/utils"

const SEVERITY_STYLE = {
  high: "border-destructive/30 bg-destructive/10 text-destructive",
  medium: "border-warning/30 bg-warning/10 text-warning",
  low: "border-border text-muted-foreground",
}

export function IssueList({ issues, empty }: { issues: CriticIssue[]; empty: string }) {
  if (issues.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="space-y-2">
      {issues.map((issue, i) => (
        <li key={i} className="rounded-lg border p-3 text-sm">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className={cn("font-normal capitalize", SEVERITY_STYLE[issue.severity])}>
              {issue.severity}
            </Badge>
            <Badge variant="outline" className="font-normal">
              {issue.type.replaceAll("_", " ")}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {issue.origin === "deterministic" ? "automated check" : "LLM critic"}
            </span>
          </div>
          <p>{issue.description}</p>
          {issue.claim_text && (
            <p className="mt-1.5 border-l-2 pl-3 font-serif text-muted-foreground italic">“{issue.claim_text}”</p>
          )}
          {issue.recommendation && <p className="mt-1.5 text-xs text-muted-foreground">Fix: {issue.recommendation}</p>}
        </li>
      ))}
    </ul>
  )
}

export function QualityPanel({
  report,
  plan,
  usage,
}: {
  report: ResearchReport
  plan: ResearchPlan | null
  usage: UsageStats | null
}) {
  const q = report.quality_assessment
  const validity = q.citation_count ? Math.round((q.valid_citation_count / q.citation_count) * 100) : 100
  const statusInfo = {
    passed: { icon: CheckCircle2Icon, title: "Quality checks passed", tone: "text-success" },
    passed_with_warnings: { icon: CircleAlertIcon, title: "Passed with warnings", tone: "text-warning" },
    failed: { icon: CircleXIcon, title: "Quality checks failed", tone: "text-destructive" },
  }[q.status]
  const StatusIcon = statusInfo.icon

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-8">
        <Alert>
          <StatusIcon className={statusInfo.tone} />
          <AlertTitle>{statusInfo.title}</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {q.notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>

        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
          <Stat label="Citation validity" value={`${validity}%`} hint={`${q.valid_citation_count} of ${q.citation_count}`} />
          <Stat label="Sources cited" value={q.cited_source_count} hint={`${report.sources.length} retrieved`} />
          <Stat label="Distinct domains" value={q.distinct_cited_domains} hint="among cited sources" />
          <Stat label="Revision cycles" value={q.revision_cycles} />
          <Stat label="Uncited factual sentences" value={q.uncited_factual_sentences} />
          <Stat label="Unresolved issues" value={q.unresolved_issues.length} />
        </dl>

        <section className="space-y-3">
          <h3 className="text-sm font-medium">Unresolved issues</h3>
          <IssueList issues={q.unresolved_issues} empty="No medium or high severity issues remain." />
        </section>

        {report.critic && (
          <section className="space-y-3">
            <h3 className="text-sm font-medium">Final critic pass</h3>
            {report.critic.overall_assessment && (
              <p className="text-sm text-muted-foreground">{report.critic.overall_assessment}</p>
            )}
            <IssueList issues={report.critic.issues} empty="The critic raised no issues on the final draft." />
          </section>
        )}
      </div>

      <aside className="space-y-6">
        {plan && (
          <section className="space-y-2">
            <h3 className="text-sm font-medium">Subquestion coverage</h3>
            <ul className="space-y-2">
              {plan.subquestions.map((sq) => {
                const covered = q.subquestion_coverage[sq.id]
                return (
                  <li key={sq.id} className="flex gap-2 text-sm">
                    {covered ? (
                      <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-success" />
                    ) : (
                      <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-warning" />
                    )}
                    <span className={covered ? undefined : "text-muted-foreground"}>{sq.question}</span>
                  </li>
                )
              })}
            </ul>
          </section>
        )}
        {usage && (
          <section className="space-y-2">
            <h3 className="text-sm font-medium">API usage</h3>
            <dl className="space-y-1 text-sm">
              <UsageRow label="LLM calls" value={usage.llm_calls} />
              <UsageRow label="Input tokens" value={usage.input_tokens.toLocaleString()} />
              <UsageRow label="Output tokens" value={usage.output_tokens.toLocaleString()} />
              <UsageRow label="Searches" value={usage.search_calls} />
              <UsageRow label="Pages fetched" value={usage.pages_fetched} />
              <UsageRow label="Fetch failures" value={usage.fetch_failures} />
            </dl>
          </section>
        )}
      </aside>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="bg-card p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  )
}

function UsageRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  )
}
