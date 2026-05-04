import { useEffect, useState } from 'react'
import { redirectToAuthentik } from './auth'
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

// Module-level flag: Strict Mode runs the auth effect twice. During POST /auth/callback the second
// pass must not call /me (cookies not set yet) or duplicate the token exchange.
let _callbackInflight = false

export default function App() {
  const [authState, setAuthState] = useState<AuthState>('loading')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')

    if (code) {
      if (_callbackInflight) return
      _callbackInflight = true
      const verifier = sessionStorage.getItem('pkce_verifier') ?? ''
      fetch('/api/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code, code_verifier: verifier }),
      })
        .then(r => {
          _callbackInflight = false
          sessionStorage.removeItem('pkce_verifier')
          window.history.replaceState({}, '', '/')
          setAuthState(r.ok ? 'authenticated' : 'unauthenticated')
        })
        .catch(() => {
          _callbackInflight = false
          sessionStorage.removeItem('pkce_verifier')
          window.history.replaceState({}, '', '/')
          setAuthState('unauthenticated')
        })
      return
    }

    // Strict Mode runs this effect twice: first pass clears the URL during callback handling,
    // second pass would hit /me before cookies exist and redirect back to Authentik.
    if (_callbackInflight) return

    fetch('/api/auth/me', { credentials: 'include' }).then(async r => {
      if (r.ok) { setAuthState('authenticated'); return }
      const refresh = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      setAuthState(refresh.ok ? 'authenticated' : 'unauthenticated')
    })
  }, [])

  useEffect(() => {
    if (authState === 'unauthenticated') redirectToAuthentik()
  }, [authState])

  if (authState === 'authenticated') return <Layout />

  const splashLabel =
    authState === 'unauthenticated' ? 'Redirecting to sign in…' : 'Signing you in…'

  return <AuthGateSplash label={splashLabel} />
}
