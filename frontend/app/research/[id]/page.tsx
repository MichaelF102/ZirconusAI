import { Suspense } from "react"

import { ResearchWorkspace, WorkspaceSkeleton } from "@/components/research-workspace"

export default function ResearchPage({ params }: PageProps<"/research/[id]">) {
  return (
    <Suspense fallback={<WorkspaceSkeleton />}>
      <Workspace params={params} />
    </Suspense>
  )
}

async function Workspace({ params }: { params: PageProps<"/research/[id]">["params"] }) {
  const { id } = await params
  return <ResearchWorkspace key={id} researchId={id} />
}
