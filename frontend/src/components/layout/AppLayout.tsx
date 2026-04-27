import { useState } from 'react'

import { ConnectionIndicator } from '@/components/layout/ConnectionIndicator'
import { Sidebar } from '@/components/layout/Sidebar'
import { useWebSocket, type WebSocketStatus } from '@/hooks/useWebSocket'

interface AppLayoutProps {
  children: React.ReactNode
  currentPage?: string
  onNavigate?: (page: string) => void
}

export function AppLayout({ children, currentPage, onNavigate }: AppLayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const { status } = useWebSocket()

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((prev) => !prev)}
        connectionIndicator={<ConnectionIndicator status={status as WebSocketStatus} />}
        currentPage={currentPage ?? 'dashboard'}
        onNavigate={onNavigate ?? (() => {})}
      />
      <main className="flex-1 overflow-auto bg-background">
        {children}
      </main>
    </div>
  )
}
