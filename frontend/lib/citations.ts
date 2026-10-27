const CITATION_RE = /\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]/g

export const CITATION_HREF_PREFIX = "#cite-"

/** Turn `[S1, S3]` markers into Markdown links (`[S1](#cite-S1)`) so the renderer can attach source details. */
export function linkifyCitations(markdown: string, knownIds?: Set<string>): string {
  return markdown.replace(CITATION_RE, (_match, group: string) => {
    const ids = group.split(/\s*[,;]\s*/).filter((id) => !knownIds || knownIds.has(id))
    if (!ids.length) return ""
    return ids.map((id) => `[${id}](${CITATION_HREF_PREFIX}${id})`).join(" ")
  })
}

/** Split the generated references section off; the UI renders references from source records. */
export function splitReferences(markdown: string): { body: string; references: string | null } {
  const match = /^## References\s*$/m.exec(markdown)
  if (!match) return { body: markdown, references: null }
  return { body: markdown.slice(0, match.index).trimEnd(), references: markdown.slice(match.index) }
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
}

export interface TocEntry {
  id: string
  text: string
  level: 2 | 3
}

export function extractToc(markdown: string): TocEntry[] {
  const entries: TocEntry[] = []
  let inCode = false
  for (const line of markdown.split("\n")) {
    if (line.startsWith("```")) inCode = !inCode
    if (inCode) continue
    const m = /^(##|###)\s+(.+?)\s*$/.exec(line)
    if (m) {
      const text = m[2].replace(/\[(S\d+)\]\([^)]*\)/g, "").replace(/[*_`]/g, "").trim()
      entries.push({ id: slugify(text), text, level: m[1].length as 2 | 3 })
    }
  }
  return entries
}

/** Unique cited source IDs (works on raw `[S1, S2]` markers and linkified `[S1](#cite-S1)`). */
export function parseCitedIds(markdown: string): string[] {
  const ids = new Set<string>()
  for (const m of markdown.matchAll(/\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]/g)) {
    for (const id of m[1].split(/\s*[,;]\s*/)) ids.add(id)
  }
  return [...ids].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
}
