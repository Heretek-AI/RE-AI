'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected'

interface UseWebSocketReturn {
  status: WebSocketStatus
  lastMessage: unknown | null
  send: (data: unknown) => void
  reconnect: () => void
}

export function useWebSocket(
  url: string = '/ws',
): UseWebSocketReturn {
  const [status, setStatus] = useState<WebSocketStatus>('disconnected')
  const [lastMessage, setLastMessage] = useState<unknown | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close()
    }

    setStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data)
        setLastMessage(parsed)
      } catch {
        setLastMessage({ text: event.data })
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      wsRef.current = null
      // Auto-reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 3000)
    }

    ws.onerror = () => {
      // onclose will fire after onerror, so state update happens there
      ws.close()
    }
  }, [url])

  const send = useCallback(
    (data: unknown) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          typeof data === 'string' ? data : JSON.stringify(data),
        )
      }
    },
    [],
  )

  const reconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    connect()
  }, [connect])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  return { status, lastMessage, send, reconnect }
}
