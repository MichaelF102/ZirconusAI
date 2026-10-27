import { AlertTriangleIcon, BanIcon, CheckCircle2Icon, CircleDashedIcon, Loader2Icon, XCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { STATUS_LABEL } from "@/lib/research"
import type { ResearchStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const STYLES: Record<ResearchStatus, string> = {
  queued: "border-border bg-muted text-muted-foreground",
  running: "border-info/30 bg-info/10 text-info",
  completed: "border-success/30 bg-success/10 text-success",
  completed_with_warnings: "border-warning/30 bg-warning/10 text-warning",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
  cancelled: "border-border bg-muted text-muted-foreground",
}

const ICONS: Record<ResearchStatus, React.ComponentType<{ className?: string }>> = {
  queued: CircleDashedIcon,
  running: Loader2Icon,
  completed: CheckCircle2Icon,
  completed_with_warnings: AlertTriangleIcon,
  failed: XCircleIcon,
  cancelled: BanIcon,
}

export function StatusBadge({ status, className }: { status: ResearchStatus; className?: string }) {
  const Icon = ICONS[status]
  return (
    <Badge variant="outline" className={cn("gap-1 font-medium", STYLES[status], className)}>
      <Icon className={cn("size-3", status === "running" && "animate-spin")} />
      {STATUS_LABEL[status]}
    </Badge>
  )
}
