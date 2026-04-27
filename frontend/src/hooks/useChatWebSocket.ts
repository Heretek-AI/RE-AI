'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: string
  executing: boolean
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  streaming: boolean
  toolCalls: ToolCall[]
}

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

interface UseChatWebSocketReturn {
  messages: ChatMessage[]
  connectionStatus: ConnectionStatus
  sendMessage: (content: string) => void
  clearConversation: () => void
}

const CHAT_WS_URL = '/ws/chat'

let nextMessageId = 1

function createMessage(role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id: nextMessageId++,
    role,
    content,
    streaming: role === 'assistant',
    toolCalls: [],
  }
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useChatWebSocket(): UseChatWebSocketReturn {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
    }

    setConnectionStatus('connecting')
    const ws = new WebSocket(CHAT_WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnectionStatus('connected')
    }

    ws.onmessage = (event: MessageEvent) => {
      let data: Record<string, unknown>
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }

      const eventType = data.type as string | undefined

      setMessages((prev) => {
        const next = [...prev]

        switch (eventType) {
          case 'agent:delta': {
            const chunk = data.content as string
            const last = next[next.length - 1]

            // If the last message belongs to the assistant and is streaming, append
            if (last && last.role === 'assistant' && last.streaming) {
              next[next.length - 1] = {
                ...last,
                content: last.content + chunk,
              }
            } else {
              // First delta — create a new assistant message
              next.push(createMessage('assistant', chunk))
            }
            return next
          }

          case 'agent:tool_call': {
            const tc: ToolCall = {
              id: (data.id ?? '') as string,
              name: (data.name ?? '') as string,
              arguments: (data.arguments ?? {}) as Record<string, unknown>,
              executing: true,
            }
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                toolCalls: [...last.toolCalls, tc],
              }
            } else {
              // Tool call without preceding message — create placeholder
              const msg = createMessage('assistant', '')
              msg.toolCalls = [tc]
              next.push(msg)
            }
            return next
          }

          case 'agent:tool_result': {
            const tcId = data.id as string
            const result = data.result as string
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                toolCalls: last.toolCalls.map((tc) =>
                  tc.id === tcId
                    ? { ...tc, result, executing: false }
                    : tc,
                ),
              }
            }
            return next
          }

          case 'agent:done': {
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                streaming: false,
              }
            }
            return next
          }

          case 'agent:error': {
            const errMsg = (data.message ?? 'An unknown error occurred') as string
            const last = next[next.length - 1]
            if (last && last.role === 'assistant' && last.streaming) {
              // Append error to the streaming message
              next[next.length - 1] = {
                ...last,
                content: last.content + `\n\n**Error:** ${errMsg}`,
                streaming: false,
              }
            } else {
              // Create a standalone error message
              next.push(createMessage('assistant', `**Error:** ${errMsg}`))
            }
            return next
          }

          default:
            return prev
        }
      })
    }

    ws.onclose = () => {
      setConnectionStatus('disconnected')
      wsRef.current = null

      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  const sendMessage = useCallback((content: string) => {
    if (!content.trim()) return

    setMessages((prev) => [...prev, createMessage('user', content.trim())])

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: 'chat:message', content: content.trim() }),
      )
    }
  }, [])

  const clearConversation = useCallback(() => {
    setMessages([])
    nextMessageId = 1
  }, [])

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

  return {
    messages,
    connectionStatus,
    sendMessage,
    clearConversation,
  }
}
