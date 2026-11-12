import { useState } from 'react'
import { useMutation } from '@apollo/client'
import { useNavigate, Link } from 'react-router-dom'
import { CREATE_PORTFOLIO, GET_PORTFOLIOS } from '../graphql/queries'
import ErrorBanner from '../components/ErrorBanner'

const PHASES = ['PHASE_1', 'PHASE_2', 'PHASE_3']

const today = () => new Date().toISOString().slice(0, 10)
const inMonths = n => {
  const d = new Date()
  d.setMonth(d.getMonth() + n)
  return d.toISOString().slice(0, 10)
}

export default function CreatePortfolio() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    name: '',
    description: '',
    cutOffDate: inMonths(3),
    finalBidDate: inMonths(6),
    projectPhase: 'PHASE_1',
  })
  const [errors, setErrors] = useState({})

  const [createPortfolio, { loading, error }] = useMutation(CREATE_PORTFOLIO, {
    refetchQueries: [{ query: GET_PORTFOLIOS }],
    onCompleted: data => navigate(`/portfolio/${data.createPortfolio}`),
  })

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }))
    setErrors(e => ({ ...e, [field]: undefined }))
  }

  function validate() {
    const e = {}
    if (!form.name.trim()) e.name = 'Name is required'
    if (!form.cutOffDate) e.cutOffDate = 'Required'
    if (!form.finalBidDate) e.finalBidDate = 'Required'
    if (form.finalBidDate && form.cutOffDate && form.finalBidDate < form.cutOffDate)
      e.finalBidDate = 'Final bid date must be on or after cut-off date'
    return e
  }

  function submit(e) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length) { setErrors(errs); return }
    createPortfolio({ variables: { input: form } })
  }

  return (
    <div style={{ maxWidth: '640px' }}>
      <div className="breadcrumb">
        <Link to="/" className="breadcrumb-link">Portfolios</Link>
        <span className="breadcrumb-sep">›</span>
        <span>New Portfolio</span>
      </div>

      <h1 className="page-title">Create Portfolio</h1>

      {error && <ErrorBanner message={error.message} />}

      <form onSubmit={submit} className="form-card">
        <div className="form-group">
          <label className="form-label" htmlFor="name">Portfolio Name *</label>
          <input
            id="name"
            className={`form-input ${errors.name ? 'input-error' : ''}`}
            value={form.name}
            onChange={e => set('name', e.target.value)}
            placeholder="e.g. London Mixed-Use Portfolio Q4 2025"
          />
          {errors.name && <p className="field-error">{errors.name}</p>}
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="description">Description</label>
          <textarea
            id="description"
            className="form-input"
            rows={3}
            value={form.description}
            onChange={e => set('description', e.target.value)}
            placeholder="Brief description of the portfolio's assets and strategy"
          />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label" htmlFor="cutOff">Cut-off Date *</label>
            <input
              id="cutOff"
              type="date"
              className={`form-input ${errors.cutOffDate ? 'input-error' : ''}`}
              value={form.cutOffDate}
              min={today()}
              onChange={e => set('cutOffDate', e.target.value)}
            />
            {errors.cutOffDate && <p className="field-error">{errors.cutOffDate}</p>}
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="finalBid">Final Bid Date *</label>
            <input
              id="finalBid"
              type="date"
              className={`form-input ${errors.finalBidDate ? 'input-error' : ''}`}
              value={form.finalBidDate}
              min={form.cutOffDate || today()}
              onChange={e => set('finalBidDate', e.target.value)}
            />
            {errors.finalBidDate && <p className="field-error">{errors.finalBidDate}</p>}
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="phase">Project Phase *</label>
          <select
            id="phase"
            className="form-input"
            value={form.projectPhase}
            onChange={e => set('projectPhase', e.target.value)}
          >
            {PHASES.map(ph => <option key={ph} value={ph}>{ph.replace('_', ' ')}</option>)}
          </select>
        </div>

        <div className="form-actions">
          <Link to="/" className="btn btn-secondary">Cancel</Link>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Creating…' : 'Create Portfolio'}
          </button>
        </div>
      </form>
    </div>
  )
}
