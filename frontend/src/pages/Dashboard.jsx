import { api } from '../api'
import { useFetch } from '../hooks/useFetch'
import { Database, Building2, FileText, Clock } from 'lucide-react'

function StatCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div style={{
        width: 44, height: 44, borderRadius: 10,
        background: 'var(--accent-dim)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon size={20} color="var(--accent)" />
      </div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1 }}>{value}</div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>{label}</div>
        {sub && <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { data, loading, error } = useFetch(api.status, [])
  const { data: industries } = useFetch(api.industries, [])

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
  if (error) return (
    <div className="card" style={{ color: 'var(--red)' }}>
      <strong>接続エラー:</strong> {error}
      <p style={{ marginTop: 8, color: 'var(--text-dim)', fontSize: 13 }}>
        バックエンドが起動しているか確認してください: <code>uvicorn backend.main:app --reload</code>
      </p>
    </div>
  )

  const lastSync = data?.last_sync
  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 20 }}>ダッシュボード</h1>

      {data?.status === 'no_db' && (
        <div className="card" style={{ marginBottom: 20, borderColor: 'var(--yellow)', color: 'var(--yellow)' }}>
          <strong>データベース未作成</strong> — 以下を実行してデータを収集してください:
          <pre style={{ marginTop: 8, background: 'var(--surface2)', padding: 12, borderRadius: 6, color: 'var(--text)', fontSize: 13 }}>
{`cd edinetdb-viewer
python backend/collector.py --limit 100   # まず100社でテスト
python backend/collector.py               # 全企業（数時間かかる場合あり）`}
          </pre>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }}>
        <StatCard icon={Building2} label="収録企業数" value={data?.companies?.toLocaleString() ?? '–'} />
        <StatCard icon={FileText}  label="財務レコード数" value={data?.financials?.toLocaleString() ?? '–'} />
        <StatCard icon={Database}  label="DB保存先" value="ローカル" sub={data?.db_path} />
        <StatCard
          icon={Clock} label="最終同期"
          value={lastSync ? new Date(lastSync.finished_at).toLocaleString('ja-JP') : '未同期'}
          sub={lastSync ? `${lastSync.companies_synced}社` : undefined}
        />
      </div>

      {industries && industries.length > 0 && (
        <div className="card">
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 14 }}>業種別企業数 (上位20)</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
            {industries.slice(0, 20).map(ind => (
              <div key={ind.industry_code} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 12px', background: 'var(--surface2)', borderRadius: 6,
              }}>
                <span style={{ fontSize: 13 }}>{ind.industry || ind.industry_code}</span>
                <span className="badge badge-blue">{ind.company_count}社</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
