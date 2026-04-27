'use client'

import { useSortable } from '@dnd-kit/react/sortable'
import { ChevronDown, ChevronRight } from 'lucide-react'
import * as React from 'react'

import {
  Badge,
  statusToBadgeVariant,
} from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type {
  Milestone as MilestoneType,
  Slice as SliceType,
  Task,
} from '@/hooks/useKanbanData'

import { SliceCard } from './SliceCard'

interface MilestoneCardProps {
  milestone: MilestoneType
  slices: SliceType[]
  tasks: Task[]
  defaultExpanded?: boolean
  index: number
}

export function MilestoneCard({
  milestone,
  slices,
  tasks,
  defaultExpanded = false,
  index,
}: MilestoneCardProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded)
  const { ref, isDragging, isDragSource } = useSortable({
    id: `milestone-${milestone.id}`,
    index,
    group: 'milestones',
    type: 'milestone',
    accept: 'milestone',
  })

  // Count all tasks across all slices in this milestone
  const sliceIds = new Set(slices.map((s) => s.id))
  const totalTasks = tasks.filter((t) => sliceIds.has(t.slice_id)).length

  return (
    <div
      ref={ref}
      data-slot="milestone-card"
      data-milestone-id={milestone.id}
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
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        {expanded ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="flex-1 text-sm font-semibold leading-tight">
          {milestone.title}
        </span>
        <Badge
          variant={statusToBadgeVariant(milestone.status)}
          className="shrink-0 text-[10px]"
        >
          {milestone.status.replace('_', ' ')}
        </Badge>
        <Badge variant="outline" className="shrink-0 text-[10px] tabular-nums">
          {slices.length} slice{slices.length !== 1 ? 's' : ''}
        </Badge>
        <Badge variant="outline" className="shrink-0 text-[10px] tabular-nums">
          {totalTasks} task{totalTasks !== 1 ? 's' : ''}
        </Badge>
      </button>

      {/* Expanded slice list */}
      {expanded && slices.length > 0 && (
        <div className="flex flex-col gap-2 border-t px-4 py-3">
          {slices.map((slice, sliceIndex) => {
            const sliceTasks = tasks.filter((t) => t.slice_id === slice.id)
            return (
              <SliceCard
                key={slice.id}
                slice={slice}
                tasks={sliceTasks}
                index={sliceIndex}
              />
            )
          })}
        </div>
      )}
      {expanded && slices.length === 0 && (
        <p className="border-t px-4 py-3 text-xs text-muted-foreground">
          No slices in this milestone
        </p>
      )}
    </div>
  )
}
