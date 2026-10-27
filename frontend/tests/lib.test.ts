import { describe, expect, it } from "vitest"

import { deriveStages } from "@/components/workflow-timeline"
import { extractToc, linkifyCitations, parseCitedIds, splitReferences } from "@/lib/citations"
import { formatDuration } from "@/lib/research"
import { researchFormSchema } from "@/lib/schemas"

import { event } from "./fixtures"

const base = { depth: "standard", includeDomains: "", excludeDomains: "", startDate: "", endDate: "" } as const

describe("citations", () => {
  it("linkifies grouped citations and drops unknown ids", () => {
    expect(linkifyCitations("A [S1, S2]. B [S9].", new Set(["S1", "S2"]))).toBe(
      "A [S1](#cite-S1) [S2](#cite-S2). B .",
    )
  })

  it("splits the generated references section", () => {
    const { body, references } = splitReferences("# T\n\nText [S1]\n\n## References\n\n- S1")
    expect(body).toBe("# T\n\nText [S1]")
    expect(references).toContain("- S1")
  })

  it("builds a table of contents from h2/h3 headings", () => {
    expect(extractToc("# Title\n\n## Key findings\n\n### Sub *one*\n\n```\n## not a heading\n```")).toEqual([
      { id: "key-findings", text: "Key findings", level: 2 },
      { id: "sub-one", text: "Sub one", level: 3 },
    ])
  })

  it("parses unique cited ids in numeric order", () => {
    expect(parseCitedIds("x [S10] y [S2, S1] z [S2](#cite-S2)")).toEqual(["S1", "S2", "S10"])
  })
})

describe("research form schema", () => {
  it("accepts a valid request and normalises domains", () => {
    const parsed = researchFormSchema.parse({
      ...base,
      question: "  How is agentic AI changing data engineering? ",
      includeDomains: "https://www.Nature.com/articles, arxiv.org nature.com",
    })
    expect(parsed.question).toBe("How is agentic AI changing data engineering?")
    expect(parsed.includeDomains).toEqual(["nature.com", "arxiv.org"])
  })

  it.each([
    [{ question: "short" }, "at least 10"],
    [{ question: "1234567890 ???" }, "must contain words"],
    [{ question: "x".repeat(501) }, "under 500"],
    [{ question: "A valid research question", includeDomains: "not a domain!" }, "valid domains"],
    [{ question: "A valid research question", startDate: "2025-02-01", endDate: "2024-01-01" }, "before end date"],
  ])("rejects %o", (overrides, message) => {
    const result = researchFormSchema.safeParse({ ...base, ...overrides })
    expect(result.success).toBe(false)
    expect(result.error?.issues.map((i) => i.message).join(" ")).toContain(message)
  })
})

describe("deriveStages", () => {
  it("tracks active, done, revisited and skipped stages", () => {
    const events = [
      event("stage_started", "planner"),
      event("plan", "planner", "Planned 3 subquestions"),
      event("stage_started", "researcher"),
      event("stage_started", "extractor"),
      event("stage_started", "analyst"),
      event("stage_started", "writer"),
      event("stage_started", "critic"),
      event("stage_started", "revise"),
      event("stage_started", "writer"),
    ]
    const stages = deriveStages(events, "running")
    const byId = Object.fromEntries(stages.map((s) => [s.id, s]))
    expect(byId.planner.state).toBe("done")
    expect(byId.planner.lastMessage).toBe("Planned 3 subquestions")
    expect(byId.writer.state).toBe("active")
    expect(byId.writer.visits).toBe(2)
    expect(byId.critic.state).toBe("done")
    expect(byId.finalizer.state).toBe("pending")
  })

  it("marks the current stage failed and the rest skipped on failure", () => {
    const stages = deriveStages([event("stage_started", "planner"), event("stage_started", "researcher")], "failed")
    expect(stages.find((s) => s.id === "researcher")?.state).toBe("failed")
    expect(stages.find((s) => s.id === "writer")?.state).toBe("skipped")
  })
})

it("formats durations", () => {
  expect(formatDuration(null)).toBe("—")
  expect(formatDuration(42)).toBe("42s")
  expect(formatDuration(125)).toBe("2m 05s")
})
