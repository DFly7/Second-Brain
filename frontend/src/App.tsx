import { useEffect, useState } from 'react'
import { redirectToAuthentik } from './auth'
import Layout from './components/Layout'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

// Module-level flag prevents React StrictMode's double-invoke from firing
// the OIDC callback twice (second run has no verifier and would 401).
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
      sessionStorage.removeItem('pkce_verifier')
      window.history.replaceState({}, '', '/')
      fetch('/api/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ code, code_verifier: verifier }),
      }).then(r => {
        _callbackInflight = false
        setAuthState(r.ok ? 'authenticated' : 'unauthenticated')
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
    if (authState === 'unauthenticated') redirectToAuthentik()
  }, [authState])

  if (authState !== 'authenticated') return null
  return <Layout />
}
