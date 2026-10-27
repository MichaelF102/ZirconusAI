import Link from "next/link"

import { ThemeToggle } from "@/components/theme-toggle"

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-14 max-w-[1800px] items-center justify-between px-4 sm:px-6 lg:px-10">
        <Link href="/" className="flex items-center gap-2.5 font-medium tracking-tight">
          <span
            aria-hidden
            className="grid size-7 place-items-center rounded-md bg-primary font-serif text-sm text-primary-foreground"
          >
            Z
          </span>
          <span>ZirconusAI</span>
        </Link>
        <nav className="flex items-center gap-1">
          <Link
            href="/"
            className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            New research
          </Link>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  )
}
