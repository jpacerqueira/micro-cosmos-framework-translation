import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@apollo/client'
import { GET_PORTFOLIO, CLOSE_PORTFOLIO, GET_PORTFOLIOS } from '../graphql/queries'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'

function fmt(n) {
  if (n == null) return '—'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(n)
}

export default function PortfolioDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [closing, setClosing] = useState(false)
  const [closeReason, setCloseReason] = useState('')
  const [closeError, setCloseError] = useState(null)

  const { loading, error, data } = useQuery(GET_PORTFOLIO, { variables: { id } })

  const [closePortfolio, { loading: closeLoading }] = useMutation(CLOSE_PORTFOLIO, {
    refetchQueries: [{ query: GET_PORTFOLIOS }],
    onCompleted: () => navigate('/'),
    onError: e => setCloseError(e.message),
  })

  if (loading) return <Spinner />
  if (error) return <ErrorBanner message={error.message} />
  if (!data?.portfolio) return <ErrorBanner message="Portfolio not found." />

  const p = data.portfolio
  const totalValuation = p.properties.reduce((sum, prop) => sum + (prop.valuation ?? 0), 0)
  const allocatedCount = p.properties.filter(pr => pr.allocationStatus === 'ALLOCATED').length

  return (
    <div>
      <div className="breadcrumb">
        <Link to="/" className="breadcrumb-link">Portfolios</Link>
        <span className="breadcrumb-sep">›</span>
        <span>{p.name}</span>
      </div>

      <div className="page-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
            <h1 className="page-title" style={{ margin: 0 }}>{p.name}</h1>
            <StatusBadge status={p.status} />
          </div>
          {p.description && <p className="page-subtitle">{p.description}</p>}
        </div>
        {p.status !== 'CLOSED' && p.status !== 'ARCHIVED' && (
          <button className="btn btn-danger" onClick={() => setClosing(true)}>
            Close Portfolio
          </button>
        )}
      </div>

      <div className="detail-grid">
        <div className="detail-card">
          <span className="detail-label">Phase</span>
          <span className="detail-value">{p.projectPhase.replace('_', ' ')}</span>
        </div>
        <div className="detail-card">
          <span className="detail-label">Cut-off Date</span>
          <span className="detail-value">{p.cutOffDate}</span>
        </div>
        <div className="detail-card">
          <span className="detail-label">Final Bid Date</span>
          <span className="detail-value">{p.finalBidDate}</span>
        </div>
        <div className="detail-card">
          <span className="detail-label">Properties</span>
          <span className="detail-value">{p.properties.length}</span>
        </div>
        <div className="detail-card">
          <span className="detail-label">Allocated</span>
          <span className="detail-value">{allocatedCount} / {p.properties.length}</span>
        </div>
        <div className="detail-card">
          <span className="detail-label">Total Valuation</span>
          <span className="detail-value">{fmt(totalValuation)}</span>
        </div>
      </div>

      <section className="section">
        <h2 className="section-title">Properties</h2>
        {p.properties.length === 0 ? (
          <p style={{ color: '#94a3b8' }}>No properties in this portfolio.</p>
        ) : (
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>Property</th>
                  <th>Address</th>
                  <th>City</th>
                  <th>Postcode</th>
                  <th>Valuation</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {p.properties.map(pr => (
                  <tr key={pr.propertyId}>
                    <td className="td-name">{pr.name}</td>
                    <td>{pr.addressLine1 ?? '—'}</td>
                    <td>{pr.city ?? '—'}</td>
                    <td><code>{pr.postcode ?? '—'}</code></td>
                    <td className="td-value">{fmt(pr.valuation)}</td>
                    <td><StatusBadge status={pr.allocationStatus ?? 'UNKNOWN'} /></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4} style={{ textAlign: 'right', fontWeight: 600, paddingRight: '1rem' }}>Total</td>
                  <td className="td-value" style={{ fontWeight: 700 }}>{fmt(totalValuation)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      {closing && (
        <div className="modal-overlay" onClick={() => setClosing(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3 className="modal-title">Close Portfolio</h3>
            <p className="modal-body">This will mark <strong>{p.name}</strong> as CLOSED. This action cannot be undone.</p>
            {closeError && <ErrorBanner message={closeError} />}
            <label className="form-label" htmlFor="reason">Reason (optional)</label>
            <textarea
              id="reason"
              className="form-input"
              rows={3}
              value={closeReason}
              onChange={e => setCloseReason(e.target.value)}
              placeholder="e.g. Deal completed, all assets sold"
            />
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={() => setClosing(false)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={closeLoading}
                onClick={() => closePortfolio({ variables: { portfolioId: id, reason: closeReason || null } })}
              >
                {closeLoading ? 'Closing…' : 'Confirm Close'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
