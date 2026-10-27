import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }))

import { ResearchForm } from "@/components/research-form"
import { ApiError, api } from "@/lib/api"

describe("ResearchForm", () => {
  beforeEach(() => push.mockReset())

  it("shows a validation error and does not submit short questions", async () => {
    const create = vi.spyOn(api, "createResearch")
    render(<ResearchForm />)
    await userEvent.type(screen.getByLabelText("Research question"), "too short")
    await userEvent.click(screen.getByRole("button", { name: /start research/i }))
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 10 characters")
    expect(create).not.toHaveBeenCalled()
  })

  it("submits a valid question with the chosen depth and navigates to the workspace", async () => {
    const create = vi.spyOn(api, "createResearch").mockResolvedValue({ id: "abc", status: "queued" })
    render(<ResearchForm />)
    await userEvent.type(screen.getByLabelText("Research question"), "How is agentic AI changing data engineering?")
    await userEvent.click(screen.getByRole("radio", { name: "Deep" }))
    await userEvent.click(screen.getByRole("button", { name: /start research/i }))
    await waitFor(() => expect(push).toHaveBeenCalledWith("/research/abc"))
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ question: "How is agentic AI changing data engineering?", depth: "deep" }),
    )
  })

  it("prevents duplicate submissions while a request is in flight", async () => {
    let resolve!: (v: { id: string; status: string }) => void
    const create = vi.spyOn(api, "createResearch").mockReturnValue(new Promise((r) => (resolve = r)))
    render(<ResearchForm />)
    await userEvent.type(screen.getByLabelText("Research question"), "How is agentic AI changing data engineering?")
    const button = screen.getByRole("button", { name: /start research/i })
    await userEvent.click(button)
    expect(screen.getByRole("button", { name: /starting/i })).toBeDisabled()
    await userEvent.keyboard("{Control>}{Enter}{/Control}")
    expect(create).toHaveBeenCalledTimes(1)
    resolve({ id: "x", status: "queued" })
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1))
  })

  it("shows meaningful backend errors", async () => {
    vi.spyOn(api, "createResearch").mockRejectedValue(
      new ApiError("The research backend is not configured: missing GEMINI_API_KEY.", 503),
    )
    render(<ResearchForm />)
    await userEvent.type(screen.getByLabelText("Research question"), "How is agentic AI changing data engineering?")
    await userEvent.click(screen.getByRole("button", { name: /start research/i }))
    expect(await screen.findByText(/missing GEMINI_API_KEY/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /start research/i })).toBeEnabled()
  })
})
