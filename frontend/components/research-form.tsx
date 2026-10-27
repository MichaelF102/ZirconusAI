"use client"

import { ArrowRightIcon, ChevronDownIcon, Loader2Icon, SlidersHorizontalIcon } from "lucide-react"
import { useRouter } from "next/navigation"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, api } from "@/lib/api"
import { researchFormSchema, type ResearchFormInput } from "@/lib/schemas"
import type { ResearchDepth } from "@/lib/types"
import { cn } from "@/lib/utils"

const DEPTHS: { value: ResearchDepth; label: string; hint: string }[] = [
  { value: "quick", label: "Quick", hint: "3 subquestions, fewer sources" },
  { value: "standard", label: "Standard", hint: "Balanced coverage" },
  { value: "deep", label: "Deep", hint: "More subquestions and searches" },
]

const EXAMPLES = [
  "How is agentic AI changing data engineering?",
  "What does current evidence say about GLP-1 drugs for long-term weight management?",
  "How do Server-Sent Events compare with WebSockets for streaming updates?",
]

type FieldErrors = Partial<Record<keyof ResearchFormInput, string>>

const INITIAL: ResearchFormInput = {
  question: "",
  depth: "standard",
  includeDomains: "",
  excludeDomains: "",
  startDate: "",
  endDate: "",
}

export function ResearchForm({ onCreated }: { onCreated?: (id: string) => void }) {
  const router = useRouter()
  const [values, setValues] = useState<ResearchFormInput>(INITIAL)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const inFlight = useRef(false)

  const set = <K extends keyof ResearchFormInput>(key: K, value: ResearchFormInput[K]) => {
    setValues((v) => ({ ...v, [key]: value }))
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }))
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (inFlight.current) return // prevent duplicate submissions
    setSubmitError(null)
    const parsed = researchFormSchema.safeParse(values)
    if (!parsed.success) {
      const fieldErrors: FieldErrors = {}
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as keyof ResearchFormInput
        fieldErrors[key] ??= issue.message
      }
      setErrors(fieldErrors)
      if (fieldErrors.includeDomains || fieldErrors.excludeDomains || fieldErrors.endDate) setSettingsOpen(true)
      return
    }
    inFlight.current = true
    setSubmitting(true)
    try {
      const v = parsed.data
      const created = await api.createResearch({
        question: v.question,
        depth: v.depth,
        include_domains: v.includeDomains,
        exclude_domains: v.excludeDomains,
        start_date: v.startDate || null,
        end_date: v.endDate || null,
      })
      onCreated?.(created.id)
      router.push(`/research/${created.id}`)
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Something went wrong starting the research."
      setSubmitError(message)
      toast.error("Could not start research", { description: message })
      inFlight.current = false
      setSubmitting(false)
    }
  }

  const length = values.question.trim().length

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4" aria-label="Start a research task">
      <div className="rounded-xl border bg-card shadow-xs transition-shadow focus-within:ring-3 focus-within:ring-ring/30">
        <Label htmlFor="question" className="sr-only">
          Research question
        </Label>
        <Textarea
          id="question"
          name="question"
          value={values.question}
          onChange={(e) => set("question", e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit(e)
          }}
          placeholder="What do you want to research?"
          aria-invalid={Boolean(errors.question)}
          aria-describedby={errors.question ? "question-error" : "question-hint"}
          maxLength={500}
          rows={3}
          className="min-h-28 resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:ring-0 md:text-[1.0625rem] dark:bg-transparent"
        />
        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-3 py-2.5">
          <div role="radiogroup" aria-label="Research depth" className="flex rounded-lg bg-muted p-0.5">
            {DEPTHS.map((d) => (
              <button
                key={d.value}
                type="button"
                role="radio"
                aria-checked={values.depth === d.value}
                title={d.hint}
                onClick={() => set("depth", d.value)}
                className={cn(
                  "rounded-md px-3 py-1 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  values.depth === d.value
                    ? "bg-background font-medium text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <span id="question-hint" className="hidden text-xs text-muted-foreground tabular-nums sm:inline">
              {length}/500 · ⌘↵ to start
            </span>
            <Button type="submit" disabled={submitting} className="gap-1.5">
              {submitting ? <Loader2Icon className="animate-spin" /> : null}
              {submitting ? "Starting…" : "Start research"}
              {!submitting && <ArrowRightIcon />}
            </Button>
          </div>
        </div>
      </div>
      {errors.question && (
        <p id="question-error" role="alert" className="text-sm text-destructive">
          {errors.question}
        </p>
      )}

      <Collapsible open={settingsOpen} onOpenChange={setSettingsOpen}>
        <CollapsibleTrigger
          render={
            <Button type="button" variant="ghost" size="sm" className="gap-1.5 px-2 text-muted-foreground" />
          }
        >
          <SlidersHorizontalIcon />
          Source filters
          <ChevronDownIcon className={cn("transition-transform", settingsOpen && "rotate-180")} />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-2 grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2">
            <Field
              id="include"
              label="Only search these domains"
              hint="Comma-separated, e.g. nature.com, who.int"
              error={errors.includeDomains}
            >
              <Input
                id="include"
                value={values.includeDomains}
                onChange={(e) => set("includeDomains", e.target.value)}
                placeholder="nature.com, arxiv.org"
                aria-invalid={Boolean(errors.includeDomains)}
              />
            </Field>
            <Field id="exclude" label="Exclude domains" hint="Skip low-quality or irrelevant sites" error={errors.excludeDomains}>
              <Input
                id="exclude"
                value={values.excludeDomains}
                onChange={(e) => set("excludeDomains", e.target.value)}
                placeholder="pinterest.com"
                aria-invalid={Boolean(errors.excludeDomains)}
              />
            </Field>
            <Field id="start" label="Published after" error={errors.startDate}>
              <Input id="start" type="date" value={values.startDate} onChange={(e) => set("startDate", e.target.value)} />
            </Field>
            <Field id="end" label="Published before" error={errors.endDate}>
              <Input
                id="end"
                type="date"
                value={values.endDate}
                onChange={(e) => set("endDate", e.target.value)}
                aria-invalid={Boolean(errors.endDate)}
              />
            </Field>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {submitError && (
        <Alert variant="destructive">
          <AlertTitle>Research could not be started</AlertTitle>
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      {!values.question && (
        <div className="flex flex-wrap gap-2 pt-1">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => set("question", example)}
              className="rounded-full border px-3 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
            >
              {example}
            </button>
          ))}
        </div>
      )}
    </form>
  )
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
