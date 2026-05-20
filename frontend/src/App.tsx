import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { redirectToAuthentik, devLogin, DEV_AUTH_BYPASS, saveAccessToken, getStoredAccessToken, clearStoredTokens } from './auth'
import { AppShell } from './components/shell/AppShell'
import WikiWorkspace from './components/shell/WikiWorkspace'
import FilesView from './components/FilesView'
import AutomationsPage from './components/AutomationsPage'
import BrowserChatPage from './components/BrowserChatPage'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

/** Full-viewport placeholder so OAuth callback / session checks don’t flash an empty shell before AppShell. */
function AuthGateSplash({ label }: { label: string }) {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0d1117',
        color: '#8b949e',
        fontSize: 14,
      }}
    >
      {label}
    </div>
  )
}

function hasLoggedInCookie() {
  return document.cookie.split(';').some(c => c.trim().startsWith('logged_in='))
}

/** Returns true if the access token expiry cookie exists and the token hasn't expired yet. */
function isAccessTokenFresh() {
  const raw = document.cookie.split(';').find(c => c.trim().startsWith('token_expires_at='))
  if (!raw) return false
  const expiresAt = parseInt(raw.split('=')[1], 10)
  return Number.isFinite(expiresAt) && expiresAt > Math.floor(Date.now() / 1000)
}

// Module-level flag: Strict Mode runs the auth effect twice. During POST /auth/callback the second
// pass must not call /me (cookies not set yet) or duplicate the token exchange.
let _callbackInflight = false

export default function App() {
  const hasCode = new URLSearchParams(window.location.search).has('code')
  const [authState, setAuthState] = useState<AuthState>(() => {
    if (!hasCode) {
      // Prefer the sessionStorage token (works even when cookies are stripped by Cloudflare).
      if (getStoredAccessToken()) return 'authenticated'
      if (!hasLoggedInCookie()) return 'unauthenticated'
      if (isAccessTokenFresh()) return 'authenticated'
    }
    return 'loading'
  })

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')

    if (code) {
      if (_callbackInflight) return
      _callbackInflight = true
      const verifier = sessionStorage.getItem('pkce_verifier') ?? ''
      const state = params.get('state') ?? ''
      const expectedState = sessionStorage.getItem('oauth_state') ?? ''
      if (!state || state !== expectedState) {
        _callbackInflight = false
        sessionStorage.removeItem('pkce_verifier')
        sessionStorage.removeItem('oauth_state')
        window.history.replaceState({}, '', '/')
        setAuthState('unauthenticated')
        return
      }
      fetch('/api/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code, code_verifier: verifier }),
      })
        .then(async r => {
          _callbackInflight = false
          sessionStorage.removeItem('pkce_verifier')
          sessionStorage.removeItem('oauth_state')
          window.history.replaceState({}, '', '/')
          if (r.ok) {
            try {
              const data = await r.json()
              if (data.access_token) saveAccessToken(data.access_token, data.expires_in)
            } catch { /* ignore */ }
            setAuthState('authenticated')
          } else {
            setAuthState('unauthenticated')
          }
        })
        .catch(() => {
          _callbackInflight = false
          sessionStorage.removeItem('pkce_verifier')
          sessionStorage.removeItem('oauth_state')
          window.history.replaceState({}, '', '/')
          setAuthState('unauthenticated')
        })
      return
    }

    if (!hasLoggedInCookie() && !getStoredAccessToken()) return  // already initialised as unauthenticated above

    if (_callbackInflight) return

    const storedToken = getStoredAccessToken()
    const meHeaders: Record<string, string> = storedToken ? { Authorization: `Bearer ${storedToken}` } : {}

    if (storedToken || isAccessTokenFresh()) {
      fetch('/api/auth/me', { credentials: 'include', headers: meHeaders }).then(r => {
        if (!r.ok) setAuthState('unauthenticated')
      })
      return
    }

    fetch('/api/auth/me', { credentials: 'include', headers: meHeaders }).then(async r => {
      if (r.ok) { setAuthState('authenticated'); return }
      const refresh = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      if (refresh.ok) {
        try {
          const data = await refresh.clone().json()
          if (data.access_token) saveAccessToken(data.access_token, data.expires_in)
        } catch { /* ignore */ }
        setAuthState('authenticated')
      } else {
        setAuthState('unauthenticated')
      }
    })
  }, [])

  useEffect(() => {
    const handler = () => { clearStoredTokens(); setAuthState('unauthenticated') }
    window.addEventListener('auth:unauthenticated', handler)
    return () => window.removeEventListener('auth:unauthenticated', handler)
  }, [])

  useEffect(() => {
    if (authState === 'unauthenticated' && !DEV_AUTH_BYPASS) redirectToAuthentik()
  }, [authState])

  if (authState === 'authenticated') {
    return (
      <>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/wiki" element={<WikiWorkspace />} />
              <Route path="/files" element={<FilesView />} />
              <Route path="/automations" element={<AutomationsPage />} />
              <Route path="/browser-chat" element={<BrowserChatPage />} />
              <Route path="*" element={<Navigate to="/wiki" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster position="bottom-right" theme="dark" />
      </>
    )
  }

  if (authState === 'unauthenticated' && DEV_AUTH_BYPASS) {
    return (
      <>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0d1117' }}>
          <button
            onClick={() => devLogin().then(() => setAuthState('authenticated'))}
            style={{ padding: '10px 24px', fontSize: 14, cursor: 'pointer', borderRadius: 6, border: '1px solid #30363d', background: '#21262d', color: '#c9d1d9' }}
          >
            Dev Login
          </button>
        </div>
        <Toaster position="bottom-right" theme="dark" />
      </>
    )
  }

  const splashLabel =
    authState === 'unauthenticated' ? 'Redirecting to sign in…' : 'Signing you in…'

  return (
    <>
      <AuthGateSplash label={splashLabel} />
      <Toaster position="bottom-right" theme="dark" />
    </>
  )
}
