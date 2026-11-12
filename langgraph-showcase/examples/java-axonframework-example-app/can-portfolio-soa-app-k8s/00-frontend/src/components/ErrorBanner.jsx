export default function ErrorBanner({ message }) {
  return (
    <div style={{
      background: '#fef2f2',
      border: '1px solid #fecaca',
      borderRadius: '8px',
      color: '#b91c1c',
      padding: '1rem 1.25rem',
      marginBottom: '1.5rem',
      fontSize: '0.9rem',
    }}>
      <strong>Error: </strong>{message}
    </div>
  )
}
