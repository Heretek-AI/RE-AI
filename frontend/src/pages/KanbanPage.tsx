'use client'

import * as React from 'react'
import { DragDropProvider } from '@dnd-kit/react'
import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { CreateEntityDialog } from '@/components/kanban/CreateEntityDialog'
import { KanbanColumn } from '@/components/kanban/KanbanColumn'
import { MilestoneCard } from '@/components/kanban/MilestoneCard'
import { useKanbanData } from '@/hooks/useKanbanData'

const COLUMNS = [
  { id: 'pending', title: 'Backlog', status: 'pending' },
  { id: 'in_progress', title: 'In Progress', status: 'in_progress' },
  { id: 'complete', title: 'Done', status: 'complete' },
  { id: 'errored', title: 'Errored', status: 'errored' },
] as const

export function KanbanPage() {
  const {
    milestones,
    slices,
    tasks,
    loading,
    createMilestone,
    updateTaskStatus,
  } = useKanbanData()

  // ═══ Error toast state for invalid transitions ═══════════════════════════
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const errorTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  function showError(msg: string) {
    setErrorMessage(msg)
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current)
    errorTimeoutRef.current = setTimeout(() => setErrorMessage(null), 4000)
  }

  // ═══ Drag-end handler ═════════════════════════════════════════════════════
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function handleDragEnd(event: { operation: { source: any; target: any } }) {
    const op = event.operation
    const sourceId = op.source?.id
    const targetId = op.target?.id
    if (!sourceId || !targetId) return

    const taskId = Number(sourceId)
    if (Number.isNaN(taskId)) return

    const column = COLUMNS.find((c) => c.id === targetId)
    if (!column) return

    try {
      await updateTaskStatus(taskId, column.status)
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : 'Failed to update task status'
      showError(msg)
    }
  }

  // ═══ Create handlers ══════════════════════════════════════════════════════
  function handleCreateMilestone(data: { title: string; description?: string }) {
    createMilestone(data).catch((err) => {
      showError(err instanceof Error ? err.message : 'Failed to create milestone')
    })
  }

  // ═══ Loading state ════════════════════════════════════════════════════════
  if (loading) {
    return (
      <div className="flex h-full flex-col p-6">
        <h1 className="mb-6 text-2xl font-bold tracking-tight">Kanban Board</h1>
        <div className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="border-primary size-8 animate-spin rounded-full border-2 border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading board data...</p>
          </div>
        </div>
      </div>
    )
  }

  // ═══ Empty state ══════════════════════════════════════════════════════════
  if (milestones.length === 0) {
    return (
      <div className="flex h-full flex-col p-6">
        <h1 className="mb-6 text-2xl font-bold tracking-tight">Kanban Board</h1>
        <div className="flex flex-1 items-center justify-center">
          <Card className="flex max-w-md flex-col items-center gap-4 p-8 text-center">
            <h2 className="text-lg font-semibold">No milestones yet</h2>
            <p className="text-sm text-muted-foreground">
              Create your first milestone to start organizing your project
              into manageable slices and tasks.
            </p>
            <CreateEntityDialog
              type="milestone"
              onCreate={handleCreateMilestone}
            >
              <Button>
                <Plus className="mr-1 size-4" />
                Create your first milestone
              </Button>
            </CreateEntityDialog>
          </Card>
        </div>
      </div>
    )
  }

  // ═══ Main render ══════════════════════════════════════════════════════════
  return (
    <div className="flex h-full flex-col p-6">
      {/* Header row */}
      <div className="mb-4 flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Kanban Board</h1>
        <CreateEntityDialog
          type="milestone"
          onCreate={handleCreateMilestone}
        >
          <Button size="sm">
            <Plus className="mr-1 size-4" />
            Milestone
          </Button>
        </CreateEntityDialog>
      </div>

      {/* Error toast */}
      {errorMessage && (
        <div className="mb-4 shrink-0 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {errorMessage}
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="ml-3 font-medium underline underline-offset-2"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Columns */}
      <div className="flex flex-1 gap-4 overflow-x-auto pb-2">
        <DragDropProvider onDragEnd={handleDragEnd}>
          {COLUMNS.map((col) => {
            // Count milestones that actually have content in this column
            const colCount = milestones.filter((m) => {
              const milestoneSlices = slices.filter(
                (s) => s.milestone_id === m.id,
              )
              return milestoneSlices.some((s) =>
                tasks.some(
                  (t) => t.slice_id === s.id && t.status === col.status,
                ),
              )
            }).length

            return (
              <KanbanColumn
                key={col.id}
                id={col.id}
                title={col.title}
                status={col.status}
                count={col.status === 'pending' ? milestones.length : colCount}
              >
                {milestones.map((milestone, mIndex) => {
                  const milestoneSlices = slices.filter(
                    (s) => s.milestone_id === milestone.id,
                  )
                  // Filter tasks to only those matching this column's status
                  const colTasks = tasks.filter(
                    (t) => t.status === col.status,
                  )

                  // For non-pending columns, skip milestones with no tasks here
                  if (
                    col.status !== 'pending' &&
                    !milestoneSlices.some((s) =>
                      colTasks.some((t) => t.slice_id === s.id),
                    )
                  ) {
                    return null
                  }

                  return (
                    <MilestoneCard
                      key={milestone.id}
                      milestone={milestone}
                      slices={milestoneSlices}
                      tasks={colTasks}
                      index={mIndex}
                      defaultExpanded={true}
                    />
                  )
                })}

                {milestones.every((m) => {
                  const ms = slices.filter((s) => s.milestone_id === m.id)
                  return !ms.some((s) =>
                    tasks.some(
                      (t) => t.slice_id === s.id && t.status === col.status,
                    ),
                  )
                }) &&
                  col.status !== 'pending' && (
                    <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                      No items in this column
                    </p>
                  )}
              </KanbanColumn>
            )
          })}
        </DragDropProvider>
      </div>
    </div>
  )
}
