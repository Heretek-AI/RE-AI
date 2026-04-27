'use client'

import { useSortable } from '@dnd-kit/react/sortable'

import {
  Badge,
  statusToBadgeVariant,
} from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { Task } from '@/hooks/useKanbanData'

interface TaskCardProps {
  task: Task
  index: number
}

export function TaskCard({ task, index }: TaskCardProps) {
  const {
    ref,
    isDragging,
    isDragSource,
    isDropTarget,
  } = useSortable({
    id: task.id.toString(),
    index,
    group: task.status,
    type: 'task',
    accept: 'task',
  })

  return (
    <div
      ref={ref}
      data-slot="task-card"
      data-task-id={task.id}
      data-task-status={task.status}
      data-dragging={isDragging || isDragSource ? 'true' : undefined}
      data-drop-target={isDropTarget ? 'true' : undefined}
      className={cn(
        'cursor-grab rounded-lg border bg-card px-3 py-2 shadow-xs transition-shadow hover:shadow-sm active:cursor-grabbing',
        (isDragging || isDragSource) && 'opacity-50 shadow-lg ring-2 ring-ring',
        isDropTarget && 'ring-2 ring-ring',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium leading-tight">{task.title}</span>
        <Badge
          variant={statusToBadgeVariant(task.status)}
          className="shrink-0 text-[10px]"
        >
          {task.status.replace('_', ' ')}
        </Badge>
      </div>
      {task.description && (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {task.description}
        </p>
      )}
    </div>
  )
}
