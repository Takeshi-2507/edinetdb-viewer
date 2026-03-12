import { useState, useCallback } from 'react'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'

const REGIME_COLORS = {
  risk_off: '#f87171', trend_down: '#f87171', inflation: '#fb923c',
  trend_up: '#4ade80', range_bound: '#facc15',
}

const SIGNAL_LABELS = {
  golden_cross: 'GC', death_cross: 'DC', '52w_high': '52H',
  '52w_low': '52L', rsi_over: 'RSI↑', rsi_under: 'RSI↓', momentum_top: 'MOM',
}
const SIGNAL_COLORS = {
  golden_cross: '#4ade80', death_cross: '#f87171', '52w_high': '#4ade80',
  '52w_low': '#fb923c', rsi_over: '#f87171', rsi_under: '#4ade80', momentum_top: '#60a5fa',
}
const SIGNAL_FULL = {
  golden_cross: 'ゴールデンクロス', death_cross: 'デスクロス',
  '52w_high': '52週高値', '52w_low': '52週安値',
  rsi_over: 'RSI買われすぎ', rsi_under: 'RSI売られすぎ', momentum_top: 'モメンタム上位',
}

const CATEGORY_COLORS = {
  growth: '#4ade80', cyclical: '#60a5fa', defensive: '#facc15',
  financial: '#c084fc', other: '#9ca3af',
}

function scoreColor(s) {
  if (s >= 70) return '#4ade80'
  if (s >= 50) return '#facc15'
  if (s >= 30) return '#fb923c'
  return '#f87171'
}

/** 市場概況ヘッダー */
function MarketOverview({ data }) {
  if (!data) return null
  const regime = data.current_regime
  const regimeJa = data.current_regime_ja || regime
  const regimeCol = REGIME_COLORS[regime] || '#9ca3af'

  return (
    <div style={{
      background: 'var(--surface)', borderRadius: 12, padding: '20px 24px',
      border: '1px solid var(--border)', marginBottom: 20,
    }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'center', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 2 }}>現在の局面</div>
          <span style={{
            padding: '4px 14px', borderRadius: 20, fontSize: 14, fontWeight: 700,
            background: `${regimeCol}22`, color: regimeCol, border: `1px solid ${regimeCol}44`,
          }}>{regimeJa}</span>
        </div>
        {data.nikkei225 && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>日経225</div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              {data.nikkei225.value?.toLocaleString()}
              <span style={{
                fontSize: 12, marginLeft: 6,
                color: data.nikkei225.change_pct >= 0 ? '#4ade80' : '#f87171',
              }}>{data.nikkei225.change_pct >= 0 ? '+' : ''}{data.nikkei225.change_pct}%</span>
            </div>
          </div>
        )}
        {data.usdjpy && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>USD/JPY</div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              {data.usdjpy.value?.toFixed(2)}
              <span style={{
                fontSize: 11, marginLeft: 6, padding: '2px 6px', borderRadius: 8,
                background: data.usdjpy.trend === 'yen_weak' ? 'rgba(251,146,60,0.15)' :
                  data.usdjpy.trend === 'yen_strong' ? 'rgba(96,165,250,0.15)' : 'var(--surface2)',
                color: data.usdjpy.trend === 'yen_weak' ? '#fb923c' :
                  data.usdjpy.trend === 'yen_strong' ? '#60a5fa' : 'var(--text-dim)',
              }}>
                {data.usdjpy.trend === 'yen_weak' ? '円安傾向' :
                  data.usdjpy.trend === 'yen_strong' ? '円高傾向' : '安定'}
              </span>
            </div>
          </div>
        )}
      </div>
      {data.recommended_categories?.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: '24px' }}>推奨:</span>
          {data.recommended_categories.map(c => (
            <span key={c.key} style={{
              padding: '2px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
              background: `${CATEGORY_COLORS[c.key] || '#9ca3af'}22`,
              color: CATEGORY_COLORS[c.key] || '#9ca3af',
              border: `1px solid ${CATEGORY_COLORS[c.key] || '#9ca3af'}44`,
            }}>{c.label}</span>
          ))}
        </div>
      )}
    </div>
  )
}

/** 業種ヒートマップ */
function IndustryHeatmap({ industries, onSelect }) {
  const isMobile = useIsMobile()
  if (!industries?.length) return <div style={{ color: 'var(--text-dim)', padding: 20 }}>データ取得中...</div>

  // Group by category
  const byCategory = {}
  for (const ind of industries) {
    const cat = ind.category || 'other'
    if (!byCategory[cat]) byCategory[cat] = []
    byCategory[cat].push(ind)
  }

  const catOrder = ['growth', 'cyclical', 'defensive', 'financial', 'other']

  return (
    <div>
      {catOrder.filter(c => byCategory[c]).map(cat => (
        <div key={cat} style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 12, fontWeight: 700, marginBottom: 8,
            color: CATEGORY_COLORS[cat], display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: CATEGORY_COLORS[cat], display: 'inline-block',
            }} />
            {byCategory[cat][0]?.category_ja || cat}
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(auto-fill, minmax(140px, 1fr))',
            gap: 8,
          }}>
            {byCategory[cat].map(ind => {
              const sc = ind.recommendation_score || 0
              const col = scoreColor(sc)
              return (
                <div key={ind.industry}
                  onClick={() => onSelect(ind.industry)}
                  style={{
                    padding: '10px 12px', borderRadius: 10, cursor: 'pointer',
                    background: `${col}11`, border: `1px solid ${col}33`,
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = `${col}22` }}
                  onMouseLeave={e => { e.currentTarget.style.background = `${col}11` }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                    {ind.industry}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 18, fontWeight: 800, color: col }}>{sc}</span>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 8,
                      background: ind.regime_match === '★推奨' ? 'rgba(74,222,128,0.15)' :
                        ind.regime_match === '⚠非推奨' ? 'rgba(248,113,113,0.15)' : 'var(--surface2)',
                      color: ind.regime_match === '★推奨' ? '#4ade80' :
                        ind.regime_match === '⚠非推奨' ? '#f87171' : 'var(--text-dim)',
                      fontWeight: 600,
                    }}>{ind.regime_match}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
                    {ind.company_count}社 | ROE {ind.avg_roe ?? '-'}%
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** トレンドシグナル銘柄テーブル */
function TrendSignalTable({ signals }) {
  const isMobile = useIsMobile()
  if (!signals?.length) return <div style={{ color: 'var(--text-dim)', padding: 20 }}>シグナルなし</div>

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-dim)', fontSize: 11, fontWeight: 600 }}>コード</th>
            <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-dim)', fontSize: 11, fontWeight: 600 }}>企業名</th>
            {!isMobile && <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-dim)', fontSize: 11, fontWeight: 600 }}>業種</th>}
            <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-dim)', fontSize: 11, fontWeight: 600 }}>シグナル</th>
            <th style={{ textAlign: 'right', padding: '8px 10px', color: 'var(--text-dim)', fontSize: 11, fontWeight: 600 }}>株価</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s, i) => (
            <tr key={`${s.securities_code}-${s.signal_type}-${i}`}
              style={{ borderBottom: '1px solid var(--border)', background: i % 2 ? 'var(--surface)' : 'transparent' }}>
              <td style={{ padding: '8px 10px', fontWeight: 600, fontFamily: 'monospace', fontSize: 12 }}>{s.securities_code}</td>
              <td style={{ padding: '8px 10px', maxWidth: isMobile ? 100 : 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.company_name}</td>
              {!isMobile && <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text-dim)' }}>{s.industry}</td>}
              <td style={{ padding: '8px 10px' }}>
                <span style={{
                  padding: '2px 8px', borderRadius: 8, fontSize: 10, fontWeight: 700,
                  background: `${SIGNAL_COLORS[s.signal_type] || '#9ca3af'}22`,
                  color: SIGNAL_COLORS[s.signal_type] || '#9ca3af',
                }}>{SIGNAL_LABELS[s.signal_type] || s.signal_type}</span>
              </td>
              <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>
                {s.price ? `¥${s.price.toLocaleString()}` : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 業種詳細パネル */
function IndustryDetail({ name, onBack }) {
  const { data, loading } = useFetch(useCallback(() => api.jpTrendIndustry(name), [name]))
  const isMobile = useIsMobile()

  if (loading) return <div style={{ color: 'var(--text-dim)', padding: 20 }}>読み込み中...</div>
  if (!data) return null

  const m = data.metrics || {}

  return (
    <div>
      <button onClick={onBack} style={{
        background: 'none', border: '1px solid var(--border)', borderRadius: 8,
        padding: '6px 14px', color: 'var(--text-dim)', cursor: 'pointer',
        fontSize: 12, marginBottom: 12,
      }}>← 業種一覧に戻る</button>

      <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4, color: 'var(--text)' }}>
        {data.industry}
        <span style={{
          marginLeft: 8, fontSize: 11, padding: '2px 8px', borderRadius: 8,
          background: `${CATEGORY_COLORS[data.category] || '#9ca3af'}22`,
          color: CATEGORY_COLORS[data.category] || '#9ca3af', fontWeight: 600,
        }}>{data.category_ja}</span>
      </h3>

      {/* メトリクス */}
      <div style={{
        display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(4, 1fr)',
        gap: 10, marginBottom: 16, marginTop: 12,
      }}>
        {[
          ['PER平均', m.avg_per, '倍'], ['PER中央値', m.median_per, '倍'],
          ['ROE平均', m.avg_roe, '%'], ['営業利益率', m.avg_operating_margin, '%'],
          ['売上成長率', m.avg_revenue_growth, '%'], ['企業数', m.company_count, '社'],
        ].map(([label, val, unit]) => (
          <div key={label} style={{
            padding: '10px 14px', borderRadius: 8, background: 'var(--surface)',
            border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{label}</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {val != null ? val : '-'}<span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* レジーム適性 */}
      {data.regime_affinity && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 6 }}>局面適性</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(data.regime_affinity).map(([regime, info]) => (
              <span key={regime} style={{
                padding: '3px 10px', borderRadius: 8, fontSize: 11,
                background: info.match === '★推奨' ? 'rgba(74,222,128,0.12)' :
                  info.match === '⚠非推奨' ? 'rgba(248,113,113,0.12)' : 'var(--surface2)',
                color: info.match === '★推奨' ? '#4ade80' :
                  info.match === '⚠非推奨' ? '#f87171' : 'var(--text-dim)',
                fontWeight: 600,
              }}>{info.label} {info.match}</span>
            ))}
          </div>
        </div>
      )}

      {/* 構成銘柄テーブル */}
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 6 }}>構成銘柄</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>コード</th>
              <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>企業名</th>
              <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>PER</th>
              <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>ROE</th>
              {!isMobile && <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>営業利益率</th>}
              <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-dim)', fontSize: 10 }}>シグナル</th>
            </tr>
          </thead>
          <tbody>
            {data.stocks?.map((s, i) => (
              <tr key={s.securities_code} style={{
                borderBottom: '1px solid var(--border)',
                background: i % 2 ? 'var(--surface)' : 'transparent',
              }}>
                <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontWeight: 600 }}>{s.securities_code}</td>
                <td style={{ padding: '6px 8px', maxWidth: isMobile ? 80 : 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.company_name}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{s.per != null ? s.per.toFixed(1) : '-'}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right', color: s.roe >= 15 ? '#4ade80' : s.roe >= 8 ? 'var(--text)' : 'var(--text-dim)' }}>
                  {s.roe != null ? `${s.roe.toFixed(1)}%` : '-'}
                </td>
                {!isMobile && <td style={{ padding: '6px 8px', textAlign: 'right' }}>{s.operating_margin != null ? `${s.operating_margin}%` : '-'}</td>}
                <td style={{ padding: '6px 8px' }}>
                  <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                    {s.signals?.map(sig => (
                      <span key={sig} style={{
                        padding: '1px 5px', borderRadius: 6, fontSize: 9, fontWeight: 700,
                        background: `${SIGNAL_COLORS[sig] || '#9ca3af'}22`,
                        color: SIGNAL_COLORS[sig] || '#9ca3af',
                      }}>{SIGNAL_LABELS[sig] || sig}</span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


export default function JPTrend() {
  const isMobile = useIsMobile()
  const [tab, setTab] = useState('map')
  const [sigFilter, setSigFilter] = useState('')
  const [indFilter, setIndFilter] = useState('')
  const [selectedIndustry, setSelectedIndustry] = useState(null)

  const { data: dashboard } = useFetch(useCallback(() => api.jpTrendDashboard(), []))
  const { data: indData } = useFetch(useCallback(() => api.jpTrendIndustries(), []))
  const { data: sigData } = useFetch(useCallback(
    () => api.jpTrendSignals({ signal_type: sigFilter || undefined, industry: indFilter || undefined, limit: 100 }),
    [sigFilter, indFilter]
  ))

  const tabs = [
    { key: 'map', label: '業種マップ' },
    { key: 'signals', label: 'トレンド銘柄' },
    { key: 'detail', label: '業種詳細' },
  ]

  // Signal summary badges
  const sigSummary = dashboard?.signal_summary || {}

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: isMobile ? '12px 10px' : '20px 24px' }}>
      <h2 style={{
        fontSize: isMobile ? 18 : 22, fontWeight: 800, marginBottom: 16,
        color: 'var(--accent)', letterSpacing: '.04em',
      }}>日本株トレンド</h2>

      <MarketOverview data={dashboard} />

      {/* Signal summary chips */}
      {Object.keys(sigSummary).length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          {Object.entries(sigSummary).map(([type, cnt]) => (
            <span key={type} style={{
              padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
              background: `${SIGNAL_COLORS[type] || '#9ca3af'}15`,
              color: SIGNAL_COLORS[type] || '#9ca3af',
            }}>{SIGNAL_FULL[type] || type}: {cnt}</span>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div style={{
        display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--border)',
        paddingBottom: 0,
      }}>
        {tabs.map(t => (
          <button key={t.key}
            onClick={() => { setTab(t.key); if (t.key !== 'detail') setSelectedIndustry(null) }}
            style={{
              padding: '8px 16px', fontSize: 13, fontWeight: tab === t.key ? 700 : 400,
              color: tab === t.key ? 'var(--accent)' : 'var(--text-dim)',
              background: 'none', border: 'none', cursor: 'pointer',
              borderBottom: tab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'all 0.15s',
            }}
          >{t.label}</button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'map' && (
        <IndustryHeatmap
          industries={indData?.industries}
          onSelect={(name) => { setSelectedIndustry(name); setTab('detail') }}
        />
      )}

      {tab === 'signals' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <select value={sigFilter} onChange={e => setSigFilter(e.target.value)}
              style={{
                padding: '6px 10px', borderRadius: 8, fontSize: 12,
                background: 'var(--surface)', color: 'var(--text)',
                border: '1px solid var(--border)',
              }}>
              <option value="">全シグナル</option>
              {Object.entries(SIGNAL_FULL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            {indData?.industries && (
              <select value={indFilter} onChange={e => setIndFilter(e.target.value)}
                style={{
                  padding: '6px 10px', borderRadius: 8, fontSize: 12,
                  background: 'var(--surface)', color: 'var(--text)',
                  border: '1px solid var(--border)',
                }}>
                <option value="">全業種</option>
                {[...new Set(indData.industries.map(i => i.industry))].sort().map(ind => (
                  <option key={ind} value={ind}>{ind}</option>
                ))}
              </select>
            )}
          </div>
          <TrendSignalTable signals={sigData?.signals} />
        </div>
      )}

      {tab === 'detail' && (
        selectedIndustry ? (
          <IndustryDetail name={selectedIndustry} onBack={() => setSelectedIndustry(null)} />
        ) : (
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 12 }}>業種を選択してください</div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(3, 1fr)',
              gap: 8,
            }}>
              {indData?.industries?.map(ind => (
                <button key={ind.industry}
                  onClick={() => setSelectedIndustry(ind.industry)}
                  style={{
                    padding: '10px 14px', borderRadius: 10, cursor: 'pointer',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    textAlign: 'left', color: 'var(--text)', fontSize: 12,
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)' }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>{ind.industry}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                    {ind.company_count}社 | スコア {ind.recommendation_score}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )
      )}
    </div>
  )
}
