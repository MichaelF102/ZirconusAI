"use client"

import { CheckIcon, CopyIcon, DownloadIcon, ExternalLinkIcon } from "lucide-react"
import { Children, isValidElement, useMemo, useState } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"

import { CitationLink } from "@/components/citation-link"
import { useSources } from "@/components/source-context"
import { Button } from "@/components/ui/button"
import { CITATION_HREF_PREFIX, extractToc, linkifyCitations, parseCitedIds, slugify, splitReferences } from "@/lib/citations"
import { formatDate } from "@/lib/research"
import type { ResearchReport } from "@/lib/types"

function textOf(node: React.ReactNode): string {
  return Children.toArray(node)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") return String(child)
      if (isValidElement<{ children?: React.ReactNode }>(child)) return textOf(child.props.children)
      return ""
    })
    .join("")
}

const components: Components = {
  // The title is rendered by the viewer header; skip the Markdown H1 to keep one heading per title.
  h1: () => null,
  h2: ({ children }) => <h2 id={slugify(textOf(children))}>{children}</h2>,
  h3: ({ children }) => <h3 id={slugify(textOf(children))}>{children}</h3>,
  a: ({ href, children }) => {
    if (href?.startsWith(CITATION_HREF_PREFIX)) {
      return <CitationLink sourceId={href.slice(CITATION_HREF_PREFIX.length)} />
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    )
  },
}

export function ReportViewer({ report }: { report: ResearchReport }) {
  const { sources } = useSources()
  const [copied, setCopied] = useState(false)

  const { body, toc, citedIds } = useMemo(() => {
    const { body } = splitReferences(report.report_markdown)
    const known = new Set(report.sources.map((s) => s.source_id))
    return { body: linkifyCitations(body, known), toc: extractToc(body), citedIds: parseCitedIds(body) }
  }, [report])

  async function copy() {
    try {
      await navigator.clipboard.writeText(report.report_markdown)
      setCopied(true)
      toast.success("Report copied as Markdown")
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Clipboard access was blocked by the browser")
    }
  }

  function download() {
    const blob = new Blob([report.report_markdown], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${slugify(report.title).slice(0, 60) || "research-report"}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[13rem_minmax(0,1fr)] 2xl:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="hidden lg:block">
        <nav aria-label="Table of contents" className="sticky top-24 space-y-1 text-sm">
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Contents</p>
          {toc.map((entry) => (
            <a
              key={entry.id}
              href={`#${entry.id}`}
              className={
                entry.level === 2
                  ? "block truncate py-0.5 text-muted-foreground hover:text-foreground"
                  : "block truncate py-0.5 pl-3 text-xs text-muted-foreground/80 hover:text-foreground"
              }
            >
              {entry.text}
            </a>
          ))}
          <a href="#references" className="block py-0.5 text-muted-foreground hover:text-foreground">
            References
          </a>
        </nav>
      </aside>

      <article className="min-w-0">
        <header className="mb-8 space-y-4">
          <h2 className="font-serif text-3xl leading-tight tracking-tight text-balance sm:text-4xl">{report.title}</h2>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
            <span>{formatDate(report.completed_at, true)}</span>
            <span>{citedIds.length} sources cited</span>
            <div className="ml-auto flex gap-2">
              <Button variant="outline" size="sm" onClick={copy}>
                {copied ? <CheckIcon /> : <CopyIcon />} Copy
              </Button>
              <Button variant="outline" size="sm" onClick={download}>
                <DownloadIcon /> Markdown
              </Button>
            </div>
          </div>
        </header>

        <div className="report-prose max-w-[100ch]">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {body}
          </ReactMarkdown>
        </div>

        <section id="references" className="mt-12 max-w-[100ch] scroll-mt-24 border-t pt-8">
          <h2 className="mb-4 text-lg font-semibold tracking-tight">References</h2>
          <ol className="space-y-3">
            {citedIds.map((id) => {
              const s = sources.get(id)
              if (!s) return null
              return (
                <li key={id} id={`ref-${id}`} className="flex scroll-mt-24 gap-3 text-sm">
                  <span className="w-8 shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">{id}</span>
                  <div className="min-w-0 space-y-0.5">
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex items-baseline gap-1 font-medium hover:underline"
                    >
                      {s.title}
                      <ExternalLinkIcon className="size-3 shrink-0 translate-y-0.5 text-muted-foreground" />
                    </a>
                    <p className="text-xs text-muted-foreground">
                      {s.domain} · {s.published_at ? `Published ${formatDate(s.published_at)}` : "Publication date not stated"}{" "}
                      · Retrieved {formatDate(s.retrieved_at)}
                      {s.extraction_status !== "extracted" && " · snippet only"}
                    </p>
                  </div>
                </li>
              )
            })}
          </ol>
        </section>
      </article>
    </div>
  )
}
