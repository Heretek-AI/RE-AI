import { useCallback, useState } from 'react'

import { ProviderConfigStep } from '@/components/wizard/ProviderConfigStep'
import { SummaryStep } from '@/components/wizard/SummaryStep'
import { ToolDetectionStep } from '@/components/wizard/ToolDetectionStep'
import { WelcomeStep } from '@/components/wizard/WelcomeStep'

interface ToolResult {
  id: string
  display_name: string
  detected: boolean
  path: string | null
  method: string | null
}

type Step = 'welcome' | 'provider' | 'tools' | 'summary'

interface WizardData {
  provider: string
  apiKey: string
  model: string
  tools: ToolResult[]
}

interface SetupWizardProps {
  onComplete: () => void
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const [step, setStep] = useState<Step>('welcome')
  const [data, setData] = useState<WizardData>({
    provider: 'openai',
    apiKey: '',
    model: '',
    tools: [],
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleProviderNext = useCallback((provider: string, apiKey: string, model: string) => {
    setData((prev) => ({ ...prev, provider, apiKey, model }))
    setStep('tools')
  }, [])

  const handleToolsNext = useCallback((tools: ToolResult[]) => {
    setData((prev) => ({ ...prev, tools }))
    setStep('summary')
  }, [])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setError(null)

    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ai_provider: data.provider,
          ai_api_key: data.apiKey,
          ai_model: data.model,
        }),
      })

      if (!res.ok) throw new Error(`Server returned ${res.status}`)

      setSaved(true)
      // Wait a moment for the user to see the success state, then reload
      setTimeout(() => onComplete(), 1500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration.')
    } finally {
      setSaving(false)
    }
  }, [data, onComplete])

  switch (step) {
    case 'welcome':
      return (
        <WelcomeStep
          onStart={() => setStep('provider')}
          onSkip={onComplete}
        />
      )
    case 'provider':
      return (
        <ProviderConfigStep
          initialProvider={data.provider}
          initialModel={data.model}
          onNext={handleProviderNext}
          onBack={() => setStep('welcome')}
        />
      )
    case 'tools':
      return (
        <ToolDetectionStep
          onNext={handleToolsNext}
          onBack={() => setStep('provider')}
        />
      )
    case 'summary':
      return (
        <SummaryStep
          provider={data.provider}
          model={data.model}
          tools={data.tools}
          saving={saving}
          saved={saved}
          error={error}
          onSave={handleSave}
          onBack={() => setStep('tools')}
        />
      )
    default:
      return null
  }
}
