import { Routes, Route, Link, useLocation } from 'react-router-dom'
import PortfolioList from './pages/PortfolioList'
import PortfolioDetail from './pages/PortfolioDetail'
import CreatePortfolio from './pages/CreatePortfolio'

export default function App() {
  const location = useLocation()

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="logo">
            <span className="logo-icon">🏢</span>
            <span className="logo-text">CAN Portfolio</span>
          </Link>
          <nav className="nav">
            <Link to="/" className={location.pathname === '/' ? 'nav-link active' : 'nav-link'}>
              Portfolios
            </Link>
            <Link to="/create" className={location.pathname === '/create' ? 'nav-link active' : 'nav-link'}>
              + New Portfolio
            </Link>
          </nav>
        </div>
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<PortfolioList />} />
          <Route path="/portfolio/:id" element={<PortfolioDetail />} />
          <Route path="/create" element={<CreatePortfolio />} />
        </Routes>
      </main>

      <footer className="footer">
        <span>CAN — CQRS / Event Sourcing · Axon Framework 4.10 · Spring Boot 3.2</span>
      </footer>
    </div>
  )
}
