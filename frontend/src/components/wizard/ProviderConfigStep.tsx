import { useState } from 'react'

import { CheckCircle2, Loader2, ShieldAlert, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

interface ProviderConfigStepProps {
  initialProvider?: string
  initialModel?: string
  onNext: (provider: string, apiKey: string, model: string) => void
  onBack: () => void
}

const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'] },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-sonnet-4-20250514', 'claude-3-5-sonnet-latest', 'claude-3-haiku-20240307'] },
  { id: 'ollama', label: 'Ollama (Local)', models: ['llama3.2', 'llama3.1', 'qwen2.5', 'deepseek-r1', 'codestral'] },
  { id: 'minimax', label: 'MiniMax', models: ['MiniMax-Text-01'] },
]

interface ValidationState {
  loading: boolean
  valid: boolean | null
  error: string | null
}

export function ProviderConfigStep({
  initialProvider = 'openai',
  initialModel = '',
  onNext,
  onBack,
}: ProviderConfigStepProps) {
  const [provider, setProvider] = useState(initialProvider)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(initialModel)
  const [validation, setValidation] = useState<ValidationState>({ loading: false, valid: null, error: null })

  const selectedProvider = PROVIDERS.find((p) => p.id === provider)
  const needsKey = provider !== 'ollama'

  const handleValidate = async () => {
    if (needsKey && !apiKey.trim()) return

    setValidation({ loading: true, valid: null, error: null })

    try {
      const res = await fetch('/api/config/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: apiKey }),
      })
      const data = await res.json()
      setValidation({
        loading: false,
        valid: data.valid ?? false,
        error: data.error ?? null,
      })
    } catch {
      setValidation({ loading: false, valid: false, error: 'Network error — could not reach the backend.' })
    }
  }

  const handleNext = () => {
    onNext(provider, apiKey, model || (selectedProvider?.models[0] ?? ''))
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-2xl">AI Provider Configuration</CardTitle>
          <CardDescription>
            Choose your AI provider and enter your API key. Keys are encrypted at
            rest and never logged.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Provider dropdown */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Provider</label>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value)
                setValidation({ loading: false, valid: null, error: null })
                if (e.target.value === 'ollama') {
                  setModel('llama3.2')
                  setApiKey('')
                } else {
                  setModel('')
                }
              }}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </div>

          {/* API key (hidden for Ollama) */}
          {needsKey && (
            <div className="space-y-2">
              <label className="text-sm font-medium">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value)
                  setValidation({ loading: false, valid: null, error: null })
                }}
                placeholder="sk-..."
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
          )}

          {provider === 'ollama' && (
            <p className="text-xs text-muted-foreground">
              Ollama runs locally — no API key needed. Make sure the Ollama service
              is running on localhost:11434.
            </p>
          )}

          {/* Model dropdown */}
          {selectedProvider && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {selectedProvider.models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          )}

          {/* Validate button + result */}
          <div className="space-y-2">
            <Button
              variant="outline"
              onClick={handleValidate}
              disabled={validation.loading || (needsKey && !apiKey.trim())}
              className="gap-2"
            >
              {validation.loading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldAlert className="size-4" />
              )}
              {validation.loading ? 'Validating...' : 'Validate Connection'}
            </Button>

            {validation.valid === true && (
              <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
                <CheckCircle2 className="size-4" />
                Connection verified — credentials are valid.
              </div>
            )}
            {validation.valid === false && (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <XCircle className="size-4" />
                {validation.error || 'Validation failed.'}
              </div>
            )}
          </div>
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button onClick={handleNext}>
            Next: Tool Detection
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
