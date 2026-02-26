"""
FastAPI バックエンド
SQLiteに保存されたEDINETデータをREST APIで提供する
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from time import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# --------------- 株価キャッシュ (ファイル永続化) ---------------
import json

_price_lock = threading.Lock()
PRICE_TTL = 300  # 5分キャッシュ (市場営業時間)
PRICE_TTL_STALE = 86400 * 3  # 非営業時は3日まで古いデータを返す

_CACHE_FILE = Path(__file__).parent.parent / "data" / "price_cache.json"

def _load_price_cache() -> dict[str, tuple[float, dict]]:
    """ファイルから株価キャッシュを読み込み"""
    if _CACHE_FILE.exists():
        try:
            raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            return {k: (v[0], v[1]) for k, v in raw.items()}
        except Exception:
            pass
    return {}

def _save_price_cache(cache: dict):
    """株価キャッシュをファイルに保存"""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

_price_cache: dict[str, tuple[float, dict]] = _load_price_cache()


# --------------- バランスシートキャッシュ (有利子負債・ネットキャッシュ) ---------------
_BS_CACHE_FILE = Path(__file__).parent.parent / "data" / "bs_cache.json"
BS_TTL = 86400 * 30  # 30日（四半期決算ベース）

def _load_bs_cache() -> dict[str, tuple[float, dict]]:
    if _BS_CACHE_FILE.exists():
        try:
            raw = json.loads(_BS_CACHE_FILE.read_text(encoding="utf-8"))
            return {k: (v[0], v[1]) for k, v in raw.items()}
        except Exception:
            pass
    return {}

def _save_bs_cache(cache: dict):
    try:
        _BS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BS_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8",
        )
    except Exception:
        pass

_bs_cache: dict[str, tuple[float, dict]] = _load_bs_cache()
_bs_lock = threading.Lock()


def fetch_balance_sheet(ticker: str) -> dict | None:
    """yfinance でバランスシート情報 (Total Debt, Net Debt) を取得 (長期キャッシュ)"""
    now = time()
    with _bs_lock:
        if ticker in _bs_cache:
            ts, data = _bs_cache[ticker]
            if now - ts < BS_TTL:
                return data
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        bs = t.balance_sheet
        if bs is None or bs.empty:
            return None
        import math
        latest = bs.iloc[:, 0]

        def _safe_float(val):
            if val is None:
                return None
            v = float(val)
            return None if math.isnan(v) or math.isinf(v) else v

        total_debt = _safe_float(latest.get("Total Debt"))
        net_debt = _safe_float(latest.get("Net Debt"))
        cash_equiv = _safe_float(latest.get("Cash And Cash Equivalents"))
        total_assets = _safe_float(latest.get("Total Assets"))
        data = {
            "ticker": ticker,
            "total_debt": total_debt,
            "net_debt": net_debt,
            "cash_equiv": cash_equiv,
            "total_assets": total_assets,
        }
        with _bs_lock:
            _bs_cache[ticker] = (now, data)
            _save_bs_cache(_bs_cache)
        return data
    except Exception:
        # キャッシュにstaleデータがあれば返す
        with _bs_lock:
            if ticker in _bs_cache:
                return _bs_cache[ticker][1]
        return None


def _sec_code_to_ticker(securities_code: str | int | None) -> str | None:
    """証券コード(5桁) → Yahoo Finance ticker (4桁.T)"""
    if not securities_code:
        return None
    code = str(securities_code).strip()
    if len(code) == 5:
        return code[:4] + ".T"
    if len(code) == 4:
        return code + ".T"
    return None


def fetch_stock_price(ticker: str) -> dict | None:
    """yfinance で現在株価を取得 (ファイル永続キャッシュ付き)"""
    now = time()
    with _price_lock:
        if ticker in _price_cache:
            ts, data = _price_cache[ticker]
            if now - ts < PRICE_TTL:
                return data
            # TTL超過でも、stale期間内なら古いデータを保持（取得失敗時に使う）
            stale_data = data if now - ts < PRICE_TTL_STALE else None
        else:
            stale_data = None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        if price is None:
            return stale_data  # 取得失敗→古いデータを返す
        data = {
            "ticker": ticker,
            "price": round(float(price), 1),
            "market_cap": fi.get("marketCap"),
        }
        with _price_lock:
            _price_cache[ticker] = (now, data)
            _save_price_cache(_price_cache)
        return data
    except Exception:
        return stale_data  # レートリミット等→古いデータを返す


def calc_takehara_score(d: dict) -> tuple[float, dict]:
    """竹原式スコアを計算 (0-100点)。DBの財務データだけで算出可能。
    d には per, roe, operating_income, revenue, cash, total_assets, fcf 等を含む dict を渡す。
    Returns: (score, parts_dict)
    """
    score = 0.0
    parts: dict[str, float] = {}

    # PER (25点): 5以下で満点, 40以上で0点
    per = d.get("per")
    if per and per > 0:
        s = max(0, min(25, 25 * (1 - (per - 5) / 35)))
        score += s
        parts["per"] = round(s, 1)

    # PBR (20点): 0.3以下で満点, 3.0以上で0点
    pbr = d.get("pbr")
    if pbr is None and d.get("per") and d.get("roe") and d["roe"] > 0:
        pbr = d["per"] * d["roe"]
    if pbr is not None and pbr > 0:
        s = max(0, min(20, 20 * (1 - (pbr - 0.3) / 2.7)))
        score += s
        parts["pbr"] = round(s, 1)

    # ROE (20点): 15%以上で満点
    roe = d.get("roe")
    if roe and roe > 0:
        s = max(0, min(20, 20 * min(1, roe / 0.15)))
        score += s
        parts["roe"] = round(s, 1)

    # 営業利益率 (15点): 15%以上で満点
    om = d.get("operating_margin")
    if om is None:
        rev = d.get("revenue")
        oi = d.get("operating_income")
        if rev and rev > 0 and oi is not None:
            om = oi / rev
    if om and om > 0:
        s = max(0, min(15, 15 * min(1, om / 0.15)))
        score += s
        parts["operating_margin"] = round(s, 1)

    # 現金比率 (10点): 30%以上で満点
    cr = d.get("cash_ratio")
    if cr is None:
        cash = d.get("cash")
        ta = d.get("total_assets")
        if ta and ta > 0 and cash is not None:
            cr = cash / ta
    if cr and cr > 0:
        s = max(0, min(10, 10 * min(1, cr / 0.3)))
        score += s
        parts["cash_ratio"] = round(s, 1)

    # FCF正 (10点)
    fcf = d.get("fcf")
    if fcf and fcf > 0:
        score += 10
        parts["fcf"] = 10.0

    return round(score, 1), parts


def calc_target_prices(eps: float | None, bps: float | None) -> dict:
    """竹原式の割安基準から目安株価を算出"""
    targets = {}
    # PER 15 が竹原式の割安上限 → EPS × 15 = 割安感がなくなる株価
    if eps and eps > 0:
        targets["target_per15"] = round(eps * 15, 1)
        targets["target_per20"] = round(eps * 20, 1)  # やや割高ライン
        targets["target_per10"] = round(eps * 10, 1)  # 買い増しライン
    # BPS × 1.0 が資産面の割安上限
    if bps and bps > 0:
        targets["target_pbr1"] = round(bps * 1.0, 1)
        targets["target_pbr05"] = round(bps * 0.5, 1)  # かなり割安ライン
    return targets

DB_PATH = Path(__file__).parent.parent / "data" / "edinet.db"

app = FastAPI(title="EDINET DB Viewer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8001"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@contextmanager
def get_db(readonly: bool = True):
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="データベースが未作成です。先に collector.py を実行してください。",
        )
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if readonly:
        conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


@app.get("/api/status")
def status() -> dict:
    if not DB_PATH.exists():
        return {"status": "no_db", "message": "collector.py を先に実行してください"}

    with get_db() as conn:
        companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        financials = conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0]
        last_sync = conn.execute(
            "SELECT finished_at, companies_synced FROM sync_log WHERE status='done' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "status": "ok",
        "db_path": str(DB_PATH),
        "companies": companies,
        "financials": financials,
        "last_sync": dict(last_sync) if last_sync else None,
    }


@app.get("/api/companies")
def list_companies(
    q: str | None = Query(None, description="企業名・証券コード・EDINETコードで検索"),
    industry: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    sort_by: str = Query("credit_score", description="ソート: credit_score, takehara, company_name"),
) -> dict:
    with get_db() as conn:
        conditions = []
        params: list[Any] = []

        if q:
            conditions.append(
                "(c.company_name LIKE ? OR c.securities_code LIKE ? OR c.edinet_code LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like])
        if industry:
            conditions.append("c.industry = ?")
            params.append(industry)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 最新年度を特定
        year_row = conn.execute("SELECT MAX(fiscal_year) FROM financials").fetchone()
        fiscal_year = year_row[0] if year_row else None

        total = conn.execute(
            f"SELECT COUNT(*) FROM companies c {where}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""
            SELECT c.*,
                   (SELECT COUNT(*) FROM financials f2 WHERE f2.edinet_code = c.edinet_code) AS fiscal_years,
                   f.per, f.roe, f.eps, f.bps, f.revenue, f.operating_income,
                   f.net_income, f.total_assets, f.cash, f.equity_ratio, f.dividend,
                   f.cf_operating, f.cf_investing,
                   r.fcf
            FROM companies c
            LEFT JOIN financials f ON f.edinet_code = c.edinet_code AND f.fiscal_year = ?
            LEFT JOIN ratios r ON r.edinet_code = c.edinet_code AND r.fiscal_year = ?
            {where}
            ORDER BY c.credit_score DESC, c.company_name
            LIMIT ? OFFSET ?
            """,
            [fiscal_year, fiscal_year] + params + [per_page, offset],
        ).fetchall()

    companies = []
    for row in rows:
        d = row_to_dict(row)
        # 竹原式スコアを計算（最新年度の財務データから）
        if d.get("per") and d.get("net_income") and d["net_income"] > 0:
            score, parts = calc_takehara_score(d)
            d["takehara_score"] = score
            d["score_parts"] = parts
        else:
            d["takehara_score"] = None
            d["score_parts"] = None
        companies.append(d)

    # 竹原スコアでソートが指定された場合
    if sort_by == "takehara":
        has_score = [c for c in companies if c.get("takehara_score") is not None]
        no_score = [c for c in companies if c.get("takehara_score") is None]
        has_score.sort(key=lambda x: x["takehara_score"], reverse=True)
        companies = has_score + no_score

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "fiscal_year": fiscal_year,
        "companies": companies,
    }


@app.get("/api/companies/{edinet_code}")
def get_company(edinet_code: str) -> dict:
    with get_db() as conn:
        company = conn.execute(
            "SELECT * FROM companies WHERE edinet_code = ?", (edinet_code,)
        ).fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="企業が見つかりません")

        financials = conn.execute(
            "SELECT * FROM financials WHERE edinet_code = ? ORDER BY fiscal_year DESC",
            (edinet_code,),
        ).fetchall()

        analysis = conn.execute(
            "SELECT * FROM analysis WHERE edinet_code = ?", (edinet_code,)
        ).fetchone()

        # 最新年度のratiosからFCFを取得
        latest_fcf = None
        if financials:
            latest_fy = financials[0]["fiscal_year"]
            ratio_row = conn.execute(
                "SELECT fcf FROM ratios WHERE edinet_code = ? AND fiscal_year = ?",
                (edinet_code, latest_fy),
            ).fetchone()
            if ratio_row:
                latest_fcf = ratio_row[0]

    fins_list = [row_to_dict(r) for r in financials]
    company_dict = row_to_dict(company)

    # 竹原式スコアを最新年度データから計算
    takehara = None
    if fins_list:
        latest = fins_list[0]
        score_input = {**latest, "fcf": latest_fcf}
        if latest.get("per") and latest.get("net_income") and latest["net_income"] > 0:
            score, parts = calc_takehara_score(score_input)
            takehara = {"score": score, "parts": parts}

    return {
        "company": company_dict,
        "financials": fins_list,
        "analysis": row_to_dict(analysis) if analysis else None,
        "takehara": takehara,
    }


# --------------- IR / テキストブロック API (EDINET DB API プロキシ + キャッシュ) ---------------

_EDINET_API_BASE = "https://edinetdb.jp/v1"
_ir_cache: dict[str, tuple[float, dict]] = {}
_ir_cache_lock = threading.Lock()
IR_CACHE_TTL = 3600  # 1時間キャッシュ


def _edinet_api_key() -> str | None:
    return os.environ.get("EDINET_API_KEY")


def _fetch_edinet_api(path: str) -> dict | None:
    """EDINET DB API にリクエスト (キャッシュ付き)"""
    now = time()
    with _ir_cache_lock:
        if path in _ir_cache:
            ts, data = _ir_cache[path]
            if now - ts < IR_CACHE_TTL:
                return data
    api_key = _edinet_api_key()
    if not api_key:
        return None
    try:
        import httpx
        r = httpx.get(
            f"{_EDINET_API_BASE}{path}",
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )
        if r.status_code in (404, 204):
            # 404もキャッシュ（不要なリトライ防止）
            with _ir_cache_lock:
                _ir_cache[path] = (now, None)
            return None
        r.raise_for_status()
        data = r.json()
        with _ir_cache_lock:
            _ir_cache[path] = (now, data)
        return data
    except Exception:
        return None


@app.get("/api/companies/{edinet_code}/ir")
def get_company_ir(edinet_code: str) -> dict:
    """企業のIR情報を取得: テキストブロック（経営方針・リスク等）+ AI分析"""
    # テキストブロックと分析を並列取得
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as executor:
        tb_future = executor.submit(
            _fetch_edinet_api, f"/companies/{edinet_code}/text-blocks"
        )
        an_future = executor.submit(
            _fetch_edinet_api, f"/companies/{edinet_code}/analysis"
        )
        tb_result = tb_future.result()
        an_result = an_future.result()

    # テキストブロック整形
    text_blocks = []
    if tb_result and "data" in tb_result:
        for item in tb_result["data"]:
            text_blocks.append({
                "section": item.get("section", ""),
                "text": item.get("text", ""),
            })

    # AI分析整形
    analysis = None
    if an_result:
        an_data = an_result.get("data", an_result)
        ai_summary = an_data.get("ai_summary")
        if isinstance(ai_summary, dict):
            summary_text = ai_summary.get("text", "")
        else:
            summary_text = ai_summary or ""

        history = an_data.get("history", [])
        analysis = {
            "summary": summary_text,
            "history": history,
        }

    return {
        "edinet_code": edinet_code,
        "text_blocks": text_blocks,
        "analysis": analysis,
    }


@app.get("/api/companies/{edinet_code}/financials")
def get_financials(edinet_code: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM financials WHERE edinet_code = ? ORDER BY fiscal_year DESC",
            (edinet_code,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


VALID_METRICS = {
    "roe": "roe",
    "equity_ratio": "equity_ratio",
    "revenue": "revenue",
    "net_income": "net_income",
    "operating_income": "operating_income",
    "eps": "eps",
    "bps": "bps",
    "per": "per",
    "dividend": "dividend",
    "credit_score": "credit_score",
}


@app.get("/api/rankings/{metric}")
def get_ranking(
    metric: str,
    limit: int = Query(30, ge=1, le=200),
    fiscal_year: int | None = Query(None),
) -> dict:
    if metric == "credit_score":
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT edinet_code, securities_code, company_name, industry,
                       credit_score AS value, credit_rating
                FROM companies
                WHERE credit_score IS NOT NULL
                ORDER BY credit_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {"metric": metric, "fiscal_year": None, "ranking": [row_to_dict(r) for r in rows]}

    col = VALID_METRICS.get(metric)
    if not col:
        raise HTTPException(
            status_code=400,
            detail=f"有効なmetric: {', '.join(VALID_METRICS.keys())}",
        )

    with get_db() as conn:
        if fiscal_year is None:
            year_row = conn.execute("SELECT MAX(fiscal_year) FROM financials").fetchone()
            fiscal_year = year_row[0] if year_row else None

        if fiscal_year is None:
            return {"metric": metric, "fiscal_year": None, "ranking": []}

        rows = conn.execute(
            f"""
            SELECT c.edinet_code, c.securities_code, c.company_name, c.industry,
                   f.fiscal_year, f.{col} AS value
            FROM financials f
            JOIN companies c ON c.edinet_code = f.edinet_code
            WHERE f.fiscal_year = ? AND f.{col} IS NOT NULL
            ORDER BY f.{col} DESC
            LIMIT ?
            """,
            (fiscal_year, limit),
        ).fetchall()

    return {
        "metric": metric,
        "fiscal_year": fiscal_year,
        "ranking": [row_to_dict(r) for r in rows],
    }


@app.get("/api/industries")
def list_industries() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT industry,
                   COUNT(*) AS company_count
            FROM companies
            WHERE industry IS NOT NULL AND industry != ''
            GROUP BY industry
            ORDER BY company_count DESC
            """
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@app.get("/api/screener")
def screener(
    per_max: float | None = Query(None, description="PER上限"),
    pbr_max: float | None = Query(None, description="PBR上限"),
    roe_min: float | None = Query(None, description="ROE下限 (例: 0.08 = 8%)"),
    equity_ratio_min: float | None = Query(None, description="自己資本比率下限"),
    operating_margin_min: float | None = Query(None, description="営業利益率下限"),
    cash_ratio_min: float | None = Query(None, description="現金/総資産 下限"),
    fcf_positive: bool = Query(False, description="FCF正のみ"),
    revenue_growth_min: float | None = Query(None, description="売上成長率下限"),
    ni_growth_min: float | None = Query(None, description="純利益成長率下限"),
    dividend_min: float | None = Query(None, description="配当下限"),
    sort_by: str = Query("score", description="ソート: カンマ区切りで複数指定可 (例: score:desc,per:asc)"),
    sort_dir: str = Query("", description="ソート方向: asc or desc (単一ソート時のみ。複数ソートはsort_by内で指定)"),
    limit: int = Query(100, ge=1, le=500),
    page: int = Query(1, ge=1),
    industry: str | None = Query(None),
    tag: str | None = Query(None, description="タグでフィルタ (例: SBI取扱)"),
    with_prices: bool = Query(False, description="株価・売り時目安を結果に含める"),
    exclude_fake_growth: bool = Query(False, description="見せかけ成長株を除外"),
) -> dict:
    """竹原式スクリーニング: 複数の財務指標で銘柄をフィルタリング・スコアリング"""
    with get_db() as conn:
        # 最新年度を取得
        year_row = conn.execute("SELECT MAX(fiscal_year) FROM financials").fetchone()
        fiscal_year = year_row[0] if year_row else None
        if fiscal_year is None:
            return {"fiscal_year": None, "total": 0, "results": []}

        # メインクエリ: financials + ratios + companies をJOIN
        base_query = """
            SELECT
                c.edinet_code,
                c.securities_code,
                c.company_name,
                c.industry,
                c.credit_score,
                f.fiscal_year,
                f.per,
                f.roe,
                f.eps,
                f.bps,
                f.net_income,
                f.net_assets,
                f.total_assets,
                f.cash,
                f.equity_ratio,
                f.revenue,
                f.operating_income,
                f.dividend,
                f.cf_operating,
                f.cf_investing,
                f.payout_ratio,
                -- 計算カラム
                CASE WHEN f.per IS NOT NULL AND f.roe IS NOT NULL AND f.roe > 0
                     THEN f.per * f.roe
                     ELSE NULL END AS pbr,
                CASE WHEN f.revenue IS NOT NULL AND f.revenue > 0 AND f.operating_income IS NOT NULL
                     THEN CAST(f.operating_income AS REAL) / f.revenue
                     ELSE NULL END AS operating_margin,
                CASE WHEN f.total_assets IS NOT NULL AND f.total_assets > 0 AND f.cash IS NOT NULL
                     THEN CAST(f.cash AS REAL) / f.total_assets
                     ELSE NULL END AS cash_ratio,
                r.fcf,
                r.revenue_growth,
                r.ni_growth,
                r.oi_growth,
                r.eps_growth,
                r.ni_cagr_3y,
                r.revenue_cagr_3y
            FROM financials f
            JOIN companies c ON c.edinet_code = f.edinet_code
            LEFT JOIN ratios r ON r.edinet_code = f.edinet_code AND r.fiscal_year = f.fiscal_year
            WHERE f.fiscal_year = ?
              AND f.per IS NOT NULL
              AND f.net_income IS NOT NULL
              AND f.net_income > 0
        """
        params: list[Any] = [fiscal_year]

        # フィルタ条件
        if per_max is not None:
            base_query += " AND f.per <= ?"
            params.append(per_max)
        if roe_min is not None:
            base_query += " AND f.roe >= ?"
            params.append(roe_min)
        if equity_ratio_min is not None:
            base_query += " AND f.equity_ratio >= ?"
            params.append(equity_ratio_min)
        if pbr_max is not None:
            base_query += " AND (f.per * f.roe) <= ?"
            params.append(pbr_max)
        if operating_margin_min is not None:
            base_query += " AND f.revenue > 0 AND (CAST(f.operating_income AS REAL) / f.revenue) >= ?"
            params.append(operating_margin_min)
        if cash_ratio_min is not None:
            base_query += " AND f.total_assets > 0 AND (CAST(f.cash AS REAL) / f.total_assets) >= ?"
            params.append(cash_ratio_min)
        if fcf_positive:
            base_query += " AND r.fcf IS NOT NULL AND r.fcf > 0"
        if revenue_growth_min is not None:
            base_query += " AND r.revenue_growth IS NOT NULL AND r.revenue_growth >= ?"
            params.append(revenue_growth_min)
        if ni_growth_min is not None:
            base_query += " AND r.ni_growth IS NOT NULL AND r.ni_growth >= ?"
            params.append(ni_growth_min)
        if dividend_min is not None:
            base_query += " AND f.dividend IS NOT NULL AND f.dividend >= ?"
            params.append(dividend_min)
        if industry:
            base_query += " AND c.industry = ?"
            params.append(industry)
        if tag:
            base_query += " AND EXISTS (SELECT 1 FROM company_tags ct WHERE ct.edinet_code = f.edinet_code AND ct.tag = ?)"
            params.append(tag)

        # 全件カウント
        count_q = f"SELECT COUNT(*) FROM ({base_query})"
        total = conn.execute(count_q, params).fetchone()[0]

        # ソート（複数カラム対応: sort_by=score:desc,per:asc 形式）
        sort_col_map = {
            "per": ("f.per", "ASC"),
            "pbr": ("pbr", "ASC"),
            "roe": ("f.roe", "DESC"),
            "operating_margin": ("operating_margin", "DESC"),
            "cash_ratio": ("cash_ratio", "DESC"),
            "credit_score": ("c.credit_score", "DESC"),
            "company_name": ("c.company_name", "ASC"),
            "industry": ("c.industry", "ASC"),
            "dividend": ("f.dividend", "DESC"),
            "fcf": ("r.fcf", "DESC"),
            "score": ("f.per", "ASC"),  # スコアはPython側で再ソート
        }
        # 株価系ソートキー（Python側でのみ処理可能）
        PRICE_SORT_KEYS = {"price": "DESC", "target": "DESC", "gap": "ASC", "cn_per": "ASC", "net_cash": "DESC"}

        # 複数ソートキーのパース
        has_score_sort = False
        has_price_sort = False
        sort_keys = []  # [(key, col_sql_or_None, direction), ...]
        for part in sort_by.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                key, d = part.split(":", 1)
                d = d.strip().upper()
                if d not in ("ASC", "DESC"):
                    d = ""
            else:
                key = part
                d = ""
            key = key.strip()
            if key == "score":
                has_score_sort = True
            if key in PRICE_SORT_KEYS:
                has_price_sort = True
                direction = d if d else PRICE_SORT_KEYS[key]
                sort_keys.append((key, None, direction))
            elif key in sort_col_map:
                col_sql, default_d = sort_col_map[key]
                direction = d if d else (sort_dir.upper() if sort_dir.upper() in ("ASC", "DESC") else default_d)
                sort_keys.append((key, col_sql, direction))

        # 株価系ソートやscoreソートがある場合は全件Python側で処理
        need_python_sort = has_score_sort or has_price_sort

        if not need_python_sort and sort_keys:
            sql_sorts = [f"{col_sql} {direction} NULLS LAST"
                         for key, col_sql, direction in sort_keys if col_sql]
            if sql_sorts:
                base_query += " ORDER BY " + ", ".join(sql_sorts)
            else:
                base_query += " ORDER BY f.per ASC NULLS LAST"
        else:
            base_query += " ORDER BY f.per ASC NULLS LAST"

        # Python側ソートが必要な場合は全件取得、それ以外はページネーション
        if need_python_sort:
            rows = conn.execute(base_query, params).fetchall()
        else:
            offset = (page - 1) * limit
            base_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(base_query, params).fetchall()

    results = []
    for row in rows:
        d = row_to_dict(row)
        # 竹原式スコア計算 (共通関数)
        score, parts = calc_takehara_score(d)
        d["takehara_score"] = score
        d["score_parts"] = parts
        d.update(calc_target_prices(d.get("eps"), d.get("bps")))

        results.append(d)

    # with_prices=true または株価系ソート時は株価を一括取得
    if with_prices or has_price_sort:
        from concurrent.futures import ThreadPoolExecutor
        codes = list({d["securities_code"] for d in results if d.get("securities_code")})
        tickers = {}
        for code in codes:
            t = _sec_code_to_ticker(code)
            if t:
                tickers[code] = t

        # 並列で株価取得 (max 20 workers)
        import time as _time

        def _fetch(code_ticker):
            code, ticker = code_ticker
            try:
                data = fetch_stock_price(ticker)
                return code, data
            except Exception:
                return code, None

        price_map = {}   # securities_code -> price
        mcap_map = {}    # securities_code -> market_cap
        # yfinanceのレートリミット回避のためバッチ処理
        items = list(tickers.items())
        batch_size = 50
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            with ThreadPoolExecutor(max_workers=10) as executor:
                for code, data in executor.map(_fetch, batch):
                    if data and data.get("price"):
                        price_map[code] = data["price"]
                    if data and data.get("market_cap"):
                        mcap_map[code] = data["market_cap"]
            if i + batch_size < len(items):
                _time.sleep(0.5)  # バッチ間スリープ

        # バランスシート情報も並列取得 (有利子負債→ネットキャッシュ)
        def _fetch_bs(code_ticker):
            code, ticker = code_ticker
            try:
                data = fetch_balance_sheet(ticker)
                return code, data
            except Exception:
                return code, None

        bs_map = {}  # securities_code -> {total_debt, net_debt, ...}
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            with ThreadPoolExecutor(max_workers=10) as executor:
                for code, data in executor.map(_fetch_bs, batch):
                    if data:
                        bs_map[code] = data
            if i + batch_size < len(items):
                _time.sleep(0.3)

        # 結果に株価・乖離率・ネットキャッシュを付与
        for d in results:
            code = d.get("securities_code")
            cp = price_map.get(code)
            d["current_price"] = cp
            target = d.get("target_per15")
            if cp is not None and target:
                d["gap_pct"] = round(((cp - target) / target) * 100, 1)
            else:
                d["gap_pct"] = None

            # ネットキャッシュ計算 (= 現金 - 有利子負債)
            import math
            bs = bs_map.get(code)
            td = bs.get("total_debt") if bs else None
            ce = bs.get("cash_equiv") if bs else None
            # NaN/Infチェック
            if td is not None and (math.isnan(td) or math.isinf(td)):
                td = None
            if ce is not None and (math.isnan(ce) or math.isinf(ce)):
                ce = None

            if td is not None and ce is not None:
                net_cash = ce - td
                d["net_cash"] = round(net_cash)
                d["total_debt_yf"] = round(td)
                mcap = mcap_map.get(code)
                if mcap and mcap > 0:
                    ncr = net_cash / mcap
                    if not math.isnan(ncr) and not math.isinf(ncr):
                        d["net_cash_ratio"] = round(ncr, 4)
                        per_val = d.get("per")
                        if per_val and per_val > 0:
                            cn_per = per_val * (1 - ncr)
                            d["cn_per"] = round(cn_per, 2)
                        else:
                            d["cn_per"] = None
                    else:
                        d["net_cash_ratio"] = None
                        d["cn_per"] = None
                else:
                    d["net_cash_ratio"] = None
                    d["cn_per"] = None
            else:
                d["net_cash"] = None
                d["total_debt_yf"] = None
                d["net_cash_ratio"] = None
                d["cn_per"] = None

        # CN-PERが取得できた銘柄はスコアのPER部分をCN-PERベースで再計算
        for d in results:
            cn = d.get("cn_per")
            if cn is not None:
                # 旧PERスコアを差し引いて、CN-PERスコアに置換
                old_per_score = d.get("score_parts", {}).get("per", 0)
                # CN-PER: 8以下で満点(25), 20以上で0点
                cn_per_score = max(0, min(25, 25 * (1 - (cn - 3) / 17)))
                d["score_parts"]["cn_per"] = round(cn_per_score, 1)
                d["score_parts"]["per"] = round(cn_per_score, 1)  # 表示上もCN-PERベースに
                d["takehara_score"] = round(
                    d["takehara_score"] - old_per_score + cn_per_score, 1
                )

    # ── 見せかけ成長株検出 ──
    for d in results:
        flags = []
        rg = d.get("revenue_growth")
        ng = d.get("ni_growth")
        og = d.get("oi_growth")
        eg = d.get("eps_growth")
        fcf_val = d.get("fcf")
        rcagr = d.get("revenue_cagr_3y")

        # 1) 売上増・利益減: 売上+5%以上なのに営業利益or純利益が-5%以下
        if rg is not None and rg > 0.05:
            if og is not None and og < -0.05:
                flags.append("売上増・営業利益減")
            elif ng is not None and ng < -0.05:
                flags.append("売上増・純利益減")

        # 2) 売上増・FCFマイナス: 売上+5%以上なのにFCF赤字
        if rg is not None and rg > 0.05 and fcf_val is not None and fcf_val < 0:
            flags.append("売上増・FCFマイナス")

        # 3) EPS水増し: EPS成長率が純利益成長率を10pp以上上回る（自社株買い効果）
        if eg is not None and ng is not None and eg - ng > 0.10 and eg > 0.05:
            flags.append("EPS水増し疑い")

        # 4) 一発成長: 直近売上+20%以上なのに3年CAGRが5%未満（一過性）
        if rg is not None and rg > 0.20 and rcagr is not None and rcagr < 0.05:
            flags.append("一過性成長")

        d["fake_growth_flags"] = flags
        d["is_fake_growth"] = len(flags) > 0

    # 見せかけ成長株除外フィルタ
    if exclude_fake_growth:
        results = [d for d in results if not d["is_fake_growth"]]

    # Python側ソート (Noneは常に末尾)
    if need_python_sort:
        SORT_FIELD_MAP = {
            "score": "takehara_score",
            "price": "current_price",
            "target": "target_per15",
            "gap": "gap_pct",
            "cn_per": "cn_per",
            "net_cash": "net_cash",
        }
        for key, col_sql, direction in reversed(sort_keys):
            desc = direction == "DESC"
            field = SORT_FIELD_MAP.get(key, key)
            # None有無で分離してからソート→結合（Noneは常に末尾）
            has_val = [r for r in results if r.get(field) is not None]
            no_val = [r for r in results if r.get(field) is None]
            has_val.sort(key=lambda x: x[field], reverse=desc)
            results = has_val + no_val

        # Python側ページネーション
        total_after_sort = len(results)
        offset = (page - 1) * limit
        results = results[offset:offset + limit]

    return {
        "fiscal_year": fiscal_year,
        "total": total if not need_python_sort else total_after_sort,
        "page": page,
        "per_page": limit,
        "results": results,
    }


@app.get("/api/tags")
def list_tags() -> list[dict]:
    """利用可能なタグ一覧と件数を取得"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT tag, COUNT(*) AS count FROM company_tags GROUP BY tag ORDER BY count DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/api/tags/{edinet_code}")
def add_tag(edinet_code: str, tag: str = Query(...)) -> dict:
    """銘柄にタグを追加"""
    from datetime import datetime, timezone
    with get_db(readonly=False) as conn:
        try:
            conn.execute(
                "INSERT INTO company_tags (edinet_code, tag, created_at) VALUES (?, ?, ?)",
                (edinet_code, tag, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception:
            pass  # 既にあればスキップ
    return {"status": "ok", "edinet_code": edinet_code, "tag": tag}


@app.delete("/api/tags/{edinet_code}")
def remove_tag(edinet_code: str, tag: str = Query(...)) -> dict:
    """銘柄からタグを削除"""
    with get_db(readonly=False) as conn:
        conn.execute(
            "DELETE FROM company_tags WHERE edinet_code = ? AND tag = ?",
            (edinet_code, tag),
        )
        conn.commit()
    return {"status": "ok", "edinet_code": edinet_code, "tag": tag}


@app.get("/api/price/{securities_code}")
def get_price(securities_code: str) -> dict:
    """証券コードから現在株価を取得 (Yahoo Finance)"""
    ticker = _sec_code_to_ticker(securities_code)
    if not ticker:
        raise HTTPException(404, "Invalid securities code")
    data = fetch_stock_price(ticker)
    if not data:
        raise HTTPException(404, f"Price not found for {ticker}")
    return data


@app.get("/api/prices")
def get_prices(codes: str = Query(..., description="カンマ区切り証券コード (例: 7203,9984,6758)")) -> dict:
    """複数銘柄の株価を一括取得"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if len(code_list) > 50:
        raise HTTPException(400, "最大50銘柄まで")
    results = {}
    for code in code_list:
        ticker = _sec_code_to_ticker(code)
        if ticker:
            data = fetch_stock_price(ticker)
            if data:
                results[code] = data
    return {"prices": results}


@app.get("/api/sync-log")
def sync_log(limit: int = Query(10, ge=1, le=50)) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# --------------- デモトレード API ---------------

from pydantic import BaseModel


class TradeRequest(BaseModel):
    securities_code: str
    company_name: str | None = None
    trade_type: str  # "buy" or "sell"
    trade_date: str  # "YYYY-MM-DD"
    price: float
    quantity: int
    memo: str | None = None


@app.get("/api/demo-trades")
def list_trades() -> list[dict]:
    """デモトレード一覧"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM demo_trades ORDER BY trade_date DESC, id DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/api/demo-trades")
def create_trade(req: TradeRequest) -> dict:
    """デモトレード登録"""
    from datetime import datetime, timezone
    with get_db(readonly=False) as conn:
        conn.execute(
            """INSERT INTO demo_trades
               (securities_code, company_name, trade_type, trade_date, price, quantity, memo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (req.securities_code, req.company_name, req.trade_type,
             req.trade_date, req.price, req.quantity, req.memo,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return {"status": "ok"}


@app.delete("/api/demo-trades/{trade_id}")
def delete_trade(trade_id: int) -> dict:
    """デモトレード削除"""
    with get_db(readonly=False) as conn:
        conn.execute("DELETE FROM demo_trades WHERE id = ?", (trade_id,))
        conn.commit()
    return {"status": "ok"}


@app.get("/api/demo-portfolio")
def demo_portfolio() -> dict:
    """デモポートフォリオ（現在の保有状況と損益）"""
    with get_db() as conn:
        trades = conn.execute(
            "SELECT * FROM demo_trades ORDER BY trade_date ASC, id ASC"
        ).fetchall()

    # 銘柄ごとに集計
    holdings: dict[str, dict] = {}
    for t in trades:
        t = row_to_dict(t)
        code = t["securities_code"]
        if code not in holdings:
            holdings[code] = {
                "securities_code": code,
                "company_name": t.get("company_name") or code,
                "total_qty": 0,
                "total_cost": 0.0,
                "trades": [],
            }
        h = holdings[code]
        h["trades"].append(t)
        if t["trade_type"] == "buy":
            h["total_qty"] += t["quantity"]
            h["total_cost"] += t["price"] * t["quantity"]
        elif t["trade_type"] == "sell":
            # 平均取得単価ベースでコスト減算
            if h["total_qty"] > 0:
                avg_cost = h["total_cost"] / h["total_qty"]
                sell_qty = min(t["quantity"], h["total_qty"])
                h["total_qty"] -= sell_qty
                h["total_cost"] -= avg_cost * sell_qty

    # 現在株価を取得して損益計算
    result = []
    for code, h in holdings.items():
        if h["total_qty"] <= 0:
            h["avg_cost"] = 0
            h["current_price"] = None
            h["unrealized_pnl"] = 0
            h["pnl_pct"] = 0
        else:
            h["avg_cost"] = round(h["total_cost"] / h["total_qty"], 1)
            ticker = _sec_code_to_ticker(code)
            price_data = fetch_stock_price(ticker) if ticker else None
            h["current_price"] = price_data["price"] if price_data else None
            if h["current_price"]:
                h["unrealized_pnl"] = round(
                    (h["current_price"] - h["avg_cost"]) * h["total_qty"], 0
                )
                h["pnl_pct"] = round(
                    (h["current_price"] - h["avg_cost"]) / h["avg_cost"] * 100, 1
                ) if h["avg_cost"] > 0 else 0
            else:
                h["unrealized_pnl"] = None
                h["pnl_pct"] = None
        result.append(h)

    # 合計
    total_cost = sum(h["total_cost"] for h in result)
    total_value = sum(
        h["current_price"] * h["total_qty"]
        for h in result
        if h["current_price"] and h["total_qty"] > 0
    )
    total_pnl = total_value - total_cost if total_value else None

    return {
        "holdings": result,
        "summary": {
            "total_cost": round(total_cost, 0),
            "total_value": round(total_value, 0) if total_value else None,
            "total_pnl": round(total_pnl, 0) if total_pnl is not None else None,
            "total_pnl_pct": round(total_pnl / total_cost * 100, 1) if total_pnl and total_cost > 0 else None,
        },
    }


@app.get("/api/stock-history/{securities_code}")
def stock_history(
    securities_code: str,
    period: str = Query("1y", description="期間: 1m, 3m, 6m, 1y, 2y, 5y, max"),
) -> dict:
    """株価履歴を取得 (Yahoo Finance)"""
    # yfinance は "1mo","3mo","6mo","1y" 形式を要求する
    period_map = {"1m": "1mo", "3m": "3mo", "6m": "6mo"}
    period = period_map.get(period, period)

    ticker = _sec_code_to_ticker(securities_code)
    if not ticker:
        raise HTTPException(404, "Invalid securities code")
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return {"ticker": ticker, "history": []}
        data = []
        for date, row in hist.iterrows():
            data.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 1),
                "high": round(float(row["High"]), 1),
                "low": round(float(row["Low"]), 1),
                "close": round(float(row["Close"]), 1),
                "volume": int(row["Volume"]),
            })
        return {"ticker": ticker, "history": data}
    except Exception as e:
        raise HTTPException(500, str(e))


# --------------- 企業検索 (オートコンプリート) ---------------

@app.get("/api/company-search")
def company_search(q: str = Query(..., min_length=1)) -> list[dict]:
    """企業名・証券コードで検索 (オートコンプリート用、上位10件)"""
    with get_db() as conn:
        like = f"%{q}%"
        rows = conn.execute(
            """SELECT edinet_code, securities_code, company_name, industry
               FROM companies
               WHERE company_name LIKE ? OR securities_code LIKE ? OR edinet_code LIKE ?
               ORDER BY CASE WHEN company_name LIKE ? THEN 0
                             WHEN securities_code LIKE ? THEN 1
                             ELSE 2 END, company_name
               LIMIT 10""",
            (like, like, like, f"{q}%", f"{q}%"),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# --------------- 売り時アラート API ---------------

@app.get("/api/alerts")
def get_alerts() -> dict:
    """保有銘柄の売り時アラートを生成"""
    from datetime import datetime, timezone

    with get_db() as conn:
        # デモトレード保有数量を集計
        trades = conn.execute(
            "SELECT * FROM demo_trades ORDER BY trade_date ASC, id ASC"
        ).fetchall()

    holdings: dict[str, dict] = {}
    for t in trades:
        t = row_to_dict(t)
        code = t["securities_code"]
        if code not in holdings:
            holdings[code] = {
                "securities_code": code,
                "company_name": t.get("company_name") or code,
                "total_qty": 0,
                "total_cost": 0.0,
            }
        h = holdings[code]
        if t["trade_type"] == "buy":
            h["total_qty"] += t["quantity"]
            h["total_cost"] += t["price"] * t["quantity"]
        elif t["trade_type"] == "sell":
            if h["total_qty"] > 0:
                avg = h["total_cost"] / h["total_qty"]
                sell_qty = min(t["quantity"], h["total_qty"])
                h["total_qty"] -= sell_qty
                h["total_cost"] -= avg * sell_qty

    # 保有中の銘柄のみ
    active = {c: h for c, h in holdings.items() if h["total_qty"] > 0}
    if not active:
        return {"alerts": [], "checked_at": datetime.now(timezone.utc).isoformat()}

    # 財務データと株価を取得してアラート判定
    alerts = []
    with get_db() as conn:
        for code, h in active.items():
            avg_cost = round(h["total_cost"] / h["total_qty"], 1) if h["total_qty"] > 0 else 0

            # EPS取得（最新年度）
            fin_row = conn.execute(
                """SELECT eps, bps FROM financials
                   WHERE edinet_code = (SELECT edinet_code FROM companies WHERE securities_code = ? LIMIT 1)
                   AND eps IS NOT NULL
                   ORDER BY fiscal_year DESC LIMIT 1""",
                (code,),
            ).fetchone()

            if not fin_row or not fin_row[0] or fin_row[0] <= 0:
                continue

            eps = fin_row[0]
            target = round(eps * 15, 1)  # PER15倍ライン

            # 現在株価
            ticker = _sec_code_to_ticker(code)
            if not ticker:
                continue
            price_data = fetch_stock_price(ticker)
            if not price_data or not price_data.get("price"):
                continue

            current_price = price_data["price"]
            gap_pct = round(((current_price - target) / target) * 100, 1)

            if gap_pct > 0:
                severity = "danger" if gap_pct > 20 else "warning"
                unrealized_pnl = round((current_price - avg_cost) * h["total_qty"], 0)
                alerts.append({
                    "securities_code": code,
                    "company_name": h["company_name"],
                    "current_price": current_price,
                    "target_price": target,
                    "gap_pct": gap_pct,
                    "avg_cost": avg_cost,
                    "total_qty": h["total_qty"],
                    "unrealized_pnl": unrealized_pnl,
                    "severity": severity,
                    "message": f"PER15倍ライン(¥{target:,.0f})を{gap_pct:.1f}%上回っています。" + (
                        "売り検討のタイミングです。" if gap_pct > 20 else "注意して推移を確認してください。"
                    ),
                })

    alerts.sort(key=lambda x: x["gap_pct"], reverse=True)
    return {
        "alerts": alerts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------- 米国株スクリーニング API ---------------

# 人気米国株リスト (S&P500 上位 + テック + 高配当 等)
US_STOCK_UNIVERSE = {
    # メガキャップテック
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "NVDA": "NVIDIA", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe", "AMD": "AMD",
    "INTC": "Intel", "CSCO": "Cisco", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "IBM": "IBM", "NFLX": "Netflix", "PYPL": "PayPal", "SHOP": "Shopify",
    # 金融
    "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan Chase", "V": "Visa",
    "MA": "Mastercard", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "GS": "Goldman Sachs", "MS": "Morgan Stanley", "AXP": "American Express",
    "BLK": "BlackRock",
    # ヘルスケア
    "JNJ": "Johnson & Johnson", "UNH": "UnitedHealth", "PFE": "Pfizer",
    "MRK": "Merck", "ABBV": "AbbVie", "LLY": "Eli Lilly", "TMO": "Thermo Fisher",
    "ABT": "Abbott Labs", "BMY": "Bristol-Myers Squibb", "AMGN": "Amgen",
    # 消費財・小売
    "WMT": "Walmart", "PG": "Procter & Gamble", "KO": "Coca-Cola",
    "PEP": "PepsiCo", "COST": "Costco", "MCD": "McDonald's",
    "NKE": "Nike", "SBUX": "Starbucks", "HD": "Home Depot", "LOW": "Lowe's",
    # 工業・エネルギー
    "XOM": "Exxon Mobil", "CVX": "Chevron", "CAT": "Caterpillar",
    "BA": "Boeing", "GE": "GE Aerospace", "HON": "Honeywell",
    "UNP": "Union Pacific", "RTX": "RTX Corp", "DE": "Deere & Co",
    "LMT": "Lockheed Martin",
    # 通信・メディア
    "DIS": "Disney", "CMCSA": "Comcast", "T": "AT&T", "VZ": "Verizon",
    "TMUS": "T-Mobile US",
    # 不動産・公益
    "NEE": "NextEra Energy", "SO": "Southern Co", "DUK": "Duke Energy",
    "AMT": "American Tower", "PLD": "Prologis",
}

# 米国株データキャッシュ (ticker -> (timestamp, data))
_us_stock_cache: dict[str, tuple[float, dict]] = {}
_us_cache_lock = threading.Lock()
US_CACHE_TTL = 600  # 10分


def _fetch_us_stock_info(ticker: str) -> dict | None:
    """yfinance で米国株の財務情報を取得 (キャッシュ付き)"""
    now = time()
    with _us_cache_lock:
        if ticker in _us_stock_cache:
            ts, data = _us_stock_cache[ticker]
            if now - ts < US_CACHE_TTL:
                return data
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        if not info or "symbol" not in info:
            return None

        # 基本情報
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        market_cap = info.get("marketCap")
        per = info.get("trailingPE") or info.get("forwardPE")
        pbr = info.get("priceToBook")
        roe = info.get("returnOnEquity")  # already decimal (0.xx)
        eps = info.get("trailingEps")
        bps = info.get("bookValue")
        dividend = info.get("dividendRate") or 0
        dividend_yield = info.get("dividendYield") or 0
        revenue = info.get("totalRevenue")
        net_income = info.get("netIncomeToCommon")
        operating_margin = info.get("operatingMargins")
        profit_margin = info.get("profitMargins")
        total_cash = info.get("totalCash")
        total_assets = info.get("totalAssets") if info.get("totalAssets") else None
        total_debt = info.get("totalDebt")
        free_cash_flow = info.get("freeCashflow")
        revenue_growth = info.get("revenueGrowth")
        earnings_growth = info.get("earningsGrowth")
        sector = info.get("sector", "")
        industry = info.get("industry", "")

        # 現金比率を推定 (total_cash / (total_cash + total_debt + market_cap))
        cash_ratio = None
        if total_cash and total_assets:
            cash_ratio = total_cash / total_assets
        elif total_cash and market_cap:
            # total_assetsがない場合は概算
            estimated_assets = market_cap + (total_debt or 0)
            if estimated_assets > 0:
                cash_ratio = total_cash / estimated_assets

        # equity_ratio (自己資本比率) は米国株の場合 info から直接取れないので推定
        equity_ratio = None
        shares = info.get("sharesOutstanding")
        if bps and shares and total_assets:
            equity = bps * shares
            equity_ratio = equity / total_assets

        data = {
            "ticker": ticker,
            "company_name": US_STOCK_UNIVERSE.get(ticker, info.get("shortName", ticker)),
            "sector": sector,
            "industry": industry,
            "price": round(float(price), 2) if price else None,
            "market_cap": market_cap,
            "per": round(float(per), 2) if per else None,
            "pbr": round(float(pbr), 2) if pbr else None,
            "roe": round(float(roe), 4) if roe else None,
            "eps": round(float(eps), 2) if eps else None,
            "bps": round(float(bps), 2) if bps else None,
            "dividend": round(float(dividend), 2) if dividend else None,
            "dividend_yield": round(float(dividend_yield), 4) if dividend_yield else None,
            "revenue": revenue,
            "net_income": net_income,
            "operating_margin": round(float(operating_margin), 4) if operating_margin else None,
            "profit_margin": round(float(profit_margin), 4) if profit_margin else None,
            "cash_ratio": round(float(cash_ratio), 4) if cash_ratio else None,
            "equity_ratio": round(float(equity_ratio), 4) if equity_ratio else None,
            "fcf": free_cash_flow,
            "revenue_growth": round(float(revenue_growth), 4) if revenue_growth else None,
            "earnings_growth": round(float(earnings_growth), 4) if earnings_growth else None,
            "total_debt": total_debt,
        }

        with _us_cache_lock:
            _us_stock_cache[ticker] = (now, data)
        return data
    except Exception as e:
        print(f"[WARN] US stock {ticker}: {e}")
        return None


def _takehara_score_us(d: dict) -> tuple[float, dict]:
    """米国株にも竹原式スコアを適用 (0-100点)"""
    score = 0.0
    parts = {}

    # PER: 15以下が理想。0-40の範囲で逆数スコア (25点満点)
    per = d.get("per")
    if per and per > 0:
        per_score = max(0, min(25, 25 * (1 - (per - 5) / 35)))
        score += per_score
        parts["per"] = round(per_score, 1)

    # PBR: 1以下が理想 (20点満点)
    pbr = d.get("pbr")
    if pbr is not None and pbr > 0:
        pbr_score = max(0, min(20, 20 * (1 - (pbr - 0.3) / 2.7)))
        score += pbr_score
        parts["pbr"] = round(pbr_score, 1)

    # ROE: 15%以上で満点 (20点満点)
    roe = d.get("roe")
    if roe and roe > 0:
        roe_score = max(0, min(20, 20 * min(1, roe / 0.15)))
        score += roe_score
        parts["roe"] = round(roe_score, 1)

    # 営業利益率: 15%以上で満点 (15点満点)
    om = d.get("operating_margin")
    if om and om > 0:
        om_score = max(0, min(15, 15 * min(1, om / 0.15)))
        score += om_score
        parts["operating_margin"] = round(om_score, 1)

    # 現金比率: 30%以上で満点 (10点満点)
    cr = d.get("cash_ratio")
    if cr and cr > 0:
        cash_score = max(0, min(10, 10 * min(1, cr / 0.3)))
        score += cash_score
        parts["cash_ratio"] = round(cash_score, 1)

    # FCF正: ボーナス (10点)
    fcf = d.get("fcf")
    if fcf and fcf > 0:
        score += 10
        parts["fcf"] = 10

    return round(score, 1), parts


@app.get("/api/us-screener")
def us_screener(
    per_max: float | None = Query(None),
    pbr_max: float | None = Query(None),
    roe_min: float | None = Query(None),
    operating_margin_min: float | None = Query(None),
    fcf_positive: bool = Query(False),
    dividend_min: float | None = Query(None),
    sector: str | None = Query(None),
    sort_by: str = Query("score"),
    sort_dir: str = Query(""),
    tickers: str | None = Query(None, description="カンマ区切りティッカー(未指定で全銘柄)"),
) -> dict:
    """米国株 竹原式スクリーニング (yfinance ベース)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 対象銘柄の決定
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = list(US_STOCK_UNIVERSE.keys())

    # 並列取得 (最大10スレッド)
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_us_stock_info, t): t for t in ticker_list}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                data = future.result()
                if data and data.get("price"):
                    results.append(data)
            except Exception:
                pass

    # フィルタ適用
    filtered = []
    for d in results:
        if per_max is not None and (d.get("per") is None or d["per"] > per_max):
            continue
        if pbr_max is not None and (d.get("pbr") is None or d["pbr"] > pbr_max):
            continue
        if roe_min is not None and (d.get("roe") is None or d["roe"] < roe_min):
            continue
        if operating_margin_min is not None and (d.get("operating_margin") is None or d["operating_margin"] < operating_margin_min):
            continue
        if fcf_positive and (d.get("fcf") is None or d["fcf"] <= 0):
            continue
        if dividend_min is not None and (d.get("dividend") is None or d["dividend"] < dividend_min):
            continue
        if sector and d.get("sector") != sector:
            continue

        # スコア計算
        score, parts = _takehara_score_us(d)
        d["takehara_score"] = score
        d["score_parts"] = parts

        # 売り時目安
        d.update(calc_target_prices(d.get("eps"), d.get("bps")))

        filtered.append(d)

    # ソート
    sort_defaults = {
        "score": ("takehara_score", True),
        "per": ("per", False),
        "pbr": ("pbr", False),
        "roe": ("roe", True),
        "operating_margin": ("operating_margin", True),
        "dividend": ("dividend", True),
        "company_name": ("company_name", False),
        "market_cap": ("market_cap", True),
    }
    col, default_desc = sort_defaults.get(sort_by, ("takehara_score", True))
    desc = default_desc if sort_dir == "" else (sort_dir.lower() == "desc")
    filtered.sort(key=lambda x: x.get(col) or 0, reverse=desc)

    # セクター一覧を返す
    all_sectors = sorted(set(d.get("sector", "") for d in results if d.get("sector")))

    return {
        "total": len(filtered),
        "universe_size": len(ticker_list),
        "fetched": len(results),
        "sectors": all_sectors,
        "results": filtered,
    }


@app.get("/api/us-sectors")
def us_sectors() -> list[str]:
    """米国株セクター一覧（キャッシュから取得）"""
    sectors = set()
    with _us_cache_lock:
        for _, (_, data) in _us_stock_cache.items():
            if data.get("sector"):
                sectors.add(data["sector"])
    return sorted(sectors)


# --------------- 静的ファイル配信 (本番: Dockerコンテナ用) ---------------

_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """React SPA のフォールバック: /api以外は index.html を返す"""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_static_dir / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
