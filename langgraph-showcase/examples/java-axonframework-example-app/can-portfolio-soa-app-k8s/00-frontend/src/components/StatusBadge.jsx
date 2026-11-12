const STATUS_STYLES = {
  OPEN:     { background: '#dcfce7', color: '#166534', border: '#bbf7d0' },
  BIDDING:  { background: '#fef9c3', color: '#854d0e', border: '#fde68a' },
  CLOSED:   { background: '#f1f5f9', color: '#475569', border: '#e2e8f0' },
  ARCHIVED: { background: '#f1f5f9', color: '#94a3b8', border: '#e2e8f0' },
  DRAFT:    { background: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
  ALLOCATED:{ background: '#dcfce7', color: '#166534', border: '#bbf7d0' },
  PENDING:  { background: '#fff7ed', color: '#c2410c', border: '#fed7aa' },
}

export default function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] ?? { background: '#f8fafc', color: '#64748b', border: '#e2e8f0' }
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: '9999px',
      fontSize: '0.75rem',
      fontWeight: 600,
      letterSpacing: '0.05em',
      textTransform: 'uppercase',
      background: style.background,
      color: style.color,
      border: `1px solid ${style.border}`,
    }}>
      {status}
    </span>
  )
}
