import { z } from "zod"

const DOMAIN_RE = /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/

export function parseDomains(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,]+/)
        .map((d) =>
          d
            .trim()
            .toLowerCase()
            .replace(/^https?:\/\//, "")
            .split("/")[0]
            .replace(/^www\./, ""),
        )
        .filter(Boolean),
    ),
  )
}

const domainList = z
  .string()
  .transform(parseDomains)
  .refine((ds) => ds.length <= 10, "Use at most 10 domains")
  .refine((ds) => ds.every((d) => DOMAIN_RE.test(d)), "Enter valid domains such as nature.com")

export const researchFormSchema = z
  .object({
    question: z
      .string()
      .trim()
      .min(10, "Ask a question of at least 10 characters")
      .max(500, "Keep the question under 500 characters")
      .refine((q) => (q.match(/[A-Za-z]/g) ?? []).length >= 5, "The question must contain words"),
    depth: z.enum(["quick", "standard", "deep"]),
    includeDomains: domainList,
    excludeDomains: domainList,
    startDate: z.string(),
    endDate: z.string(),
  })
  .refine((v) => !v.startDate || !v.endDate || v.startDate <= v.endDate, {
    message: "Start date must be before end date",
    path: ["endDate"],
  })

export type ResearchFormInput = z.input<typeof researchFormSchema>
export type ResearchFormValues = z.output<typeof researchFormSchema>
