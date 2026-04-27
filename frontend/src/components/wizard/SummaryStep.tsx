import { CheckCircle2, Loader2, Rocket, XCircle } from 'lucide-react'

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

interface SummaryStepProps {
  provider: string
  model: string
  tools: ToolResult[]
  toolConfigs?: Record<string, string>
  saving: boolean
  saved: boolean
  error: string | null
  onSave: () => void
  onBack: () => void
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama (Local)',
  minimax: 'MiniMax',
}

export function SummaryStep({
  provider,
  model,
  tools,
  toolConfigs = {},
  saving,
  saved,
  error,
  onSave,
  onBack,
}: SummaryStepProps) {
  const detectedCount = tools.filter((t) => t.detected).length

  if (saved) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-lg">
          <CardHeader className="text-center">
            <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-full bg-green-600/10">
              <CheckCircle2 className="size-8 text-green-600 dark:text-green-400" />
            </div>
            <CardTitle className="text-2xl">Setup Complete!</CardTitle>
            <CardDescription className="mt-2 text-base">
              Your configuration has been saved and encrypted.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Provider: <strong>{PROVIDER_LABELS[provider] || provider}</strong> ({model})
            </p>
            <p>
              Tools detected: <strong>{detectedCount}</strong> of {tools.length}
            </p>
          </CardContent>
          <CardFooter className="justify-center">
            <Button onClick={() => window.location.reload()} className="gap-2">
              <Rocket className="size-4" />
              Enter RE-AI
            </Button>
          </CardFooter>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-2xl">Summary</CardTitle>
          <CardDescription>
            Review your settings before saving.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Provider */}
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">AI Provider</p>
            <p className="mt-1 text-sm font-medium">
              {PROVIDER_LABELS[provider] || provider}
            </p>
            <p className="text-xs text-muted-foreground">Model: {model}</p>
          </div>

          {/* Tool detection */}
          <div className="rounded-md border p-3">
            <p className="text-xs text-muted-foreground">Tool Detection</p>
            <p className="mt-1 text-sm">
              {detectedCount} of {tools.length} tools detected
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {tools
                .filter((t) => t.detected)
                .slice(0, 6)
                .map((t) => (
                  <span
                    key={t.id}
                    className="inline-flex items-center gap-1 rounded-full bg-green-600/10 px-2 py-0.5 text-xs text-green-600 dark:text-green-400"
                  >
                    {t.display_name}
                  </span>
                ))}
              {detectedCount > 6 && (
                <span className="text-xs text-muted-foreground">
                  +{detectedCount - 6} more
                </span>
              )}
            </div>
          </div>

          {/* Tool config paths */}
          {Object.keys(toolConfigs).length > 0 && (
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">Configured Tool Paths</p>
              <div className="mt-2 space-y-1.5">
                {Object.entries(toolConfigs).map(([toolId, path]) => (
                  <div key={toolId} className="flex items-start gap-2 text-xs">
                    <span className="shrink-0 font-medium capitalize">
                      {toolId === 'ida_pro' ? 'IDA Pro' : toolId === 'ghidra' ? 'Ghidra' : toolId}:
                    </span>
                    <span className="text-muted-foreground break-all">{path}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Key security note */}
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
            <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
              🔒 Configuration is encrypted at rest
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              API keys are encrypted using PBKDF2HMAC-derived keys before being
              written to disk. No plaintext secrets are ever stored.
            </p>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
              <XCircle className="size-4 shrink-0" />
              {error}
            </div>
          )}
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button variant="ghost" onClick={onBack} disabled={saving}>
            Back
          </Button>
          <Button onClick={onSave} disabled={saving} className="gap-2">
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Rocket className="size-4" />
            )}
            {saving ? 'Saving...' : 'Save & Finish'}
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
