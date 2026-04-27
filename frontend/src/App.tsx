import { useCallback, useEffect, useState } from 'react'

import { AppLayout } from '@/components/layout/AppLayout'
import { SetupWizard } from '@/components/wizard/SetupWizard'

function Dashboard() {
  return (
    <div className="flex h-full flex-col items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="mb-2 text-3xl font-bold tracking-tight">RE-AI</h1>
        <p className="text-muted-foreground">
          Welcome to your AI-powered research environment.
          Use the sidebar to navigate between features.
        </p>
      </div>
    </div>
  )
}

function App() {
  const [loading, setLoading] = useState(true)
  const [configured, setConfigured] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function checkStatus() {
      try {
        const res = await fetch('/api/config/wizard-status')
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const data = await res.json()
        if (!cancelled) {
          setConfigured(data.configured ?? false)
        }
      } catch {
        // Backend not reachable or not configured — show wizard
        if (!cancelled) setConfigured(false)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    checkStatus()
    return () => { cancelled = true }
  }, [])

  const handleComplete = useCallback(() => {
    window.location.reload()
  }, [])

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-center">
          <div className="mx-auto mb-4 size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (!configured) {
    return <SetupWizard onComplete={handleComplete} />
  }

  return (
    <AppLayout>
      <Dashboard />
    </AppLayout>
  )
}

export default App
