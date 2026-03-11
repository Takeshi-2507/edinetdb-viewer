---
paths:
  - "backend/**/*.py"
---

# Backend Rules

- FastAPI エンドポイントは `/api/` prefix 必須
- 認証が必要なエンドポイントは `_require_user(request)` を使う
- DB アクセスは `with get_db() as conn:` コンテキストマネージャ経由
- 読み取り専用は `get_db(readonly=True)`
- 新しい依存は `backend/requirements.txt` に追加すること
- yfinance 呼び出しはキャッシュを活用 (`_us_cache`)
- EDINET API は月3000制限、不要な呼び出しを避ける
