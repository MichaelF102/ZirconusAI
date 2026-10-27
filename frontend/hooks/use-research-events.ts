"use client"

import { useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { ProgressEvent } from "@/lib/types"

export type ConnectionState = "idle" | "connecting" | "open" | "reconnecting" | "closed"

interface Options {
  enabled: boolean
  onEvent?: (event: ProgressEvent) => void
  onEnd?: () => void
  onReconnect?: () => void
}

/**
 * Subscribes to the backend SSE stream. Events are persisted server-side, so after a dropped
 * connection we reconnect with `?after=<last id>` (exponential backoff) and receive only what we missed.
 */
export function useResearchEvents(researchId: string, { enabled, onEvent, onEnd, onReconnect }: Options) {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [connection, setConnection] = useState<ConnectionState>("idle")
  const lastId = useRef(0)
  const handlers = useRef({ onEvent, onEnd, onReconnect })

  useEffect(() => {
    handlers.current = { onEvent, onEnd, onReconnect }
  })

  useEffect(() => {
    if (!enabled) return
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    let stopped = false

    const connect = () => {
      setConnection(attempts === 0 ? "connecting" : "reconnecting")
      source = new EventSource(api.eventsUrl(researchId, lastId.current))
      source.onopen = () => {
        if (attempts > 0) handlers.current.onReconnect?.()
        attempts = 0
        setConnection("open")
      }
      source.addEventListener("progress", (message) => {
        let event: ProgressEvent
        try {
          event = JSON.parse((message as MessageEvent<string>).data)
        } catch {
          return
        }
        if (event.id <= lastId.current) return
        lastId.current = event.id
        setEvents((prev) => [...prev, event])
        handlers.current.onEvent?.(event)
      })
      source.addEventListener("end", () => {
        stopped = true
        source?.close()
        setConnection("closed")
        handlers.current.onEnd?.()
      })
      source.onerror = () => {
        source?.close()
        if (stopped) return
        attempts += 1
        setConnection("reconnecting")
        timer = setTimeout(connect, Math.min(15000, 1000 * 2 ** Math.min(attempts, 4)))
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      source?.close()
    }
  }, [researchId, enabled])

  return { events, connection }
}
