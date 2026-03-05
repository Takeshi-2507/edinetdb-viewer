# EDINET DB Viewer — 現行アプリ仕様書（SnowWillow Terminal 改修用）

## 概要

日本上場企業（約3,848社）のEDINET財務データを可視化・スクリーニングするフルスタックWebアプリ。
「竹原式スコア」による割安小型株のスクリーニングがコア機能。

- **URL（オンライン版）**: Render.com にデプロイ（Free tier, Docker）
- **ローカル版**: 株価表示ON・サイバーテーマ（cyan/purple + 地球背景）

---

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| Backend | Python 3.11 / FastAPI / SQLite |
| 株価取得 | yfinance（リアルタイム、5分キャッシュ） |
| Frontend | React 18 / Vite / Recharts / Lucide Icons |
| デプロイ | Docker multi-stage / Render.com |
| データ同期 | GitHub Actions（毎日JST 3:00にEDINET APIからDB更新） |
| DB | SQLite（`data/edinet.db`） |

---

## データベーススキーマ

### companies テーブル
| カラム | 型 | 説明 |
|--------|------|------|
| edinet_code | TEXT PK | EDINET企業コード（例: E02419） |
| securities_code | TEXT | 証券コード（例: 7203） |
| company_name | TEXT | 企業名 |
| industry | TEXT | 業種（例: 機械、情報・通信業） |
| accounting_std | TEXT | 会計基準（IFRS / J-GAAP） |
| credit_score | INTEGER | 信用スコア 0-100 |
| credit_rating | TEXT | 信用格付け（S/A/B/C/D） |
| updated_at | TEXT | 最終更新日時 |

### financials テーブル
| カラム | 型 | 説明 |
|--------|------|------|
| edinet_code | TEXT FK | |
| fiscal_year | INTEGER | 会計年度 |
| revenue | INTEGER | 売上高 |
| operating_income | INTEGER | 営業利益 |
| ordinary_income | INTEGER | 経常利益 |
| net_income | INTEGER | 当期純利益 |
| total_assets | INTEGER | 総資産 |
| net_assets | INTEGER | 純資産 |
| cash | INTEGER | 現金及び預金 |
| roe | REAL | ROE |
| equity_ratio | REAL | 自己資本比率 |
| eps | REAL | EPS |
| bps | REAL | BPS |
| dividend | REAL | 配当 |
| per | REAL | PER |
| payout_ratio | REAL | 配当性向 |
| cf_operating | INTEGER | 営業CF |
| cf_investing | INTEGER | 投資CF |
| cf_financing | INTEGER | 財務CF |
| accounting_std | TEXT | |
| UNIQUE(edinet_code, fiscal_year) | | |

### ratios テーブル
| カラム | 型 | 説明 |
|--------|------|------|
| edinet_code | TEXT FK | |
| fiscal_year | INTEGER | |
| fcf | INTEGER | FCF（営業CF - 投資CF） |
| roa | REAL | ROA |
| roe | REAL | ROE |
| net_margin | REAL | 純利益率 |
| operating_margin | REAL | 営業利益率 |
| eps_growth | REAL | EPS成長率（前年比） |
| ni_growth | REAL | 純利益成長率 |
| oi_growth | REAL | 営業利益成長率 |
| revenue_growth | REAL | 売上成長率 |
| eps_cagr_3y / 5y | REAL | EPS CAGR |
| ni_cagr_3y / 5y | REAL | 純利益 CAGR |
| revenue_cagr_3y / 5y | REAL | 売上 CAGR |
| UNIQUE(edinet_code, fiscal_year) | | |

### analysis テーブル
| カラム | 型 | 説明 |
|--------|------|------|
| edinet_code | TEXT PK | |
| credit_score | INTEGER | |
| credit_rating | TEXT | |
| ai_summary | TEXT | AI要約 |
| strengths | TEXT | 強み（JSON配列） |
| risks | TEXT | リスク（JSON配列） |
| updated_at | TEXT | |

### その他テーブル
- **sync_log**: 夜間同期のログ（status, companies_synced, started_at, finished_at）
- **company_tags**: ユーザータグ（edinet_code, tag）※例: "SBI取扱"
- **demo_trades**: デモトレード（device_id, securities_code, trade_type, price, quantity等）

---

## 竹原式スコアリング（現行ロジック）

`calc_takehara_score(d)` — 100点満点

| 項目 | 配点 | ロジック |
|------|------|---------|
| PER | 25点 | 5以下で満点、40以上で0点（線形補間） |
| PBR | 20点 | 0.3以下で満点、3.0以上で0点 |
| ROE | 20点 | 15%以上で満点 |
| 営業利益率 | 15点 | 15%以上で満点 |
| キャッシュ比率 | 10点 | 30%以上で満点（cash/total_assets） |
| FCF | 10点 | 正ならボーナス10点 |

### CN-PER（キャッシュネットPER）
- CN-PER = PER × (1 - net_cash_ratio)
- net_cash = 現金同等物 - 総負債（yfinanceのバランスシートから取得）
- net_cash_ratioが高い＝実質PERが低い（割安度が高い）
- CN-PERデータがある場合、PERスコアをCN-PERベースに置き換え

### 偽成長検知（4フラグ）
1. 売上+5%だが営業利益or純利益が-5%以下
2. 売上+5%だがFCFがマイナス
3. EPS成長率がNI成長率を10pp以上上回る（自社株買い効果）
4. 直近売上+20%だが3Y CAGRが5%未満（一過性）

---

## APIエンドポイント一覧

### 基本情報
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/status | DB状態、企業数、最終同期 |
| GET | /api/industries | 業種一覧（企業数付き） |
| GET | /api/sync-log | 同期ログ履歴 |
| GET | /api/tags | タグ一覧 |

### 企業データ
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/companies | 企業一覧（検索/業種フィルタ/ソート/ページング） |
| GET | /api/companies/{edinet_code} | 企業詳細（全財務データ+竹原スコア） |
| GET | /api/companies/{edinet_code}/financials | 財務履歴（年度DESC） |
| GET | /api/companies/{edinet_code}/ir | IR情報（EDINET APIプロキシ） |
| GET | /api/company-search | オートコンプリート検索 |

### スクリーニング
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/screener | メインスクリーナー（後述） |
| GET | /api/us-screener | 米国株スクリーナー（75銘柄） |

### スクリーナーパラメータ詳細
```
per_max, pbr_max          — バリュエーション上限
roe_min                   — ROE下限
equity_ratio_min          — 自己資本比率下限
operating_margin_min      — 営業利益率下限
cash_ratio_min            — キャッシュ比率下限
dividend_min              — 配当下限
revenue_growth_min        — 売上成長率下限
ni_growth_min             — 純利益成長率下限
fcf_positive              — FCF正のみ
industry                  — 業種フィルタ
tag                       — タグフィルタ
with_prices               — 株価データ付与（yfinance）
exclude_fake_growth       — 偽成長除外
exclude_pachinko          — パチンコ筐体メーカー除外（8社）
sort_by, sort_dir         — ソート（score:desc,per:asc 等の複合ソート対応）
limit, page               — ページング
```

### 株価
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/price/{code} | 単一銘柄の現在株価 |
| GET | /api/prices | バッチ株価（最大50銘柄） |
| GET | /api/stock-history/{code} | OHLCV履歴（1m/3m/6m/1y/2y/5y） |

### デモトレード
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/demo-trades | トレード履歴（device_id別） |
| POST | /api/demo-trades | トレード作成 |
| DELETE | /api/demo-trades/{id} | トレード削除 |
| GET | /api/demo-portfolio | ポートフォリオ（含み損益付き） |

### アラート
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/alerts | 売り時アラート（EPS×15超えで発火） |

### タグ
| メソッド | パス | 説明 |
|---------|------|------|
| POST | /api/tags/{edinet_code} | タグ追加 |
| DELETE | /api/tags/{edinet_code} | タグ削除 |

### ランキング
| メソッド | パス | 説明 |
|---------|------|------|
| GET | /api/rankings/{metric} | 指標別ランキング（roe/revenue/eps等） |

---

## フロントエンド画面構成

### App.jsx（メインレイアウト）
- 7画面ルーティング: Dashboard / Screener / USScreener / DemoTrade / Companies / Rankings / CompanyDetail
- サイドバー（デスクトップ）/ ハンバーガーメニュー（モバイル）
- 右スライドインのアラートパネル（5分間隔ポーリング）
- ローカル版: theme-localクラス + 地球SVG背景（回転アニメーション120秒）

### Screener.jsx（メイン画面、42.5KB）
- フィルターパネル: PER/PBR/ROE/自己資本比率/営業利益率/キャッシュ比率/配当のスライダー
- FCF正のみ / 偽成長除外 / パチンコ除外のチェックボックス
- 業種・タグフィルタドロップダウン
- Excel風の複合ソート（最大3段階）
- 結果テーブル: 竹原スコアバー、目標株価（PER10/15/20, PBR0.5/1.0）、現在株価、乖離率、CN-PER
- ネットキャッシュ比率バッジ
- 偽成長フラグ展開行

### CompanyDetail.jsx（企業詳細）
- 財務チャート（Recharts）: 売上/利益/ROE/EPSトレンド
- 指標カード6列グリッド
- IR情報: 4セクション展開可能（事業方針・事業内容・リスク・分析）
- 年度別分析履歴
- 竹原スコア内訳

### Dashboard.jsx
- ステータスカード: 企業数、財務レコード数、DB場所、最終同期
- 業種別企業数（上位20）

### Companies.jsx（企業一覧）
- 名前/コード検索、業種フィルタ、ソート（信用スコア/竹原スコア）

### USScreener.jsx（米国株）
- プリセット: ALL / Value / Income / Growth
- 75銘柄固定（メガキャップ中心）

### DemoTrade.jsx（デモトレード）
- 売買入力: オートコンプリート企業検索、売買種別、日付、価格、数量、メモ
- ポートフォリオ: 保有一覧、平均取得単価、含み損益率
- ミニチャート（SVGポリライン）
- device_idで端末分離

### Rankings.jsx（ランキング）
- 指標選択: ROE/自己資本比率/売上/純利益/EPS/BPS/PER/配当/信用スコア
- 上位30/50/100/200

---

## データ取得・キャッシュ

| データ | ソース | キャッシュTTL | 保存先 |
|--------|--------|-------------|--------|
| 企業情報・財務 | EDINET DB API (edinetdb.jp) | 夜間同期で更新 | SQLite |
| 株価（日本株） | yfinance | 5分（市場時間）/ 3日（フォールバック） | price_cache.json |
| バランスシート | yfinance | 30日 | bs_cache.json |
| IR テキスト | EDINET API プロキシ | 1時間 | メモリ |
| 米国株情報 | yfinance .info | 10分 | メモリ |

株価取得は ThreadPoolExecutor で並列化（最大5ワーカー、50銘柄バッチ、バッチ間0.5秒sleep）。

---

## データ収集バッチ（collector.py）

```bash
python backend/collector.py [--limit N] [--no-financials] [--with-analysis] [--concurrency 3]
```

- EDINET DB API（要APIキー）から全上場企業の財務データを取得
- financials: 10年分、ratios: 5年分
- 50社ごとにバッチコミット
- GitHub Actionsで毎日JST 3:00に自動実行 → DBファイルを自動コミット・push

---

## テーマシステム

### オンライン版（Asiimovテーマ）
- アクセント: `#ff6a00`（オレンジ）
- 背景: `#08080c`（ほぼ黒）
- ノード: `#0f0f16`, `#181822`

### ローカル版（サイバーテーマ）
- アクセント: `#00d4ff`（シアン）
- セカンダリ: `#a78bfa`（パープル）
- `html.theme-local` CSSクラスでCSS変数を上書き
- 地球SVG背景（earth-bg.svg）: ワイヤーフレーム、アジア太平洋ビュー、120秒回転

判定: `window.location.hostname === 'localhost'` で自動切替。

---

## パチンコ筐体メーカー除外リスト

| EDINETコード | 企業名 |
|-------------|--------|
| E02419 | 三共 |
| E02403 | 平和 |
| E02488 | 藤商事 |
| E02452 | ユニバーサルエンターテインメント |
| E02475 | セガサミーホールディングス |
| E01718 | オーイズミ |
| E02073 | ダイコク電機 |
| E02424 | マースグループホールディングス |

デフォルトON。チェックボックスで切替可能。

---

## ディレクトリ構造

```
edinetdb-viewer/
├── backend/
│   ├── main.py              # 全APIエンドポイント（1,753行）
│   ├── collector.py          # EDINET データ収集（504行）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── Screener.jsx       # メイン画面（42.5KB）
│   │   │   ├── USScreener.jsx
│   │   │   ├── Companies.jsx
│   │   │   ├── CompanyDetail.jsx   # 企業詳細（20KB）
│   │   │   ├── DemoTrade.jsx       # デモトレード（25KB）
│   │   │   └── Rankings.jsx
│   │   ├── hooks/
│   │   │   ├── useFetch.js
│   │   │   ├── useIsLocal.js       # ローカル判定
│   │   │   └── useIsMobile.js
│   │   ├── App.jsx                 # ルーティング+レイアウト
│   │   ├── api.js                  # APIクライアント
│   │   └── index.css               # グローバルCSS+テーマ
│   ├── public/
│   │   └── earth-bg.svg            # 地球背景
│   ├── package.json
│   └── vite.config.js
├── data/
│   ├── edinet.db                   # SQLite本体
│   ├── price_cache.json
│   └── bs_cache.json
├── .github/workflows/
│   └── nightly-sync.yml            # 毎日3:00 AM JST
├── Dockerfile
├── render.yaml
├── start.bat
└── .env
```

---

## 依存関係

### Backend
- fastapi >= 0.111.0
- uvicorn[standard] >= 0.30.0
- httpx >= 0.27.0
- python-dotenv >= 1.0.0
- yfinance >= 0.2.0

### Frontend
- react 18.3.1
- react-router-dom 6.26.2
- recharts 2.12.7
- lucide-react 0.445.0
- vite 5.4.6

---

## SnowWillow Terminal への拡張時の考慮事項

### 既に実装済み（=そのまま使える層）
- **A層（Value/竹原式）**: スコアリング・スクリーニング完全実装済み
- **B層（Quality）の一部**: ROE, 営業利益率, 自己資本比率, FCFは既にスコアに含まれる

### 追加が必要なデータ
- **粗利率（売上総利益率）**: EDINET XBRL から取得可能だが現在未取得
- **ROIC**: 有利子負債データが必要（現在未取得）
- **日足株価**: yfinanceで取れるが、MAやRSI等のテクニカル指標の計算・保存が未実装
- **イベントデータ**: TDnet/EDINET の自社株買い・業績修正は未パース
- **大量保有報告書**: 未実装

### 現在の株価取得の制約
- yfinanceはリアルタイムだが、レート制限あり（バッチ50、0.5秒sleep）
- 全銘柄の日足蓄積はyfinanceでは現実的でない（J-Quants API推奨）
- J-Quants無料プランは12週遅延 → Momentum/Breakout判定には不十分

### アーキテクチャ上の拡張ポイント
- DB: テーブル追加は容易（SQLite）。ただし大量の日足データはSQLiteの限界に近づく可能性
- バックエンド: main.pyが1,753行で既に大きい。機能追加時はモジュール分割を検討
- フロント: Screener.jsxが42.5KBで巨大。コンポーネント分割推奨
