import { ResearchForm } from "@/components/research-form"
import { ResearchHistory } from "@/components/research-history"

export default function HomePage() {
  return (
    <div className="mx-auto grid w-full max-w-[1800px] gap-14 px-4 py-12 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1fr)_24rem] lg:px-10 2xl:grid-cols-[minmax(0,1fr)_30rem]">
      <div className="min-w-0">
        <div className="mb-8 space-y-3">
          <h1 className="font-serif text-3xl tracking-tight sm:text-4xl">What should ZirconusAI research?</h1>
          <p className="max-w-2xl text-muted-foreground">
            ZirconusAI plans subquestions, searches the web, compares evidence across sources and writes a report in
            which every citation resolves to a retrieved source. A critic checks the draft before you see it.
          </p>
        </div>
        <ResearchForm />
      </div>
      <div className="min-w-0 lg:pt-2">
        <ResearchHistory />
      </div>
    </div>
  )
}
