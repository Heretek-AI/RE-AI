import { Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import type { ToolCall } from '@/hooks/useChatWebSocket'
import { cn } from '@/lib/utils'

interface ToolCallCardProps {
  toolCall: ToolCall
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [argsOpen, setArgsOpen] = useState(false)
  const [resultOpen, setResultOpen] = useState(false)

  return (
    <div className="my-2 rounded-md border bg-muted/30 text-sm">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-3 py-2">
        {toolCall.executing ? (
          <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
        ) : (
          <div
            className={cn(
              'size-2 rounded-full',
              toolCall.result
                ? 'bg-green-500'
                : 'bg-yellow-500',
            )}
          />
        )}
        <span className="font-mono text-xs font-medium">
          {toolCall.name}
        </span>
      </div>

      {/* Arguments (collapsible) */}
      <div className="border-b">
        <button
          type="button"
          onClick={() => setArgsOpen(!argsOpen)}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/50"
        >
          {argsOpen ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )}
          Arguments
        </button>
        {argsOpen && (
          <pre className="overflow-x-auto px-3 pb-2 text-xs text-muted-foreground">
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>
        )}
      </div>

      {/* Result (collapsible) */}
      {toolCall.result && (
        <div>
          <button
            type="button"
            onClick={() => setResultOpen(!resultOpen)}
            className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/50"
          >
            {resultOpen ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
            Result
          </button>
          {resultOpen && (
            <pre className="overflow-x-auto whitespace-pre-wrap px-3 pb-2 text-xs text-muted-foreground">
              {toolCall.result}
            </pre>
          )}
        </div>
      )}

      {/* Loading indicator when still executing */}
      {toolCall.executing && (
        <div className="px-3 pb-2 pt-1 text-xs text-muted-foreground">
          Executing...
        </div>
      )}
    </div>
  )
}
