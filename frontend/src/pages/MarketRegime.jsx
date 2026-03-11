import { useState, useCallback, useMemo } from 'react'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ReferenceArea } from 'recharts'

// ─── 定数 ───────────────────────────────────────────
const REGIME_META = {
  risk_off:    { color: '#ef4444', bg: 'rgba(239,68,68,.12)', icon: '🛡️', label: 'リスクオフ' },
  inflation:   { color: '#ff6a00', bg: 'rgba(255,106,0,.12)', icon: '🔥', label: 'インフレ局面' },
  trend_up:    { color: '#22c55e', bg: 'rgba(34,197,94,.12)',  icon: '📈', label: '上昇トレンド' },
  trend_down:  { color: '#ef4444', bg: 'rgba(239,68,68,.12)', icon: '📉', label: '下降トレンド' },
  range_bound: { color: '#f59e0b', bg: 'rgba(245,158,11,.12)', icon: '➡️', label: 'レンジ相場' },
}

const INDICATOR_META = {
  vix:       { label: 'VIX (恐怖指数)', fmt: v => v?.toFixed(1) },
  tnx:       { label: '米10年金利 (%)', fmt: v => v?.toFixed(2) + '%' },
  gold:      { label: '金 ($/oz)', fmt: v => '$' + v?.toLocaleString('en', { maximumFractionDigits: 0 }) },
  oil:       { label: '原油 WTI ($)', fmt: v => '$' + v?.toFixed(1) },
  usd_index: { label: 'ドル指数', fmt: v => v?.toFixed(1) },
  sp500:     { label: 'S&P 500', fmt: v => v?.toLocaleString('en', { maximumFractionDigits: 0 }) },
}

const TABS = ['推奨戦略', 'ブレイクアウト', 'バックテスト', 'レジーム履歴']

const ALLOC_LABELS = {
  stocks: '株式', bonds_long: '長期債', bonds_mid: '中期債',
  gold: 'ゴールド', commodities: 'コモディティ', cash: '現金',
}

// ─── ヘルパー ───────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function pctBadge(v) {
  if (v == null) return null
  const color = v >= 0 ? 'var(--green)' : 'var(--red)'
  return <span style={{ color, fontSize: 11, marginLeft: 4 }}>{v >= 0 ? '+' : ''}{v}%</span>
}

// ─── SVGスパークライン ──────────────────────────────
function Sparkline({ data, width = 120, height = 32 }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data) * 0.999
  const max = Math.max(...data) * 1.001
  const range = max - min || 1
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = height - ((v - min) / range) * (height - 4) - 2
    return `${x},${y}`
  }).join(' ')
  const color = data[data.length - 1] >= data[0] ? 'var(--green)' : 'var(--red)'
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', width: '100%', height }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

// ─── レジームカード ─────────────────────────────────
function RegimeCard({ regime }) {
  if (!regime) return <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)' }}>データ取得中…</div>
  const meta = REGIME_META[regime.regime] || REGIME_META.range_bound
  return (
    <div style={{
      background: meta.bg, border: `1px solid ${meta.color}33`, borderRadius: 12,
      padding: '20px 24px', marginBottom: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <span style={{ fontSize: 28 }}>{meta.icon}</span>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: meta.color }}>
            {regime.regime_ja}
            {regime.sub_regime_ja && <span style={{ fontSize: 14, fontWeight: 400, marginLeft: 8, opacity: .7 }}>({regime.sub_regime_ja})</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>
            信頼度: {regime.confidence}% ・ 判定日: {regime.date}
            {regime.details?.transitional && <span style={{ color: '#f59e0b', marginLeft: 8 }}>⚡ 転換期の可能性</span>}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 20, fontSize: 13, color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
        <span>VIX: <b>{regime.vix_level}</b></span>
        <span>利回り差: <b>{regime.yield_spread}%</b></span>
        <span>S&P500: <b>{regime.sp500_trend === 'above_200sma' ? '200SMA上 ✓' : '200SMA下 ✗'}</b></span>
        {regime.details?.sp500_rsi && <span>RSI: <b>{regime.details.sp500_rsi}</b></span>}
        {regime.details?.sp500_drawdown != null && <span>DD: <b>{regime.details.sp500_drawdown}%</b></span>}
      </div>
      {/* Score bars */}
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        {regime.details && Object.entries(regime.details).length > 0 && Object.entries(REGIME_META).map(([key, m]) => {
          const score = regime.details?.[key] ?? (regime.scores || {})[key]
          if (score == null) return null
          // Check from scores
          const s = (regime.scores || {})[key]
          if (s == null) return null
          return (
            <div key={key} style={{ flex: '1 1 100px', minWidth: 90 }}>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 2 }}>{m.label}</div>
              <div style={{ background: 'var(--surface)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                <div style={{ width: `${s}%`, height: '100%', background: m.color, borderRadius: 4 }} />
              </div>
              <div style={{ fontSize: 10, color: m.color, textAlign: 'right' }}>{s}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── 指標カード群 ───────────────────────────────────
function IndicatorGrid({ indicators }) {
  const keys = ['vix', 'tnx', 'gold', 'oil', 'usd_index', 'sp500']
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10, marginBottom: 20 }}>
      {keys.map(key => {
        const d = indicators?.[key]
        const meta = INDICATOR_META[key]
        if (!d) return <div key={key} style={{ background: 'var(--surface)', borderRadius: 8, padding: 12, minHeight: 80 }}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{meta.label}</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>—</div>
        </div>
        return (
          <div key={key} style={{ background: 'var(--surface)', borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4 }}>{meta.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>
              {meta.fmt(d.current)}
              {pctBadge(d.change_1d)}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>
              週間: {d.change_1w != null ? `${d.change_1w >= 0 ? '+' : ''}${d.change_1w}%` : '—'}
            </div>
            <Sparkline data={d.sparkline} height={28} />
          </div>
        )
      })}
    </div>
  )
}

// ─── 戦略カード ─────────────────────────────────────
function StrategyCards({ strategies, onSelect }) {
  if (!strategies || !strategies.length) return <div style={{ color: 'var(--text-dim)', padding: 20 }}>戦略データなし</div>
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
      {strategies.map(s => (
        <div key={s.strategy_id}
          onClick={() => onSelect(s.strategy_id)}
          style={{
            background: 'var(--surface)', borderRadius: 10, padding: 16,
            border: s.is_recommended ? '2px solid var(--green)' : s.is_avoid ? '1px solid var(--red)' : '1px solid var(--border)',
            cursor: 'pointer', transition: 'transform .15s',
          }}
          onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-2px)'}
          onMouseLeave={e => e.currentTarget.style.transform = ''}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontWeight: 700, fontSize: 15 }}>{s.name_ja}</span>
            {s.is_recommended && <span style={{ background: 'var(--green)', color: '#000', fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10 }}>★ 推奨</span>}
            {s.is_avoid && <span style={{ background: 'var(--red)', color: '#fff', fontSize: 10, padding: '2px 8px', borderRadius: 10 }}>⚠ 非推奨</span>}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8, lineHeight: 1.4 }}>{s.description_ja}</div>
          {/* Allocation bar */}
          <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
            {Object.entries(s.allocation || {}).map(([k, v]) => {
              const colors = { stocks: '#3b82f6', bonds_long: '#8b5cf6', bonds_mid: '#a78bfa', gold: '#f59e0b', commodities: '#ef4444', cash: '#6b7280' }
              return <div key={k} style={{ width: `${v}%`, background: colors[k] || '#666' }} title={`${ALLOC_LABELS[k] || k}: ${v}%`} />
            })}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 10, color: 'var(--text-dim)' }}>
            {Object.entries(s.allocation || {}).map(([k, v]) => (
              <span key={k}>{ALLOC_LABELS[k] || k} {v}%</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── 戦略詳細モーダル ───────────────────────────────
function StrategyDetail({ strategyId, onClose }) {
  const { data, loading } = useFetch(() => strategyId ? api.regimeStrategy(strategyId) : null, [strategyId])
  const { data: btData } = useFetch(() => strategyId ? api.regimeBacktest(strategyId) : null, [strategyId])

  if (!strategyId) return null
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={onClose}>
      <div style={{ background: 'var(--bg)', borderRadius: 12, maxWidth: 800, width: '100%', maxHeight: '85vh', overflow: 'auto', padding: 24 }}
        onClick={e => e.stopPropagation()}>
        {loading ? <div style={{ textAlign: 'center', padding: 40 }}>読み込み中...</div> : data && <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2 style={{ margin: 0, fontSize: 20 }}>{data.name_ja}</h2>
            <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text)', fontSize: 20, cursor: 'pointer' }}>✕</button>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 16 }}>{data.description_ja}</p>

          {/* Current allocation */}
          <h3 style={{ fontSize: 14, marginBottom: 8 }}>現在の配分 (レジーム: {REGIME_META[data.current_regime]?.label || data.current_regime})</h3>
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            {Object.entries(data.current_allocation || {}).map(([k, v]) => (
              <div key={k} style={{ background: 'var(--surface)', borderRadius: 8, padding: '8px 14px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{v}%</div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{ALLOC_LABELS[k] || k}</div>
              </div>
            ))}
          </div>

          {/* Stock picks */}
          {data.picks?.length > 0 && <>
            <h3 style={{ fontSize: 14, marginBottom: 8 }}>推奨銘柄 ({data.picks.length}銘柄)</h3>
            <div style={{ overflowX: 'auto', marginBottom: 20 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>銘柄</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>価格</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>PER</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>ROE</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px' }}>スコア</th>
                  </tr>
                </thead>
                <tbody>
                  {data.picks.map(p => (
                    <tr key={p.ticker} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px' }}><b>{p.ticker}</b> <span style={{ color: 'var(--text-dim)' }}>{p.company_name}</span></td>
                      <td style={{ textAlign: 'right', padding: '6px 8px' }}>${p.price?.toFixed(2)}</td>
                      <td style={{ textAlign: 'right', padding: '6px 8px' }}>{p.per?.toFixed(1)}</td>
                      <td style={{ textAlign: 'right', padding: '6px 8px' }}>{(p.roe * 100)?.toFixed(1)}%</td>
                      <td style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 700, color: 'var(--accent)' }}>{p.takehara_score?.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>}

          {/* Backtest chart */}
          {btData?.results?.length > 0 && <>
            <h3 style={{ fontSize: 14, marginBottom: 8 }}>バックテスト ({btData.summary?.months || 0}ヶ月)</h3>
            {btData.summary && (
              <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap', fontSize: 12 }}>
                <span>累積: <b style={{ color: btData.summary.total_return >= 0 ? 'var(--green)' : 'var(--red)' }}>{btData.summary.total_return}%</b></span>
                <span>年率: <b>{btData.summary.annualized_return}%</b></span>
                <span>S&P500: <b>{btData.summary.sp500_return}%</b></span>
                <span>最大DD: <b style={{ color: 'var(--red)' }}>{btData.summary.max_drawdown}%</b></span>
                <span>Sharpe: <b>{btData.summary.sharpe_ratio}</b></span>
              </div>
            )}
            <BacktestChart results={btData.results} />
          </>}
        </>}
      </div>
    </div>
  )
}

// ─── バックテストチャート ────────────────────────────
function BacktestChart({ results }) {
  if (!results?.length) return null
  const data = results.map(r => ({
    date: r.date?.slice(0, 7),
    strategy: +(r.cumulative_return * 100).toFixed(1),
    sp500: +(r.sp500_cumulative * 100).toFixed(1),
    regime: r.regime,
  }))
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `${v}%`} />
        <Tooltip
          contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }}
          formatter={(v, name) => [`${v}%`, name === 'strategy' ? '戦略' : 'S&P500']}
          labelFormatter={l => l}
        />
        <Legend formatter={v => v === 'strategy' ? '戦略' : 'S&P500'} />
        <Line type="monotone" dataKey="strategy" stroke="var(--accent)" dot={false} strokeWidth={2} />
        <Line type="monotone" dataKey="sp500" stroke="#6b7280" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ─── ブレイクアウト銘柄テーブル ──────────────────────
function BreakoutTable({ breakouts }) {
  if (!breakouts) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>読み込み中...</div>
  if (!breakouts.length) return <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>シグナル銘柄なし</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--border)', fontSize: 11, color: 'var(--text-dim)' }}>
            <th style={{ textAlign: 'left', padding: '8px' }}>銘柄</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>セクター</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>シグナル</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>価格</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>52週高値</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>52週安値</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>スコア</th>
          </tr>
        </thead>
        <tbody>
          {breakouts.map(b => (
            <tr key={b.ticker} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '8px' }}>
                <b>{b.ticker}</b>
                <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{b.company_name}</div>
              </td>
              <td style={{ padding: '8px', fontSize: 11 }}>{b.sector}</td>
              <td style={{ padding: '8px' }}>
                {b.signals.map((s, i) => (
                  <div key={i} style={{ fontSize: 11, marginBottom: 2 }}>
                    <span style={{
                      display: 'inline-block', padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                      background: s.type.includes('high') || s.type === 'range_top' ? 'rgba(34,197,94,.15)' : 'rgba(239,68,68,.15)',
                      color: s.type.includes('high') || s.type === 'range_top' ? 'var(--green)' : 'var(--red)',
                    }}>{s.label}</span>
                    <span style={{ color: 'var(--text-dim)', marginLeft: 4 }}>{s.detail}</span>
                  </div>
                ))}
              </td>
              <td style={{ textAlign: 'right', padding: '8px', fontWeight: 600 }}>${b.price?.toFixed(2)}</td>
              <td style={{ textAlign: 'right', padding: '8px', fontSize: 12 }}>${b.hi52?.toFixed(2)}</td>
              <td style={{ textAlign: 'right', padding: '8px', fontSize: 12 }}>${b.lo52?.toFixed(2)}</td>
              <td style={{ textAlign: 'right', padding: '8px', fontWeight: 700, color: 'var(--accent)' }}>{b.takehara_score?.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── バックテスト比較タブ ────────────────────────────
function BacktestTab() {
  const [selected, setSelected] = useState('all_weather')
  const { data } = useFetch(() => api.regimeBacktest(selected), [selected])
  const strategies = [
    { id: 'all_weather', label: '全天候型' },
    { id: 'buffett_value', label: 'バフェット' },
    { id: 'ark_growth', label: 'ARK' },
    { id: 'soros_macro', label: 'ソロス' },
    { id: 'trend_following', label: 'トレンド' },
  ]
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {strategies.map(s => (
          <button key={s.id} onClick={() => setSelected(s.id)}
            style={{
              padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
              background: selected === s.id ? 'var(--accent)' : 'var(--surface)',
              color: selected === s.id ? '#000' : 'var(--text)',
            }}>{s.label}</button>
        ))}
      </div>
      {data?.summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 10, marginBottom: 16 }}>
          {[
            { label: '累積リターン', value: `${data.summary.total_return}%`, color: data.summary.total_return >= 0 ? 'var(--green)' : 'var(--red)' },
            { label: '年率リターン', value: `${data.summary.annualized_return}%` },
            { label: 'S&P500累積', value: `${data.summary.sp500_return}%` },
            { label: '最大DD', value: `${data.summary.max_drawdown}%`, color: 'var(--red)' },
            { label: 'ボラティリティ', value: `${data.summary.volatility}%` },
            { label: 'シャープレシオ', value: data.summary.sharpe_ratio },
          ].map(item => (
            <div key={item.label} style={{ background: 'var(--surface)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: item.color || 'var(--text)' }}>{item.value}</div>
            </div>
          ))}
        </div>
      )}
      <BacktestChart results={data?.results} />
      {/* Regime breakdown */}
      {data?.summary?.regime_breakdown && (
        <div style={{ marginTop: 16 }}>
          <h4 style={{ fontSize: 13, marginBottom: 8 }}>レジーム別パフォーマンス</h4>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(data.summary.regime_breakdown).map(([regime, perf]) => {
              const meta = REGIME_META[regime] || { color: '#666', label: regime }
              return (
                <div key={regime} style={{ background: 'var(--surface)', borderRadius: 8, padding: '8px 12px', borderLeft: `3px solid ${meta.color}` }}>
                  <div style={{ fontSize: 11, color: meta.color, fontWeight: 600 }}>{meta.label}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{perf.months}ヶ月 ・ 月平均 {perf.avg_monthly}%</div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── レジーム履歴タブ ───────────────────────────────
function RegimeHistoryTab() {
  const { data } = useFetch(() => api.regimeHistory(), [])
  if (!data?.regimes?.length) return <div style={{ color: 'var(--text-dim)', padding: 20 }}>履歴データなし</div>
  // Show last 30 entries as timeline
  const items = data.regimes.slice(-60)
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--border)', fontSize: 11, color: 'var(--text-dim)' }}>
            <th style={{ textAlign: 'left', padding: '6px 8px' }}>日付</th>
            <th style={{ textAlign: 'left', padding: '6px 8px' }}>レジーム</th>
            <th style={{ textAlign: 'left', padding: '6px 8px' }}>詳細</th>
            <th style={{ textAlign: 'right', padding: '6px 8px' }}>VIX</th>
            <th style={{ textAlign: 'right', padding: '6px 8px' }}>利回り差</th>
            <th style={{ textAlign: 'right', padding: '6px 8px' }}>信頼度</th>
          </tr>
        </thead>
        <tbody>
          {[...items].reverse().map(r => {
            const meta = REGIME_META[r.regime] || { color: '#666' }
            return (
              <tr key={r.date} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 8px' }}>{r.date}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{ color: meta.color, fontWeight: 600 }}>{r.regime_ja}</span>
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-dim)' }}>{r.sub_regime_ja}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px' }}>{r.vix_level?.toFixed(1)}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px' }}>{r.yield_spread?.toFixed(2)}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px' }}>{r.confidence}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── メインページ ───────────────────────────────────
export default function MarketRegime() {
  const isMobile = useIsMobile()
  const [tab, setTab] = useState(0)
  const [selectedStrategy, setSelectedStrategy] = useState(null)

  const { data: dashboard, loading } = useFetch(() => api.regimeDashboard(), [])
  const { data: breakoutData } = useFetch(() => api.regimeBreakouts(), [])

  return (
    <div style={{ padding: isMobile ? 12 : 20, maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: isMobile ? 20 : 24, margin: 0 }}>マーケットレジーム</h1>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
          マクロ指標による市場局面判定 / 戦略モデル / バックテスト
          {dashboard?.updated_at && <span style={{ marginLeft: 12 }}>最終更新: {fmtDate(dashboard.updated_at)}</span>}
          {dashboard?.updating && <span style={{ marginLeft: 8, color: 'var(--accent)' }}>🔄 更新中...</span>}
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-dim)' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
          <div>マクロデータ読み込み中...</div>
          <div style={{ fontSize: 12, marginTop: 8 }}>初回は1〜2分かかります</div>
        </div>
      ) : <>
        {/* Regime card */}
        <RegimeCard regime={dashboard?.regime} />

        {/* Indicator grid */}
        <IndicatorGrid indicators={dashboard?.indicators} />

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', marginBottom: 16 }}>
          {TABS.map((t, i) => (
            <button key={t} onClick={() => setTab(i)}
              style={{
                padding: '10px 18px', border: 'none', cursor: 'pointer',
                background: 'transparent', fontSize: 13, fontWeight: tab === i ? 700 : 400,
                color: tab === i ? 'var(--accent)' : 'var(--text-dim)',
                borderBottom: tab === i ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -2,
              }}>{t}</button>
          ))}
        </div>

        {/* Tab content */}
        {tab === 0 && <StrategyCards strategies={dashboard?.strategies} onSelect={setSelectedStrategy} />}
        {tab === 1 && <BreakoutTable breakouts={breakoutData?.breakouts} />}
        {tab === 2 && <BacktestTab />}
        {tab === 3 && <RegimeHistoryTab />}

        {/* Strategy detail modal */}
        <StrategyDetail strategyId={selectedStrategy} onClose={() => setSelectedStrategy(null)} />
      </>}
    </div>
  )
}
