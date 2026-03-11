# SnowWillow Terminal (edinetdb-viewer)

EDINET DB + 米国株スクリーナーを備えた日本語金融データビューア。

## Tech Stack
- **Backend**: FastAPI (Python 3.11) / SQLite / uvicorn
- **Frontend**: React 18 + Vite + Recharts + Lucide icons
- **Auth**: JWT (PyJWT) / 固定4ユーザー (env定義, SHA-256ハッシュ)
- **Deploy**: Docker multi-stage → Render.com (free tier)
- **Data**: EDINET API (月3000リクエスト制限) / yfinance (米国株)

## Directory Layout
```
backend/main.py        # FastAPI 全エンドポイント (~2500行)
backend/collector.py   # EDINET データ同期 (GitHub Actions nightly)
frontend/src/pages/    # React ページコンポーネント
frontend/src/api.js    # HTTP クライアント (Bearer token 付き)
data/edinet.db         # SQLite DB (本番もこのファイルを使用)
```

## Dev Commands
```bash
# Backend (port 8001)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001

# Frontend (port 5173, proxy → 8001)
cd frontend && npm run dev

# Build
cd frontend && npm run build
```

## Key Constraints
- Python path (Windows): `/c/Users/tai_p/AppData/Local/Python/pythoncore-3.14-64/python.exe`
- EDINET API 月間上限 3000 (x-ratelimit-monthly-remaining で確認)
- Render free tier: auto-deploy on git push, スリープあり
- `.env` は `.gitignore` 済み → Dockerfile の ENV で本番設定
- 日本語 UI / コメントは日本語で書く

## Code Style
- Backend: snake_case, type hints, docstring は日本語OK
- Frontend: functional components, hooks, inline style (CSS-in-JS)
- Commit message: 英語 (conventional commits)

## Auth
パスワードは SHA-256 ハッシュで保存・比較。`_load_users()` が env から読み込み。
