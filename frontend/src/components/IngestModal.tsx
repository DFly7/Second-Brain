export default function IngestModal({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', color: '#e6edf3' }}
      onClick={onClose}>
      Ingest modal coming soon.
    </div>
  )
}
