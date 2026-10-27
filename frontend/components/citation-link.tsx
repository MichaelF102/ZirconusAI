"use client"

import { ExternalLinkIcon, PanelRightOpenIcon } from "lucide-react"

import { useSources } from "@/components/source-context"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatDate } from "@/lib/research"
import { cn } from "@/lib/utils"

export function CitationLink({ sourceId, className }: { sourceId: string; className?: string }) {
  const { sources, showSource } = useSources()
  const source = sources.get(sourceId)

  if (!source) {
    // Should not happen: the backend strips unresolved citations. Render inertly if it does.
    return (
      <span className="mx-0.5 rounded px-1 text-[0.7em] text-muted-foreground line-through" title="Unknown source">
        {sourceId}
      </span>
    )
  }

  const excerpt = (source.extracted_content || source.snippet).slice(0, 280)

  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={250}
        data-citation={sourceId}
        aria-label={`Source ${sourceId}: ${source.title}`}
        className={cn(
          "mx-[0.1em] inline-flex -translate-y-[0.35em] items-center rounded-[4px] bg-brand/10 px-1 py-px align-baseline font-sans text-[0.68em] leading-none font-semibold text-brand tabular-nums transition-colors outline-none hover:bg-brand hover:text-brand-foreground focus-visible:ring-2 focus-visible:ring-brand/50 data-popup-open:bg-brand data-popup-open:text-brand-foreground",
          className,
        )}
      >
        {sourceId.slice(1)}
      </PopoverTrigger>
      <PopoverContent className="w-80 gap-3 font-sans" side="top">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{sourceId}</span> · {source.domain}
            {source.published_at ? ` · ${formatDate(source.published_at)}` : ""}
          </p>
          <p className="text-sm leading-snug font-medium">{source.title}</p>
        </div>
        {excerpt && (
          <p className="line-clamp-5 text-xs leading-relaxed text-muted-foreground">
            {excerpt}
            {excerpt.length >= 280 ? "…" : ""}
          </p>
        )}
        {source.extraction_status !== "extracted" && (
          <p className="text-xs text-warning">Only a search snippet was available for this source.</p>
        )}
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<a href={source.url} target="_blank" rel="noopener noreferrer" />}
          >
            <ExternalLinkIcon /> Open
          </Button>
          <Button size="sm" variant="ghost" onClick={() => showSource(sourceId)}>
            <PanelRightOpenIcon /> Details
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
