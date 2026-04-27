import Markdown from 'react-markdown'

import type { ChatMessage as ChatMessageType } from '@/hooks/useChatWebSocket'
import { cn } from '@/lib/utils'

import { ToolCallCard } from './ToolCallCard'

interface ChatMessageProps {
  message: ChatMessageType
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div
      className={cn(
        'flex',
        isUser ? 'justify-end' : 'justify-start',
      )}
    >
      <div
        className={cn(
          'flex max-w-[80%] flex-col gap-1',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        {/* Sender label */}
        <span className="px-1 text-xs font-medium text-muted-foreground">
          {isUser ? 'You' : 'RE-AI'}
        </span>

        {/* Message bubble */}
        <div
          className={cn(
            'rounded-lg px-4 py-2.5 text-sm leading-relaxed',
            isUser
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-foreground',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown>{message.content}</Markdown>
              {/* Blinking cursor when streaming */}
              {message.streaming && (
                <span className="inline-block ml-0.5 h-4 w-[2px] animate-pulse bg-foreground align-text-bottom" />
              )}
            </div>
          )}
        </div>

        {/* Tool call cards */}
        {message.toolCalls.length > 0 && (
          <div className={cn('flex flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
            {message.toolCalls.map((tc, i) => (
              <ToolCallCard key={tc.id || i} toolCall={tc} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
