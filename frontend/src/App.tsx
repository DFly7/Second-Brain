import { useEffect, useState } from 'react'
import { redirectToAuthentik, devLogin, DEV_AUTH_BYPASS } from './auth'
import Layout from './components/Layout'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

/** Full-viewport placeholder so OAuth callback / session checks don’t flash an empty shell before Layout. */
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
  // Start authenticated immediately if we know the token is still fresh — eliminates the
  // "Signing you in…" splash on normal return visits. Fall back to loading for OAuth callbacks,
  // expired tokens, or missing cookies so the async check/refresh can run.
  const [authState, setAuthState] = useState<AuthState>(() => {
    if (!hasCode && !hasLoggedInCookie()) return 'unauthenticated'
    if (!hasCode && isAccessTokenFresh()) return 'authenticated'
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
        .then(r => {
          _callbackInflight = false
          sessionStorage.removeItem('pkce_verifier')
          sessionStorage.removeItem('oauth_state')
          window.history.replaceState({}, '', '/')
          setAuthState(r.ok ? 'authenticated' : 'unauthenticated')
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

    if (!hasLoggedInCookie()) return  // already initialised as unauthenticated above

    // Strict Mode runs this effect twice: first pass clears the URL during callback handling,
    // second pass would hit /me before cookies exist and redirect back to Authentik.
    if (_callbackInflight) return

    if (isAccessTokenFresh()) {
      // Token is fresh — already started as authenticated. Silently revalidate in the background
      // so a clock-skewed or otherwise invalid cookie gets caught without blocking the UI.
      fetch('/api/auth/me', { credentials: 'include' }).then(r => {
        if (!r.ok) setAuthState('unauthenticated')
      })
      return
    }

    fetch('/api/auth/me', { credentials: 'include' }).then(async r => {
      if (r.ok) { setAuthState('authenticated'); return }
      const refresh = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      setAuthState(refresh.ok ? 'authenticated' : 'unauthenticated')
    })
  }, [])

  useEffect(() => {
    if (authState === 'unauthenticated' && !DEV_AUTH_BYPASS) redirectToAuthentik()
  }, [authState])

  if (authState === 'authenticated') return <Layout />

  if (authState === 'unauthenticated' && DEV_AUTH_BYPASS) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0d1117' }}>
        <button
          onClick={() => devLogin().then(() => setAuthState('authenticated'))}
          style={{ padding: '10px 24px', fontSize: 14, cursor: 'pointer', borderRadius: 6, border: '1px solid #30363d', background: '#21262d', color: '#c9d1d9' }}
        >
          Dev Login
        </button>
      </div>
    )
  }

  const splashLabel =
    authState === 'unauthenticated' ? 'Redirecting to sign in…' : 'Signing you in…'

  return <AuthGateSplash label={splashLabel} />
}
