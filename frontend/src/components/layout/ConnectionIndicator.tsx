import { cn } from '@/lib/utils'
import { type WebSocketStatus } from '@/hooks/useWebSocket'

const statusConfig: Record<
  WebSocketStatus,
  { color: string; label: string }
> = {
  connected: { color: 'bg-green-500', label: 'Connected' },
  connecting: { color: 'bg-yellow-500', label: 'Connecting...' },
  disconnected: { color: 'bg-red-500', label: 'Disconnected' },
}

interface ConnectionIndicatorProps {
  status: WebSocketStatus
}

export function ConnectionIndicator({ status }: ConnectionIndicatorProps) {
  const config = statusConfig[status]

  return (
    <div className="flex items-center gap-2" title={config.label}>
      <span
        className={cn(
          'inline-block size-2 rounded-full',
          config.color,
          status === 'connecting' && 'animate-pulse',
        )}
      />
      <span className="text-xs text-muted-foreground">{config.label}</span>
    </div>
  )
}
