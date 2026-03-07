import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'
import { IS_LOCAL } from '../hooks/useIsLocal'

function fmtAmt(v) {
  if (v == null) return '-'
  const n = Number(v)
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}兆`
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(1)}億`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(0)}万`
  return n.toLocaleString('ja-JP')
}

function fmtPrice(v) {
  if (v == null) return '-'
  return `¥${Number(v).toLocaleString('ja-JP')}`
}

function pct(v, digits = 1) {
  if (v == null) return '-'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function ScoreBar({ score, max = 100 }) {
  const ratio = Math.min(100, (score / max) * 100)
  const color = score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : score >= 30 ? 'var(--accent)' : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 60, height: 6, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${ratio}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontWeight: 700, fontSize: 13, color, minWidth: 30 }}>{score}</span>
    </div>
  )
}

function TotalScoreCell({ row }) {
  const total = row.total_score
  const value = row.takehara_score
  const quality = row.quality_score
  const momentum = row.momentum_score
  const event = row.event_score
  const ai = row.ai_score
  if (total == null) return <span style={{ color: 'var(--text-dim)' }}>-</span>
  const color = total >= 70 ? 'var(--green)' : total >= 50 ? 'var(--yellow)' : total >= 30 ? 'var(--accent)' : 'var(--red)'
  const sc = (v, hi = 70, lo = 50) => v > 0 ? (v >= hi ? 'var(--green)' : v >= lo ? 'var(--yellow)' : 'var(--text-dim)') : 'var(--text-dim)'
  const ratio = Math.min(100, (total / 100) * 100)
  return (
    <div style={{ minWidth: 90 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 50, height: 6, background: 'var(--surface2)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ width: `${ratio}%`, height: '100%', background: color, borderRadius: 3 }} />
        </div>
        <span style={{ fontWeight: 700, fontSize: 13, color, minWidth: 28 }}>{total}</span>
      </div>
      <div style={{ display: 'flex', gap: 5, marginTop: 2, fontSize: 10, lineHeight: 1.2, flexWrap: 'wrap' }}>
        <span style={{ color: sc(value) }}>V:{value ?? '-'}</span>
        <span style={{ color: sc(quality) }}>Q:{quality ?? '-'}</span>
        {momentum > 0 && <span style={{ color: sc(momentum, 60, 40) }}>M:{momentum}</span>}
        {event > 0 && <span style={{ color: sc(event, 60, 40) }}>D:{event}</span>}
        {ai > 0 && <span style={{ color: sc(ai, 60, 40) }}>E:{ai}</span>}
      </div>
    </div>
  )
}

/** 目安株価と現在株価の比較表示 */
function PriceTarget({ row, currentPrice }) {
  const target = row.target_per15
  if (!target) return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>-</span>

  let gapPct = null
  let gapColor = 'var(--text-dim)'
  let label = ''
  if (currentPrice && target) {
    gapPct = ((currentPrice - target) / target) * 100
    if (gapPct <= -20) { gapColor = 'var(--green)'; label = '割安' }
    else if (gapPct <= 0) { gapColor = 'var(--green)'; label = 'やや割安' }
    else if (gapPct <= 20) { gapColor = 'var(--yellow)'; label = '適正~やや割高' }
    else { gapColor = 'var(--red)'; label = '売り検討' }
  }

  return (
    <div style={{ fontSize: 11, lineHeight: 1.6 }}>
      <div style={{ whiteSpace: 'nowrap' }}>
        <span style={{ color: 'var(--text-dim)' }}>目安: </span>
        <span style={{ fontWeight: 600 }}>{fmtPrice(target)}</span>
      </div>
      {currentPrice != null && (
        <div style={{ whiteSpace: 'nowrap' }}>
          <span style={{ color: 'var(--text-dim)' }}>現在: </span>
          <span style={{ fontWeight: 500 }}>{fmtPrice(currentPrice)}</span>
          <span style={{ marginLeft: 4, fontWeight: 600, color: gapColor, fontSize: 10 }}>
            {gapPct != null ? `${gapPct > 0 ? '+' : ''}${gapPct.toFixed(0)}% ${label}` : ''}
          </span>
        </div>
      )}
    </div>
  )
}

/** CN-PERバッジ */
function CnPerBadge({ cnPer, ncr }) {
  if (cnPer == null) return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>-</span>
  let color = 'var(--text-dim)'
  let label = ''
  if (cnPer < 8) { color = 'var(--green)'; label = '強い買い' }
  else if (cnPer < 12) { color = 'var(--accent2)'; label = '買い候補' }
  else if (cnPer < 15) { color = 'var(--yellow)'; label = '適正' }
  else { color = 'var(--red)'; label = '割高' }

  return (
    <div style={{ fontSize: 11, lineHeight: 1.5 }}>
      <span style={{ fontWeight: 700, color }}>{cnPer.toFixed(1)}</span>
      <span style={{ fontSize: 9, color, marginLeft: 3 }}>{label}</span>
      {ncr != null && (
        <div style={{ fontSize: 9, color: 'var(--text-dim)' }}>
          NC比率: {(ncr * 100).toFixed(0)}%
        </div>
      )}
    </div>
  )
}

// ソート可能カラム定義
const SORTABLE_COLUMNS = [
  { key: 'company_name', label: '銘柄', align: 'left', defaultDir: 'asc' },
  { key: 'industry',     label: '業種', align: 'left', defaultDir: 'asc' },
  { key: 'score',        label: '総合', align: 'right', defaultDir: 'desc',
    tooltip: '総合 = V×30% + Q×25% + M×20% + D×15% + E×10%\nV(竹原式): PER+PBR+ROE+営業利益率+現金+FCF\nQ(Quality): 粗利率+営業利益率+ROE+CF質\nM(Momentum): MA乖離率+GC/DC+RS+出来高+ボラ\nD(Event): 増配+配当性向+増収増益+加速\nE(AI定性): 信用+財務安定+収益安定+利益の質\n※データなし層の重みは自動再配分' },
  { key: 'per',              label: 'PER',      align: 'right', defaultDir: 'asc' },
  { key: 'pbr',              label: 'PBR',      align: 'right', defaultDir: 'asc' },
  { key: 'roe',              label: 'ROE',      align: 'right', defaultDir: 'desc' },
  { key: 'operating_margin', label: '営業利益率', align: 'right', defaultDir: 'desc' },
  { key: 'cash_ratio',       label: '現金比率',   align: 'right', defaultDir: 'desc' },
  { key: 'dividend',         label: '配当',      align: 'right', defaultDir: 'desc' },
  { key: 'fcf',              label: 'FCF',      align: 'right', defaultDir: 'desc' },
]

// 株価系ソートカラム（売り時目安列用 — バックエンド側でソート処理）
const PRICE_SORT_COLUMNS = {
  price:  { label: '現在値',  defaultDir: 'desc' },
  target: { label: '目安価格', defaultDir: 'desc' },
  gap:    { label: '乖離率',  defaultDir: 'asc' },
  cn_per: { label: 'CN-PER',  defaultDir: 'asc' },
  net_cash: { label: 'NC',    defaultDir: 'desc' },
}

// 全ソートキーのラベル解決用
const ALL_SORT_LABELS = Object.fromEntries([
  ...SORTABLE_COLUMNS.map(c => [c.key, c.label]),
  ...Object.entries(PRICE_SORT_COLUMNS).map(([k, v]) => [k, v.label]),
])

const SORT_BADGES = ['①', '②', '③']

/** ソートダイアログ（Excel風） */
function SortDialog({ sortKeys, onApply, onClose, isMobile }) {
  const [keys, setKeys] = useState(() => {
    const arr = [...sortKeys]
    while (arr.length < 3) arr.push({ key: '', dir: '' })
    return arr
  })

  function setLevel(idx, field, value) {
    setKeys(prev => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: value }
      // キーが選択されたらデフォルト方向を設定
      if (field === 'key' && value) {
        const col = SORTABLE_COLUMNS.find(c => c.key === value)
        const pCol = PRICE_SORT_COLUMNS[value]
        const defDir = col?.defaultDir || pCol?.defaultDir || 'desc'
        if (!next[idx].dir) next[idx] = { ...next[idx], dir: defDir }
      }
      if (field === 'key' && !value) next[idx] = { key: '', dir: '' }
      return next
    })
  }

  function handleApply() {
    onApply(keys.filter(k => k.key))
    onClose()
  }

  function handleClear() {
    const defaultSort = [{ key: 'score', dir: 'desc' }]
    onApply(defaultSort)
    onClose()
  }

  // 使用済みキーを取得（他のレベルで使われてるもの）
  function usedKeys(excludeIdx) {
    return keys.filter((k, i) => i !== excludeIdx && k.key).map(k => k.key)
  }

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.6)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: isMobile ? 16 : 24, minWidth: isMobile ? 'auto' : 420, maxWidth: 500,
        width: isMobile ? 'calc(100vw - 32px)' : undefined,
        boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16, color: 'var(--text)' }}>
          並び替え設定
          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8 }}>
            最大3段階のソート
          </span>
        </div>

        {[0, 1, 2].map(idx => {
          const used = usedKeys(idx)
          const level = keys[idx]
          const disabled = idx > 0 && !keys[idx - 1]?.key
          return (
            <div key={idx} style={{
              display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10,
              opacity: disabled ? 0.35 : 1,
              pointerEvents: disabled ? 'none' : 'auto',
            }}>
              <span style={{
                fontSize: 11, fontWeight: 700, color: 'var(--accent)',
                minWidth: 60, whiteSpace: 'nowrap',
              }}>
                {idx === 0 ? '第1キー' : idx === 1 ? '第2キー' : '第3キー'}
              </span>
              <select
                value={level.key}
                onChange={e => setLevel(idx, 'key', e.target.value)}
                style={{
                  flex: 1, padding: '6px 10px', borderRadius: 6, fontSize: 12,
                  background: 'var(--surface2)', border: '1px solid var(--border)',
                  color: 'var(--text)',
                }}
              >
                <option value="">-- 選択 --</option>
                {SORTABLE_COLUMNS.map(col => (
                  <option key={col.key} value={col.key} disabled={used.includes(col.key)}>
                    {col.label}
                  </option>
                ))}
                <option disabled>──── 株価系 ────</option>
                {Object.entries(PRICE_SORT_COLUMNS).map(([key, col]) => (
                  <option key={key} value={key} disabled={used.includes(key)}>
                    📈 {col.label}
                  </option>
                ))}
              </select>
              <select
                value={level.dir}
                onChange={e => setLevel(idx, 'dir', e.target.value)}
                disabled={!level.key}
                style={{
                  width: 90, padding: '6px 8px', borderRadius: 6, fontSize: 12,
                  background: 'var(--surface2)', border: '1px solid var(--border)',
                  color: level.key ? 'var(--text)' : 'var(--text-dim)',
                }}
              >
                <option value="asc">▲ 昇順</option>
                <option value="desc">▼ 降順</option>
              </select>
              {level.key && (
                <button onClick={() => setLevel(idx, 'key', '')} style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text-dim)', fontSize: 14, padding: '2px 4px',
                }}>×</button>
              )}
            </div>
          )
        })}

        <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
          <button onClick={handleClear} style={{
            padding: '7px 16px', borderRadius: 6, fontSize: 12,
            background: 'var(--surface2)', border: '1px solid var(--border)',
            color: 'var(--text-dim)', cursor: 'pointer',
          }}>リセット</button>
          <button onClick={onClose} style={{
            padding: '7px 16px', borderRadius: 6, fontSize: 12,
            background: 'var(--surface2)', border: '1px solid var(--border)',
            color: 'var(--text)', cursor: 'pointer',
          }}>キャンセル</button>
          <button onClick={handleApply} style={{
            padding: '7px 20px', borderRadius: 6, fontSize: 12, fontWeight: 600,
            background: 'var(--accent)', border: 'none',
            color: '#fff', cursor: 'pointer',
          }}>適用</button>
        </div>
      </div>
    </div>
  )
}

// 竹原式プリセット
const PRESETS = {
  takehara: {
    label: '竹原式（バリュー）',
    desc: 'PER15以下 / PBR1以下 / ROE8%以上 / 営業利益率5%以上',
    params: { per_max: 15, pbr_max: 1, roe_min: 0.08, operating_margin_min: 0.05 },
  },
  value_cash: {
    label: '割安キャッシュリッチ',
    desc: 'PER12以下 / 現金比率20%以上 / FCF正',
    params: { per_max: 12, cash_ratio_min: 0.2, fcf_positive: true },
  },
  growth: {
    label: '成長株',
    desc: 'ROE10%以上 / 売上成長率10%以上 / 純利益成長率10%以上',
    params: { roe_min: 0.1, revenue_growth_min: 0.1, ni_growth_min: 0.1 },
  },
  dividend: {
    label: '高配当',
    desc: '配当あり / ROE5%以上 / PER20以下',
    params: { dividend_min: 1, roe_min: 0.05, per_max: 20 },
  },
  custom: {
    label: 'カスタム',
    desc: '自由にフィルタ条件を設定',
    params: {},
  },
}

const DEFAULT_FILTERS = {
  per_max: '', pbr_max: '', roe_min: '', equity_ratio_min: '',
  operating_margin_min: '', cash_ratio_min: '', fcf_positive: false,
  revenue_growth_min: '', ni_growth_min: '', dividend_min: '',
  industry: '', exclude_industries: '機械', tag: '', exclude_fake_growth: false,
}

// sort_byのカンマ区切り文字列をパース
function parseSortBy(str) {
  if (!str) return [{ key: 'score', dir: 'desc' }]
  return str.split(',').map(part => {
    const [key, dir] = part.split(':')
    return { key: key.trim(), dir: (dir || '').trim() || undefined }
  }).filter(s => s.key)
}

// sortKeysをカンマ区切り文字列に変換
function buildSortBy(sortKeys) {
  return sortKeys.map(s => `${s.key}:${s.dir || 'desc'}`).join(',')
}

export default function Screener() {
  const isMobile = useIsMobile()
  const [preset, setPreset] = useState('takehara')
  const [filters, setFilters] = useState({ ...DEFAULT_FILTERS, ...PRESETS.takehara.params })
  const [sortKeys, setSortKeys] = useState([{ key: 'score', dir: 'desc' }])
  const [page, setPage] = useState(1)
  const [showScoreHelp, setShowScoreHelp] = useState(false)
  const [showPrices, setShowPrices] = useState(IS_LOCAL)  // ローカル=ON、オンライン=OFF（メモリ節約）
  const [showSortDialog, setShowSortDialog] = useState(false)

  // appliedFiltersを計算
  const [appliedFilters, setAppliedFilters] = useState(() => ({
    ...DEFAULT_FILTERS, ...PRESETS.takehara.params,
    sort_by: 'score:desc', page: 1, limit: 100, with_prices: IS_LOCAL,
  }))

  const fetcher = useCallback(() => {
    const p = {}
    for (const [k, v] of Object.entries(appliedFilters)) {
      if (v !== '' && v !== null && v !== undefined && v !== false) p[k] = v
    }
    if (appliedFilters.fcf_positive) p.fcf_positive = true
    if (appliedFilters.exclude_fake_growth) p.exclude_fake_growth = true
    if (appliedFilters.exclude_industries) p.exclude_industries = appliedFilters.exclude_industries
    if (appliedFilters.with_prices) p.with_prices = true
    return api.screener(p)
  }, [appliedFilters])

  const { data, loading, error } = useFetch(fetcher, [appliedFilters])

  function doApply(newFilters, newSortKeys, newShowPrices) {
    const f = newFilters || filters
    const sk = newSortKeys || sortKeys
    const wp = newShowPrices !== undefined ? newShowPrices : showPrices
    setPage(1)
    setAppliedFilters({ ...f, sort_by: buildSortBy(sk), page: 1, limit: 100, with_prices: wp })
  }

  function applyPreset(key) {
    setPreset(key)
    const p = PRESETS[key]?.params || {}
    const newFilters = { ...DEFAULT_FILTERS, ...p }
    setFilters(newFilters)
    const defaultSort = [{ key: 'score', dir: 'desc' }]
    setSortKeys(defaultSort)
    doApply(newFilters, defaultSort)
  }

  function handleApply() {
    doApply()
  }

  function handlePageChange(newPage) {
    setPage(newPage)
    setAppliedFilters(prev => ({ ...prev, page: newPage, with_prices: showPrices }))
  }

  function setFilter(key, value) {
    setFilters(f => ({ ...f, [key]: value }))
    setPreset('custom')
  }

  // カラムヘッダークリック: 通常=主ソート置き換え, Shift=追加
  function handleSort(colKey, e) {
    const col = SORTABLE_COLUMNS.find(c => c.key === colKey)
    const pCol = PRICE_SORT_COLUMNS[colKey]
    const defaultDir = col?.defaultDir || pCol?.defaultDir || 'desc'
    if (!col && !pCol) return

    const shiftKey = e?.shiftKey
    let newKeys

    if (shiftKey) {
      const existing = sortKeys.findIndex(s => s.key === colKey)
      if (existing >= 0) {
        newKeys = [...sortKeys]
        newKeys[existing] = { ...newKeys[existing], dir: newKeys[existing].dir === 'asc' ? 'desc' : 'asc' }
      } else if (sortKeys.length < 3) {
        newKeys = [...sortKeys, { key: colKey, dir: defaultDir }]
      } else {
        return
      }
    } else {
      const current = sortKeys.find(s => s.key === colKey)
      if (current) {
        newKeys = [{ key: colKey, dir: current.dir === 'asc' ? 'desc' : 'asc' }]
      } else {
        newKeys = [{ key: colKey, dir: defaultDir }]
      }
    }

    setSortKeys(newKeys)
    setPreset('custom')
    doApply(null, newKeys)
  }

  // ソートダイアログから適用
  function handleSortDialogApply(newKeys) {
    setSortKeys(newKeys.length ? newKeys : [{ key: 'score', dir: 'desc' }])
    setPreset('custom')
    doApply(null, newKeys.length ? newKeys : [{ key: 'score', dir: 'desc' }])
  }

  // ソートキーの順番とdirを取得
  function getSortInfo(colKey) {
    const idx = sortKeys.findIndex(s => s.key === colKey)
    if (idx < 0) return null
    return { index: idx, dir: sortKeys[idx].dir }
  }

  // ソートチップを削除
  function removeSortKey(colKey) {
    const newKeys = sortKeys.filter(s => s.key !== colKey)
    if (newKeys.length === 0) newKeys.push({ key: 'score', dir: 'desc' })
    setSortKeys(newKeys)
    doApply(null, newKeys)
  }

  const { data: industries } = useFetch(api.industries, [])
  const totalCols = 11 + (showPrices ? 2 : 0)

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
        竹原式スクリーニング
      </h1>
      <p style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16 }}>
        複数の財務指標で割安優良銘柄を発見
      </p>

      {/* プリセットボタン */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {Object.entries(PRESETS).map(([key, { label }]) => (
          <button
            key={key}
            onClick={() => applyPreset(key)}
            style={{
              padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer',
              border: preset === key ? '1.5px solid var(--accent)' : '1px solid var(--border)',
              background: preset === key ? 'var(--accent-dim)' : 'var(--surface)',
              color: preset === key ? 'var(--accent)' : 'var(--text)',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* フィルタパネル */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>
          フィルタ条件
          {preset !== 'custom' && (
            <span style={{ fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8, fontSize: 11 }}>
              {PRESETS[preset]?.desc}
            </span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(auto-fill, minmax(180px, 1fr))', gap: isMobile ? 8 : 10 }}>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>PER上限</span>
            <input type="number" step="0.1" placeholder="例: 15"
              value={filters.per_max} onChange={e => setFilter('per_max', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>PBR上限</span>
            <input type="number" step="0.1" placeholder="例: 1.0"
              value={filters.pbr_max} onChange={e => setFilter('pbr_max', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>ROE下限 (%)</span>
            <input type="number" step="0.01" placeholder="例: 0.08"
              value={filters.roe_min} onChange={e => setFilter('roe_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>自己資本比率下限</span>
            <input type="number" step="0.01" placeholder="例: 0.3"
              value={filters.equity_ratio_min} onChange={e => setFilter('equity_ratio_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>営業利益率下限</span>
            <input type="number" step="0.01" placeholder="例: 0.05"
              value={filters.operating_margin_min} onChange={e => setFilter('operating_margin_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>現金/総資産 下限</span>
            <input type="number" step="0.01" placeholder="例: 0.1"
              value={filters.cash_ratio_min} onChange={e => setFilter('cash_ratio_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>売上成長率下限</span>
            <input type="number" step="0.01" placeholder="例: 0.1"
              value={filters.revenue_growth_min} onChange={e => setFilter('revenue_growth_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>純利益成長率下限</span>
            <input type="number" step="0.01" placeholder="例: 0.1"
              value={filters.ni_growth_min} onChange={e => setFilter('ni_growth_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12 }}>
            <span style={{ color: 'var(--text-dim)' }}>配当下限 (円)</span>
            <input type="number" step="1" placeholder="例: 10"
              value={filters.dividend_min} onChange={e => setFilter('dividend_min', e.target.value)} />
          </label>
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, paddingTop: 16 }}>
            <input type="checkbox" checked={filters.fcf_positive}
              onChange={e => setFilter('fcf_positive', e.target.checked)} />
            <span>FCF正のみ</span>
          </label>
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, paddingTop: 16 }}>
            <input type="checkbox" checked={filters.exclude_fake_growth}
              onChange={e => setFilter('exclude_fake_growth', e.target.checked)} />
            <span style={{ color: 'var(--yellow)' }}>見せかけ成長株を除外</span>
          </label>
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, paddingTop: 16 }}>
            <input type="checkbox" checked={filters.tag === 'SBI取扱'}
              onChange={e => setFilter('tag', e.target.checked ? 'SBI取扱' : '')} />
            <span style={{ fontWeight: 500 }}>SBI取扱のみ</span>
          </label>
          {industries && (
            <label style={{ fontSize: 12 }}>
              <span style={{ color: 'var(--text-dim)' }}>業種（絞り込み）</span>
              <select value={filters.industry} onChange={e => setFilter('industry', e.target.value)}>
                <option value="">全業種</option>
                {industries.map(i => (
                  <option key={i.industry} value={i.industry}>{i.industry} ({i.company_count})</option>
                ))}
              </select>
            </label>
          )}
          {industries && (
            <div style={{ fontSize: 12, gridColumn: '1 / -1' }}>
              <span style={{ color: 'var(--red)', fontWeight: 500, display: 'block', marginBottom: 4 }}>除外する業種</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', maxHeight: 120, overflowY: 'auto', padding: 4, background: 'var(--surface2)', borderRadius: 6 }}>
                {industries.map(i => {
                  const excList = (filters.exclude_industries || '').split(',').map(s => s.trim()).filter(Boolean)
                  const checked = excList.includes(i.industry)
                  return (
                    <label key={i.industry} style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer', whiteSpace: 'nowrap', fontSize: 11 }}>
                      <input type="checkbox" checked={checked} onChange={e => {
                        const next = e.target.checked
                          ? [...excList, i.industry]
                          : excList.filter(x => x !== i.industry)
                        setFilter('exclude_industries', next.join(','))
                      }} />
                      <span style={{ color: checked ? 'var(--red)' : 'var(--text-dim)' }}>{i.industry}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          )}
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={handleApply} style={{
            padding: '8px 24px', borderRadius: 6, background: 'var(--accent)', color: '#fff',
            border: 'none', fontWeight: 600, cursor: 'pointer',
          }}>
            スクリーニング実行
          </button>
          <button onClick={() => applyPreset('takehara')} style={{
            padding: '8px 16px', borderRadius: 6, background: 'var(--surface2)',
            border: '1px solid var(--border)', cursor: 'pointer', fontSize: 12,
          }}>
            リセット
          </button>
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, marginLeft: 16 }}>
            <input type="checkbox" checked={showPrices}
              onChange={e => {
                const v = e.target.checked
                setShowPrices(v)
                // 株価系ソートが入っている状態でOFFにしたらソートをリセット
                const hasPriceSort = sortKeys.some(s => s.key in PRICE_SORT_COLUMNS)
                if (!v && hasPriceSort) {
                  const newKeys = [{ key: 'score', dir: 'desc' }]
                  setSortKeys(newKeys)
                  doApply(null, newKeys, false)
                } else {
                  doApply(null, null, v)
                }
              }} />
            <span style={{ fontWeight: 500 }}>株価・売り時目安を表示</span>
          </label>
        </div>
      </div>

      {/* ソート状態バー */}
      <div className="card" style={{
        marginBottom: 16, padding: '8px 16px',
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)', fontWeight: 500, marginRight: 4 }}>
          並び替え:
        </span>
        {sortKeys.map((sk, idx) => {
          const label = ALL_SORT_LABELS[sk.key]
          if (!label) return null
          const isPriceKey = sk.key in PRICE_SORT_COLUMNS
          return (
            <span key={sk.key} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
              background: isPriceKey ? 'rgba(34,197,94,0.1)' : 'var(--accent-dim)',
              color: isPriceKey ? 'var(--green)' : 'var(--accent)',
              border: `1px solid ${isPriceKey ? 'var(--green)' : 'var(--accent)'}`,
            }}>
              <span style={{ fontSize: 10, opacity: 0.7 }}>{SORT_BADGES[idx]}</span>
              {isPriceKey && '📈 '}{label}
              <span style={{ fontSize: 10 }}>{sk.dir === 'asc' ? '▲' : '▼'}</span>
              <button onClick={() => removeSortKey(sk.key)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: isPriceKey ? 'var(--green)' : 'var(--accent)', fontSize: 12, padding: '0 2px', marginLeft: 2,
                lineHeight: 1,
              }}>×</button>
            </span>
          )
        })}
        <button onClick={() => setShowSortDialog(true)} style={{
          padding: '3px 10px', borderRadius: 12, fontSize: 11,
          background: 'var(--surface2)', border: '1px solid var(--border)',
          color: 'var(--text-dim)', cursor: 'pointer',
        }}>
          + ソート設定
        </button>
        <span style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 8 }}>
          Shift+クリックでソート追加
        </span>
      </div>

      {showSortDialog && (
        <SortDialog
          sortKeys={sortKeys}
          onApply={handleSortDialogApply}
          onClose={() => setShowSortDialog(false)}
          isMobile={isMobile}
        />
      )}

      {/* 結果 */}
      {error && <div style={{ color: 'var(--red)', marginBottom: 12 }}>エラー: {error}</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
        ) : (
          <>
            <div style={{
              padding: '10px 16px', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {data?.fiscal_year}年度 / {data?.total ?? 0}件ヒット
              </span>
              {data?.total > 100 && (
                <div style={{ display: 'flex', gap: 4 }}>
                  <button disabled={page <= 1} onClick={() => handlePageChange(page - 1)}
                    style={{ padding: '2px 8px', fontSize: 11, cursor: 'pointer', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)' }}>
                    前
                  </button>
                  <span style={{ fontSize: 11, padding: '2px 8px', color: 'var(--text-dim)' }}>
                    {page} / {Math.ceil((data?.total || 1) / 100)}
                  </span>
                  <button disabled={page >= Math.ceil((data?.total || 1) / 100)} onClick={() => handlePageChange(page + 1)}
                    style={{ padding: '2px 8px', fontSize: 11, cursor: 'pointer', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)' }}>
                    次
                  </button>
                </div>
              )}
            </div>

            {/* スコア説明パネル */}
            <div style={{ padding: '0 16px', borderBottom: '1px solid var(--border)' }}>
              <button
                onClick={() => setShowScoreHelp(v => !v)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer', fontSize: 11,
                  color: 'var(--accent)', padding: '6px 0', fontWeight: 500,
                }}
              >
                {showScoreHelp ? '▼' : '▶'} スコアの算出方法 / 売り時目安の見方
              </button>
              {showScoreHelp && (
                <div style={{ paddingBottom: 10, fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.8 }}>
                  <div style={{ marginBottom: 8, padding: '4px 8px', background: 'var(--surface2)', borderRadius: 4 }}>
                    <strong style={{ color: 'var(--text)' }}>総合スコア = V×30% + Q×25% + M×20% + D×15% + E×10%</strong>
                    <span style={{ marginLeft: 8, fontSize: 10 }}>（V:割安度 Q:質 M:勢い D:イベント E:定性）Phase 3 ※データなし層は自動再配分</span>
                  </div>
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Value スコア（竹原式 / 100点）</div>
                      <table style={{ fontSize: 11, minWidth: 'auto', borderCollapse: 'collapse' }}>
                        <tbody>
                          {[
                            ['CN-PER', '25点', 'CN-PER 3以下で満点。20以上で0点'],
                            ['PBR', '20点', '0.3以下で満点。3以上で0点'],
                            ['ROE', '20点', '15%以上で満点'],
                            ['営業利益率', '15点', '15%以上で満点'],
                            ['現金比率', '10点', '現金/総資産 30%以上で満点'],
                            ['FCF', '10点', '正なら加点'],
                          ].map(([name, pts, desc]) => (
                            <tr key={name} style={{ borderBottom: '1px solid var(--border)' }}>
                              <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{name}</td>
                              <td style={{ padding: '2px 8px 2px 0', color: 'var(--accent)', whiteSpace: 'nowrap' }}>{pts}</td>
                              <td style={{ padding: '2px 0' }}>{desc}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Quality スコア（100点）</div>
                      <table style={{ fontSize: 11, minWidth: 'auto', borderCollapse: 'collapse' }}>
                        <tbody>
                          {[
                            ['粗利率', '25点', '40%以上で満点。ブランド力・価格決定力'],
                            ['営業利益率', '30点', '20%以上で満点。コスト管理力'],
                            ['ROE', '25点', '15%以上で満点。資本効率'],
                            ['CF質', '20点', '営業CF/営業利益 ≥1.0で満点。現金回収力'],
                          ].map(([name, pts, desc]) => (
                            <tr key={name} style={{ borderBottom: '1px solid var(--border)' }}>
                              <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{name}</td>
                              <td style={{ padding: '2px 8px 2px 0', color: 'var(--accent)', whiteSpace: 'nowrap' }}>{pts}</td>
                              <td style={{ padding: '2px 0' }}>{desc}</td>
                            </tr>
                          ))}
                          <tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--yellow)', whiteSpace: 'nowrap' }}>偽成長</td>
                            <td style={{ padding: '2px 8px 2px 0', color: 'var(--red)', whiteSpace: 'nowrap' }}>減点</td>
                            <td style={{ padding: '2px 0' }}>偽成長フラグ1つ=-15点, 2つ以上=-30点</td>
                          </tr>
                          <tr>
                            <td colSpan={3} style={{ padding: '2px 0', fontSize: 10, color: 'var(--text-dim)' }}>
                              ※粗利データ未取得の企業は3指標(営業利益率35/ROE35/CF質30)で算出
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                  {/* Momentum Score */}
                  <div style={{ marginTop: 4 }}>
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Momentum スコア（100点）</div>
                      <table style={{ fontSize: 11, minWidth: 'auto', borderCollapse: 'collapse' }}>
                        <tbody>
                          {[
                            ['MA乖離率', '25点', '75日移動平均との乖離。+10%以上で満点'],
                            ['GC/DC', '20点', '25日MA > 75日MA（ゴールデンクロス）で加点'],
                            ['相対強度', '25点', '3ヶ月リターンがTOPIXを上回れば加点'],
                            ['出来高', '15点', '直近20日平均 vs 60日平均。増加で加点'],
                            ['ボラ調整', '15点', '年率ボラティリティ15%以下で満点'],
                          ].map(([name, pts, desc]) => (
                            <tr key={name} style={{ borderBottom: '1px solid var(--border)' }}>
                              <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{name}</td>
                              <td style={{ padding: '2px 8px 2px 0', color: 'var(--accent)', whiteSpace: 'nowrap' }}>{pts}</td>
                              <td style={{ padding: '2px 0' }}>{desc}</td>
                            </tr>
                          ))}
                          <tr>
                            <td colSpan={3} style={{ padding: '2px 0', fontSize: 10, color: 'var(--text-dim)' }}>
                              ※株価表示OFF時はMomentum=0点（V/Qのみで算出）
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                  {/* Event / AI Qualitative Score */}
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 4 }}>
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Event スコア（100点）</div>
                      <table style={{ fontSize: 11, minWidth: 'auto', borderCollapse: 'collapse' }}>
                        <tbody>
                          {[
                            ['増配トレンド', '25点', '直近3年で連続増配で加点'],
                            ['配当性向', '25点', '20-50%=適正。無配・80%超=減点'],
                            ['増収増益', '25点', '直近3年の増収・増益の連続性'],
                            ['業績加速', '25点', '直近成長率 > 過去平均で加点'],
                          ].map(([name, pts, desc]) => (
                            <tr key={name} style={{ borderBottom: '1px solid var(--border)' }}>
                              <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{name}</td>
                              <td style={{ padding: '2px 8px 2px 0', color: 'var(--accent)', whiteSpace: 'nowrap' }}>{pts}</td>
                              <td style={{ padding: '2px 0' }}>{desc}</td>
                            </tr>
                          ))}
                          <tr>
                            <td colSpan={3} style={{ padding: '2px 0', fontSize: 10, color: 'var(--text-dim)' }}>
                              ※財務履歴2年未満の企業はEvent=0（重み再配分）
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>AI定性 スコア（100点）</div>
                      <table style={{ fontSize: 11, minWidth: 'auto', borderCollapse: 'collapse' }}>
                        <tbody>
                          {[
                            ['信用スコア', '30点', 'EDINET信用スコアを正規化'],
                            ['財務安定性', '25点', '自己資本比率50%以上で満点'],
                            ['収益安定性', '25点', '純利益の変動係数が低いほど加点'],
                            ['利益の質', '20点', '経常利益/純利益≥80%で満点'],
                          ].map(([name, pts, desc]) => (
                            <tr key={name} style={{ borderBottom: '1px solid var(--border)' }}>
                              <td style={{ padding: '2px 8px 2px 0', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{name}</td>
                              <td style={{ padding: '2px 8px 2px 0', color: 'var(--accent)', whiteSpace: 'nowrap' }}>{pts}</td>
                              <td style={{ padding: '2px 0' }}>{desc}</td>
                            </tr>
                          ))}
                          <tr>
                            <td colSpan={3} style={{ padding: '2px 0', fontSize: 10, color: 'var(--text-dim)' }}>
                              ※信用スコア未取得の企業は残り3指標で算出
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-dim)' }}>
                    70点以上=<span style={{ color: 'var(--green)' }}>優良</span>
                    50点以上=<span style={{ color: 'var(--yellow)' }}>良好</span>
                    30点以上=<span style={{ color: 'var(--accent)' }}>普通</span>
                    30未満=<span style={{ color: 'var(--red)' }}>要注意</span>
                  </div>
                  <div style={{ marginTop: 8, padding: '6px 10px', background: 'var(--surface2)', borderRadius: 6 }}>
                    <strong style={{ color: 'var(--text)' }}>売り時目安の見方：</strong>
                    <br />目安株価 = EPS × 15（PER15倍ライン）。この株価を超えると竹原式では「割安感なし」。
                    <br /><span style={{ color: 'var(--green)' }}>■割安</span>（-20%以下）
                    → <span style={{ color: 'var(--green)' }}>■やや割安</span>（0%以下）
                    → <span style={{ color: 'var(--yellow)' }}>■適正~やや割高</span>（+20%以下）
                    → <span style={{ color: 'var(--red)' }}>■売り検討</span>（+20%超）
                  </div>
                </div>
              )}
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ minWidth: isMobile ? 700 : (showPrices ? 1350 : 1000), fontSize: isMobile ? 11 : undefined }}>
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    {SORTABLE_COLUMNS.map(col => {
                      const si = getSortInfo(col.key)
                      return (
                        <th
                          key={col.key}
                          onClick={(e) => handleSort(col.key, e)}
                          title={col.tooltip || `${col.label}でソート (Shift+クリックで追加)`}
                          style={{
                            textAlign: col.align,
                            cursor: 'pointer',
                            userSelect: 'none',
                            whiteSpace: 'nowrap',
                            background: si ? 'var(--accent-dim, rgba(99,102,241,0.08))' : undefined,
                            transition: 'background 0.15s',
                            position: 'relative',
                          }}
                        >
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                            {col.label}
                            {si ? (
                              <span style={{ marginLeft: 3, fontSize: 10, color: 'var(--accent)' }}>
                                {si.dir === 'asc' ? '▲' : '▼'}
                              </span>
                            ) : (
                              <span style={{ opacity: 0.25, marginLeft: 2, fontSize: 10 }}>&#x25B2;&#x25BC;</span>
                            )}
                            {si && sortKeys.length > 1 && (
                              <span style={{
                                fontSize: 9, fontWeight: 800, color: 'var(--accent)',
                                marginLeft: 1,
                              }}>{SORT_BADGES[si.index]}</span>
                            )}
                          </span>
                        </th>
                      )
                    })}
                    {showPrices && (
                      <th style={{ textAlign: 'right', whiteSpace: 'nowrap', minWidth: 80, padding: '4px 8px' }}>
                        {(() => {
                          const si = sortKeys.find(s => s.key === 'cn_per')
                          return (
                            <span
                              onClick={(e) => handleSort('cn_per', e)}
                              title="CN-PERでソート (Shift+クリックで追加)"
                              style={{
                                cursor: 'pointer', userSelect: 'none', fontSize: 11,
                                padding: '2px 5px', borderRadius: 4,
                                background: si ? 'rgba(34,197,94,0.15)' : 'transparent',
                                color: si ? 'var(--green)' : 'var(--text-dim)',
                                fontWeight: si ? 700 : 400,
                              }}
                            >
                              CN-PER{si ? (si.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                            </span>
                          )
                        })()}
                      </th>
                    )}
                    {showPrices && (
                      <th style={{ textAlign: 'right', whiteSpace: 'nowrap', minWidth: 200, padding: '4px 8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 6 }}>
                          {[
                            { key: 'target', label: '目安' },
                            { key: 'price', label: '現在値' },
                            { key: 'gap', label: '乖離率' },
                          ].map(col => {
                            const si = sortKeys.find(s => s.key === col.key)
                            return (
                              <span
                                key={col.key}
                                onClick={(e) => handleSort(col.key, e)}
                                title={`${col.label}でソート (Shift+クリックで追加)`}
                                style={{
                                  cursor: 'pointer', userSelect: 'none', fontSize: 11,
                                  padding: '2px 5px', borderRadius: 4,
                                  background: si ? 'rgba(34,197,94,0.15)' : 'transparent',
                                  color: si ? 'var(--green)' : 'var(--text-dim)',
                                  fontWeight: si ? 700 : 400,
                                  transition: 'all 0.15s',
                                }}
                              >
                                {col.label}
                                {si ? (si.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                              </span>
                            )
                          })}
                          {loading && showPrices && <span className="spinner" style={{ width: 12, height: 12 }} />}
                        </div>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data?.results?.map((row, i) => {
                    return (
                      <tr key={row.edinet_code}>
                        <td style={{ color: 'var(--text-dim)', fontSize: 11 }}>{(page - 1) * 100 + i + 1}</td>
                        <td>
                          <Link to={`/companies/${row.edinet_code}`} state={{ from: 'screener' }} style={{ fontWeight: 500 }}>
                            {row.company_name}
                          </Link>
                          <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{row.securities_code ? row.securities_code.slice(0, 4) : ''}</div>
                          {row.is_fake_growth && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, marginTop: 2 }}>
                              {row.fake_growth_flags?.map((f, fi) => (
                                <span key={fi} style={{
                                  fontSize: 9, background: 'rgba(234,179,8,0.15)', color: 'var(--yellow)',
                                  padding: '1px 4px', borderRadius: 3, lineHeight: 1.3,
                                }}>{f}</span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td style={{ fontSize: 11, color: 'var(--text-dim)' }}>{row.industry || '-'}</td>
                        <td style={{ textAlign: 'right' }}>
                          <TotalScoreCell row={row} />
                        </td>
                        <td className="number" style={{ textAlign: 'right', fontWeight: 500 }}>
                          {row.per != null ? `${Number(row.per).toFixed(1)}` : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {row.pbr != null ? `${Number(row.pbr).toFixed(2)}` : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {pct(row.roe)}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {pct(row.operating_margin)}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {pct(row.cash_ratio)}
                        </td>
                        <td className="number" style={{ textAlign: 'right' }}>
                          {row.dividend != null ? `${row.dividend}` : '-'}
                        </td>
                        <td className="number" style={{ textAlign: 'right', fontSize: 11 }}>
                          {row.fcf != null ? fmtAmt(row.fcf) : '-'}
                        </td>
                        {showPrices && (
                          <td style={{ textAlign: 'right' }}>
                            <CnPerBadge cnPer={row.cn_per} ncr={row.net_cash_ratio} />
                          </td>
                        )}
                        {showPrices && (
                          <td style={{ textAlign: 'right' }}>
                            <PriceTarget row={row} currentPrice={row.current_price} />
                          </td>
                        )}
                      </tr>
                    )
                  })}
                  {(!data?.results || data.results.length === 0) && (
                    <tr>
                      <td colSpan={totalCols} style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>
                        条件に一致する銘柄がありません。フィルタを緩めてみてください。
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
