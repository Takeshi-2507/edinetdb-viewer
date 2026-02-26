import { useParams, Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useCallback, useState, useEffect } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { ArrowLeft, ChevronDown, ChevronRight, FileText, Brain, TrendingUp, AlertTriangle } from 'lucide-react'

const fmt = (v, unit = '') => {
  if (v == null) return '–'
  const n = Number(v)
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}兆${unit}`
  if (Math.abs(n) >= 1e8)  return `${(n / 1e8).toFixed(1)}億${unit}`
  if (Math.abs(n) >= 1e4)  return `${(n / 1e4).toFixed(0)}万${unit}`
  return `${n.toLocaleString('ja-JP')}${unit}`
}
// ROE/equity_ratio come from API as decimals like 0.213 = 21.3%
const fmtRatio = (v) => v == null ? '–' : `${(Number(v) * 100).toFixed(1)}%`

function MetricCard({ label, value, sub }) {
  return (
    <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '12px 16px' }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

const TOOLTIP_STYLE = {
  background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8,
  color: 'var(--text)', fontSize: 12,
}

/* セクションアイコンマッピング */
const SECTION_ICONS = {
  '事業方針・経営環境': TrendingUp,
  '事業の内容': FileText,
  '事業等のリスク': AlertTriangle,
  '経営者による分析': Brain,
}

/* 折りたたみ可能テキストブロック */
function TextBlock({ section, text }) {
  const [open, setOpen] = useState(false)
  const Icon = SECTION_ICONS[section] || FileText
  const preview = text.slice(0, 120) + (text.length > 120 ? '…' : '')

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 8, marginBottom: 8,
      overflow: 'hidden', transition: 'all 0.2s',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 16px', background: 'var(--surface2)', border: 'none',
          color: 'var(--text)', cursor: 'pointer', fontSize: 13, fontWeight: 600,
          textAlign: 'left',
        }}
      >
        <Icon size={16} style={{ flexShrink: 0, color: 'var(--accent)' }} />
        <span style={{ flex: 1 }}>{section}</span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {!open && (
        <div style={{
          padding: '8px 16px 12px', fontSize: 12, color: 'var(--text-dim)',
          lineHeight: 1.5, borderTop: '1px solid var(--border)',
        }}>
          {preview}
        </div>
      )}
      {open && (
        <div style={{
          padding: '12px 16px 16px', fontSize: 13, lineHeight: 1.8,
          borderTop: '1px solid var(--border)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          maxHeight: 400, overflowY: 'auto',
        }}>
          {text}
        </div>
      )}
    </div>
  )
}

/* 年度別分析ヒストリー */
function AnalysisHistory({ history }) {
  const [expanded, setExpanded] = useState(false)
  if (!history || history.length === 0) return null

  const sorted = [...history].sort((a, b) => b.fiscal_year - a.fiscal_year)
  const display = expanded ? sorted : sorted.slice(0, 3)

  const ratingColor = (r) => {
    if (r === 'S') return 'var(--green)'
    if (r === 'A') return '#22d3ee'
    if (r === 'B') return 'var(--accent)'
    if (r === 'C') return 'var(--yellow)'
    return 'var(--red)'
  }

  return (
    <div>
      <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
        <TrendingUp size={14} /> 年度別スコア推移
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {display.map(h => (
          <div key={h.fiscal_year} style={{
            display: 'grid', gridTemplateColumns: '60px 50px 1fr',
            gap: 10, alignItems: 'center', padding: '8px 12px',
            background: 'var(--surface2)', borderRadius: 6, fontSize: 12,
          }}>
            <span style={{ fontWeight: 700 }}>FY{h.fiscal_year}</span>
            <span style={{
              fontWeight: 700, color: ratingColor(h.credit_rating),
              textAlign: 'center',
            }}>
              {h.credit_rating} {h.credit_score}
            </span>
            <div style={{ color: 'var(--text-dim)', lineHeight: 1.4 }}>
              {h.investment_summary && (
                <div>{h.investment_summary}</div>
              )}
              {h.credit_summary && h.credit_summary !== h.investment_summary && (
                <div style={{ marginTop: 2, fontSize: 11 }}>{h.credit_summary}</div>
              )}
            </div>
          </div>
        ))}
      </div>
      {sorted.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            display: 'block', margin: '8px auto 0', padding: '4px 16px',
            background: 'none', border: '1px solid var(--border)', borderRadius: 6,
            color: 'var(--text-dim)', cursor: 'pointer', fontSize: 12,
          }}
        >
          {expanded ? '折りたたむ' : `全 ${sorted.length} 年度を表示`}
        </button>
      )}
    </div>
  )
}

/* IR/分析セクション（遅延読み込み） */
function IrSection({ edinetCode }) {
  const [ir, setIr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.companyIr(edinetCode)
      .then(d => { if (!cancelled) setIr(d) })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [edinetCode])

  if (loading) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileText size={16} /> IR・経営情報
        </h2>
        <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-dim)', fontSize: 13 }}>
          <span className="spinner" style={{ marginRight: 8 }} />
          IR情報を取得中...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileText size={16} /> IR・経営情報
        </h2>
        <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: '8px 0' }}>
          IR情報の取得に失敗しました
        </div>
      </div>
    )
  }

  const hasBlocks = ir?.text_blocks?.length > 0
  const hasAnalysis = ir?.analysis
  if (!hasBlocks && !hasAnalysis) return null

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
        <FileText size={16} /> IR・経営情報
      </h2>

      {/* AI分析サマリー */}
      {hasAnalysis && ir.analysis.summary && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(99,102,241,0.08), rgba(59,130,246,0.06))',
          borderRadius: 8, padding: 16, marginBottom: 16,
          border: '1px solid rgba(99,102,241,0.15)',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10,
            fontSize: 12, fontWeight: 600, color: 'var(--accent)',
          }}>
            <Brain size={14} /> AI分析サマリー
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
            {ir.analysis.summary}
          </div>
        </div>
      )}

      {/* 有報テキストブロック */}
      {hasBlocks && (
        <div style={{ marginBottom: hasAnalysis?.history?.length > 0 ? 16 : 0 }}>
          <div style={{
            fontSize: 12, color: 'var(--text-dim)', marginBottom: 8,
            display: 'flex', alignItems: 'center', gap: 4,
          }}>
            有価証券報告書より
          </div>
          {ir.text_blocks.map((tb, i) => (
            <TextBlock key={i} section={tb.section} text={tb.text} />
          ))}
        </div>
      )}

      {/* 年度別スコア推移 */}
      {hasAnalysis && <AnalysisHistory history={ir.analysis.history} />}
    </div>
  )
}

export default function CompanyDetail() {
  const { id } = useParams()
  const fetcher = useCallback(() => api.company(id), [id])
  const { data, loading, error } = useFetch(fetcher, [id])

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
  if (error)   return <div style={{ color: 'var(--red)' }}>エラー: {error}</div>
  if (!data)   return null

  const { company: c, financials: fins, analysis: anal, takehara } = data
  const latest = fins?.[0]

  // チャート用データ（古い順）
  const chartData = [...(fins || [])].reverse().map(f => ({
    year: f.fiscal_year,
    売上高: f.revenue ? +(f.revenue / 1e8).toFixed(1) : null,
    営業利益: f.operating_income ? +(f.operating_income / 1e8).toFixed(1) : null,
    純利益: f.net_income ? +(f.net_income / 1e8).toFixed(1) : null,
    ROE: f.roe != null ? +(Number(f.roe) * 100).toFixed(1) : null,
    自己資本比率: f.equity_ratio != null ? +(Number(f.equity_ratio) * 100).toFixed(1) : null,
  }))

  return (
    <div>
      <Link to="/companies" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-dim)', fontSize: 13, marginBottom: 16 }}>
        <ArrowLeft size={14} /> 企業一覧に戻る
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700 }}>{c.company_name}</h1>
          <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {c.industry && <span className="badge badge-gray">{c.industry}</span>}
            {c.accounting_std && <span className="badge badge-gray">{c.accounting_std}</span>}
            {c.credit_rating && (
              <span className={`badge ${c.credit_score >= 70 ? 'badge-green' : c.credit_score >= 40 ? 'badge-blue' : 'badge-red'}`}>
                信用 {c.credit_score} ({c.credit_rating})
              </span>
            )}
            {takehara && (
              <span className={`badge ${takehara.score >= 70 ? 'badge-green' : takehara.score >= 50 ? 'badge-blue' : takehara.score >= 30 ? 'badge-yellow' : 'badge-red'}`}
                    title={Object.entries(takehara.parts || {}).map(([k, v]) => `${k}: ${v}`).join(', ')}>
                竹原式 {takehara.score}
              </span>
            )}
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>証券コード</div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{c.securities_code || '–'}</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4 }}>EDINETコード: {c.edinet_code}</div>
        </div>
      </div>

      {/* 最新年度サマリ */}
      {latest && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 24 }}>
          <MetricCard label="売上高" value={fmt(latest.revenue, '円')} sub={`FY${latest.fiscal_year}`} />
          <MetricCard label="営業利益" value={fmt(latest.operating_income, '円')} />
          <MetricCard label="経常利益" value={fmt(latest.ordinary_income, '円')} />
          <MetricCard label="純利益" value={fmt(latest.net_income, '円')} />
          <MetricCard label="ROE" value={fmtRatio(latest.roe)} />
          <MetricCard label="自己資本比率" value={fmtRatio(latest.equity_ratio)} />
          <MetricCard label="EPS" value={latest.eps != null ? `¥${Number(latest.eps).toLocaleString('ja-JP', { maximumFractionDigits: 2 })}` : '–'} />
          <MetricCard label="配当" value={latest.dividend != null ? `¥${Number(latest.dividend).toLocaleString()}` : '–'} />
          <MetricCard label="PER" value={latest.per != null ? `${Number(latest.per).toFixed(1)}倍` : '–'} />
          <MetricCard label="BPS" value={latest.bps != null ? `¥${Number(latest.bps).toLocaleString('ja-JP', { maximumFractionDigits: 0 })}` : '–'} />
        </div>
      )}

      {/* IR・経営情報セクション（遅延読み込み） */}
      <IrSection edinetCode={id} />

      {/* 売上・利益チャート */}
      {chartData.length > 1 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>売上・利益推移（億円）</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="売上高" stroke="var(--accent)" dot={false} strokeWidth={2} connectNulls />
              <Line type="monotone" dataKey="営業利益" stroke="var(--green)" dot={false} strokeWidth={2} connectNulls />
              <Line type="monotone" dataKey="純利益" stroke="var(--yellow)" dot={false} strokeWidth={2} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ROE・自己資本比率チャート */}
      {chartData.length > 1 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>ROE・自己資本比率推移（%）</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={v => `${v}%`} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [`${v}%`, n]} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="ROE" stroke="var(--accent)" dot={false} strokeWidth={2} connectNulls />
              <Line type="monotone" dataKey="自己資本比率" stroke="var(--green)" dot={false} strokeWidth={2} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* AI分析（DBからの既存データ） */}
      {anal && (
        <div className="card" style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>AI分析</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10, marginBottom: 16 }}>
            {anal.credit_score != null && (
              <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: anal.credit_score >= 70 ? 'var(--green)' : anal.credit_score >= 40 ? 'var(--yellow)' : 'var(--red)' }}>
                  {Number(anal.credit_score).toFixed(0)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>信用スコア</div>
              </div>
            )}
          </div>
          {anal.ai_summary && (
            <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: 16, fontSize: 13, lineHeight: 1.7 }}>
              {anal.ai_summary}
            </div>
          )}
        </div>
      )}

      {/* 財務データ表 */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 14 }}>
          財務データ一覧
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>年度</th>
                <th>売上高</th>
                <th>営業利益</th>
                <th>経常利益</th>
                <th>純利益</th>
                <th>総資産</th>
                <th>純資産</th>
                <th>ROE</th>
                <th>自己資本比率</th>
                <th>EPS</th>
                <th>PER</th>
                <th>配当</th>
              </tr>
            </thead>
            <tbody>
              {fins?.map(f => (
                <tr key={f.fiscal_year}>
                  <td style={{ fontWeight: 600 }}>{f.fiscal_year}</td>
                  <td className="number">{fmt(f.revenue, '円')}</td>
                  <td className="number" style={{ color: f.operating_income < 0 ? 'var(--red)' : 'inherit' }}>
                    {fmt(f.operating_income, '円')}
                  </td>
                  <td className="number" style={{ color: f.ordinary_income < 0 ? 'var(--red)' : 'inherit' }}>
                    {fmt(f.ordinary_income, '円')}
                  </td>
                  <td className="number" style={{ color: f.net_income < 0 ? 'var(--red)' : 'inherit' }}>
                    {fmt(f.net_income, '円')}
                  </td>
                  <td className="number">{fmt(f.total_assets, '円')}</td>
                  <td className="number">{fmt(f.net_assets, '円')}</td>
                  <td className="number">{fmtRatio(f.roe)}</td>
                  <td className="number">{fmtRatio(f.equity_ratio)}</td>
                  <td className="number">{f.eps != null ? `¥${Number(f.eps).toFixed(2)}` : '–'}</td>
                  <td className="number">{f.per != null ? `${Number(f.per).toFixed(1)}` : '–'}</td>
                  <td className="number">{f.dividend != null ? `¥${Number(f.dividend).toLocaleString()}` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
