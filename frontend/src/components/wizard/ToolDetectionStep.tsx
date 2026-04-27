import { useCallback, useEffect, useState } from 'react'

import { CheckCircle2, Loader2, ShieldAlert, Wrench, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface ToolResult {
  id: string
  display_name: string
  detected: boolean
  path: string | null
  method: string | null
}

interface ValidationState {
  loading: boolean
  valid: boolean | null
  error: string | null
}

interface ToolDetectionStepProps {
  onNext: (tools: ToolResult[], toolConfigs: Record<string, string>) => void
  onBack: () => void
}

/** Tools that support manual path configuration + validation. */
const CONFIGURABLE_TOOLS: Array<{ id: string; displayName: string; label: string }> = [
  { id: 'ida_pro', displayName: 'IDA Pro', label: 'IDA Pro Executable Path' },
  { id: 'ghidra', displayName: 'Ghidra', label: 'Ghidra analyzeHeadless Path' },
]

export function ToolDetectionStep({ onNext, onBack }: ToolDetectionStepProps) {
  const [tools, setTools] = useState<ToolResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Per-tool path overrides — keyed by tool_id
  const [toolConfigs, setToolConfigs] = useState<Record<string, string>>({})
  // Per-tool validation state — keyed by tool_id
  const [validationResults, setValidationResults] = useState<
    Record<string, ValidationState>
  >({})

  useEffect(() => {
    let cancelled = false

    async function scan() {
      try {
        const res = await fetch('/api/tools/detect')
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const data: Record<string, ToolResult> = await res.json()
        if (!cancelled) {
          const toolList = Object.values(data)
          setTools(toolList)

          // Auto-fill IDA Pro and Ghidra paths from detection results
          const initialConfigs: Record<string, string> = {}
          for (const tool of toolList) {
            if (
              (tool.id === 'ida_pro' || tool.id === 'ghidra') &&
              tool.path
            ) {
              initialConfigs[tool.id] = tool.path
            }
          }
          setToolConfigs(initialConfigs)
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

  const handlePathChange = useCallback(
    (toolId: string, value: string) => {
      setToolConfigs((prev) => ({ ...prev, [toolId]: value }))
      // Clear validation when the user edits the path
      setValidationResults((prev) => ({
        ...prev,
        [toolId]: { loading: false, valid: null, error: null },
      }))
    },
    [],
  )

  const handleValidate = useCallback(async (toolId: string) => {
    const path = toolConfigs[toolId]
    if (!path || !path.trim()) return

    setValidationResults((prev) => ({
      ...prev,
      [toolId]: { loading: true, valid: null, error: null },
    }))

    try {
      const res = await fetch('/api/tools/validate-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_id: toolId, path }),
      })

      // 400 means the tool_id is not validatable — treat as user-facing error
      if (res.status === 400) {
        const detail = await res.json()
        setValidationResults((prev) => ({
          ...prev,
          [toolId]: {
            loading: false,
            valid: false,
            error: detail.detail ?? 'Unknown tool.',
          },
        }))
        return
      }

      const data = await res.json()
      setValidationResults((prev) => ({
        ...prev,
        [toolId]: {
          loading: false,
          valid: data.valid ?? false,
          error: data.error ?? null,
        },
      }))
    } catch {
      setValidationResults((prev) => ({
        ...prev,
        [toolId]: {
          loading: false,
          valid: false,
          error: 'Network error — could not reach the backend.',
        },
      }))
    }
  }, [toolConfigs])

  const handleNext = useCallback(() => {
    // Pass both the original tool detection results and any manual path overrides
    onNext(tools, toolConfigs)
  }, [tools, toolConfigs, onNext])

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

        <CardContent className="space-y-6">
          {/* Scan results */}
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
            <>
              {/* Tool detection list */}
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
                            {tool.method === 'path'
                              ? 'In PATH'
                              : tool.method === 'registry'
                                ? 'Registry'
                                : 'Found'}
                          </span>
                        ) : tool.path === null ? (
                          <span className="text-xs text-muted-foreground">Not found</span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Separator */}
              <hr className="border-t" />

              {/* Tool path configuration section */}
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-medium">Tool Paths</h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Configure custom paths for tools that were not auto-detected
                    or override the detected location.
                  </p>
                </div>

                {CONFIGURABLE_TOOLS.map((configTool) => {
                  const valState = validationResults[configTool.id] ?? {
                    loading: false,
                    valid: null,
                    error: null,
                  }
                  const currentPath = toolConfigs[configTool.id] ?? ''

                  return (
                    <div key={configTool.id} className="space-y-2">
                      <Label htmlFor={`tool-path-${configTool.id}`}>
                        {configTool.label}
                      </Label>
                      <div className="flex gap-2">
                        <Input
                          id={`tool-path-${configTool.id}`}
                          type="text"
                          value={currentPath}
                          onChange={(e) =>
                            handlePathChange(configTool.id, e.target.value)
                          }
                          placeholder={
                            configTool.id === 'ida_pro'
                              ? 'C:\\Program Files\\IDA Pro\\idat64.exe'
                              : 'C:\\ghidra\\support\\analyzeHeadless.bat'
                          }
                          className="flex-1"
                        />
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleValidate(configTool.id)}
                          disabled={valState.loading || !currentPath.trim()}
                          className="gap-1.5 shrink-0"
                        >
                          {valState.loading ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <ShieldAlert className="size-3.5" />
                          )}
                          Validate
                        </Button>
                      </div>

                      {/* Validation result */}
                      {valState.valid === true && (
                        <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
                          <CheckCircle2 className="size-4 shrink-0" />
                          Path verified — tool binary is functional.
                        </div>
                      )}
                      {valState.valid === false && (
                        <div className="flex items-center gap-2 text-sm text-destructive">
                          <XCircle className="size-4 shrink-0" />
                          {valState.error || 'Validation failed.'}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button onClick={handleNext}>
            Next: Summary
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
