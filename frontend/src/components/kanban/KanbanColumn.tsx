'use client'

import { useDroppable } from '@dnd-kit/react'
import * as React from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface KanbanColumnProps {
  id: string
  title: string
  count: number
  status: string
  children: React.ReactNode
  onAddItem?: () => void
}

const statusBorderColors: Record<string, string> = {
  backlog: 'border-t-blue-500',
  in_progress: 'border-t-yellow-500',
  done: 'border-t-green-500',
  errored: 'border-t-red-500',
}

const statusBgColors: Record<string, string> = {
  backlog: 'bg-blue-50/50 dark:bg-blue-950/10',
  in_progress: 'bg-yellow-50/50 dark:bg-yellow-950/10',
  done: 'bg-green-50/50 dark:bg-green-950/10',
  errored: 'bg-red-50/50 dark:bg-red-950/10',
}

export function KanbanColumn({
  id,
  title,
  count,
  status,
  children,
  onAddItem,
}: KanbanColumnProps) {
  const { ref, isDropTarget } = useDroppable({
    id,
    type: 'column',
    accept: 'task',
  })

  return (
    <Card
      ref={ref}
      data-slot="kanban-column"
      data-column-status={status}
      data-drop-target={isDropTarget ? 'true' : undefined}
      className={cn(
        'flex min-h-48 w-72 shrink-0 flex-col border-t-2 transition-colors',
        statusBorderColors[status] ?? 'border-t-gray-300',
        isDropTarget && (statusBgColors[status] ?? 'bg-accent/50'),
      )}
    >
      <CardHeader className="flex flex-row items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <Badge variant="secondary" className="size-5 rounded-full p-0 text-xs tabular-nums">
            {count}
          </Badge>
        </div>
        {onAddItem && (
          <button
            type="button"
            onClick={onAddItem}
            className="text-muted-foreground hover:text-foreground -mr-1 flex size-5 items-center justify-center rounded-full text-lg leading-none transition-colors"
            aria-label={`Add item to ${title}`}
          >
            +
          </button>
        )}
      </CardHeader>
      <CardContent
        data-slot="kanban-column-content"
        className={cn(
          'flex flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3',
          // Minimum height when empty so droppable area is accessible
          React.Children.count(children) === 0 && 'min-h-24',
        )}
      >
        {children}
      </CardContent>
    </Card>
  )
}
