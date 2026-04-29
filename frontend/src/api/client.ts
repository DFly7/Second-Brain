const BASE = '/api'

function token() {
  return localStorage.getItem('token') || ''
}

function headers(extra: Record<string, string> = {}) {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...extra }
}

export async function login(email: string, password: string) {
  const r = await fetch(`${BASE}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  })
  if (!r.ok) throw new Error('Login failed')
  const data = await r.json()
  localStorage.setItem('token', data.access_token)
  return data
}

export async function listPages() {
  const r = await fetch(`${BASE}/wiki/pages`, { headers: headers() })
  return r.json()
}

export async function getPage(slug: string) {
  const r = await fetch(`${BASE}/wiki/pages/${slug}`, { headers: headers() })
  if (r.status === 404) return null
  return r.json()
}

export async function updatePage(slug: string, body: { title?: string; body_md?: string; summary?: string }) {
  const r = await fetch(`${BASE}/wiki/pages/${slug}`, {
    method: 'PUT', headers: headers(), body: JSON.stringify(body)
  })
  return r.json()
}

export async function sendMessage(message: string, sessionId?: string) {
  const r = await fetch(`${BASE}/chat/message`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ message, session_id: sessionId })
  })
  return r.json()
}

export async function ingestText(text: string, title?: string) {
  const r = await fetch(`${BASE}/ingest/text`, {
    method: 'POST', headers: headers(), body: JSON.stringify({ text, title })
  })
  return r.json()
}

export async function ingestUrl(url: string) {
  const r = await fetch(`${BASE}/ingest/url`, {
    method: 'POST', headers: headers(), body: JSON.stringify({ url })
  })
  return r.json()
}

export async function ingestFile(file: File) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${BASE}/ingest/file`, {
    method: 'POST', headers: { Authorization: `Bearer ${token()}` }, body: fd
  })
  return r.json()
}

export async function getActivity(limit = 50) {
  const r = await fetch(`${BASE}/activity/?limit=${limit}`, { headers: headers() })
  return r.json()
}

export function createSSE(onEvent: (data: unknown) => void): () => void {
  const es = new EventSource(`${BASE}/chat/sse?token=${token()}`)
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)) } catch {} }
  return () => es.close()
}

export async function runHealthCheck() {
  const r = await fetch(`${BASE}/health/run`, {
    method: 'POST',
    headers: headers(),
  })
  if (!r.ok) throw new Error('Health check failed to start')
  return r.json()
}
