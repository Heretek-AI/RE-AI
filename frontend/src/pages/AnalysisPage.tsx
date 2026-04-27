'use client'

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useAnalysis,
  type AnalysisResult,
  type DisassemblyResult,
  type ImportsExportsResult,
  type PeStructureResult,
  type StringsResult,
} from '@/hooks/useAnalysis'

// ── Helpers ────────────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = Math.round(bytes / 1024 ** i)
  return `${value} ${units[i]}`
}

function truncateHash(hash: string): string {
  if (hash.length <= 16) return hash
  return `${hash.slice(0, 16)}...`
}

// ── File Info Card ─────────────────────────────────────────────────────────

function FileInfoCard({ result }: { result: AnalysisResult }) {
  const { fileInfo, peStructure } = result
  if (!fileInfo) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">File Information</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Path</dt>
          <dd className="font-mono text-xs break-all">{fileInfo.path}</dd>

          <dt className="text-muted-foreground">Size</dt>
          <dd>{formatSize(fileInfo.size_bytes)}</dd>

          <dt className="text-muted-foreground">MD5</dt>
          <dd className="font-mono text-xs">{truncateHash(fileInfo.md5)}</dd>

          <dt className="text-muted-foreground">SHA256</dt>
          <dd className="font-mono text-xs">{truncateHash(fileInfo.sha256)}</dd>

          <dt className="text-muted-foreground">Architecture</dt>
          <dd>
            <Badge variant="outline">{fileInfo.architecture ?? '?'}</Badge>
          </dd>

          <dt className="text-muted-foreground">Type</dt>
          <dd className="flex gap-2">
            {fileInfo.is_exe && <Badge variant="default">EXE</Badge>}
            {fileInfo.is_dll && <Badge variant="secondary">DLL</Badge>}
            {!fileInfo.is_exe && !fileInfo.is_dll && (
              <span className="text-muted-foreground italic">Unknown</span>
            )}
          </dd>

          <dt className="text-muted-foreground">Entry Point</dt>
          <dd className="font-mono text-xs">
            {fileInfo.entry_point != null
              ? `0x${fileInfo.entry_point.toString(16).toUpperCase()}`
              : '—'}
          </dd>

          <dt className="text-muted-foreground">Imphash</dt>
          <dd className="font-mono text-xs">{peStructure?.imphash ?? '—'}</dd>
        </dl>
      </CardContent>
    </Card>
  )
}

// ── Tab panels ─────────────────────────────────────────────────────────────

interface TabPanelProps {
  active: boolean
  children: React.ReactNode
}

function TabPanel({ active, children }: TabPanelProps) {
  if (!active) return null
  return <div className="space-y-4">{children}</div>
}

// ── PE Structure Tab ───────────────────────────────────────────────────────

function PeStructureTab({ data }: { data: PeStructureResult | null }) {
  if (!data) return <p className="text-sm text-muted-foreground">No PE structure data.</p>

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Header Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Machine Type</dt>
            <dd>
              <Badge variant="outline">{data.machine_type}</Badge>
            </dd>
            <dt className="text-muted-foreground">Characteristics</dt>
            <dd className="font-mono text-xs">{data.characteristics}</dd>
            <dt className="text-muted-foreground">Subsystem</dt>
            <dd>{data.subsystems.join(', ')}</dd>
            <dt className="text-muted-foreground">Image Base</dt>
            <dd className="font-mono text-xs">0x{data.image_base.toString(16).toUpperCase()}</dd>
            <dt className="text-muted-foreground">Size of Image</dt>
            <dd>{formatSize(data.size_of_image)}</dd>
            <dt className="text-muted-foreground">Entry Point</dt>
            <dd className="font-mono text-xs">
              0x{data.entry_point.toString(16).toUpperCase()}
            </dd>
            <dt className="text-muted-foreground">Imphash</dt>
            <dd className="font-mono text-xs">{data.imphash ?? '—'}</dd>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sections ({data.sections.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium">VA</th>
                  <th className="pb-2 pr-4 font-medium">Virtual Size</th>
                  <th className="pb-2 pr-4 font-medium">Raw Size</th>
                  <th className="pb-2 font-medium">Characteristics</th>
                </tr>
              </thead>
              <tbody>
                {data.sections.map((sec) => (
                  <tr key={sec.name} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{sec.name}</td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      0x{sec.virtual_address.toString(16).toUpperCase()}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">{sec.virtual_size.toLocaleString()}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{sec.size_of_raw_data.toLocaleString()}</td>
                    <td className="py-2 font-mono text-xs">{sec.characteristics}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ── Imports / Exports Tab ──────────────────────────────────────────────────

function ImportsExportsTab({ data }: { data: ImportsExportsResult | null }) {
  if (!data) return <p className="text-sm text-muted-foreground">No import/export data.</p>

  return (
    <div className="space-y-6">
      {/* Imports */}
      {data.imports.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Imports ({data.imports.length} DLLs)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.imports.map((dll) => (
              <details key={dll.dll} className="group">
                <summary className="cursor-pointer text-sm font-medium hover:text-foreground/80">
                  {dll.dll}
                  <span className="ml-2 text-xs text-muted-foreground">
                    ({dll.imports.length} function{dll.imports.length !== 1 ? 's' : ''})
                  </span>
                </summary>
                <ul className="mt-2 space-y-0.5 pl-4">
                  {dll.imports.map((imp, i) => (
                    <li key={i} className="text-xs font-mono text-muted-foreground">
                      {imp.name ?? `ordinal_${imp.ordinal}`}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Exports */}
      {data.exports.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Exports ({data.exports.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="pb-2 pr-4 font-medium">Ordinal</th>
                    <th className="pb-2 pr-4 font-medium">Name</th>
                    <th className="pb-2 font-medium">Address</th>
                  </tr>
                </thead>
                <tbody>
                  {data.exports.map((exp, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5 pr-4 font-mono text-xs">{exp.ordinal}</td>
                      <td className="py-1.5 pr-4 font-mono text-xs">
                        {exp.name ?? (exp.forwarder_string ? `→ ${exp.forwarder_string}` : '—')}
                      </td>
                      <td className="py-1.5 font-mono text-xs">
                        0x{exp.address.toString(16).toUpperCase()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {data.imports.length === 0 && data.exports.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No imports or exports found in this file.
        </p>
      )}
    </div>
  )
}

// ── Strings Tab ────────────────────────────────────────────────────────────

function StringsTab({ data }: { data: StringsResult | null }) {
  if (!data) return <p className="text-sm text-muted-foreground">No strings data.</p>

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Strings
          {data.truncated && (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              (showing {data.displayed_count} of {data.total_count})
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.strings.length === 0 ? (
          <p className="text-sm text-muted-foreground">No strings found.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b text-muted-foreground sticky top-0 bg-card">
                  <th className="pb-2 pr-4 font-medium">Offset</th>
                  <th className="pb-2 font-medium">String</th>
                </tr>
              </thead>
              <tbody>
                {data.strings.map((s, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-1 pr-4 font-mono text-xs text-muted-foreground whitespace-nowrap">
                      0x{s.offset.toString(16).toUpperCase()}
                    </td>
                    <td className="py-1 font-mono text-xs break-all">{s.string}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Disassembly Tab ────────────────────────────────────────────────────────

function DisassemblyTab({ data }: { data: DisassemblyResult | null }) {
  if (!data) return <p className="text-sm text-muted-foreground">No disassembly data.</p>

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Disassembly
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {data.architecture} / {data.mode}
            {data.truncated && ` (truncated at ${data.instructions.length} insns)`}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <dt>Section:</dt>
          <dd className="font-mono">{data.section_name}</dd>
          <dt>Offset:</dt>
          <dd className="font-mono">0x{data.offset.toString(16).toUpperCase()}</dd>
          <dt>Bytes:</dt>
          <dd className="font-mono">{data.bytes_count.toLocaleString()}</dd>
          <dt>Instructions:</dt>
          <dd className="font-mono">{data.instructions.length.toLocaleString()}</dd>
        </dl>

        {data.instructions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No instructions found.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm font-mono">
              <thead>
                <tr className="border-b text-muted-foreground sticky top-0 bg-card">
                  <th className="pb-2 pr-4 font-medium text-xs">Address</th>
                  <th className="pb-2 pr-4 font-medium text-xs">Bytes</th>
                  <th className="pb-2 pr-4 font-medium text-xs">Mnemonic</th>
                  <th className="pb-2 font-medium text-xs">Operands</th>
                </tr>
              </thead>
              <tbody>
                {data.instructions.map((insn, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-0.5 pr-4 text-xs text-muted-foreground whitespace-nowrap">
                      0x{insn.address.toString(16).toUpperCase()}
                    </td>
                    <td className="py-0.5 pr-4 text-xs text-muted-foreground">
                      {insn.bytes.slice(0, 16)}
                    </td>
                    <td className="py-0.5 pr-4 text-xs font-semibold">{insn.mnemonic}</td>
                    <td className="py-0.5 text-xs">{insn.operands}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Tab bar ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'pe-structure', label: 'PE Structure' },
  { id: 'imports-exports', label: 'Imports / Exports' },
  { id: 'strings', label: 'Strings' },
  { id: 'disassembly', label: 'Disassembly' },
] as const

// ── Main page component ────────────────────────────────────────────────────

export function AnalysisPage() {
  const { result, loading, error, analyzeFile, clearResult } = useAnalysis()
  const [filePath, setFilePath] = useState('')
  const [activeTab, setActiveTab] = useState<string>('pe-structure')

  const hasResult = result.peStructure !== null

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!filePath.trim()) return
    analyzeFile(filePath.trim())
  }

  function handleClear() {
    setFilePath('')
    clearResult()
    setActiveTab('pe-structure')
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Analysis</h1>

      {/* File input bar */}
      <form
        onSubmit={handleSubmit}
        className="mb-6 flex shrink-0 items-center gap-3"
      >
        <Input
          type="text"
          placeholder="Path to PE/DLL file..."
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          className="flex-1"
        />
        <Button type="submit" disabled={loading || !filePath.trim()}>
          {loading ? 'Analyzing...' : 'Analyze'}
        </Button>
        {hasResult && (
          <Button type="button" variant="ghost" onClick={handleClear}>
            Clear
          </Button>
        )}
      </form>

      {/* Error state */}
      {error && (
        <div className="mb-4 shrink-0 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!hasResult && !loading && !error && (
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-sm text-center">
            <p className="text-muted-foreground">
              Enter a file path and click Analyze to begin
            </p>
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="border-primary size-8 animate-spin rounded-full border-2 border-t-transparent" />
            <p className="text-sm text-muted-foreground">Analyzing file...</p>
          </div>
        </div>
      )}

      {/* Results */}
      {hasResult && !loading && (
        <div className="flex flex-1 flex-col gap-4 overflow-hidden">
          {/* File info summary card */}
          <FileInfoCard result={result} />

          {/* Tab bar */}
          <div className="flex shrink-0 gap-1 border-b">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'border-b-2 border-primary text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto">
            <TabPanel active={activeTab === 'pe-structure'}>
              <PeStructureTab data={result.peStructure} />
            </TabPanel>
            <TabPanel active={activeTab === 'imports-exports'}>
              <ImportsExportsTab data={result.importsExports} />
            </TabPanel>
            <TabPanel active={activeTab === 'strings'}>
              <StringsTab data={result.strings} />
            </TabPanel>
            <TabPanel active={activeTab === 'disassembly'}>
              <DisassemblyTab data={result.disassembly} />
            </TabPanel>
          </div>
        </div>
      )}
    </div>
  )
}
