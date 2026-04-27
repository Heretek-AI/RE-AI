'use client'

import { useSortable } from '@dnd-kit/react/sortable'
import { ChevronDown, ChevronRight } from 'lucide-react'
import * as React from 'react'

import {
  Badge,
  statusToBadgeVariant,
} from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { Slice as SliceType, Task } from '@/hooks/useKanbanData'

import { TaskCard } from './TaskCard'

interface SliceCardProps {
  slice: SliceType
  tasks: Task[]
  defaultExpanded?: boolean
  index: number
}

export function SliceCard({
  slice,
  tasks,
  defaultExpanded = false,
  index,
}: SliceCardProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded)
  const { ref, isDragging, isDragSource } = useSortable({
    id: `slice-${slice.id}`,
    index,
    group: `milestone-${slice.milestone_id}`,
    type: 'slice',
    accept: 'slice',
  })

  return (
    <div
      ref={ref}
      data-slot="slice-card"
      data-slice-id={slice.id}
      data-dragging={isDragging || isDragSource ? 'true' : undefined}
      className={cn(
        'rounded-lg border bg-card shadow-xs transition-shadow',
        (isDragging || isDragSource) && 'opacity-50 shadow-lg',
      )}
    >
      {/* Header (always visible) */}
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {expanded ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="flex-1 text-sm font-medium leading-tight">
          {slice.title}
        </span>
        <Badge
          variant={statusToBadgeVariant(slice.status)}
          className="shrink-0 text-[10px]"
        >
          {slice.status.replace('_', ' ')}
        </Badge>
        <Badge variant="outline" className="shrink-0 text-[10px] tabular-nums">
          {tasks.length}
        </Badge>
      </button>

      {/* Expanded task list */}
      {expanded && tasks.length > 0 && (
        <div className="flex flex-col gap-1.5 border-t px-3 py-2">
          {tasks.map((task, taskIndex) => (
            <TaskCard key={task.id} task={task} index={taskIndex} />
          ))}
        </div>
      )}
      {expanded && tasks.length === 0 && (
        <p className="border-t px-3 py-2 text-xs text-muted-foreground">
          No tasks in this slice
        </p>
      )}
    </div>
  )
}
