import { getStoredAccessToken, saveAccessToken } from '../auth'

const BASE = '/api'

/** One in-flight refresh so parallel 401s don't stampede Authentik. */
let refreshInflight: Promise<Response> | null = null

function sleep(ms: number): Promise<void> {
  return new Promise(res => setTimeout(res, ms))
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getStoredAccessToken()
  return token ? { Authorization: `Bearer ${token}`, ...extra } : extra
}

function postRefreshWithRetries(): Promise<Response> {
  if (refreshInflight !== null) return refreshInflight
  const promiseRef: { current: Promise<Response> | null } = { current: null }
  promiseRef.current = (async () => {
    try {
      let last: Response | undefined
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          last = await fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
          if (last.ok) {
            try {
              const data = await last.clone().json()
              if (data.access_token) saveAccessToken(data.access_token, data.expires_in)
            } catch { /* ignore */ }
            return last
          }
        } catch {
          last = undefined
        }
        if (attempt < 2) await sleep(450 * (attempt + 1))
      }
      return last ?? new Response(null, { status: 401 })
    } finally {
      if (refreshInflight === promiseRef.current) refreshInflight = null
    }
  })()
  refreshInflight = promiseRef.current
  return promiseRef.current
}

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const opts: RequestInit = {
    ...options,
    credentials: 'include',
    headers: authHeaders(options.headers as Record<string, string> ?? {}),
  }
  let r = await fetch(url, opts)
  if (r.status !== 401) return r
  const refresh = await postRefreshWithRetries()
  if (!refresh.ok) {
    window.dispatchEvent(new CustomEvent('auth:unauthenticated'))
    return r
  }
  r = await fetch(url, { ...opts, headers: authHeaders(options.headers as Record<string, string> ?? {}) })
  return r
}

function jsonHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { 'Content-Type': 'application/json', ...extra }
}

export async function listPages() {
  const r = await fetchWithAuth(`${BASE}/wiki/pages`)
  return r.json()
}

export async function getPage(slug: string) {
  const r = await fetchWithAuth(`${BASE}/wiki/pages/${slug}`)
  if (r.status === 404) throw Object.assign(new Error('Page not found'), { status: 404 })
  return r.json()
}

export async function updatePage(
  slug: string,
  body: { title?: string; body_md?: string; summary?: string },
) {
  const r = await fetchWithAuth(`${BASE}/wiki/pages/${slug}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  })
  return r.json()
}

export async function sendMessage(
  message: string,
  sessionId?: string,
  mode: 'query' | 'edit' = 'query',
) {
  const r = await fetchWithAuth(`${BASE}/chat/message`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ message, session_id: sessionId, mode }),
  })
  return r.json()
}

export async function ingestText(text: string, title?: string) {
  const r = await fetchWithAuth(`${BASE}/ingest/text`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ text, title }),
  })
  return r.json()
}

export async function ingestUrl(url: string) {
  const r = await fetchWithAuth(`${BASE}/ingest/url`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ url }),
  })
  return r.json()
}

export async function ingestFile(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetchWithAuth(`${BASE}/ingest/file`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error(`ingestFile failed: ${r.status}`)
  return r.json()
}

export async function getActivity(limit = 50) {
  const r = await fetchWithAuth(`${BASE}/activity/?limit=${limit}`)
  return r.json()
}

export function createSSE(onEvent: (data: unknown) => void): () => void {
  const token = getStoredAccessToken()
  const sseUrl = token ? `${BASE}/chat/sse?token=${encodeURIComponent(token)}` : `${BASE}/chat/sse`
  const es = new EventSource(sseUrl, { withCredentials: true })
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data))
    } catch {
      /* ignore parse errors */
    }
  }
  return () => es.close()
}

export async function runHealthCheck() {
  const r = await fetchWithAuth(`${BASE}/health/run`, { method: 'POST' })
  if (!r.ok) throw new Error('Health check failed to start')
  return r.json()
}

export async function listSessions(): Promise<{ id: string; created_at: string }[]> {
  const r = await fetchWithAuth(`${BASE}/chat/sessions`)
  if (!r.ok) throw new Error('Failed to load sessions')
  return r.json()
}

export async function getSessionMessages(
  sessionId: string,
): Promise<{ id: string; role: string; content: string }[]> {
  const r = await fetchWithAuth(`${BASE}/chat/sessions/${sessionId}/messages`)
  if (!r.ok) return []
  return r.json()
}

export interface SourceItem {
  id: string
  kind: string
  filename: string | null
  title: string | null
  description: string | null
  status: string
  has_file: boolean
  has_markdown: boolean
  created_at: string
}

export async function listSources(): Promise<SourceItem[]> {
  const r = await fetchWithAuth(`${BASE}/sources`)
  if (!r.ok) throw new Error(`listSources failed: ${r.status}`)
  return r.json()
}

export async function fetchSourceFile(
  sourceId: string,
  onProgress?: (received: number, total: number | null) => void,
): Promise<Blob> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}/file`)
  if (!r.ok) throw new Error(`fetchSourceFile failed: ${r.status}`)
  if (!onProgress || !r.body) return r.blob()

  const total = r.headers.get('Content-Length') ? parseInt(r.headers.get('Content-Length')!, 10) : null
  const contentType = r.headers.get('Content-Type') ?? undefined
  const reader = r.body.getReader()
  const chunks: BlobPart[] = []
  let received = 0

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    chunks.push(value)
    received += value.length
    onProgress(received, total)
  }

  return new Blob(chunks, { type: contentType })
}

export async function fetchSourceMarkdown(sourceId: string): Promise<string> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}/markdown`)
  if (!r.ok) throw new Error(`fetchSourceMarkdown failed: ${r.status}`)
  return r.text()
}

export async function fetchSourceImage(sourceId: string, filename: string): Promise<Blob> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}/images/${encodeURIComponent(filename)}`)
  if (!r.ok) throw new Error(`fetchSourceImage failed: ${r.status}`)
  return r.blob()
}

export async function patchSource(
  sourceId: string,
  patch: { title?: string; description?: string },
): Promise<SourceItem> {
  const r = await fetchWithAuth(`${BASE}/sources/${sourceId}`, {
    method: 'PATCH',
    headers: jsonHeaders(),
    body: JSON.stringify(patch),
  })
  if (!r.ok) throw new Error(`patchSource failed: ${r.status}`)
  return r.json()
}

// --- Automations ---

export type AutomationStatus = 'pending' | 'running' | 'stopping' | 'completed' | 'failed' | 'stopped'

export interface AutomationRun {
  id: string
  goal: string
  status: AutomationStatus
  created_at: string
  completed_at: string | null
  recording_url: string | null
}

export interface AutomationAction {
  id: string
  type: string
  detail: string
  timestamp: string
}

export interface AutomationRunDetail extends AutomationRun {
  actions: AutomationAction[]
}

export async function startAutomationRun(goal: string): Promise<{ run_id: string; status: string }> {
  const r = await fetchWithAuth(`${BASE}/automations/run`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ goal }),
  })
  if (!r.ok) throw new Error(`startAutomationRun failed: ${r.status}`)
  return r.json()
}

export async function stopAutomationRun(runId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/automations/runs/${runId}/stop`, { method: 'POST' })
  if (!r.ok) throw new Error(`stopAutomationRun failed: ${r.status}`)
}

export async function getAutomationRuns(): Promise<AutomationRun[]> {
  const r = await fetchWithAuth(`${BASE}/automations/runs`)
  if (!r.ok) throw new Error(`getAutomationRuns failed: ${r.status}`)
  return r.json()
}

export async function getAutomationRun(runId: string): Promise<AutomationRunDetail> {
  const r = await fetchWithAuth(`${BASE}/automations/runs/${runId}`)
  if (!r.ok) throw new Error(`getAutomationRun failed: ${r.status}`)
  return r.json()
}

export async function getNovncUrl(): Promise<string> {
  const r = await fetchWithAuth(`${BASE}/automations/novnc-url`)
  if (!r.ok) throw new Error(`getNovncUrl failed: ${r.status}`)
  const data: { url: string } = await r.json()
  return data.url
}

/** window.open cannot send Authorization headers; fetch authenticated blob instead. */
export async function openAutomationRecording(runId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/automations/runs/${runId}/recording`)
  if (!r.ok) throw new Error(`recording failed: ${r.status}`)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.target = '_blank'
  a.rel = 'noopener noreferrer'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

// --- Browser Chat ---

export interface BrowserChatSession {
  id: string
  status: 'active' | 'completed'
  created_at: string
  completed_at: string | null
}

export interface BrowserChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface BrowserChatSessionDetail extends BrowserChatSession {
  messages: BrowserChatMessage[]
}

export async function connectBrowserChat(): Promise<{ session_id: string }> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`, { method: 'POST' })
  if (!r.ok) throw new Error(`connectBrowserChat failed: ${r.status}`)
  return r.json()
}

export async function sendBrowserChatMessage(sessionId: string, content: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/message`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ content }),
  })
  if (!r.ok) throw new Error(`sendBrowserChatMessage failed: ${r.status}`)
}

export async function interruptBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/interrupt`, { method: 'POST' })
  if (!r.ok) throw new Error(`interruptBrowserChat failed: ${r.status}`)
}

export async function disconnectBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/disconnect`, { method: 'POST' })
  if (!r.ok) throw new Error(`disconnectBrowserChat failed: ${r.status}`)
}

export async function recoverBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/recover`, { method: 'POST' })
  if (!r.ok) throw new Error(`recoverBrowserChat failed: ${r.status}`)
}

export async function listBrowserChatSessions(): Promise<BrowserChatSession[]> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`)
  if (!r.ok) throw new Error(`listBrowserChatSessions failed: ${r.status}`)
  return r.json()
}

export async function getBrowserChatSession(sessionId: string): Promise<BrowserChatSessionDetail> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}`)
  if (!r.ok) throw new Error(`getBrowserChatSession failed: ${r.status}`)
  return r.json()
}
