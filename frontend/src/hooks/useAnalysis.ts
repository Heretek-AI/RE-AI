'use client'

import { useCallback, useState } from 'react'

// ── Type definitions (matching backend Pydantic Response models) ─────────

export interface PeStructureResult {
  machine_type: string
  characteristics: string
  is_dll: boolean
  is_exe: boolean
  subsystems: string[]
  sections: {
    name: string
    virtual_address: number
    virtual_size: number
    size_of_raw_data: number
    pointer_to_raw_data: number
    characteristics: string
  }[]
  entry_point: number
  image_base: number
  size_of_image: number
  imphash: string | null
}

export interface ImportsExportsResult {
  imports: {
    dll: string
    imports: {
      name: string | null
      hint: number
      ordinal: number
      address: number
      import_by_ordinal: boolean
    }[]
  }[]
  exports: {
    name: string | null
    ordinal: number
    address: number
    forwarder_string: string | null
  }[]
  has_exceptions: boolean
}

export interface StringsResult {
  strings: { string: string; offset: number }[]
  total_count: number
  displayed_count: number
  truncated: boolean
}

export interface DisassemblyResult {
  architecture: string
  mode: string
  section_name: string
  offset: number
  bytes_count: number
  instructions: {
    address: number
    mnemonic: string
    operands: string
    bytes: string
    size: number
  }[]
  truncated: boolean
}

export interface FileInfoResult {
  path: string
  size_bytes: number
  md5: string
  sha256: string
  is_pe: boolean
  subsystem: string | null
  architecture: string | null
  is_dll: boolean | null
  is_exe: boolean | null
  entry_point: number | null
  timestamp: string | null
}

export interface AnalysisResult {
  peStructure: PeStructureResult | null
  importsExports: ImportsExportsResult | null
  strings: StringsResult | null
  disassembly: DisassemblyResult | null
  fileInfo: FileInfoResult | null
}

export interface UseAnalysisReturn {
  result: AnalysisResult
  loading: boolean
  error: string | null
  analyzeFile: (path: string) => Promise<void>
  clearResult: () => void
}

// ── Generic API fetch helper ────────────────────────────────────────────

export const API_BASE = '/api'

export async function apiFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(errBody.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Initial state ───────────────────────────────────────────────────────

const INITIAL_RESULT: AnalysisResult = {
  peStructure: null,
  importsExports: null,
  strings: null,
  disassembly: null,
  fileInfo: null,
}

// ── Hook ─────────────────────────────────────────────────────────────────

export function useAnalysis(): UseAnalysisReturn {
  const [result, setResult] = useState<AnalysisResult>(INITIAL_RESULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const analyzeFile = useCallback(async (filePath: string) => {
    setLoading(true)
    setError(null)
    setResult(INITIAL_RESULT)

    try {
      const body = { path: filePath }

      // Fire all four analysis requests in parallel
      const [peStructure, importsExports, strings, disassembly, fileInfo] =
        await Promise.all([
          apiFetch<PeStructureResult>('/analysis/extract-pe-info', body),
          apiFetch<ImportsExportsResult>('/analysis/list-imports-exports', body),
          apiFetch<StringsResult>('/analysis/extract-strings', { ...body, min_length: 5, max_results: 200 }),
          apiFetch<DisassemblyResult>('/analysis/disassemble', {
            ...body,
            section_name: '.text',
            offset: 0,
            size: 256,
          }),
          apiFetch<FileInfoResult>('/analysis/get-file-info', body),
        ])

      setResult({ peStructure, importsExports, strings, disassembly, fileInfo })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'An unexpected error occurred'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  const clearResult = useCallback(() => {
    setResult(INITIAL_RESULT)
    setError(null)
  }, [])

  return { result, loading, error, analyzeFile, clearResult }
}
