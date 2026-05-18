import type React from 'react'
import { Link, useMatch } from 'react-router-dom'
import { logout } from '../auth'

interface TopBarProps {
  agentStatus?: string | null
  onShowIngest?: () => void
}

export default function TopBar({ agentStatus, onShowIngest }: TopBarProps) {
  const onWiki = useMatch({ path: '/wiki', end: true })
  const onFiles = useMatch({ path: '/files', end: true })
  const onAutomations = useMatch({ path: '/automations', end: true })
  const onBrowserChat = useMatch({ path: '/browser-chat', end: true })

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '8px 16px',
        background: '#161b22',
        borderBottom: '1px solid #30363d',
        gap: 12,
        flexShrink: 0,
      }}
    >
      <span style={{ fontWeight: 600, fontSize: 15, color: '#e6edf3' }}>LLM Wiki</span>

      <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
        <Link
          to="/wiki"
          style={{
            padding: '4px 12px',
            borderRadius: 6,
            fontSize: 13,
            textDecoration: 'none',
            border: `1px solid ${onWiki ? '#58a6ff' : '#30363d'}`,
            color: onWiki ? '#58a6ff' : '#8b949e',
            background: onWiki ? '#1f3a5f' : 'transparent',
          }}
        >
          Wiki
        </Link>
        <Link
          to="/files"
          style={{
            padding: '4px 12px',
            borderRadius: 6,
            fontSize: 13,
            textDecoration: 'none',
            border: `1px solid ${onFiles ? '#58a6ff' : '#30363d'}`,
            color: onFiles ? '#58a6ff' : '#8b949e',
            background: onFiles ? '#1f3a5f' : 'transparent',
          }}
        >
          Files
        </Link>
        <Link
          to="/automations"
          style={{
            padding: '4px 12px',
            borderRadius: 6,
            fontSize: 13,
            textDecoration: 'none',
            border: `1px solid ${onAutomations ? '#58a6ff' : '#30363d'}`,
            color: onAutomations ? '#58a6ff' : '#8b949e',
            background: onAutomations ? '#1f3a5f' : 'transparent',
          }}
        >
          Automations
        </Link>
        <Link
          to="/browser-chat"
          style={{
            padding: '4px 12px',
            borderRadius: 6,
            fontSize: 13,
            textDecoration: 'none',
            border: `1px solid ${onBrowserChat ? '#58a6ff' : '#30363d'}`,
            color: onBrowserChat ? '#58a6ff' : '#8b949e',
            background: onBrowserChat ? '#1f3a5f' : 'transparent',
          }}
        >
          Browser
        </Link>
      </div>

      {onWiki && agentStatus && (
        <span style={{ fontSize: 12, color: '#58a6ff', marginLeft: 8 }}>⟳ {agentStatus}</span>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
        {onWiki && onShowIngest && (
          <button type="button" onClick={onShowIngest} style={btnStyle}>
            + Ingest
          </button>
        )}
        <button type="button" onClick={logout} style={btnStyle}>
          Sign out
        </button>
      </div>
    </div>
  )
}

const btnStyle: React.CSSProperties = {
  padding: '4px 12px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 6,
  color: '#e6edf3',
  cursor: 'pointer',
  fontSize: 13,
}
