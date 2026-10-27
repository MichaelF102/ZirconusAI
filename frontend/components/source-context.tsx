"use client"

import { createContext, useContext } from "react"

import type { SourceRecord } from "@/lib/types"

interface SourceContextValue {
  sources: Map<string, SourceRecord>
  showSource: (sourceId: string) => void
}

export const SourceContext = createContext<SourceContextValue>({
  sources: new Map(),
  showSource: () => {},
})

export const useSources = () => useContext(SourceContext)
