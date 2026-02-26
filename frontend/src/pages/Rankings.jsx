import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'

function fmtAmt(v) {
  if (v == null) return '–'
  const n = Number(v)
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}兆円`
  if (Math.abs(n) >= 1e8)  return `${(n / 1e8).toFixed(1)}億円`
  return `${n.toLocaleString('ja-JP')}円`
}

const METRICS = [
  { value: 'roe',              label: 'ROE',           fmt: v => `${(Number(v) * 100).toFixed(1)}%` },
  { value: 'equity_ratio',     label: '自己資本比率',   fmt: v => `${(Number(v) * 100).toFixed(1)}%` },
  { value: 'revenue',          label: '売上高',         fmt: v => fmtAmt(v) },
  { value: 'net_income',       label: '純利益',         fmt: v => fmtAmt(v) },
  { value: 'operating_income', label: '営業利益',       fmt: v => fmtAmt(v) },
  { value: 'eps',              label: 'EPS',           fmt: v => `¥${Number(v).toFixed(2)}` },
  { value: 'bps',              label: 'BPS',           fmt: v => `¥${Number(v).toFixed(0)}` },
  { value: 'per',              label: 'PER',           fmt: v => `${Number(v).toFixed(1)}倍` },
  { value: 'credit_score',     label: '信用スコア',     fmt: v => Number(v).toFixed(0) },
]

export default function Rankings() {
  const isMobile = useIsMobile()
  const [metric, setMetric] = useState('roe')
  const [limit, setLimit] = useState(30)

  const metaObj = METRICS.find(m => m.value === metric)
  const fetcher = useCallback(() => api.ranking(metric, { limit }), [metric, limit])
  const { data, loading, error } = useFetch(fetcher, [metric, limit])

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>ランキング</h1>

      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <select value={metric} onChange={e => setMetric(e.target.value)}>
          {METRICS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <select value={limit} onChange={e => setLimit(Number(e.target.value))}>
          <option value={30}>上位30社</option>
          <option value={50}>上位50社</option>
          <option value={100}>上位100社</option>
          <option value={200}>上位200社</option>
        </select>
      </div>

      {error && <div style={{ color: 'var(--red)', marginBottom: 12 }}>エラー: {error}</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
        ) : (
          <>
            <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', fontSize: 12, color: 'var(--text-dim)' }}>
              {metaObj?.label} ランキング{data?.fiscal_year ? `（${data.fiscal_year}年度）` : ''}
            </div>
            <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}>順位</th>
                  <th>企業名</th>
                  {!isMobile && <th>業種</th>}
                  {!isMobile && <th>証券コード</th>}
                  <th style={{ textAlign: 'right' }}>{metaObj?.label}</th>
                </tr>
              </thead>
              <tbody>
                {data?.ranking?.map((row, i) => (
                  <tr key={row.edinet_code}>
                    <td style={{ color: i < 3 ? 'var(--yellow)' : 'var(--text-dim)', fontWeight: i < 3 ? 700 : 400 }}>
                      {i + 1}
                    </td>
                    <td>
                      <Link to={`/companies/${row.edinet_code}`} style={{ fontWeight: 500 }}>
                        {row.company_name}
                      </Link>
                    </td>
                    {!isMobile && <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>{row.industry || '–'}</td>}
                    {!isMobile && <td className="number" style={{ fontSize: 12 }}>{row.securities_code || '–'}</td>}
                    <td className="number" style={{ textAlign: 'right', fontWeight: 600, color: 'var(--accent)' }}>
                      {metaObj?.fmt(row.value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
