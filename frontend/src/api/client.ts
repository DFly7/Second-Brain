const BASE = '/api'

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const opts: RequestInit = { ...options, credentials: 'include' }
  let r = await fetch(url, opts)
  if (r.status !== 401) return r
  const refresh = await fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
  if (!refresh.ok) {
    window.location.href = '/'
    return r
  }
  r = await fetch(url, opts)
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
  if (r.status === 404) return null
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
  const es = new EventSource(`${BASE}/chat/sse`, { withCredentials: true })
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
