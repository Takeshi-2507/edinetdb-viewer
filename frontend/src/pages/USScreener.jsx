import { useState, useCallback } from 'react'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'

function fmtUSD(v) {
  if (v == null) return '-'
  return `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtCap(v) {
  if (v == null) return '-'
  const n = Number(v)
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toLocaleString('en-US')}`
}

function pct(v, digits = 1) {
  if (v == null) return '-'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function ScoreBar({ score }) {
  const ratio = Math.min(100, (score / 100) * 100)
  const color = score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : score >= 30 ? 'var(--accent)' : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 50, height: 5, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${ratio}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontWeight: 700, fontSize: 12, color, minWidth: 26 }}>{score}</span>
    </div>
  )
}

const US_COLUMNS = [
  { key: 'company_name', label: 'Company', align: 'left', defaultDir: 'asc' },
  { key: 'sector',       label: 'Sector', align: 'left', defaultDir: 'asc' },
  { key: 'score',        label: 'Score', align: 'right', defaultDir: 'desc' },
  { key: 'per',          label: 'PER', align: 'right', defaultDir: 'asc' },
  { key: 'pbr',          label: 'PBR', align: 'right', defaultDir: 'asc' },
  { key: 'roe',          label: 'ROE', align: 'right', defaultDir: 'desc' },
  { key: 'operating_margin', label: 'OPM', align: 'right', defaultDir: 'desc' },
  { key: 'dividend',     label: 'Div $', align: 'right', defaultDir: 'desc' },
  { key: 'market_cap',   label: 'MCap', align: 'right', defaultDir: 'desc' },
]

const PRESETS = {
  all: { label: 'ALL', desc: '全銘柄表示', params: {} },
  takehara: { label: 'Value', desc: 'PER20以下 / PBR3以下 / ROE8%以上', params: { per_max: 20, pbr_max: 3, roe_min: 0.08 } },
  income: { label: 'Income', desc: '配当$2以上 / ROE5%以上', params: { dividend_min: 2, roe_min: 0.05 } },
  growth: { label: 'Growth', desc: 'ROE15%以上 / 営業利益率10%以上', params: { roe_min: 0.15, operating_margin_min: 0.1 } },
}

export default function USScreener() {
  const isMobile = useIsMobile()
  const [preset, setPreset] = useState('all')
  const [filters, setFilters] = useState({})
  const [sortBy, setSortBy] = useState('score')
  const [sortDir, setSortDir] = useState('desc')
  const [appliedParams, setAppliedParams] = useState({ sort_by: 'score', sort_dir: 'desc' })

  const fetcher = useCallback(() => {
    const p = { ...appliedParams }
    // remove empty values
    for (const [k, v] of Object.entries(p)) {
      if (v === '' || v === null || v === undefined || v === false) delete p[k]
    }
    return api.usScreener(p)
  }, [appliedParams])

  const { data, loading, error } = useFetch(fetcher, [appliedParams])

  function applyPreset(key) {
    setPreset(key)
    const p = PRESETS[key]?.params || {}
    setFilters(p)
    setAppliedParams({ ...p, sort_by: sortBy, sort_dir: sortDir })
  }

  function handleApply() {
    setAppliedParams({ ...filters, sort_by: sortBy, sort_dir: sortDir })
  }

  function handleSort(colKey) {
    const col = US_COLUMNS.find(c => c.key === colKey)
    if (!col) return
    let newDir
    if (sortBy === colKey) {
      newDir = sortDir === 'asc' ? 'desc' : 'asc'
    } else {
      newDir = col.defaultDir
    }
    setSortBy(colKey)
    setSortDir(newDir)
    setAppliedParams(prev => ({ ...prev, sort_by: colKey, sort_dir: newDir }))
  }

  function getSortIcon(colKey) {
    if (sortBy !== colKey) return <span style={{ opacity: 0.25, marginLeft: 2, fontSize: 10 }}>&#x25B2;&#x25BC;</span>
    return <span style={{ marginLeft: 3, fontSize: 10, color: 'var(--accent)' }}>{sortDir === 'asc' ? '▲' : '▼'}</span>
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 22 }}>🇺🇸</span> 米国株スクリーニング
      </h1>
      <p style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16 }}>
        S&P500主要75銘柄に竹原式スコアリングを適用 (Yahoo Finance リアルタイム)
      </p>

      {/* プリセット */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {Object.entries(PRESETS).map(([key, { label, desc }]) => (
          <button key={key} onClick={() => applyPreset(key)}
            title={desc}
            style={{
              padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer',
              border: preset === key ? '1.5px solid var(--accent)' : '1px solid var(--border)',
              background: preset === key ? 'var(--accent-dim)' : 'var(--surface)',
              color: preset === key ? 'var(--accent)' : 'var(--text)',
            }}
          >{label}</button>
        ))}
      </div>

      {/* フィルタ */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
          フィルタ
          {preset !== 'all' && (
            <span style={{ fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8, fontSize: 11 }}>
              {PRESETS[preset]?.desc}
            </span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(auto-fill, minmax(160px, 1fr))', gap: isMobile ? 8 : 10 }}>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>PER上限</span>
            <input type="number" step="1" placeholder="例: 20"
              value={filters.per_max || ''} onChange={e => { setFilters(f => ({ ...f, per_max: e.target.value })); setPreset('custom') }} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>PBR上限</span>
            <input type="number" step="0.5" placeholder="例: 3"
              value={filters.pbr_max || ''} onChange={e => { setFilters(f => ({ ...f, pbr_max: e.target.value })); setPreset('custom') }} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>ROE下限</span>
            <input type="number" step="0.01" placeholder="例: 0.08"
              value={filters.roe_min || ''} onChange={e => { setFilters(f => ({ ...f, roe_min: e.target.value })); setPreset('custom') }} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>営業利益率下限</span>
            <input type="number" step="0.01" placeholder="例: 0.1"
              value={filters.operating_margin_min || ''} onChange={e => { setFilters(f => ({ ...f, operating_margin_min: e.target.value })); setPreset('custom') }} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>配当下限 ($)</span>
            <input type="number" step="0.5" placeholder="例: 2"
              value={filters.dividend_min || ''} onChange={e => { setFilters(f => ({ ...f, dividend_min: e.target.value })); setPreset('custom') }} />
          </label>
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, paddingTop: 16 }}>
            <input type="checkbox" checked={!!filters.fcf_positive}
              onChange={e => { setFilters(f => ({ ...f, fcf_positive: e.target.checked })); setPreset('custom') }} />
            <span>FCF正のみ</span>
          </label>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button onClick={handleApply} style={{
            padding: '8px 24px', borderRadius: 6, background: 'var(--accent)', color: '#fff',
            border: 'none', fontWeight: 600, cursor: 'pointer',
          }}>スクリーニング実行</button>
          <button onClick={() => applyPreset('all')} style={{
            padding: '8px 16px', borderRadius: 6, background: 'var(--surface2)',
            border: '1px solid var(--border)', cursor: 'pointer', fontSize: 12,
          }}>リセット</button>
        </div>
      </div>

      {error && <div style={{ color: 'var(--red)', marginBottom: 12 }}>エラー: {error}</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <span className="spinner" />
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 8 }}>
              Yahoo Financeからリアルタイムデータを取得中...（初回は30秒程度かかります）
            </div>
          </div>
        ) : (
          <>
            <div style={{
              padding: '10px 16px', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {data?.total ?? 0}銘柄 / {data?.universe_size ?? 0}銘柄中
                {data?.fetched && data.fetched < data.universe_size && (
                  <span style={{ marginLeft: 6, color: 'var(--yellow)' }}>
                    ({data.fetched}銘柄取得成功)
                  </span>
                )}
              </span>
              {data?.sectors?.length > 0 && (
                <select
                  value={filters.sector || ''}
                  onChange={e => {
                    setFilters(f => ({ ...f, sector: e.target.value }))
                    setPreset('custom')
                    setAppliedParams(prev => ({ ...prev, sector: e.target.value }))
                  }}
                  style={{
                    padding: '3px 8px', fontSize: 11, borderRadius: 4,
                    background: 'var(--surface2)', border: '1px solid var(--border)',
                    color: 'var(--text)',
                  }}
                >
                  <option value="">All Sectors</option>
                  {data.sectors.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              )}
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ minWidth: isMobile ? 600 : 1100, fontSize: isMobile ? 11 : undefined }}>
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    {US_COLUMNS.map(col => (
                      <th key={col.key}
                        onClick={() => handleSort(col.key)}
                        style={{
                          textAlign: col.align, cursor: 'pointer', userSelect: 'none',
                          whiteSpace: 'nowrap',
                          background: sortBy === col.key ? 'var(--accent-dim, rgba(99,102,241,0.08))' : undefined,
                        }}
                      >
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                          {col.label}
                          {getSortIcon(col.key)}
                        </span>
                      </th>
                    ))}
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Price</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.results?.map((row, i) => {
                    const target = row.target_per15
                    let gapColor = 'var(--text-dim)'
                    let gapLabel = ''
                    if (target && row.price) {
                      const g = ((row.price - target) / target) * 100
                      if (g <= -20) { gapColor = 'var(--green)'; gapLabel = `${g.toFixed(0)}%` }
                      else if (g <= 0) { gapColor = 'var(--green)'; gapLabel = `${g.toFixed(0)}%` }
                      else if (g <= 20) { gapColor = 'var(--yellow)'; gapLabel = `+${g.toFixed(0)}%` }
                      else { gapColor = 'var(--red)'; gapLabel = `+${g.toFixed(0)}%` }
                    }
                    return (
                      <tr key={row.ticker}>
                        <td style={{ color: 'var(--text-dim)', fontSize: 11 }}>{i + 1}</td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{row.ticker}</div>
                          <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{row.company_name}</div>
                        </td>
                        <td style={{ fontSize: 10, color: 'var(--text-dim)' }}>{row.sector || '-'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <ScoreBar score={row.takehara_score} />
                        </td>
                        <td className="number" style={{ textAlign: 'right', fontWeight: 500 }}>
                          {row.per != null ? Number(row.per).toFixed(1) : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {row.pbr != null ? Number(row.pbr).toFixed(2) : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>{pct(row.roe)}</td>
                        <td className="number" style={{ textAlign: 'right' }}>{pct(row.operating_margin)}</td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {row.dividend != null ? `$${Number(row.dividend).toFixed(2)}` : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right', fontSize: 11 }}>
                          {fmtCap(row.market_cap)}
                        </td>
                        <td className="number" style={{ textAlign: 'right', fontWeight: 600 }}>
                          {fmtUSD(row.price)}
                        </td>
                        <td style={{ textAlign: 'right', fontSize: 11 }}>
                          {target ? (
                            <div>
                              <span style={{ color: 'var(--text-dim)' }}>{fmtUSD(target)}</span>
                              <span style={{ marginLeft: 4, fontWeight: 600, color: gapColor, fontSize: 10 }}>
                                {gapLabel}
                              </span>
                            </div>
                          ) : '-'}
                        </td>
                      </tr>
                    )
                  })}
                  {(!data?.results || data.results.length === 0) && !loading && (
                    <tr>
                      <td colSpan={12} style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>
                        条件に一致する銘柄がありません
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
