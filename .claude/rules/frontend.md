---
paths:
  - "frontend/src/**/*.{js,jsx}"
---

# Frontend Rules

- HTTP は `frontend/src/api.js` の `api.*` メソッド経由で呼ぶ
- 401 レスポンスは api.js 内で自動処理 (トークンクリア + /login リダイレクト)
- スタイルは inline style (CSS ファイル追加しない)
- CSS 変数: `--bg`, `--surface`, `--accent`, `--text`, `--text-dim`, `--border`, `--red`, `--green`
- モバイル判定: `window.innerWidth < 768` (isMobile)
- 新ページ追加時は App.jsx の Route と Sidebar に追加
