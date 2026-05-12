export const DEV_AUTH_BYPASS = import.meta.env.VITE_DEV_AUTH_BYPASS === 'true'

const _AT_KEY = 'sb_at'
const _AT_EXP_KEY = 'sb_at_exp'

export function saveAccessToken(token: string, expiresIn?: number | null): void {
  try {
    sessionStorage.setItem(_AT_KEY, token)
    if (expiresIn) {
      sessionStorage.setItem(_AT_EXP_KEY, String(Math.floor(Date.now() / 1000) + expiresIn))
    }
  } catch { /* storage unavailable */ }
}

export function getStoredAccessToken(): string | null {
  try {
    const exp = sessionStorage.getItem(_AT_EXP_KEY)
    if (exp && parseInt(exp, 10) < Math.floor(Date.now() / 1000)) {
      clearStoredTokens()
      return null
    }
    return sessionStorage.getItem(_AT_KEY)
  } catch {
    return null
  }
}

export function clearStoredTokens(): void {
  try {
    sessionStorage.removeItem(_AT_KEY)
    sessionStorage.removeItem(_AT_EXP_KEY)
  } catch { /* ignore */ }
}

const AUTHENTIK_URL = DEV_AUTH_BYPASS ? '' : (import.meta.env.VITE_AUTHENTIK_URL as string ?? '').replace(/\/$/, '')
const CLIENT_ID = DEV_AUTH_BYPASS ? '' : import.meta.env.VITE_AUTHENTIK_CLIENT_ID as string
const REDIRECT_URI = DEV_AUTH_BYPASS ? '' : import.meta.env.VITE_REDIRECT_URI as string

export function generateVerifier(): string {
  const array = new Uint8Array(32)
  crypto.getRandomValues(array)
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

export async function generateChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

export async function devLogin(): Promise<void> {
  await fetch('/api/auth/dev-login', { credentials: 'include' })
}

export async function logout(): Promise<void> {
  clearStoredTokens()
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
  if (DEV_AUTH_BYPASS) {
    window.location.reload()
    return
  }
  const params = new URLSearchParams({
    post_logout_redirect_uri: REDIRECT_URI,
  })
  window.location.href = `${AUTHENTIK_URL}/application/o/${CLIENT_ID}/end-session/?${params}`
}

export async function redirectToAuthentik(): Promise<void> {
  const verifier = generateVerifier()
  const challenge = await generateChallenge(verifier)
  const state = generateVerifier()
  sessionStorage.setItem('pkce_verifier', verifier)
  sessionStorage.setItem('oauth_state', state)
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: 'openid profile email offline_access',
    code_challenge: challenge,
    code_challenge_method: 'S256',
    state,
  })
  window.location.href = `${AUTHENTIK_URL}/application/o/authorize/?${params}`
}
