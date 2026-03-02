// ローカル（localhost / 127.0.0.1）かどうかを判定
// モジュールレベル定数 — useState 初期値などフック外でも使える
export const IS_LOCAL =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')

// フック版（コンポーネント内で使用）
export function useIsLocal() {
  return IS_LOCAL
}
