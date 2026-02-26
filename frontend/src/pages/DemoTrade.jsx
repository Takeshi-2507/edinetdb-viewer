import { useState, useCallback, useEffect, useRef } from 'react'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'

function fmtPrice(v) {
  if (v == null) return '-'
  return `¥${Number(v).toLocaleString('ja-JP')}`
}

function fmtPnl(v) {
  if (v == null) return '-'
  const n = Number(v)
  return `${n >= 0 ? '+' : ''}¥${n.toLocaleString('ja-JP')}`
}

/** SVGラインチャート */
function MiniChart({ history, width = 320, height = 120 }) {
  if (!history || history.length < 2) {
    return <div style={{ width, height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', fontSize: 11 }}>データなし</div>
  }
  const closes = history.map(h => h.close)
  const min = Math.min(...closes) * 0.998
  const max = Math.max(...closes) * 1.002
  const range = max - min || 1

  const points = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * width
    const y = height - ((c - min) / range) * (height - 8) - 4
    return `${x},${y}`
  }).join(' ')

  const first = closes[0]
  const last = closes[closes.length - 1]
  const color = last >= first ? 'var(--green)' : 'var(--red)'

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
      {/* 最新価格の点 */}
      <circle cx={width} cy={height - ((last - min) / range) * (height - 8) - 4} r="3" fill={color} />
    </svg>
  )
}

/** 銘柄検索コンポーネント */
function CompanySearch({ onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [show, setShow] = useState(false)
  const timer = useRef(null)

  function handleChange(val) {
    setQuery(val)
    if (timer.current) clearTimeout(timer.current)
    if (val.length < 1) { setResults([]); setShow(false); return }
    timer.current = setTimeout(() => {
      api.companySearch(val)
        .then(r => { setResults(r); setShow(true) })
        .catch(() => {})
    }, 300)
  }

  function handleSelect(c) {
    setQuery(`${c.company_name} (${c.securities_code})`)
    setShow(false)
    onSelect(c)
  }

  return (
    <div style={{ position: 'relative' }}>
      <input
        type="text"
        placeholder="銘柄名 or 証券コードで検索..."
        value={query}
        onChange={e => handleChange(e.target.value)}
        onFocus={() => results.length > 0 && setShow(true)}
        style={{
          width: '100%', padding: '10px 14px', borderRadius: 8, fontSize: 13,
          background: 'var(--surface2)', border: '1px solid var(--border)',
          color: 'var(--text)',
        }}
      />
      {show && results.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 8, marginTop: 4, maxHeight: 250, overflow: 'auto',
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
        }}>
          {results.map(c => (
            <div key={c.edinet_code}
              onClick={() => handleSelect(c)}
              style={{
                padding: '8px 14px', cursor: 'pointer', borderBottom: '1px solid var(--border)',
                fontSize: 12,
              }}
              onMouseOver={e => e.currentTarget.style.background = 'var(--surface2)'}
              onMouseOut={e => e.currentTarget.style.background = 'transparent'}
            >
              <span style={{ fontWeight: 600 }}>{c.company_name}</span>
              <span style={{ color: 'var(--text-dim)', marginLeft: 8 }}>{c.securities_code}</span>
              <span style={{ color: 'var(--text-dim)', marginLeft: 8, fontSize: 10 }}>{c.industry}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DemoTrade() {
  const isMobile = useIsMobile()
  const [portfolio, setPortfolio] = useState(null)
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // 選択中銘柄
  const [selected, setSelected] = useState(null) // { securities_code, company_name, ... }
  const [currentPrice, setCurrentPrice] = useState(null)
  const [priceLoading, setPriceLoading] = useState(false)
  const [chartData, setChartData] = useState(null)
  const [chartPeriod, setChartPeriod] = useState('6m')

  // 取引フォーム
  const [tradeType, setTradeType] = useState('buy')
  const [formPrice, setFormPrice] = useState('')
  const [formQty, setFormQty] = useState('')
  const [formDate, setFormDate] = useState(new Date().toISOString().slice(0, 10))
  const [formMemo, setFormMemo] = useState('')
  const [showMemo, setShowMemo] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // ポートフォリオ読み込み
  const loadPortfolio = useCallback(async () => {
    try {
      const data = await api.demoPortfolio()
      setPortfolio(data)
    } catch (e) { }
  }, [])

  const loadTrades = useCallback(async () => {
    try {
      const data = await api.demoTrades()
      setTrades(data)
    } catch (e) { }
  }, [])

  useEffect(() => {
    loadPortfolio()
    loadTrades()
  }, [])

  // 銘柄選択時: 株価取得 + チャート取得
  function handleSelectCompany(company) {
    setSelected(company)
    setCurrentPrice(null)
    setChartData(null)
    const code = company.securities_code

    setPriceLoading(true)
    api.price(code)
      .then(d => {
        setCurrentPrice(d.price)
        setFormPrice(String(d.price))
      })
      .catch(() => {})
      .finally(() => setPriceLoading(false))

    api.stockHistory(code, chartPeriod)
      .then(d => setChartData(d.history))
      .catch(() => {})
  }

  // チャート期間変更
  function changeChartPeriod(p) {
    setChartPeriod(p)
    if (selected) {
      api.stockHistory(selected.securities_code, p)
        .then(d => setChartData(d.history))
        .catch(() => {})
    }
  }

  // 注文送信
  async function handleSubmit() {
    if (!selected || !formPrice || !formQty) return
    setSubmitting(true)
    try {
      await api.createTrade({
        securities_code: selected.securities_code,
        company_name: selected.company_name,
        trade_type: tradeType,
        trade_date: formDate,
        price: Number(formPrice),
        quantity: Number(formQty),
        memo: formMemo || null,
      })
      setFormQty('')
      setFormMemo('')
      loadPortfolio()
      loadTrades()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(id) {
    try {
      await api.deleteTrade(id)
      loadTrades()
      loadPortfolio()
    } catch (e) { setError(e.message) }
  }

  // 選択中銘柄の保有情報
  const holding = selected
    ? portfolio?.holdings?.find(h => h.securities_code === selected.securities_code && h.total_qty > 0)
    : null

  const estimatedTotal = formPrice && formQty ? Number(formPrice) * Number(formQty) : 0

  const lastClose = chartData?.length > 0 ? chartData[chartData.length - 1].close : null
  const prevClose = chartData?.length > 1 ? chartData[chartData.length - 2].close : null
  const dayChange = lastClose && prevClose ? lastClose - prevClose : null
  const dayChangePct = dayChange && prevClose ? (dayChange / prevClose) * 100 : null

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>デモトレード</h1>
      <p style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16 }}>仮想売買で投資判断をシミュレーション</p>

      {error && <div style={{ color: 'var(--red)', marginBottom: 12, fontSize: 12 }}>エラー: {error}</div>}

      {/* メインレイアウト: 左(チャート) + 右(注文) */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 340px', gap: 16, marginBottom: 16 }}>

        {/* 左パネル: 検索 + チャート */}
        <div>
          {/* 銘柄検索バー */}
          <div style={{ marginBottom: 12 }}>
            <CompanySearch onSelect={handleSelectCompany} />
          </div>

          {/* 銘柄情報 + チャート */}
          <div className="card" style={{ minHeight: 200 }}>
            {!selected ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)', fontSize: 13 }}>
                上の検索バーから銘柄を選択してください
              </div>
            ) : (
              <>
                {/* 銘柄ヘッダー */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>{selected.company_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {selected.securities_code} / {selected.industry || ''}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    {priceLoading ? (
                      <span className="spinner" style={{ width: 16, height: 16 }} />
                    ) : currentPrice ? (
                      <>
                        <div style={{ fontSize: 24, fontWeight: 800 }}>{fmtPrice(currentPrice)}</div>
                        {dayChange != null && (
                          <div style={{
                            fontSize: 12, fontWeight: 600,
                            color: dayChange >= 0 ? 'var(--green)' : 'var(--red)',
                          }}>
                            {dayChange >= 0 ? '+' : ''}{dayChange.toFixed(1)}
                            ({dayChangePct >= 0 ? '+' : ''}{dayChangePct.toFixed(2)}%)
                          </div>
                        )}
                      </>
                    ) : (
                      <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>価格取得中...</span>
                    )}
                  </div>
                </div>

                {/* チャート期間ボタン */}
                <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                  {['1m', '3m', '6m', '1y'].map(p => (
                    <button key={p} onClick={() => changeChartPeriod(p)}
                      style={{
                        padding: '3px 10px', borderRadius: 4, fontSize: 11,
                        border: chartPeriod === p ? '1px solid var(--accent)' : '1px solid var(--border)',
                        background: chartPeriod === p ? 'var(--accent-dim)' : 'var(--surface2)',
                        color: chartPeriod === p ? 'var(--accent)' : 'var(--text-dim)',
                        cursor: 'pointer',
                      }}
                    >{p.toUpperCase()}</button>
                  ))}
                </div>

                {/* チャート */}
                <MiniChart history={chartData} width={isMobile ? 320 : 500} height={isMobile ? 100 : 140} />
              </>
            )}
          </div>
        </div>

        {/* 右パネル: 注文フォーム */}
        <div>
          <div className="card">
            {/* Buy/Sell トグル */}
            <div style={{ display: 'flex', marginBottom: 14, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)' }}>
              <button
                onClick={() => setTradeType('buy')}
                style={{
                  flex: 1, padding: '10px 0', border: 'none', cursor: 'pointer',
                  fontWeight: 700, fontSize: 14,
                  background: tradeType === 'buy' ? 'var(--green)' : 'var(--surface2)',
                  color: tradeType === 'buy' ? '#fff' : 'var(--text-dim)',
                }}
              >買い</button>
              <button
                onClick={() => setTradeType('sell')}
                style={{
                  flex: 1, padding: '10px 0', border: 'none', cursor: 'pointer',
                  fontWeight: 700, fontSize: 14,
                  background: tradeType === 'sell' ? 'var(--red)' : 'var(--surface2)',
                  color: tradeType === 'sell' ? '#fff' : 'var(--text-dim)',
                }}
              >売り</button>
            </div>

            {/* 価格入力 */}
            <label style={{ fontSize: 11, color: 'var(--text-dim)', display: 'block', marginBottom: 8 }}>
              価格 (円)
              <div style={{ position: 'relative', marginTop: 4 }}>
                <input type="number" step="0.1" value={formPrice}
                  onChange={e => setFormPrice(e.target.value)}
                  style={{
                    width: '100%', padding: '8px 12px', borderRadius: 6, fontSize: 14, fontWeight: 600,
                    background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)',
                  }}
                />
                {currentPrice && (
                  <button onClick={() => setFormPrice(String(currentPrice))}
                    style={{
                      position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                      padding: '2px 8px', borderRadius: 4, fontSize: 10,
                      background: 'var(--accent-dim)', border: '1px solid var(--accent)',
                      color: 'var(--accent)', cursor: 'pointer',
                    }}
                  >現在値</button>
                )}
              </div>
            </label>

            {/* 数量入力 */}
            <label style={{ fontSize: 11, color: 'var(--text-dim)', display: 'block', marginBottom: 8 }}>
              数量 (株)
              <input type="number" step="1" value={formQty}
                onChange={e => setFormQty(e.target.value)}
                style={{
                  width: '100%', padding: '8px 12px', borderRadius: 6, fontSize: 14, fontWeight: 600,
                  marginTop: 4, background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)',
                }}
              />
              <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                {[100, 500, 1000].map(q => (
                  <button key={q} onClick={() => setFormQty(String(q))}
                    style={{
                      padding: '3px 10px', borderRadius: 4, fontSize: 10,
                      background: 'var(--surface2)', border: '1px solid var(--border)',
                      color: 'var(--text-dim)', cursor: 'pointer',
                    }}
                  >{q}株</button>
                ))}
              </div>
            </label>

            {/* 日付 */}
            <label style={{ fontSize: 11, color: 'var(--text-dim)', display: 'block', marginBottom: 8 }}>
              取引日
              <input type="date" value={formDate}
                onChange={e => setFormDate(e.target.value)}
                style={{
                  width: '100%', padding: '6px 12px', borderRadius: 6, fontSize: 12, marginTop: 4,
                  background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)',
                }}
              />
            </label>

            {/* 見積もり */}
            {estimatedTotal > 0 && (
              <div style={{
                padding: '8px 12px', borderRadius: 6, background: 'var(--surface2)',
                marginBottom: 10, display: 'flex', justifyContent: 'space-between', fontSize: 12,
              }}>
                <span style={{ color: 'var(--text-dim)' }}>取引金額</span>
                <span style={{ fontWeight: 700, fontSize: 14 }}>{fmtPrice(estimatedTotal)}</span>
              </div>
            )}

            {/* メモ */}
            <div style={{ marginBottom: 12 }}>
              <button onClick={() => setShowMemo(v => !v)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 11, color: 'var(--text-dim)', padding: 0,
              }}>
                {showMemo ? '▼' : '▶'} メモ
              </button>
              {showMemo && (
                <input type="text" placeholder="投資メモ..."
                  value={formMemo} onChange={e => setFormMemo(e.target.value)}
                  style={{
                    width: '100%', padding: '6px 12px', borderRadius: 6, fontSize: 12, marginTop: 4,
                    background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)',
                  }}
                />
              )}
            </div>

            {/* 送信ボタン */}
            <button
              onClick={handleSubmit}
              disabled={!selected || !formPrice || !formQty || submitting}
              style={{
                width: '100%', padding: '12px 0', borderRadius: 8, border: 'none',
                fontSize: 15, fontWeight: 800, cursor: 'pointer',
                background: tradeType === 'buy' ? 'var(--green)' : 'var(--red)',
                color: '#fff',
                opacity: (!selected || !formPrice || !formQty || submitting) ? 0.4 : 1,
              }}
            >
              {submitting ? '送信中...' : tradeType === 'buy' ? `買い注文` : '売り注文'}
            </button>
          </div>

          {/* 選択中銘柄の保有状況 */}
          {holding && (
            <div className="card" style={{ marginTop: 12, padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', fontWeight: 600, marginBottom: 6 }}>
                現在のポジション
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 10px', fontSize: 12 }}>
                <div><span style={{ color: 'var(--text-dim)' }}>保有: </span><strong>{holding.total_qty}株</strong></div>
                <div><span style={{ color: 'var(--text-dim)' }}>取得単価: </span><strong>{fmtPrice(holding.avg_cost)}</strong></div>
                <div><span style={{ color: 'var(--text-dim)' }}>現在値: </span><strong>{fmtPrice(holding.current_price)}</strong></div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>損益: </span>
                  <strong style={{ color: holding.unrealized_pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    {fmtPnl(holding.unrealized_pnl)} ({holding.pnl_pct > 0 ? '+' : ''}{holding.pnl_pct}%)
                  </strong>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ポートフォリオサマリー */}
      {portfolio && portfolio.holdings.some(h => h.total_qty > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ textAlign: 'center', padding: '12px' }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 3 }}>投資総額</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{fmtPrice(portfolio.summary.total_cost)}</div>
          </div>
          <div className="card" style={{ textAlign: 'center', padding: '12px' }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 3 }}>評価額</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{fmtPrice(portfolio.summary.total_value)}</div>
          </div>
          <div className="card" style={{ textAlign: 'center', padding: '12px' }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 3 }}>含み損益</div>
            <div style={{
              fontSize: 16, fontWeight: 700,
              color: portfolio.summary.total_pnl > 0 ? 'var(--green)' : portfolio.summary.total_pnl < 0 ? 'var(--red)' : 'var(--text)',
            }}>
              {fmtPnl(portfolio.summary.total_pnl)}
              {portfolio.summary.total_pnl_pct != null && (
                <span style={{ fontSize: 11, marginLeft: 4 }}>({portfolio.summary.total_pnl_pct > 0 ? '+' : ''}{portfolio.summary.total_pnl_pct}%)</span>
              )}
            </div>
          </div>
          <div className="card" style={{ textAlign: 'center', padding: '12px' }}>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 3 }}>保有銘柄</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{portfolio.holdings.filter(h => h.total_qty > 0).length}</div>
          </div>
        </div>
      )}

      {/* 保有一覧 + 取引履歴 (下部) */}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 16 }}>
        {/* 保有一覧 */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 600, color: 'var(--text-dim)' }}>
            保有銘柄
          </div>
          <div style={{ overflowX: 'auto', maxHeight: 300, overflow: 'auto' }}>
            <table style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th style={{ textAlign: 'right' }}>数量</th>
                  <th style={{ textAlign: 'right' }}>取得単価</th>
                  <th style={{ textAlign: 'right' }}>損益</th>
                </tr>
              </thead>
              <tbody>
                {portfolio?.holdings?.filter(h => h.total_qty > 0).map(h => (
                  <tr key={h.securities_code}
                    onClick={() => handleSelectCompany({ securities_code: h.securities_code, company_name: h.company_name })}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      <span style={{ fontWeight: 500 }}>{h.company_name}</span>
                      <div style={{ fontSize: 9, color: 'var(--text-dim)' }}>{h.securities_code}</div>
                    </td>
                    <td className="number" style={{ textAlign: 'right' }}>{h.total_qty}</td>
                    <td className="number" style={{ textAlign: 'right' }}>{fmtPrice(h.avg_cost)}</td>
                    <td className="number" style={{
                      textAlign: 'right', fontWeight: 600,
                      color: h.unrealized_pnl > 0 ? 'var(--green)' : h.unrealized_pnl < 0 ? 'var(--red)' : 'var(--text)',
                    }}>
                      {h.pnl_pct != null ? `${h.pnl_pct > 0 ? '+' : ''}${h.pnl_pct}%` : '-'}
                    </td>
                  </tr>
                ))}
                {(!portfolio?.holdings || portfolio.holdings.filter(h => h.total_qty > 0).length === 0) && (
                  <tr><td colSpan={4} style={{ textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>保有なし</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* 取引履歴 */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 600, color: 'var(--text-dim)' }}>
            取引履歴
          </div>
          <div style={{ overflowX: 'auto', maxHeight: 300, overflow: 'auto' }}>
            <table style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>日付</th>
                  <th>銘柄</th>
                  <th>売買</th>
                  <th style={{ textAlign: 'right' }}>価格</th>
                  <th style={{ textAlign: 'right' }}>数量</th>
                  <th style={{ width: 28 }}></th>
                </tr>
              </thead>
              <tbody>
                {trades.map(t => (
                  <tr key={t.id}>
                    <td style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{t.trade_date}</td>
                    <td style={{ fontSize: 11 }}>{t.company_name || t.securities_code}</td>
                    <td>
                      <span style={{
                        padding: '1px 6px', borderRadius: 3, fontSize: 10, fontWeight: 700,
                        background: t.trade_type === 'buy' ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                        color: t.trade_type === 'buy' ? 'var(--green)' : 'var(--red)',
                      }}>{t.trade_type === 'buy' ? '買' : '売'}</span>
                    </td>
                    <td className="number" style={{ textAlign: 'right' }}>{fmtPrice(t.price)}</td>
                    <td className="number" style={{ textAlign: 'right' }}>{t.quantity}</td>
                    <td>
                      <button onClick={() => handleDelete(t.id)} style={{
                        background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: 11,
                      }}>×</button>
                    </td>
                  </tr>
                ))}
                {trades.length === 0 && (
                  <tr><td colSpan={6} style={{ textAlign: 'center', padding: 20, color: 'var(--text-dim)' }}>取引なし</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
