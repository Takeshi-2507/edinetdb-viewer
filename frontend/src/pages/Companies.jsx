import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { Search, ChevronLeft, ChevronRight } from 'lucide-react'

function ScoreBadge({ score }) {
  if (score == null) return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>-</span>
  let color = 'var(--text-dim)'
  if (score >= 70) color = 'var(--green)'
  else if (score >= 50) color = '#22d3ee'
  else if (score >= 30) color = 'var(--yellow)'
  else color = 'var(--red)'
  return (
    <span style={{ fontWeight: 700, fontSize: 13, color }}>{score.toFixed(0)}</span>
  )
}

export default function Companies() {
  const [q, setQ] = useState('')
  const [inputVal, setInputVal] = useState('')
  const [industry, setIndustry] = useState('')
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('credit_score')

  const { data: industriesData } = useFetch(api.industries, [])

  const fetcher = useCallback(
    () => api.companies({ q: q || undefined, industry: industry || undefined, page, per_page: 50, sort_by: sortBy }),
    [q, industry, page, sortBy]
  )
  const { data, loading, error } = useFetch(fetcher, [q, industry, page, sortBy])

  const handleSearch = (e) => {
    e.preventDefault()
    setQ(inputVal)
    setPage(1)
  }

  const totalPages = data ? Math.ceil(data.total / 50) : 1

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>企業一覧</h1>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 260px' }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }} />
          <input
            style={{ paddingLeft: 32, width: '100%' }}
            placeholder="企業名・証券コード・EDINETコード"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
          />
        </div>
        <select value={industry} onChange={e => { setIndustry(e.target.value); setPage(1) }} style={{ flex: '0 0 200px' }}>
          <option value="">全業種</option>
          {industriesData?.map(i => (
            <option key={i.industry} value={i.industry}>
              {i.industry} ({i.company_count})
            </option>
          ))}
        </select>
        <select value={sortBy} onChange={e => { setSortBy(e.target.value); setPage(1) }} style={{ flex: '0 0 160px' }}>
          <option value="credit_score">信用スコア順</option>
          <option value="takehara">竹原式スコア順</option>
        </select>
        <button type="submit">検索</button>
      </form>

      {error && <div style={{ color: 'var(--red)', marginBottom: 12 }}>エラー: {error}</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
        ) : (
          <>
            <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', color: 'var(--text-dim)', fontSize: 12 }}>
              {data?.total?.toLocaleString()}社 見つかりました
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>企業名</th>
                    <th>証券コード</th>
                    <th>業種</th>
                    <th>会計基準</th>
                    <th>信用スコア</th>
                    <th style={{ cursor: 'pointer' }} onClick={() => { setSortBy(s => s === 'takehara' ? 'credit_score' : 'takehara'); setPage(1) }}>
                      竹原式 {sortBy === 'takehara' ? '▼' : ''}
                    </th>
                    <th>年度数</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.companies?.map(c => (
                    <tr key={c.edinet_code}>
                      <td>
                        <Link to={`/companies/${c.edinet_code}`} style={{ fontWeight: 500 }}>
                          {c.company_name}
                        </Link>
                        <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{c.edinet_code}</div>
                      </td>
                      <td className="number">{c.securities_code ? c.securities_code.slice(0, 4) : '–'}</td>
                      <td style={{ fontSize: 12 }}>{c.industry || '–'}</td>
                      <td style={{ fontSize: 12 }}>{c.accounting_std || '–'}</td>
                      <td>
                        {c.credit_score != null && (
                          <span className={`badge ${c.credit_score >= 70 ? 'badge-green' : c.credit_score >= 40 ? 'badge-blue' : 'badge-red'}`}>
                            {c.credit_score} ({c.credit_rating || ''})
                          </span>
                        )}
                      </td>
                      <td className="number">
                        <ScoreBadge score={c.takehara_score} />
                      </td>
                      <td className="number">{c.fiscal_years ?? '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, padding: 16, borderTop: '1px solid var(--border)' }}>
                <button className="secondary" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>
                  <ChevronLeft size={14} />
                </button>
                <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>{page} / {totalPages}</span>
                <button className="secondary" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
                  <ChevronRight size={14} />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
