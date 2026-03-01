# EDINET DB Viewer

全上場企業(3,848社)の財務データをローカル/クラウドで閲覧できるWebアプリ。
竹原式スコアリング・CN-PER算出・粉飾検知・デモトレード対応。

**クラウド版:** https://edinetdb-viewer.onrender.com (Render Free)

---

## クイックスタート

```bash
# 1. リポジトリをクローン
git clone https://github.com/Takeshi-2507/edinetdb-viewer.git
cd edinetdb-viewer

# 2. 環境変数を設定
copy .env.example .env
# .env を開いて EDINET_API_KEY=取得したキー に書き換える
# APIキーは https://edinetdb.jp/developers で無料取得

# 3. 依存関係インストール
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 4. データ収集 (初回のみ)
python backend/collector.py --limit 100   # まず100社でテスト
python backend/collector.py               # 全企業 (数十分〜数時間)

# 5. 起動
start.bat
```

ブラウザで http://localhost:5173 を開く

---

## コマンド一覧

### 起動・停止

| コマンド | 説明 |
|---------|------|
| `start.bat` | バックエンド+フロントエンド同時起動 (ブラウザも自動で開く) |
| `python -m uvicorn backend.main:app --reload --port 8000` | バックエンドのみ起動 |
| `cd frontend && npm run dev` | フロントエンドのみ起動 |

バックエンドとフロントエンドを別々に再起動したい場合:
```bash
# バックエンド再起動 → 起動中のターミナルで Ctrl+C → 再度実行
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# フロントエンド再起動 → 起動中のターミナルで Ctrl+C → 再度実行
cd frontend
npm run dev
```

### データ収集

| コマンド | 説明 |
|---------|------|
| `python backend/collector.py` | 全企業の財務データを同期 |
| `python backend/collector.py --limit 100` | 100社だけテスト同期 |
| `python backend/collector.py --no-financials` | 企業リストのみ (財務データなし、高速) |
| `python backend/collector.py --with-analysis` | AI分析も取得 (API多消費) |
| `python backend/collector.py --concurrency 5` | 同時リクエスト数を指定 (デフォルト3) |

### フロントエンドビルド

| コマンド | 説明 |
|---------|------|
| `cd frontend && npm run build` | 本番用ビルド (`frontend/dist/` に出力) |
| `cd frontend && npm run preview` | ビルド結果をプレビュー |

### Docker (クラウドデプロイ用)

```bash
docker build -t edinetdb-viewer .
docker run -p 8080:8080 -e EDINET_API_KEY=your_key edinetdb-viewer
```

---

## 自動同期 (GitHub Actions)

毎日 JST 3:00 に GitHub Actions が自動で全企業データを同期し、
更新があれば git push → Render に自動デプロイされる。

- ワークフロー: `.github/workflows/nightly-sync.yml`
- 手動実行: GitHub > Actions > 「夜間EDINET同期」 > 「ワークフローを実行する」
- Secret: `EDINET_API_KEY` (リポジトリ Settings > Secrets に設定済み)

---

## 機能一覧

| ページ | 内容 |
|--------|------|
| ダッシュボード | 収録企業数・財務レコード数・業種別企業数 |
| スクリーニング | 竹原式100点スコア・PER/PBR/ROE/配当利回りでフィルタ・ソート |
| 米国株 | S&P500上位75銘柄のリアルタイムスクリーニング |
| デモトレード | 仮想売買・ポートフォリオ管理・損益計算 (端末ごとにデータ分離) |
| 企業一覧 | 全企業の検索・業種フィルタ |
| 企業詳細 | 財務推移グラフ・竹原式分析・IR/CEO情報 |
| ランキング | ROE/EPS成長率/配当利回り等でランキング |
| アラート | 保有銘柄がPER15倍を超えたら通知 |

### 竹原式スコア (100点満点)

| 指標 | 配点 |
|------|------|
| CN-PER (キャッシュニュートラルPER) | 25点 |
| PBR | 20点 |
| ROE | 20点 |
| 営業利益率 | 15点 |
| キャッシュ比率 | 10点 |
| FCF | 10点 |

---

## APIレート制限

- Free: 100回/日
- β版期間中は Pro 相当 (1,000回/日) が無料
- 全企業の財務データ取得は約3,848リクエスト必要

**推奨:** `--no-financials` で企業リストだけ先に取得 (49リクエスト)、財務は毎日少しずつ蓄積

---

## ディレクトリ構成

```
edinetdb-viewer/
├── backend/
│   ├── main.py            # FastAPI バックエンド (全APIエンドポイント)
│   ├── collector.py        # EDINET データ収集スクリプト
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/          # Dashboard, Screener, USScreener, DemoTrade, Companies, Rankings 等
│   │   ├── hooks/          # useFetch, useIsMobile
│   │   ├── App.jsx         # ルーティング・サイドバー・ドロワーメニュー
│   │   ├── api.js          # API クライアント (端末ID管理含む)
│   │   └── index.css       # グローバルCSS (近未来テーマ)
│   ├── package.json
│   └── vite.config.js
├── data/
│   ├── edinet.db           # SQLite DB (collector.py で生成)
│   ├── price_cache.json    # 株価キャッシュ (自動生成)
│   └── bs_cache.json       # BS キャッシュ (自動生成)
├── .github/workflows/
│   └── nightly-sync.yml    # 夜間自動同期
├── Dockerfile              # クラウドデプロイ用
├── render.yaml             # Render 設定
├── start.bat               # ローカル起動スクリプト
└── .env                    # APIキー (gitignore済み)
```

---

## 技術スタック

- **バックエンド:** Python / FastAPI / SQLite / yfinance
- **フロントエンド:** React 18 / Vite / Recharts / Lucide Icons
- **デプロイ:** Docker / Render.com (Free) / GitHub Actions
- **データソース:** EDINET DB API / Yahoo Finance
