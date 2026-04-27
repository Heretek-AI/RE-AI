import { AppLayout } from '@/components/layout/AppLayout'

function App() {
  return (
    <AppLayout>
      <div className="flex h-full flex-col items-center justify-center p-8">
        <div className="max-w-md text-center">
          <h1 className="mb-2 text-3xl font-bold tracking-tight">RE-AI</h1>
          <p className="text-muted-foreground">
            Welcome to your AI-powered research environment.
            Use the sidebar to navigate between features.
          </p>
        </div>
      </div>
    </AppLayout>
  )
}

export default App
