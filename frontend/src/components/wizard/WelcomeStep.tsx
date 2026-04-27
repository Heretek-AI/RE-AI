import { Rocket, SkipForward } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

interface WelcomeStepProps {
  onStart: () => void
  onSkip: () => void
}

export function WelcomeStep({ onStart, onSkip }: WelcomeStepProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-full bg-primary/10">
            <Rocket className="size-8 text-primary" />
          </div>
          <CardTitle className="text-2xl">Welcome to RE-AI</CardTitle>
          <CardDescription className="mt-2 text-base">
            Your AI-powered reverse engineering research environment.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            RE-AI connects AI language models with reverse engineering tools
            to help you analyze binaries, understand malware, and accelerate
            your research workflow.
          </p>
          <ul className="space-y-2">
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-primary">•</span>
              <span>Configure an AI provider (OpenAI, Anthropic, Ollama, or MiniMax)</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-primary">•</span>
              <span>Auto-detect installed RE tools on your system</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-primary">•</span>
              <span>Chat with AI agents that understand binary analysis</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-primary">•</span>
              <span>All API keys encrypted at rest on your machine</span>
            </li>
          </ul>
        </CardContent>

        <CardFooter className="flex justify-between gap-4">
          <Button variant="outline" onClick={onSkip} className="gap-2">
            <SkipForward className="size-4" />
            Skip Setup
          </Button>
          <Button onClick={onStart} className="gap-2">
            Get Started
            <Rocket className="size-4" />
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
