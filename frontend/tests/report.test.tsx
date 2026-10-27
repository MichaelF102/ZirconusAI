import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }))

import { EvidencePanel } from "@/components/evidence-panel"
import { QualityPanel } from "@/components/quality-panel"
import { ReportViewer } from "@/components/report-viewer"
import { SourceContext } from "@/components/source-context"
import { WorkflowTimeline } from "@/components/workflow-timeline"

import { REPORT, SOURCES, event } from "./fixtures"

function renderReport(showSource = vi.fn()) {
  render(
    <SourceContext.Provider value={{ sources: new Map(SOURCES.map((s) => [s.source_id, s])), showSource }}>
      <ReportViewer report={REPORT} />
    </SourceContext.Provider>,
  )
  return showSource
}

describe("ReportViewer", () => {
  it("renders the report with inline citations and references from source records", () => {
    renderReport()
    expect(screen.getByRole("heading", { level: 2, name: REPORT.title })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /Source S1/ })).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: /Source S2/ })).toHaveLength(2)
    const refs = screen.getByRole("heading", { name: "References" }).parentElement!
    expect(within(refs).getByRole("link", { name: /LangGraph persistence/ })).toHaveAttribute(
      "href",
      "https://docs.langchain.com/langgraph/persistence",
    )
    expect(within(refs).getByText(/snippet only/)).toBeInTheDocument()
    // The model-written references section is not rendered twice.
    expect(screen.queryByText("**[S1]**")).not.toBeInTheDocument()
  })

  it("opens a citation popover and navigates to source details", async () => {
    const showSource = renderReport()
    await userEvent.click(screen.getAllByRole("button", { name: /Source S1/ })[0])
    expect(await screen.findByText(/implemented through checkpointers/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: /details/i }))
    expect(showSource).toHaveBeenCalledWith("S1")
  })

  it("opens external links in a new tab safely and builds a TOC", () => {
    renderReport()
    const link = screen.getByRole("link", { name: "docs" })
    expect(link).toHaveAttribute("target", "_blank")
    expect(link.getAttribute("rel")).toContain("noopener")
    const toc = screen.getByRole("navigation", { name: "Table of contents" })
    expect(within(toc).getByRole("link", { name: "Key findings" })).toHaveAttribute("href", "#key-findings")
  })
})

describe("EvidencePanel", () => {
  it("groups claims by subquestion and links citations inside conflict notes", () => {
    render(
      <SourceContext.Provider value={{ sources: new Map(SOURCES.map((s) => [s.source_id, s])), showSource: vi.fn() }}>
        <EvidencePanel evidence={REPORT.evidence_matrix!} plan={REPORT.plan} />
      </SourceContext.Provider>,
    )
    expect(screen.getByText("Checkpointers persist graph state.")).toBeInTheDocument()
    expect(screen.getByText("No grounded claims for this subquestion.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Source S2/ })).toBeInTheDocument()
    expect(screen.queryByText(/\[S2\]/)).not.toBeInTheDocument()
  })
})

describe("QualityPanel", () => {
  it("shows warnings, coverage gaps and critic issues", () => {
    render(<QualityPanel report={REPORT} plan={REPORT.plan} usage={null} />)
    expect(screen.getByText("Passed with warnings")).toBeInTheDocument()
    expect(screen.getByText(/revision limit/)).toBeInTheDocument()
    expect(screen.getByText("100%")).toBeInTheDocument()
    expect(screen.getByText("Snippet-only source.")).toBeInTheDocument()
    expect(screen.getByText("automated check")).toBeInTheDocument()
  })
})

describe("WorkflowTimeline", () => {
  it("renders stage states from events", () => {
    render(
      <WorkflowTimeline
        events={[event("stage_started", "planner"), event("stage_started", "researcher")]}
        status="running"
        revisionCount={1}
      />,
    )
    const items = screen.getAllByRole("listitem")
    expect(items[0]).toHaveAttribute("data-state", "done")
    expect(items[1]).toHaveAttribute("data-state", "active")
    expect(items[2]).toHaveAttribute("data-state", "pending")
    expect(screen.getByText(/1 revision cycle triggered/)).toBeInTheDocument()
  })
})
