'use client'

import * as React from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import type { Milestone, Slice } from '@/hooks/useKanbanData'

interface CreateEntityFormData {
  title: string
  description?: string
  parentId?: number // milestone_id for slices, slice_id for tasks
}

interface CreateEntityDialogProps {
  type: 'milestone' | 'slice' | 'task'
  milestones?: Milestone[]
  slices?: Slice[]
  onCreate: (data: CreateEntityFormData) => void
  children: React.ReactNode
}

export function CreateEntityDialog({
  type,
  milestones = [],
  slices = [],
  onCreate,
  children,
}: CreateEntityDialogProps) {
  const [open, setOpen] = React.useState(false)
  const [title, setTitle] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [parentId, setParentId] = React.useState<number | ''>('')

  const entityLabel = type === 'milestone' ? 'Milestone' : type === 'slice' ? 'Slice' : 'Task'
  const parentLabel = type === 'slice' ? 'Milestone' : 'Slice'
  const parentOptions = type === 'slice' ? milestones : slices
  const parentRequired = type !== 'milestone'

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    if (parentRequired && (parentId === '' || parentId === null)) return

    onCreate({
      title: title.trim(),
      description: description.trim() || undefined,
      parentId: parentId !== '' ? Number(parentId) : undefined,
    })

    // Reset form and close
    setTitle('')
    setDescription('')
    setParentId('')
    setOpen(false)
  }

  function handleOpenChange(newOpen: boolean) {
    setOpen(newOpen)
    if (!newOpen) {
      // Reset on close
      setTitle('')
      setDescription('')
      setParentId('')
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create {entityLabel}</DialogTitle>
            <DialogDescription>
              Add a new {entityLabel.toLowerCase()} to the kanban board.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {/* Title field */}
            <div className="grid gap-2">
              <Label htmlFor="create-title">
                Title <span className="text-destructive">*</span>
              </Label>
              <Input
                id="create-title"
                placeholder={`Enter ${entityLabel.toLowerCase()} title`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                autoFocus
              />
            </div>

            {/* Description field */}
            <div className="grid gap-2">
              <Label htmlFor="create-description">Description</Label>
              <textarea
                id="create-description"
                placeholder={`Optional description for this ${entityLabel.toLowerCase()}`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className={cn(
                  'border-input placeholder:text-muted-foreground flex min-h-[60px] w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs transition-colors outline-none',
                  'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
                )}
              />
            </div>

            {/* Parent picker for slices/tasks */}
            {parentRequired && (
              <div className="grid gap-2">
                <Label htmlFor="create-parent">
                  {parentLabel} <span className="text-destructive">*</span>
                </Label>
                <select
                  id="create-parent"
                  value={parentId}
                  onChange={(e) =>
                    setParentId(e.target.value ? Number(e.target.value) : '')
                  }
                  required
                  className={cn(
                    'border-input bg-background text-foreground flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs transition-colors outline-none',
                    'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
                  )}
                >
                  <option value="" disabled>
                    Select a {parentLabel.toLowerCase()}...
                  </option>
                  {parentOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit">Create</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
