"use client"

import { AlertTriangleIcon, HelpCircleIcon } from "lucide-react"

import { CitationLink } from "@/components/citation-link"
import { Badge } from "@/components/ui/badge"
import type { EvidenceClaim, EvidenceMatrix, ResearchPlan } from "@/lib/types"
import { cn } from "@/lib/utils"

const ASSESSMENT_STYLE: Record<EvidenceClaim["assessment"], string> = {
  established: "border-success/30 bg-success/10 text-success",
  reported: "border-info/30 bg-info/10 text-info",
  estimate: "border-border text-muted-foreground",
  interpretation: "border-border text-muted-foreground",
  contested: "border-warning/30 bg-warning/10 text-warning",
  uncertain: "border-warning/30 bg-warning/10 text-warning",
}

export function EvidencePanel({ evidence, plan }: { evidence: EvidenceMatrix; plan: ResearchPlan | null }) {
  const groups = (plan?.subquestions ?? []).map((sq) => ({
    id: sq.id,
    question: sq.question,
    claims: evidence.claims.filter((c) => c.subquestion_id === sq.id),
  }))
  const ungrouped = evidence.claims.filter((c) => !groups.some((g) => g.id === c.subquestion_id))
  if (ungrouped.length) groups.push({ id: "other", question: "Other findings", claims: ungrouped })

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-10">
        <p className="text-sm text-muted-foreground">
          {evidence.claims.length} claims grounded in retrieved sources. Assessments are the analyst model&apos;s
          categorisation, not calibrated probabilities.
          {evidence.dropped_claims > 0 &&
            ` ${evidence.dropped_claims} claim(s) were discarded because they cited sources that were never retrieved.`}
        </p>
        {groups.map((group) => (
          <section key={group.id} className="space-y-3">
            <h3 className="flex gap-2 text-base font-semibold tracking-tight">
              <span className="font-mono text-sm font-normal text-muted-foreground">{group.id !== "other" && group.id}</span>
              {group.question}
            </h3>
            {group.claims.length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                No grounded claims for this subquestion.
              </p>
            ) : (
              <ul className="space-y-3">
                {group.claims.map((claim) => (
                  <ClaimCard key={claim.claim_id} claim={claim} />
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      <aside className="space-y-6">
        <SideList
          icon={<AlertTriangleIcon className="size-4 text-warning" />}
          title="Conflicts between sources"
          items={evidence.conflicts}
          empty="No conflicting evidence was identified."
        />
        <SideList
          icon={<HelpCircleIcon className="size-4 text-muted-foreground" />}
          title="Evidence gaps"
          items={evidence.gaps}
          empty="No gaps were reported."
        />
      </aside>
    </div>
  )
}

function ClaimCard({ claim }: { claim: EvidenceClaim }) {
  return (
    <li className="rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-serif text-[0.975rem] leading-relaxed">
          {claim.claim_text}{" "}
          {claim.source_ids.map((id) => (
            <CitationLink key={id} sourceId={id} />
          ))}
        </p>
        <Badge variant="outline" className={cn("shrink-0 font-normal capitalize", ASSESSMENT_STYLE[claim.assessment])}>
          {claim.assessment}
        </Badge>
      </div>
      {claim.supporting_evidence.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {claim.supporting_evidence.map((quote, i) => (
            <blockquote key={i} className="border-l-2 border-success/40 pl-3 text-sm text-muted-foreground">
              “{quote}”
            </blockquote>
          ))}
        </div>
      )}
      {claim.contradicting_evidence.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {claim.contradicting_evidence.map((c, i) => (
            <p key={i} className="border-l-2 border-warning/50 pl-3 text-sm">
              <span className="text-warning">Disputed by</span> <CitationLink sourceId={c.source_id} />: {c.text}
            </p>
          ))}
        </div>
      )}
      {claim.limitations && <p className="mt-3 text-xs text-muted-foreground">Limitations: {claim.limitations}</p>}
    </li>
  )
}

/** Render free text from the analyst with `[S#]` markers as interactive citations. */
function WithCitations({ text }: { text: string }) {
  const parts = text.split(/(\[\s*S\d+(?:\s*[,;]\s*S\d+)*\s*\])/g)
  return (
    <>
      {parts.map((part, i) =>
        /^\[\s*S\d+/.test(part) ? (
          part.match(/S\d+/g)!.map((id) => <CitationLink key={`${i}-${id}`} sourceId={id} />)
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

function SideList({ icon, title, items, empty }: { icon: React.ReactNode; title: string; items: string[]; empty: string }) {
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        {icon}
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-2 text-sm text-muted-foreground">
          {items.map((item, i) => (
            <li key={i} className="rounded-lg bg-muted/50 p-3">
              <WithCitations text={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
