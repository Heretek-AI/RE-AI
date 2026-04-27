'use client'

import { useCallback, useEffect, useState } from 'react'
import { useWebSocket } from './useWebSocket'

// ── Type definitions (matching Pydantic Response models) ────────────────────

export interface Milestone {
  id: number
  title: string
  description: string
  status: string
  created_at: string
  updated_at: string
}

export interface Slice {
  id: number
  milestone_id: number
  title: string
  description: string
  status: string
  order: number
  created_at: string
  updated_at: string
}

export interface Task {
  id: number
  slice_id: number
  title: string
  description: string
  status: string
  order: number
  created_at: string
  updated_at: string
}

export interface KanbanData {
  milestones: Milestone[]
  slices: Slice[]
  tasks: Task[]
}

// ── WebSocket event shapes ───────────────────────────────────────────────────

interface EntityChangeEvent {
  type: 'entity_change'
  entity: 'milestone' | 'slice' | 'task'
  action: 'created' | 'updated' | 'deleted' | 'status_changed'
  data: Record<string, unknown>
}

interface UseKanbanDataReturn {
  milestones: Milestone[]
  slices: Slice[]
  tasks: Task[]
  loading: boolean
  createMilestone: (data: { title: string; description?: string }) => Promise<Milestone>
  createSlice: (milestoneId: number, data: { title: string; description?: string }) => Promise<Slice>
  createTask: (sliceId: number, data: { title: string; description?: string }) => Promise<Task>
  updateTaskStatus: (taskId: number, status: string) => Promise<Task>
}

// ── Generic API fetch helper ─────────────────────────────────────────────────

const API_BASE = 'http://localhost:8000/api'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  // 204 No Content (e.g. DELETE)
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useKanbanData(): UseKanbanDataReturn {
  const { lastMessage } = useWebSocket()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<KanbanData>({
    milestones: [],
    slices: [],
    tasks: [],
  })

  // ── Initial data fetch ──────────────────────────────────────────────────
  // Fetches all milestones, then their slices, then each slice's tasks.
  useEffect(() => {
    let cancelled = false

    async function fetchAll() {
      setLoading(true)
      try {
        const milestones = await apiFetch<Milestone[]>('/milestones')

        const allSlices: Slice[] = []
        const allTasks: Task[] = []

        for (const milestone of milestones) {
          const slices = await apiFetch<Slice[]>(
            `/milestones/${milestone.id}/slices`,
          )
          allSlices.push(...slices)

          for (const slice of slices) {
            const tasks = await apiFetch<Task[]>(`/slices/${slice.id}/tasks`)
            allTasks.push(...tasks)
          }
        }

        if (!cancelled) {
          setData({ milestones, slices: allSlices, tasks: allTasks })
        }
      } catch (err) {
        console.error('[kanban] Failed to fetch initial data:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchAll()

    return () => {
      cancelled = true
    }
  }, [])

  // ── WebSocket event merging ─────────────────────────────────────────────
  // Merges entity_change events into local state using immutable updates.
  // Skips events while the initial fetch is still loading.
  useEffect(() => {
    const msg = lastMessage as EntityChangeEvent | null
    if (!msg || msg.type !== 'entity_change') return
    if (loading) return

    setData((prev) => {
      const { entity, action, data: eventData } = msg

      switch (entity) {
        case 'milestone': {
          if (action === 'created') {
            return {
              ...prev,
              milestones: [
                ...prev.milestones,
                eventData as unknown as Milestone,
              ],
            }
          }
          if (action === 'updated' || action === 'status_changed') {
            const updated = eventData as unknown as Milestone
            return {
              ...prev,
              milestones: prev.milestones.map((m) =>
                m.id === updated.id ? updated : m,
              ),
            }
          }
          if (action === 'deleted') {
            const { id } = eventData as { id: number }
            return {
              ...prev,
              milestones: prev.milestones.filter((m) => m.id !== id),
              // Cascade: remove child slices and their tasks
              slices: prev.slices.filter((s) => s.milestone_id !== id),
              tasks: prev.tasks.filter((t) => {
                const slice = prev.slices.find((s) => s.id === t.slice_id)
                return slice ? slice.milestone_id !== id : true
              }),
            }
          }
          return prev
        }

        case 'slice': {
          if (action === 'created') {
            return {
              ...prev,
              slices: [...prev.slices, eventData as unknown as Slice],
            }
          }
          if (action === 'updated' || action === 'status_changed') {
            const updated = eventData as unknown as Slice
            return {
              ...prev,
              slices: prev.slices.map((s) =>
                s.id === updated.id ? updated : s,
              ),
            }
          }
          if (action === 'deleted') {
            const { id } = eventData as { id: number }
            return {
              ...prev,
              slices: prev.slices.filter((s) => s.id !== id),
              tasks: prev.tasks.filter((t) => t.slice_id !== id),
            }
          }
          return prev
        }

        case 'task': {
          if (action === 'created') {
            return {
              ...prev,
              tasks: [...prev.tasks, eventData as unknown as Task],
            }
          }
          if (action === 'updated' || action === 'status_changed') {
            const updated = eventData as unknown as Task
            return {
              ...prev,
              tasks: prev.tasks.map((t) =>
                t.id === updated.id ? updated : t,
              ),
            }
          }
          if (action === 'deleted') {
            const { id } = eventData as { id: number }
            return {
              ...prev,
              tasks: prev.tasks.filter((t) => t.id !== id),
            }
          }
          return prev
        }

        default:
          return prev
      }
    })
  }, [lastMessage, loading])

  // ── CRUD API wrappers ──────────────────────────────────────────────────

  const createMilestone = useCallback(
    async (payload: {
      title: string
      description?: string
    }): Promise<Milestone> => {
      return apiFetch<Milestone>('/milestones', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
    [],
  )

  const createSlice = useCallback(
    async (
      milestoneId: number,
      payload: { title: string; description?: string },
    ): Promise<Slice> => {
      return apiFetch<Slice>(`/milestones/${milestoneId}/slices`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
    [],
  )

  const createTask = useCallback(
    async (
      sliceId: number,
      payload: { title: string; description?: string },
    ): Promise<Task> => {
      return apiFetch<Task>(`/slices/${sliceId}/tasks`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
    [],
  )

  const updateTaskStatus = useCallback(
    async (taskId: number, status: string): Promise<Task> => {
      return apiFetch<Task>(`/tasks/${taskId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
    },
    [],
  )

  return {
    milestones: data.milestones,
    slices: data.slices,
    tasks: data.tasks,
    loading,
    createMilestone,
    createSlice,
    createTask,
    updateTaskStatus,
  }
}
