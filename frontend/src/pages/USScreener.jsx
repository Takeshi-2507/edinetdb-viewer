import { useState, useCallback } from 'react'
import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { useIsMobile } from '../hooks/useIsMobile'

// ── フォーマッタ ──

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

// ── ScoreBar (JP版と同一) ──

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

// ── TotalScoreCell (JP版と同一スタイル) ──

function TotalScoreCell({ row }) {
  const total = row.takehara_score
  if (total == null) return <span style={{ color: 'var(--text-dim)' }}>-</span>
  const color = total >= 70 ? 'var(--green)' : total >= 50 ? 'var(--yellow)' : total >= 30 ? 'var(--accent)' : 'var(--red)'
  const sc = (v) => v > 0 ? (v >= 70 ? 'var(--green)' : v >= 50 ? 'var(--yellow)' : 'var(--text-dim)') : 'var(--text-dim)'
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
        <span style={{ color: sc(row.value_score) }}>V:{row.value_score ?? '-'}</span>
        <span style={{ color: sc(row.quality_score) }}>Q:{row.quality_score ?? '-'}</span>
        <span style={{ color: sc(row.momentum_score) }}>M:{row.momentum_score ?? '-'}</span>
        <span style={{ color: sc(row.dividend_score) }}>D:{row.dividend_score ?? '-'}</span>
        <span style={{ color: sc(row.stability_score) }}>S:{row.stability_score ?? '-'}</span>
      </div>
    </div>
  )
}

// ── 目安株価 (JP PriceTarget の USD版) ──

function USPriceTarget({ row }) {
  const target = row.target_per15
  if (!target) return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>-</span>
  const price = row.price
  let gapPct = null, gapColor = 'var(--text-dim)', label = ''
  if (price && target) {
    gapPct = ((price - target) / target) * 100
    if (gapPct <= -20) { gapColor = 'var(--green)'; label = '割安' }
    else if (gapPct <= 0) { gapColor = 'var(--green)'; label = 'やや割安' }
    else if (gapPct <= 20) { gapColor = 'var(--yellow)'; label = '適正~やや割高' }
    else { gapColor = 'var(--red)'; label = '売り検討' }
  }
  return (
    <div style={{ fontSize: 11, lineHeight: 1.6 }}>
      <div style={{ whiteSpace: 'nowrap' }}>
        <span style={{ color: 'var(--text-dim)' }}>目安: </span>
        <span style={{ fontWeight: 600 }}>{fmtUSD(target)}</span>
      </div>
      {price != null && (
        <div style={{ whiteSpace: 'nowrap' }}>
          <span style={{ color: 'var(--text-dim)' }}>現在: </span>
          <span style={{ fontWeight: 500 }}>{fmtUSD(price)}</span>
          <span style={{ marginLeft: 4, fontWeight: 600, color: gapColor, fontSize: 10 }}>
            {gapPct != null ? `${gapPct > 0 ? '+' : ''}${gapPct.toFixed(0)}% ${label}` : ''}
          </span>
        </div>
      )}
    </div>
  )
}

// ── カラム定義 (日本語) ──

const US_COLUMNS = [
  { key: 'company_name',     label: '銘柄',      align: 'left',  defaultDir: 'asc' },
  { key: 'sector',           label: 'セクター',   align: 'left',  defaultDir: 'asc', hideMobile: true },
  { key: 'score',            label: '総合',       align: 'right', defaultDir: 'desc',
    tooltip: '総合 = V×30% + Q×25% + M×20% + D×15% + S×10%' },
  { key: 'per',              label: 'PER',        align: 'right', defaultDir: 'asc', hideMobile: true },
  { key: 'pbr',              label: 'PBR',        align: 'right', defaultDir: 'asc', hideMobile: true },
  { key: 'roe',              label: 'ROE',        align: 'right', defaultDir: 'desc' },
  { key: 'operating_margin', label: '営業利益率',  align: 'right', defaultDir: 'desc', hideMobile: true },
  { key: 'dividend',         label: '配当',       align: 'right', defaultDir: 'desc' },
  { key: 'market_cap',       label: '時価総額',   align: 'right', defaultDir: 'desc', hideMobile: true },
]

const SORT_BADGES = ['\u2460', '\u2461', '\u2462']

// ── ソートダイアログ (JP版と同一) ──

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
      if (field === 'key' && value) {
        const col = US_COLUMNS.find(c => c.key === value)
        const defDir = col?.defaultDir || 'desc'
        if (!next[idx].dir) next[idx] = { ...next[idx], dir: defDir }
      }
      if (field === 'key' && !value) next[idx] = { key: '', dir: '' }
      return next
    })
  }

  function handleApply() { onApply(keys.filter(k => k.key)); onClose() }
  function handleClear() { onApply([{ key: 'score', dir: 'desc' }]); onClose() }

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
              opacity: disabled ? 0.35 : 1, pointerEvents: disabled ? 'none' : 'auto',
            }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)', minWidth: 60, whiteSpace: 'nowrap' }}>
                {idx === 0 ? '第1キー' : idx === 1 ? '第2キー' : '第3キー'}
              </span>
              <select value={level.key} onChange={e => setLevel(idx, 'key', e.target.value)}
                style={{ flex: 1, padding: '6px 10px', borderRadius: 6, fontSize: 12, background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)' }}>
                <option value="">-- 選択 --</option>
                {US_COLUMNS.map(col => (
                  <option key={col.key} value={col.key} disabled={used.includes(col.key)}>{col.label}</option>
                ))}
              </select>
              <select value={level.dir} onChange={e => setLevel(idx, 'dir', e.target.value)} disabled={!level.key}
                style={{ width: 90, padding: '6px 8px', borderRadius: 6, fontSize: 12, background: 'var(--surface2)', border: '1px solid var(--border)', color: level.key ? 'var(--text)' : 'var(--text-dim)' }}>
                <option value="asc">{'\u25B2'} 昇順</option>
                <option value="desc">{'\u25BC'} 降順</option>
              </select>
              {level.key && (
                <button onClick={() => setLevel(idx, 'key', '')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 14, padding: '2px 4px' }}>{'\u00D7'}</button>
              )}
            </div>
          )
        })}

        <div style={{ display: 'flex', gap: 8, marginTop: 18, justifyContent: 'flex-end' }}>
          <button onClick={handleClear} style={{ padding: '7px 16px', borderRadius: 6, fontSize: 12, background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text-dim)', cursor: 'pointer' }}>リセット</button>
          <button onClick={onClose} style={{ padding: '7px 16px', borderRadius: 6, fontSize: 12, background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)', cursor: 'pointer' }}>キャンセル</button>
          <button onClick={handleApply} style={{ padding: '7px 20px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: 'var(--accent)', border: 'none', color: '#fff', cursor: 'pointer' }}>適用</button>
        </div>
      </div>
    </div>
  )
}

// ── 行展開 (5層詳細) ──

const LAYER_LABELS = [
  { key: 'value_score', short: 'V', label: 'Value', color: '#6366f1' },
  { key: 'quality_score', short: 'Q', label: 'Quality', color: '#06b6d4' },
  { key: 'momentum_score', short: 'M', label: 'Momentum', color: '#f59e0b' },
  { key: 'dividend_score', short: 'D', label: 'Dividend', color: '#10b981' },
  { key: 'stability_score', short: 'S', label: 'Stability', color: '#8b5cf6' },
]

// ── プリセット (日本語) ──

const PRESETS = {
  all:      { label: '全銘柄',           desc: '全銘柄表示', params: {} },
  takehara: { label: '竹原式（バリュー）', desc: 'PER20以下 / PBR3以下 / ROE8%以上', params: { per_max: 20, pbr_max: 3, roe_min: 0.08 } },
  income:   { label: '高配当',           desc: '配当$2以上 / ROE5%以上', params: { dividend_min: 2, roe_min: 0.05 } },
  growth:   { label: '成長株',           desc: 'ROE15%以上 / 営業利益率10%以上', params: { roe_min: 0.15, operating_margin_min: 0.1 } },
}

// ── メインコンポーネント ──

export default function USScreener() {
  const isMobile = useIsMobile()
  const [preset, setPreset] = useState('all')
  const [filters, setFilters] = useState({})
  const [sortKeys, setSortKeys] = useState([{ key: 'score', dir: 'desc' }])
  const [showSortDialog, setShowSortDialog] = useState(false)
  const [page, setPage] = useState(1)
  const [appliedParams, setAppliedParams] = useState({ sort_by: 'score', sort_dir: 'desc', page: 1, limit: 100 })
  const [expanded, setExpanded] = useState(null)

  const fetcher = useCallback(() => {
    const p = { ...appliedParams }
    for (const [k, v] of Object.entries(p)) {
      if (v === '' || v === null || v === undefined || v === false) delete p[k]
    }
    return api.usScreener(p)
  }, [appliedParams])

  const { data, loading, error } = useFetch(fetcher, [appliedParams])

  function buildSortParams(keys) {
    if (keys.length === 0) return { sort_by: 'score', sort_dir: 'desc' }
    return { sort_by: keys.map(k => `${k.key}:${k.dir}`).join(','), sort_dir: '' }
  }

  function applyPreset(key) {
    setPreset(key)
    const p = PRESETS[key]?.params || {}
    setFilters(p)
    setPage(1)
    setAppliedParams({ ...p, ...buildSortParams(sortKeys), page: 1, limit: 100 })
  }

  function handleApply() {
    setPage(1)
    setAppliedParams({ ...filters, ...buildSortParams(sortKeys), page: 1, limit: 100 })
  }

  function handleSort(colKey) {
    const col = US_COLUMNS.find(c => c.key === colKey)
    if (!col) return
    let newKeys
    const existing = sortKeys.find(k => k.key === colKey)
    if (existing) {
      newKeys = sortKeys.map(k => k.key === colKey ? { ...k, dir: k.dir === 'asc' ? 'desc' : 'asc' } : k)
    } else {
      newKeys = [{ key: colKey, dir: col.defaultDir }]
    }
    setSortKeys(newKeys)
    setPage(1)
    setAppliedParams(prev => ({ ...prev, ...buildSortParams(newKeys), page: 1 }))
  }

  function handleSortApply(keys) {
    const newKeys = keys.length > 0 ? keys : [{ key: 'score', dir: 'desc' }]
    setSortKeys(newKeys)
    setPage(1)
    setAppliedParams(prev => ({ ...prev, ...buildSortParams(newKeys), page: 1 }))
  }

  function handlePageChange(newPage) {
    setPage(newPage)
    setAppliedParams(prev => ({ ...prev, page: newPage }))
  }

  function getSortBadge(colKey) {
    const idx = sortKeys.findIndex(k => k.key === colKey)
    if (idx < 0) return null
    const k = sortKeys[idx]
    return (
      <span style={{ marginLeft: 3, fontSize: 10, color: 'var(--accent)' }}>
        {k.dir === 'asc' ? '\u25B2' : '\u25BC'}
        {sortKeys.length > 1 && <span style={{ fontSize: 8, marginLeft: 1 }}>{SORT_BADGES[idx]}</span>}
      </span>
    )
  }

  const visibleCols = isMobile ? US_COLUMNS.filter(c => !c.hideMobile) : US_COLUMNS
  const totalPages = data?.pages ?? 1

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
        {'\ud83c\uddfa\ud83c\uddf8'} 米国株スクリーニング
      </h1>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span>S&P500 全{data?.universe_size ?? '503'}銘柄 / 5層スコアリング (6時間ごと自動更新)</span>
        {data?.updated_at && (
          <span style={{ fontSize: 11 }}>
            最終更新: {new Date(data.updated_at).toLocaleString('ja-JP')}
            {data.updating && <span className="spinner" style={{ width: 10, height: 10, marginLeft: 6, display: 'inline-block' }} />}
          </span>
        )}
      </div>

      {/* プリセット */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {Object.entries(PRESETS).map(([key, { label, desc }]) => (
          <button key={key} onClick={() => applyPreset(key)} title={desc}
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
              {data?.updating ? '初回データ取得中...約2分お待ちください' : 'データを読み込み中...'}
            </div>
          </div>
        ) : (
          <>
            {/* ヘッダバー */}
            <div style={{
              padding: '10px 16px', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              flexWrap: 'wrap', gap: 8,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {data?.total ?? 0}銘柄 / {data?.universe_size ?? 0}銘柄中
                </span>
                {/* ソートバッジ */}
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {sortKeys.map((k, i) => {
                    const col = US_COLUMNS.find(c => c.key === k.key)
                    return (
                      <span key={i} onClick={() => setShowSortDialog(true)} style={{
                        padding: '2px 8px', borderRadius: 10, fontSize: 10, cursor: 'pointer',
                        background: 'var(--accent-dim, rgba(99,102,241,0.08))',
                        border: '1px solid var(--accent)',
                        color: 'var(--accent)', fontWeight: 600,
                      }}>
                        {SORT_BADGES[i]} {col?.label ?? k.key} {k.dir === 'asc' ? '\u25B2' : '\u25BC'}
                      </span>
                    )
                  })}
                  <button onClick={() => setShowSortDialog(true)} style={{
                    padding: '2px 8px', borderRadius: 10, fontSize: 10, cursor: 'pointer',
                    background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text-dim)',
                  }}>並替</button>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {data?.sectors?.length > 0 && (
                  <select value={filters.sector || ''} onChange={e => {
                    setFilters(f => ({ ...f, sector: e.target.value }))
                    setPreset('custom')
                    setPage(1)
                    setAppliedParams(prev => ({ ...prev, sector: e.target.value, page: 1 }))
                  }} style={{
                    padding: '3px 8px', fontSize: 11, borderRadius: 4,
                    background: 'var(--surface2)', border: '1px solid var(--border)', color: 'var(--text)',
                  }}>
                    <option value="">全セクター</option>
                    {data.sectors.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                )}
                {/* ページネーション */}
                {totalPages > 1 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                    <button onClick={() => handlePageChange(Math.max(1, page - 1))} disabled={page <= 1}
                      style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface2)', cursor: page > 1 ? 'pointer' : 'default', color: 'var(--text)', opacity: page <= 1 ? 0.3 : 1 }}>{'\u25C0'}</button>
                    <span style={{ color: 'var(--text-dim)', minWidth: 60, textAlign: 'center' }}>{page} / {totalPages}</span>
                    <button onClick={() => handlePageChange(Math.min(totalPages, page + 1))} disabled={page >= totalPages}
                      style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface2)', cursor: page < totalPages ? 'pointer' : 'default', color: 'var(--text)', opacity: page >= totalPages ? 0.3 : 1 }}>{'\u25B6'}</button>
                  </div>
                )}
              </div>
            </div>

            {/* テーブル */}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ minWidth: isMobile ? 420 : 1100, fontSize: isMobile ? 11 : undefined }}>
                <thead>
                  <tr>
                    <th style={{ width: 32 }}>#</th>
                    {visibleCols.map(col => (
                      <th key={col.key} onClick={() => handleSort(col.key)}
                        title={col.tooltip || ''}
                        style={{
                          textAlign: col.align, cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
                          background: sortKeys.some(k => k.key === col.key) ? 'var(--accent-dim, rgba(99,102,241,0.08))' : undefined,
                        }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                          {col.label}{getSortBadge(col.key)}
                        </span>
                      </th>
                    ))}
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>売り時目安</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.results?.map((row, i) => {
                    const isExpanded = expanded === row.ticker
                    const rowNum = (page - 1) * 100 + i + 1
                    return [
                      <tr key={row.ticker} onClick={() => setExpanded(isExpanded ? null : row.ticker)}
                        style={{ cursor: 'pointer' }}>
                        <td style={{ color: 'var(--text-dim)', fontSize: 11 }}>{rowNum}</td>
                        {visibleCols.map(col => {
                          if (col.key === 'company_name') return (
                            <td key={col.key}>
                              <div style={{ fontWeight: 600, fontSize: 13 }}>{row.ticker}</div>
                              <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                                {row.company_name}{isMobile && row.sector ? ` / ${row.sector}` : ''}
                              </div>
                            </td>
                          )
                          if (col.key === 'sector') return <td key={col.key} style={{ fontSize: 10, color: 'var(--text-dim)' }}>{row.sector || '-'}</td>
                          if (col.key === 'score') return <td key={col.key} style={{ textAlign: 'right' }}><TotalScoreCell row={row} /></td>
                          if (col.key === 'per') return <td key={col.key} className="number" style={{ textAlign: 'right', fontWeight: 500 }}>{row.per != null ? Number(row.per).toFixed(1) : '-'}</td>
                          if (col.key === 'pbr') return <td key={col.key} className="number" style={{ textAlign: 'right' }}>{row.pbr != null ? Number(row.pbr).toFixed(2) : '-'}</td>
                          if (col.key === 'roe') return <td key={col.key} className="number" style={{ textAlign: 'right' }}>{pct(row.roe)}</td>
                          if (col.key === 'operating_margin') return <td key={col.key} className="number" style={{ textAlign: 'right' }}>{pct(row.operating_margin)}</td>
                          if (col.key === 'dividend') return <td key={col.key} className="number" style={{ textAlign: 'right' }}>{row.dividend != null ? `$${Number(row.dividend).toFixed(2)}` : '-'}</td>
                          if (col.key === 'market_cap') return <td key={col.key} className="number" style={{ textAlign: 'right', fontSize: 11 }}>{fmtCap(row.market_cap)}</td>
                          return null
                        })}
                        <td style={{ textAlign: 'right' }}><USPriceTarget row={row} /></td>
                      </tr>,
                      isExpanded && (
                        <tr key={`${row.ticker}-detail`}>
                          <td colSpan={visibleCols.length + 2} style={{ padding: '8px 12px', background: 'var(--surface)' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(5, 1fr)', gap: 8 }}>
                              {LAYER_LABELS.map(l => {
                                const v = row[l.key] ?? 0
                                return (
                                  <div key={l.key} style={{
                                    padding: '6px 8px', borderRadius: 6, background: 'var(--surface2)',
                                    border: `1px solid ${l.color}22`,
                                  }}>
                                    <div style={{ fontSize: 10, color: l.color, fontWeight: 700, marginBottom: 4 }}>
                                      {l.short} {l.label}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                      <div style={{ flex: 1, height: 4, background: 'var(--bg)', borderRadius: 2, overflow: 'hidden' }}>
                                        <div style={{ width: `${Math.min(100, v)}%`, height: '100%', background: l.color, borderRadius: 2 }} />
                                      </div>
                                      <span style={{ fontWeight: 700, fontSize: 12, color: l.color, minWidth: 28, textAlign: 'right' }}>{v}</span>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                            <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text-dim)', display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
                              <span>Beta: {row.beta ?? '-'}</span>
                              <span>D/E: {row.debt_to_equity != null ? `${row.debt_to_equity}%` : '-'}</span>
                              <span>配当性向: {row.payout_ratio != null ? pct(row.payout_ratio) : '-'}</span>
                              <span>52週: {row.lo52 ? fmtUSD(row.lo52) : '-'} - {row.hi52 ? fmtUSD(row.hi52) : '-'}</span>
                              <span>売上成長: {row.revenue_growth != null ? pct(row.revenue_growth) : '-'}</span>
                              <span>利益成長: {row.earnings_growth != null ? pct(row.earnings_growth) : '-'}</span>
                            </div>
                          </td>
                        </tr>
                      ),
                    ]
                  })}
                  {(!data?.results || data.results.length === 0) && !loading && (
                    <tr>
                      <td colSpan={visibleCols.length + 2} style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>
                        {data?.updating ? '初回データ取得中...約2分お待ちください' : '条件に一致する銘柄がありません'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* 下部ページネーション */}
            {totalPages > 1 && (
              <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'center', gap: 4 }}>
                <button onClick={() => handlePageChange(Math.max(1, page - 1))} disabled={page <= 1}
                  style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface2)', cursor: page > 1 ? 'pointer' : 'default', color: 'var(--text)', fontSize: 12, opacity: page <= 1 ? 0.3 : 1 }}>{'\u25C0'} 前へ</button>
                <span style={{ padding: '4px 12px', fontSize: 12, color: 'var(--text-dim)' }}>{page} / {totalPages} ページ</span>
                <button onClick={() => handlePageChange(Math.min(totalPages, page + 1))} disabled={page >= totalPages}
                  style={{ padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface2)', cursor: page < totalPages ? 'pointer' : 'default', color: 'var(--text)', fontSize: 12, opacity: page >= totalPages ? 0.3 : 1 }}>次へ {'\u25B6'}</button>
              </div>
            )}
          </>
        )}
      </div>

      {showSortDialog && (
        <SortDialog
          sortKeys={sortKeys}
          onApply={handleSortApply}
          onClose={() => setShowSortDialog(false)}
          isMobile={isMobile}
        />
      )}
    </div>
  )
}
