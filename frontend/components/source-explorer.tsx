"use client"

import { ExternalLinkIcon, SearchIcon } from "lucide-react"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate } from "@/lib/research"
import type { EvidenceClaim, ExtractionStatus, SourceRecord } from "@/lib/types"
import { cn } from "@/lib/utils"

const EXTRACTION_LABEL: Record<ExtractionStatus, string> = {
  pending: "Pending",
  extracted: "Full text",
  snippet_only: "Snippet only",
  failed: "Unavailable",
}

const EXTRACTION_STYLE: Record<ExtractionStatus, string> = {
  pending: "text-muted-foreground",
  extracted: "border-success/30 bg-success/10 text-success",
  snippet_only: "border-warning/30 bg-warning/10 text-warning",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
}

const FILTERS: { value: ExtractionStatus | "all" | "cited"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "cited", label: "Cited" },
  { value: "extracted", label: "Full text" },
  { value: "snippet_only", label: "Snippet only" },
  { value: "failed", label: "Unavailable" },
]

export function ExtractionBadge({ status }: { status: ExtractionStatus }) {
  return (
    <Badge variant="outline" className={cn("font-normal", EXTRACTION_STYLE[status])}>
      {EXTRACTION_LABEL[status]}
    </Badge>
  )
}

export function SourceExplorer({
  sources,
  claims,
  citedIds,
  selectedId,
  onSelect,
}: {
  sources: SourceRecord[]
  claims: EvidenceClaim[]
  citedIds: Set<string>
  selectedId: string | null
  onSelect: (id: string | null) => void
}) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["value"]>("all")

  const claimsBySource = useMemo(() => {
    const map = new Map<string, EvidenceClaim[]>()
    for (const claim of claims) {
      for (const id of claim.source_ids) map.set(id, [...(map.get(id) ?? []), claim])
    }
    return map
  }, [claims])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return sources.filter((s) => {
      if (filter === "cited" && !citedIds.has(s.source_id)) return false
      if (filter !== "all" && filter !== "cited" && s.extraction_status !== filter) return false
      if (!q) return true
      return [s.source_id, s.title, s.domain, s.snippet, s.extracted_content].some((f) => f.toLowerCase().includes(q))
    })
  }, [sources, query, filter, citedIds])

  const selected = sources.find((s) => s.source_id === selectedId) ?? null

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative sm:w-80">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, domains and text"
            aria-label="Search sources"
            className="pl-8"
          />
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter sources">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={filter === f.value ? "secondary" : "ghost"}
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">ID</TableHead>
              <TableHead>Source</TableHead>
              <TableHead className="hidden md:table-cell">Published</TableHead>
              <TableHead className="hidden lg:table-cell">Retrieved</TableHead>
              <TableHead>Extraction</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Claims</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((s) => (
              <TableRow
                key={s.source_id}
                onClick={() => onSelect(s.source_id)}
                className="cursor-pointer"
                data-state={s.source_id === selectedId ? "selected" : undefined}
              >
                <TableCell className="font-mono text-xs text-muted-foreground">{s.source_id}</TableCell>
                <TableCell className="max-w-0 w-full">
                  <button
                    type="button"
                    className="block w-full text-left outline-none focus-visible:underline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onSelect(s.source_id)
                    }}
                  >
                    <span className="block truncate font-medium">{s.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {s.domain} · {s.source_type}
                      {citedIds.has(s.source_id) ? " · cited" : ""}
                    </span>
                  </button>
                </TableCell>
                <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                  {s.published_at ? formatDate(s.published_at) : "Not stated"}
                </TableCell>
                <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                  {formatDate(s.retrieved_at)}
                </TableCell>
                <TableCell>
                  <ExtractionBadge status={s.extraction_status} />
                </TableCell>
                <TableCell className="hidden text-right tabular-nums sm:table-cell">
                  {claimsBySource.get(s.source_id)?.length ?? 0}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  {sources.length === 0 ? "No sources have been collected yet." : "No sources match these filters."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        Showing {filtered.length} of {sources.length} sources · {citedIds.size} cited in the report
      </p>

      <Sheet open={selected !== null} onOpenChange={(open) => !open && onSelect(null)}>
        <SheetContent className="w-full gap-0 sm:max-w-xl">
          {selected && <SourceDetail source={selected} claims={claimsBySource.get(selected.source_id) ?? []} />}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function SourceDetail({ source, claims }: { source: SourceRecord; claims: EvidenceClaim[] }) {
  const text = source.extracted_content || source.snippet
  return (
    <>
      <SheetHeader className="border-b pr-12">
        <p className="font-mono text-xs text-muted-foreground">{source.source_id}</p>
        <SheetTitle className="leading-snug">{source.title}</SheetTitle>
        <SheetDescription className="break-all">{source.url}</SheetDescription>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <ExtractionBadge status={source.extraction_status} />
          <Badge variant="outline" className="font-normal capitalize">
            {source.source_type}
          </Badge>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            nativeButton={false}
            render={<a href={source.url} target="_blank" rel="noopener noreferrer nofollow" />}
          >
            <ExternalLinkIcon /> Open source
          </Button>
        </div>
      </SheetHeader>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-6 p-4">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Meta label="Domain" value={source.domain} />
            <Meta label="Published" value={source.published_at ? formatDate(source.published_at) : "Not stated"} />
            <Meta label="Retrieved" value={formatDate(source.retrieved_at, true)} />
            <Meta label="Subquestions" value={source.subquestion_ids.join(", ") || "—"} />
            <Meta label="Found by query" value={source.search_query || "—"} wide />
            {source.extraction_error && <Meta label="Extraction issue" value={source.extraction_error} wide />}
          </dl>

          <section className="space-y-2">
            <h3 className="text-sm font-medium">Claims supported ({claims.length})</h3>
            {claims.length === 0 ? (
              <p className="text-sm text-muted-foreground">No claims in the evidence matrix cite this source.</p>
            ) : (
              <ul className="space-y-3">
                {claims.map((c) => (
                  <li key={c.claim_id} className="rounded-lg border p-3 text-sm">
                    <p>{c.claim_text}</p>
                    {c.supporting_evidence.map((q, i) => (
                      <blockquote key={i} className="mt-2 border-l-2 pl-3 font-serif text-sm text-muted-foreground italic">
                        “{q}”
                      </blockquote>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-medium">
              {source.extraction_status === "extracted" ? "Extracted text" : "Search snippet"}
            </h3>
            {text ? (
              <p className="font-serif text-sm leading-relaxed whitespace-pre-line text-muted-foreground">{text}</p>
            ) : (
              <p className="text-sm text-muted-foreground">No text could be retrieved from this source.</p>
            )}
          </section>
        </div>
      </ScrollArea>
    </>
  )
}

function Meta({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : undefined}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words">{value}</dd>
    </div>
  )
}

