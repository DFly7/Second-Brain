import { useState } from 'react'
import { login } from './api/client'

export default function App() {
  const [authed, setAuthed] = useState(!!localStorage.getItem('token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (!authed) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div style={{ background: '#161b22', padding: 32, borderRadius: 12, width: 320, border: '1px solid #30363d' }}>
        <h2 style={{ marginBottom: 24, color: '#e6edf3' }}>LLM Wiki</h2>
        <input value={email} onChange={e => setEmail(e.target.value)}
          placeholder="Email" style={inputStyle} />
        <input value={password} onChange={e => setPassword(e.target.value)}
          placeholder="Password" type="password" style={inputStyle} />
        <button onClick={() => login(email, password).then(() => setAuthed(true))}
          style={btnStyle}>Login</button>
      </div>
    </div>
  )

  return <div style={{ padding: 24 }}>Logged in — UI coming next.</div>
}

const inputStyle = { width: '100%', marginBottom: 12, padding: '8px 12px', background: '#0d1117',
  border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 14, display: 'block' }
const btnStyle = { width: '100%', padding: '10px 0', background: '#238636', border: 'none',
  borderRadius: 6, color: '#fff', fontSize: 14, cursor: 'pointer' }
