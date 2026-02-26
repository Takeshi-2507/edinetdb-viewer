# EDINET DB Viewer

全上場企業の財務データをローカルで閲覧できるWebアプリ。

## セットアップ

### 1. APIキーを取得
https://edinetdb.jp/developers でAPIキーを無料取得

### 2. 環境変数を設定
```
copy .env.example .env
# .env を開いて EDINET_API_KEY=取得したキー に書き換える
```

### 3. Pythonの依存関係をインストール
```
pip install -r backend/requirements.txt
```

### 4. Node.jsの依存関係をインストール
```
cd frontend
npm install
cd ..
```

### 5. データを収集
```
# まず100社でテスト（すぐ終わる）
python backend/collector.py --limit 100

# 全企業 + 財務データ（APIレート次第で数時間かかる場合あり）
python backend/collector.py

# 企業リストのみ（財務データなし、高速）
python backend/collector.py --no-financials
```

### 6. アプリを起動
```
start.bat          # バックエンド + フロントエンドを同時起動
```

または個別に:
```
# バックエンド
uvicorn backend.main:app --reload

# フロントエンド
cd frontend && npm run dev
```

ブラウザで http://localhost:5173 を開く

## APIレート制限について

- Free: 100回/日
- β版期間中はPro相当（1,000回/日）が無料

全企業(3,848社)の財務データを取得すると約3,848リクエスト必要。
β版の1,000回/日制限では**4日程度**かかる計算。

**推奨手順:**
1. まず `--no-financials` で全企業情報だけ取得（49回のリクエスト）
2. 毎日 `collector.py` を実行して財務データを蓄積

## ディレクトリ構成
```
edinetdb-viewer/
├── backend/
│   ├── collector.py   # データ収集スクリプト
│   ├── main.py        # FastAPI バックエンド
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/     # Dashboard, Companies, CompanyDetail, Rankings
│   │   ├── hooks/     # useFetch
│   │   ├── App.jsx
│   │   ├── api.js
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── data/
│   └── edinet.db      # SQLite DB（collector.py実行後に生成）
├── .env               # APIキー設定
└── start.bat          # 起動スクリプト
```
