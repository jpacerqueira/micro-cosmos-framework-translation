import { useState } from 'react'
import { useQuery } from '@apollo/client'
import { Link } from 'react-router-dom'
import { GET_PORTFOLIOS } from '../graphql/queries'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'

const STATUS_FILTERS = ['ALL', 'OPEN', 'BIDDING', 'CLOSED', 'DRAFT', 'ARCHIVED']

function fmt(n) {
  if (n == null) return '—'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(n)
}

export default function PortfolioList() {
  const [statusFilter, setStatusFilter] = useState('ALL')
  const { loading, error, data, refetch } = useQuery(GET_PORTFOLIOS, {
    variables: statusFilter !== 'ALL' ? { status: statusFilter } : {},
  })

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Portfolios</h1>
          <p className="page-subtitle">
            {data ? `${data.portfolios.length} portfolio${data.portfolios.length !== 1 ? 's' : ''}` : ''}
          </p>
        </div>
        <Link to="/create" className="btn btn-primary">+ New Portfolio</Link>
      </div>

      <div className="filter-bar">
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            className={`filter-btn ${statusFilter === s ? 'active' : ''}`}
            onClick={() => { setStatusFilter(s); refetch(s !== 'ALL' ? { status: s } : {}) }}
          >
            {s}
          </button>
        ))}
      </div>

      {loading && <Spinner />}
      {error && <ErrorBanner message={error.message} />}

      {data && (
        <div className="card-grid">
          {data.portfolios.length === 0 && (
            <p style={{ color: '#94a3b8', padding: '2rem 0' }}>No portfolios found.</p>
          )}
          {data.portfolios.map(p => (
            <Link to={`/portfolio/${p.portfolioId}`} key={p.portfolioId} className="portfolio-card">
              <div className="card-top">
                <StatusBadge status={p.status} />
                <span className="phase-tag">{p.projectPhase.replace('_', ' ')}</span>
              </div>
              <h2 className="card-title">{p.name}</h2>
              {p.description && <p className="card-desc">{p.description}</p>}
              <div className="card-meta">
                <div className="meta-item">
                  <span className="meta-label">Cut-off</span>
                  <span className="meta-value">{p.cutOffDate}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Final bid</span>
                  <span className="meta-value">{p.finalBidDate}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
