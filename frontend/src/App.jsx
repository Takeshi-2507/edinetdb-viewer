import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, Building2, TrendingUp, Filter, LineChart, Globe, Bell, Menu, X } from 'lucide-react'
import { api } from './api'
import { useIsLocal } from './hooks/useIsLocal'
import Dashboard from './pages/Dashboard'
import Companies from './pages/Companies'
import CompanyDetail from './pages/CompanyDetail'
import Rankings from './pages/Rankings'
import Screener from './pages/Screener'
import DemoTrade from './pages/DemoTrade'
import USScreener from './pages/USScreener'

const NAV = [
  { to: '/',            icon: LayoutDashboard, label: 'ダッシュボード' },
  { to: '/screener',    icon: Filter,          label: 'スクリーニング' },
  { to: '/us-screener', icon: Globe,           label: '米国株' },
  { to: '/demo-trade',  icon: LineChart,       label: 'デモトレード' },
  { to: '/companies',   icon: Building2,       label: '企業一覧' },
  { to: '/rankings',    icon: TrendingUp,      label: 'ランキング' },
]

/** アラートパネル */
function AlertPanel({ alerts, checkedAt, onClose }) {
  if (!alerts) return null

  const fmtTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  }

  return (
    <div className="alert-panel">
      {/* Header */}
      <div style={{
        padding: '16px 20px', borderBottom: '1px solid var(--border)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>
            売り時アラート
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
            最終チェック: {fmtTime(checkedAt)}
          </div>
        </div>
        <button onClick={onClose} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-dim)', fontSize: 20, lineHeight: 1,
          textShadow: 'none',
        }}>×</button>
      </div>

      {/* Alert list */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {alerts.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '60px 20px',
            color: 'var(--text-dim)', fontSize: 13,
          }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>✓</div>
            アラートはありません
            <div style={{ fontSize: 11, marginTop: 4 }}>
              保有銘柄が売り目安価格を超えると通知されます
            </div>
          </div>
        ) : (
          alerts.map((alert, i) => (
            <div key={`${alert.securities_code}-${i}`} style={{
              marginBottom: 10, padding: '12px 14px', borderRadius: 8,
              background: 'var(--surface2)',
              borderLeft: `3px solid ${alert.severity === 'danger' ? 'var(--red)' : 'var(--yellow)'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)' }}>
                    {alert.company_name}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 1 }}>
                    {alert.securities_code}
                  </div>
                </div>
                <span style={{
                  padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 700,
                  background: alert.severity === 'danger' ? 'rgba(248,113,113,0.15)' : 'rgba(251,191,36,0.15)',
                  color: alert.severity === 'danger' ? 'var(--red)' : 'var(--yellow)',
                }}>
                  {alert.severity === 'danger' ? '売り検討' : '注意'}
                </span>
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px',
                marginTop: 8, fontSize: 11,
              }}>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>現在値: </span>
                  <span style={{ fontWeight: 600 }}>¥{alert.current_price?.toLocaleString()}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>目安: </span>
                  <span style={{ fontWeight: 500 }}>¥{alert.target_price?.toLocaleString()}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>乖離: </span>
                  <span style={{
                    fontWeight: 700,
                    color: alert.severity === 'danger' ? 'var(--red)' : 'var(--yellow)',
                  }}>+{alert.gap_pct}%</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>含み損益: </span>
                  <span style={{
                    fontWeight: 600,
                    color: alert.unrealized_pnl >= 0 ? 'var(--green)' : 'var(--red)',
                  }}>
                    {alert.unrealized_pnl >= 0 ? '+' : ''}{alert.unrealized_pnl?.toLocaleString()}円
                  </span>
                </div>
              </div>

              <div style={{
                marginTop: 8, fontSize: 11, color: 'var(--text-dim)',
                lineHeight: 1.5,
              }}>
                {alert.message}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default function App() {
  const isLocal = useIsLocal()
  const [menuOpen, setMenuOpen] = useState(false)
  const [alerts, setAlerts] = useState(null)
  const [checkedAt, setCheckedAt] = useState(null)
  const [showAlerts, setShowAlerts] = useState(false)
  const [dismissed, setDismissed] = useState(new Set())
  const location = useLocation()

  // ローカル版テーマクラスを <html> に適用
  useEffect(() => {
    if (isLocal) {
      document.documentElement.classList.add('theme-local')
    } else {
      document.documentElement.classList.remove('theme-local')
    }
  }, [isLocal])

  // ページ遷移時にメニューを閉じる
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  const fetchAlerts = useCallback(() => {
    api.alerts()
      .then(data => {
        setAlerts(data.alerts || [])
        setCheckedAt(data.checked_at)
      })
      .catch(() => {})
  }, [])

  // 初回 + 5分間隔でポーリング
  useEffect(() => {
    fetchAlerts()
    const id = setInterval(fetchAlerts, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchAlerts])

  const activeAlerts = alerts?.filter(a => !dismissed.has(a.securities_code)) || []
  const alertCount = activeAlerts.length

  return (
    <div className="app-layout">
      {/* ===== ローカル版: 地球の背景 ===== */}
      {isLocal && (
        <div
          aria-hidden="true"
          style={{
            position: 'fixed',
            bottom: '-8%',
            right: '-5%',
            width: '55vh',
            height: '55vh',
            backgroundImage: 'url(/earth-bg.svg)',
            backgroundSize: 'contain',
            backgroundRepeat: 'no-repeat',
            backgroundPosition: 'center',
            opacity: 0.6,
            pointerEvents: 'none',
            zIndex: 0,
            animation: 'earth-rotate 120s linear infinite',
          }}
        />
      )}

      {/* ===== モバイル用トップバー (CSSで表示制御) ===== */}
      <header className="mobile-topbar">
        <button
          className="hamburger-btn"
          onClick={() => setMenuOpen(v => !v)}
          aria-label="メニュー"
        >
          {menuOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
        <div className="topbar-title">EDINET DB</div>
        <button
          className="topbar-alert-btn"
          onClick={() => { setShowAlerts(v => !v); fetchAlerts() }}
        >
          <Bell size={18} />
          {alertCount > 0 && <span className="alert-badge-sm">{alertCount}</span>}
        </button>
      </header>

      {/* ===== オーバーレイ (モバイルメニューオープン時) ===== */}
      {menuOpen && (
        <div className="drawer-overlay" onClick={() => setMenuOpen(false)} />
      )}

      {/* ===== サイドバー ===== */}
      <nav className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
        {/* サイドバーの上部アクセント */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 2,
          background: 'linear-gradient(90deg, var(--accent), transparent)',
          pointerEvents: 'none',
        }} />

        <div style={{ padding: '20px 16px 12px', borderBottom: '1px solid var(--border)', position: 'relative' }}>
          <div style={{
            fontWeight: 800, fontSize: 16,
            color: 'var(--accent)',
            letterSpacing: '.06em',
          }}>EDINET DB</div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
            {isLocal ? 'Local' : 'Online'}
          </div>
        </div>
        <div style={{ padding: '8px 8px', flex: 1 }}>
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to} to={to} end={to === '/'}
              onClick={() => setMenuOpen(false)}
              style={({ isActive }) => ({
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '9px 12px', borderRadius: 8, marginBottom: 2,
                color: isActive ? 'var(--accent)' : 'var(--text-dim)',
                background: isActive ? 'var(--accent-dim)' : 'transparent',
                fontWeight: isActive ? 600 : 400,
                textDecoration: 'none',
                fontSize: 13,
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                transition: 'all 0.2s ease',
              })}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </div>

        {/* アラートベル */}
        <div style={{ padding: '8px 8px', borderTop: '1px solid var(--border)' }}>
          <button
            onClick={() => { setShowAlerts(v => !v); fetchAlerts(); setMenuOpen(false) }}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, width: '100%',
              padding: '9px 12px', borderRadius: 8, cursor: 'pointer',
              background: alertCount > 0 ? 'rgba(255, 77, 106, 0.08)' : 'transparent',
              border: alertCount > 0 ? '1px solid rgba(255, 77, 106, 0.2)' : '1px solid transparent',
              color: alertCount > 0 ? 'var(--red)' : 'var(--text-dim)',
              fontWeight: alertCount > 0 ? 600 : 400,
              fontSize: 13, textAlign: 'left',
              transition: 'all 0.15s',
              textShadow: 'none',
            }}
          >
            <div style={{ position: 'relative' }}>
              <Bell size={16} />
              {alertCount > 0 && (
                <span style={{
                  position: 'absolute', top: -6, right: -8,
                  width: 16, height: 16, borderRadius: '50%',
                  background: 'var(--red)', color: '#fff',
                  fontSize: 9, fontWeight: 800,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 8px rgba(255, 77, 106, 0.4)',
                }}>
                  {alertCount}
                </span>
              )}
            </div>
            アラート
          </button>
        </div>

        <div style={{
          padding: '12px 16px', borderTop: '1px solid var(--border)',
          fontSize: 10, color: 'var(--text-dim)', letterSpacing: '.03em',
        }}>
          データソース: EDINET DB
        </div>
      </nav>

      {/* ===== メインコンテンツ ===== */}
      <main className="main-content">
        <Routes>
          <Route path="/"              element={<Dashboard />} />
          <Route path="/screener"      element={<Screener />} />
          <Route path="/us-screener"   element={<USScreener />} />
          <Route path="/demo-trade"    element={<DemoTrade />} />
          <Route path="/companies"     element={<Companies />} />
          <Route path="/companies/:id" element={<CompanyDetail />} />
          <Route path="/rankings"      element={<Rankings />} />
        </Routes>
      </main>

      {/* ===== アラートパネル ===== */}
      {showAlerts && (
        <>
          <div
            onClick={() => setShowAlerts(false)}
            style={{
              position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
              background: 'rgba(0,0,0,0.3)', zIndex: 999,
            }}
          />
          <AlertPanel
            alerts={activeAlerts}
            checkedAt={checkedAt}
            onClose={() => setShowAlerts(false)}
          />
        </>
      )}
    </div>
  )
}
