export default function ActivityLog({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 360, background: '#161b22',
      borderLeft: '1px solid #30363d', zIndex: 50, display: 'flex', flexDirection: 'column', color: '#e6edf3' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid #30363d' }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Activity</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e',
          cursor: 'pointer', fontSize: 18 }}>×</button>
      </div>
      <div style={{ flex: 1, padding: 16, color: '#8b949e' }}>
        Activity log coming soon.
      </div>
    </div>
  )
}
