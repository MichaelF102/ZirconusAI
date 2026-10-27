import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }))
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

import { ResearchWorkspace } from "@/components/research-workspace"
import { ApiError, api } from "@/lib/api"

import { REPORT, SOURCES, makeDetail } from "./fixtures"

type Listener = (e: MessageEvent<string>) => void

class FakeEventSource {
  static instances: FakeEventSource[] = []
  listeners = new Map<string, Listener[]>()
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn])
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners.get(type) ?? []) fn({ data: JSON.stringify(data) } as MessageEvent<string>)
  }
  close() {
    this.closed = true
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

describe("ResearchWorkspace", () => {
  it("streams live progress and loads the report when the stream ends", async () => {
    let detail = makeDetail()
    vi.spyOn(api, "getResearch").mockImplementation(async () => detail)
    vi.spyOn(api, "getSources").mockResolvedValue([])
    const getReport = vi.spyOn(api, "getReport").mockResolvedValue(REPORT)

    render(<ResearchWorkspace researchId="r1" />)
    expect(await screen.findByText("How is agentic AI changing data engineering?")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /stop research/i })).toBeInTheDocument()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const es = FakeEventSource.instances[0]

    es.emit("progress", {
      id: 1, research_id: "r1", type: "stage_started", node: "planner",
      message: "Breaking the question into research subquestions", data: {}, timestamp: "2026-10-26T12:00:00Z",
    })
    expect(await screen.findAllByText("Breaking the question into research subquestions")).not.toHaveLength(0)

    detail = makeDetail({ status: "completed_with_warnings", has_report: true })
    es.emit("end", { status: "completed_with_warnings" })
    await waitFor(() => expect(getReport).toHaveBeenCalledWith("r1"))
    expect(await screen.findByRole("heading", { level: 2, name: REPORT.title })).toBeInTheDocument()
    expect(screen.getByText("Completed with warnings", { selector: "[data-slot=alert-title]" })).toBeInTheDocument()
    expect(es.closed).toBe(true)
  })

  it("reconnects after a dropped stream, resuming after the last event id", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.spyOn(api, "getResearch").mockResolvedValue(makeDetail())
    vi.spyOn(api, "getSources").mockResolvedValue([])
    render(<ResearchWorkspace researchId="r1" />)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const first = FakeEventSource.instances[0]
    first.emit("progress", {
      id: 7, research_id: "r1", type: "queued", node: null, message: "Research task queued", data: {},
      timestamp: "2026-10-26T12:00:00Z",
    })
    first.onerror?.()
    expect(await screen.findByText(/Reconnecting to live updates/)).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(2500)
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2))
    expect(FakeEventSource.instances[1].url).toMatch(/events\?after=7$/)
    vi.useRealTimers()
  })

  it("shows failure details for failed research", async () => {
    vi.spyOn(api, "getResearch").mockResolvedValue(
      makeDetail({ status: "failed", error: "No sources were found. Try broadening the question." }),
    )
    vi.spyOn(api, "getSources").mockResolvedValue(SOURCES)
    render(<ResearchWorkspace researchId="r1" />)
    expect(await screen.findByText("Research failed")).toBeInTheDocument()
    expect(screen.getByText(/No sources were found/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /stop research/i })).not.toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Report" })).toHaveAttribute("aria-disabled", "true")
  })

  it("shows a not-found state for unknown research ids", async () => {
    vi.spyOn(api, "getResearch").mockRejectedValue(new ApiError("Research task not found", 404))
    render(<ResearchWorkspace researchId="missing" />)
    expect(await screen.findByText("Research not found")).toBeInTheDocument()
  })

  it("lets the user navigate from a citation to source details", async () => {
    vi.spyOn(api, "getResearch").mockResolvedValue(makeDetail({ status: "completed", has_report: true }))
    vi.spyOn(api, "getSources").mockResolvedValue(SOURCES)
    vi.spyOn(api, "getReport").mockResolvedValue(REPORT)
    render(<ResearchWorkspace researchId="r1" />)
    const [cite] = await screen.findAllByRole("button", { name: /Source S1/ })
    await userEvent.click(cite)
    await userEvent.click(await screen.findByRole("button", { name: /details/i }))
    expect(await screen.findByRole("dialog")).toHaveTextContent("Claims supported (1)")
  })
})
