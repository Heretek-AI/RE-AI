import { ArrowUp, Loader2, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useChatWebSocket, type ConnectionStatus } from '@/hooks/useChatWebSocket'
import { cn } from '@/lib/utils'

import { ChatMessage } from '@/components/chat/ChatMessage'

const SUGGESTED_PROMPTS = [
  'What tools do you have available?',
  'Create a new milestone called "Analysis v2"',
]

const statusConfig: Record<
  ConnectionStatus,
  { color: string; label: string }
> = {
  connected: { color: 'bg-green-500', label: 'Connected' },
  connecting: { color: 'bg-yellow-500', label: 'Connecting...' },
  disconnected: { color: 'bg-red-500', label: 'Disconnected' },
}

export function ChatPage() {
  const { messages, connectionStatus, sendMessage, clearConversation } =
    useChatWebSocket()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isStreaming = messages.some((m) => m.streaming)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (ta) {
      ta.style.height = 'auto'
      ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`
    }
  }, [input])

  const handleSend = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming || connectionStatus !== 'connected') return
    sendMessage(trimmed)
    setInput('')
  }, [input, isStreaming, connectionStatus, sendMessage])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const status = statusConfig[connectionStatus]

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold tracking-tight">Chat</h1>
          <span
            className={cn(
              'inline-block size-2 rounded-full',
              status.color,
              connectionStatus === 'connecting' && 'animate-pulse',
            )}
            title={status.label}
          />
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearConversation}
              title="Clear conversation"
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          /* Empty state */
          <div className="flex h-full flex-col items-center justify-center gap-6">
            <div className="text-center">
              <h2 className="mb-2 text-xl font-semibold tracking-tight">
                How can I help you?
              </h2>
              <p className="text-sm text-muted-foreground">
                Ask me to analyze files, execute commands, or manage your kanban board.
              </p>
            </div>
            <div className="flex flex-col gap-2">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => {
                    sendMessage(prompt)
                  }}
                  disabled={connectionStatus !== 'connected'}
                  className="rounded-md border bg-card px-4 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Message list */
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t bg-background px-4 py-3">
        {connectionStatus === 'disconnected' && (
          <p className="mb-2 text-center text-xs text-destructive">
            Disconnected from server. Reconnecting...
          </p>
        )}
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              rows={1}
              disabled={connectionStatus !== 'connected'}
              className="min-h-[40px] w-full resize-none rounded-lg border bg-background px-3 py-2.5 pr-10 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            />
          </div>
          <Button
            size="icon"
            onClick={handleSend}
            disabled={
              !input.trim() || isStreaming || connectionStatus !== 'connected'
            }
            className="shrink-0"
          >
            {isStreaming ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowUp className="size-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
