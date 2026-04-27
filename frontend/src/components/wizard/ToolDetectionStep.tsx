import { useEffect, useState } from 'react'

import { CheckCircle2, Loader2, Wrench, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

interface ToolResult {
  id: string
  display_name: string
  detected: boolean
  path: string | null
  method: string | null
}

interface ToolDetectionStepProps {
  onNext: (tools: ToolResult[]) => void
  onBack: () => void
}

export function ToolDetectionStep({ onNext, onBack }: ToolDetectionStepProps) {
  const [tools, setTools] = useState<ToolResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function scan() {
      try {
        const res = await fetch('/api/tools/detect')
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const data: Record<string, ToolResult> = await res.json()
        if (!cancelled) {
          setTools(Object.values(data))
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to detect tools.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    scan()
    return () => { cancelled = true }
  }, [])

  const detectedCount = tools.filter((t) => t.detected).length

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-2xl">Tool Detection</CardTitle>
          <CardDescription>
            Scanning your system for installed reverse engineering tools.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {loading && (
            <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
              <Loader2 className="size-8 animate-spin" />
              <p className="text-sm">Scanning system for RE tools...</p>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              <XCircle className="size-4 shrink-0" />
              {error}
            </div>
          )}

          {!loading && !error && (
            <div className="space-y-1">
              <p className="mb-3 text-xs text-muted-foreground">
                Found {detectedCount} of {tools.length} tools
              </p>
              <div className="max-h-80 space-y-1 overflow-y-auto">
                {tools.map((tool) => (
                  <div
                    key={tool.id}
                    className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-2">
                      {tool.detected ? (
                        <CheckCircle2 className="size-4 shrink-0 text-green-600 dark:text-green-400" />
                      ) : (
                        <Wrench className="size-4 shrink-0 text-muted-foreground" />
                      )}
                      <span className={tool.detected ? '' : 'text-muted-foreground'}>
                        {tool.display_name}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {tool.detected ? (
                        <span className="text-xs text-green-600 dark:text-green-400">
                          {tool.method === 'path' ? 'In PATH' : tool.method === 'registry' ? 'Registry' : 'Found'}
                        </span>
                      ) : tool.path === null ? (
                        <span className="text-xs text-muted-foreground">Not found</span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button onClick={() => onNext(tools)}>
            Next: Summary
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
