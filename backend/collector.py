"""
EDINET DB データ収集スクリプト
全上場企業の財務データをAPIから取得してSQLiteに保存する
"""
import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE = "https://edinetdb.jp/v1"
DB_PATH = Path(__file__).parent.parent / "data" / "edinet.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_api_key() -> str:
    key = os.environ.get("EDINET_API_KEY", "")
    if not key:
        raise RuntimeError(
            "環境変数 EDINET_API_KEY が未設定です。\n"
            "https://edinetdb.jp/developers でAPIキーを取得し、\n"
            ".env ファイルに EDINET_API_KEY=your_key を設定してください。"
        )
    return key


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            edinet_code      TEXT PRIMARY KEY,
            securities_code  TEXT,
            company_name     TEXT NOT NULL,
            industry         TEXT,
            accounting_std   TEXT,
            credit_score     REAL,
            credit_rating    TEXT,
            updated_at       TEXT
        );

        CREATE TABLE IF NOT EXISTS financials (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            edinet_code      TEXT NOT NULL,
            fiscal_year      INTEGER NOT NULL,
            revenue          REAL,
            operating_income REAL,
            ordinary_income  REAL,
            net_income       REAL,
            total_assets     REAL,
            net_assets       REAL,
            roe              REAL,
            equity_ratio     REAL,
            eps              REAL,
            bps              REAL,
            dividend         REAL,
            per              REAL,
            payout_ratio     REAL,
            cash             REAL,
            cf_operating     REAL,
            cf_investing     REAL,
            cf_financing     REAL,
            accounting_std   TEXT,
            UNIQUE(edinet_code, fiscal_year)
        );

        CREATE TABLE IF NOT EXISTS analysis (
            edinet_code         TEXT PRIMARY KEY,
            credit_score        REAL,
            credit_rating       TEXT,
            ai_summary          TEXT,
            strengths           TEXT,
            risks               TEXT,
            updated_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            companies_synced INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS ratios (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            edinet_code      TEXT NOT NULL,
            fiscal_year      INTEGER NOT NULL,
            fcf              REAL,
            roa              REAL,
            roe              REAL,
            net_margin       REAL,
            operating_margin REAL,
            eps_growth       REAL,
            ni_growth        REAL,
            oi_growth        REAL,
            revenue_growth   REAL,
            eps_cagr_3y      REAL,
            eps_cagr_5y      REAL,
            ni_cagr_3y       REAL,
            ni_cagr_5y       REAL,
            revenue_cagr_3y  REAL,
            revenue_cagr_5y  REAL,
            UNIQUE(edinet_code, fiscal_year)
        );

        CREATE TABLE IF NOT EXISTS company_tags (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            edinet_code  TEXT NOT NULL,
            tag          TEXT NOT NULL,
            created_at   TEXT,
            UNIQUE(edinet_code, tag)
        );

        CREATE INDEX IF NOT EXISTS idx_ratios_code ON ratios(edinet_code);
        CREATE INDEX IF NOT EXISTS idx_financials_code ON financials(edinet_code);
        CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);
        CREATE INDEX IF NOT EXISTS idx_companies_sec ON companies(securities_code);
        CREATE INDEX IF NOT EXISTS idx_company_tags ON company_tags(edinet_code, tag);
    """)
    conn.commit()


def upsert_company(conn: sqlite3.Connection, c: dict) -> None:
    """APIレスポンス: {edinet_code, sec_code, name, industry, accounting_standard, credit_score, credit_rating}"""
    conn.execute("""
        INSERT INTO companies
            (edinet_code, securities_code, company_name, industry, accounting_std,
             credit_score, credit_rating, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(edinet_code) DO UPDATE SET
            securities_code = excluded.securities_code,
            company_name    = excluded.company_name,
            industry        = excluded.industry,
            accounting_std  = excluded.accounting_std,
            credit_score    = excluded.credit_score,
            credit_rating   = excluded.credit_rating,
            updated_at      = excluded.updated_at
    """, (
        c.get("edinet_code"),
        c.get("sec_code"),
        c.get("name"),
        c.get("industry"),
        c.get("accounting_standard"),
        c.get("credit_score"),
        c.get("credit_rating"),
        now_iso(),
    ))


def upsert_financials(conn: sqlite3.Connection, edinet_code: str, records: list[dict]) -> None:
    for r in records:
        conn.execute("""
            INSERT INTO financials
                (edinet_code, fiscal_year, revenue, operating_income, ordinary_income,
                 net_income, total_assets, net_assets, roe, equity_ratio,
                 eps, bps, dividend, per, payout_ratio,
                 cash, cf_operating, cf_investing, cf_financing, accounting_std)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(edinet_code, fiscal_year) DO UPDATE SET
                revenue          = excluded.revenue,
                operating_income = excluded.operating_income,
                ordinary_income  = excluded.ordinary_income,
                net_income       = excluded.net_income,
                total_assets     = excluded.total_assets,
                net_assets       = excluded.net_assets,
                roe              = excluded.roe,
                equity_ratio     = excluded.equity_ratio,
                eps              = excluded.eps,
                bps              = excluded.bps,
                dividend         = excluded.dividend,
                per              = excluded.per,
                payout_ratio     = excluded.payout_ratio,
                cash             = excluded.cash,
                cf_operating     = excluded.cf_operating,
                cf_investing     = excluded.cf_investing,
                cf_financing     = excluded.cf_financing,
                accounting_std   = excluded.accounting_std
        """, (
            edinet_code,
            r.get("fiscal_year"),
            r.get("revenue"),
            r.get("operating_income"),
            r.get("ordinary_income"),
            r.get("net_income"),
            r.get("total_assets"),
            r.get("net_assets"),
            r.get("roe_official"),
            r.get("equity_ratio_official"),
            r.get("eps"),
            r.get("bps"),
            r.get("dividend_per_share"),
            r.get("per"),
            r.get("payout_ratio"),
            r.get("cash"),
            r.get("cf_operating"),
            r.get("cf_investing"),
            r.get("cf_financing"),
            r.get("accounting_standard"),
        ))


async def fetch_all_companies(client: httpx.AsyncClient, api_key: str) -> list[dict]:
    """全企業一覧を取得（ページネーションで全件取得）"""
    all_companies = []
    page = 1
    per_page = 5000  # max

    while True:
        resp = await client.get(
            f"{API_BASE}/companies",
            params={"per_page": per_page, "page": page},
            headers={"X-API-Key": api_key},
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
        companies = body.get("data", [])
        all_companies.extend(companies)

        meta = body.get("meta", {}).get("pagination", {})
        total_pages = meta.get("total_pages", 1)
        total = meta.get("total", len(all_companies))
        print(f"  企業一覧取得: ページ {page}/{total_pages} ({len(all_companies)}/{total}社)")

        if page >= total_pages:
            break
        page += 1

    return all_companies


async def fetch_financials(
    client: httpx.AsyncClient,
    api_key: str,
    edinet_code: str,
    years: int = 10,
) -> list[dict]:
    resp = await client.get(
        f"{API_BASE}/companies/{edinet_code}/financials",
        params={"years": years},
        headers={"X-API-Key": api_key},
        timeout=30.0,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", [])


async def fetch_ratios(
    client: httpx.AsyncClient,
    api_key: str,
    edinet_code: str,
    years: int = 5,
) -> list[dict]:
    resp = await client.get(
        f"{API_BASE}/companies/{edinet_code}/ratios",
        params={"years": years},
        headers={"X-API-Key": api_key},
        timeout=30.0,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", [])


def upsert_ratios(conn: sqlite3.Connection, edinet_code: str, records: list[dict]) -> None:
    for r in records:
        conn.execute("""
            INSERT INTO ratios
                (edinet_code, fiscal_year, fcf, roa, roe, net_margin, operating_margin,
                 eps_growth, ni_growth, oi_growth, revenue_growth,
                 eps_cagr_3y, eps_cagr_5y, ni_cagr_3y, ni_cagr_5y,
                 revenue_cagr_3y, revenue_cagr_5y)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(edinet_code, fiscal_year) DO UPDATE SET
                fcf              = excluded.fcf,
                roa              = excluded.roa,
                roe              = excluded.roe,
                net_margin       = excluded.net_margin,
                operating_margin = excluded.operating_margin,
                eps_growth       = excluded.eps_growth,
                ni_growth        = excluded.ni_growth,
                oi_growth        = excluded.oi_growth,
                revenue_growth   = excluded.revenue_growth,
                eps_cagr_3y      = excluded.eps_cagr_3y,
                eps_cagr_5y      = excluded.eps_cagr_5y,
                ni_cagr_3y       = excluded.ni_cagr_3y,
                ni_cagr_5y       = excluded.ni_cagr_5y,
                revenue_cagr_3y  = excluded.revenue_cagr_3y,
                revenue_cagr_5y  = excluded.revenue_cagr_5y
        """, (
            edinet_code,
            r.get("fiscal_year"),
            r.get("fcf"),
            r.get("roa"),
            r.get("roe"),
            r.get("net_margin"),
            r.get("operating_margin"),
            r.get("eps_growth"),
            r.get("ni_growth"),
            r.get("oi_growth"),
            r.get("revenue_growth"),
            r.get("eps_cagr_3y"),
            r.get("eps_cagr_5y"),
            r.get("ni_cagr_3y"),
            r.get("ni_cagr_5y"),
            r.get("revenue_cagr_3y"),
            r.get("revenue_cagr_5y"),
        ))


async def fetch_analysis(
    client: httpx.AsyncClient,
    api_key: str,
    edinet_code: str,
) -> dict | None:
    resp = await client.get(
        f"{API_BASE}/companies/{edinet_code}/analysis",
        headers={"X-API-Key": api_key},
        timeout=30.0,
    )
    if resp.status_code in (404, 204):
        return None
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", body)


async def sync_company(
    client: httpx.AsyncClient,
    api_key: str,
    conn: sqlite3.Connection,
    company: dict,
    fetch_fin: bool = True,
    fetch_anal: bool = False,
    fetch_rat: bool = True,
    sem: asyncio.Semaphore | None = None,
) -> None:
    code = company.get("edinet_code", "")

    async def _do():
        upsert_company(conn, company)

        if fetch_fin:
            try:
                records = await fetch_financials(client, api_key, code)
                if records:
                    upsert_financials(conn, code, records)
            except httpx.HTTPStatusError as e:
                print(f"    [WARN] {code} financials: {e.response.status_code}")

        if fetch_rat:
            try:
                rat_records = await fetch_ratios(client, api_key, code)
                if rat_records:
                    upsert_ratios(conn, code, rat_records)
            except httpx.HTTPStatusError as e:
                print(f"    [WARN] {code} ratios: {e.response.status_code}")

        if fetch_anal:
            try:
                anal = await fetch_analysis(client, api_key, code)
                if anal:
                    conn.execute("""
                        INSERT INTO analysis
                            (edinet_code, credit_score, credit_rating,
                             ai_summary, strengths, risks, updated_at)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(edinet_code) DO UPDATE SET
                            credit_score  = excluded.credit_score,
                            credit_rating = excluded.credit_rating,
                            ai_summary    = excluded.ai_summary,
                            strengths     = excluded.strengths,
                            risks         = excluded.risks,
                            updated_at    = excluded.updated_at
                    """, (
                        code,
                        anal.get("credit_score"),
                        anal.get("credit_rating"),
                        anal.get("ai_summary") or anal.get("summary"),
                        json.dumps(anal.get("strengths", []), ensure_ascii=False),
                        json.dumps(anal.get("risks", []), ensure_ascii=False),
                        now_iso(),
                    ))
            except httpx.HTTPStatusError as e:
                print(f"    [WARN] {code} analysis: {e.response.status_code}")

    if sem:
        async with sem:
            await _do()
            await asyncio.sleep(0.1)
    else:
        await _do()


async def run_full_sync(
    fetch_financials_flag: bool = True,
    fetch_analysis_flag: bool = False,
    concurrency: int = 3,
    limit: int | None = None,
) -> None:
    api_key = get_api_key()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)

    log_id = conn.execute(
        "INSERT INTO sync_log (started_at) VALUES (?)", (now_iso(),)
    ).lastrowid
    conn.commit()

    print(f"\n{'='*50}")
    print(f"EDINET DB フルシンク開始")
    print(f"DB: {DB_PATH}")
    print(f"財務データ取得: {fetch_financials_flag}")
    print(f"AI分析取得:     {fetch_analysis_flag}")
    print(f"{'='*50}\n")

    start = time.time()
    try:
        async with httpx.AsyncClient() as client:
            companies = await fetch_all_companies(client, api_key)
            if limit:
                companies = list(companies)[:limit]
                print(f"  (テスト制限: {limit}社)")

            sem = asyncio.Semaphore(concurrency)
            tasks = [
                sync_company(
                    client, api_key, conn, c,
                    fetch_fin=fetch_financials_flag,
                    fetch_anal=fetch_analysis_flag,
                    fetch_rat=fetch_financials_flag,  # ratiosも財務と同時取得
                    sem=sem,
                )
                for c in companies
            ]

            total = len(tasks)
            batch_size = 50
            for i in range(0, total, batch_size):
                batch = tasks[i:i + batch_size]
                await asyncio.gather(*batch, return_exceptions=True)
                done = min(i + batch_size, total)
                conn.commit()
                elapsed = time.time() - start
                pct = done / total * 100
                eta = (elapsed / done * (total - done)) if done > 0 else 0
                print(
                    f"  進捗: {done}/{total} ({pct:.1f}%) "
                    f"経過: {elapsed:.0f}s 残り: {eta:.0f}s"
                )

        conn.execute(
            "UPDATE sync_log SET finished_at=?, companies_synced=?, status=? WHERE id=?",
            (now_iso(), total, "done", log_id),
        )
        conn.commit()
        elapsed = time.time() - start
        print(f"\n完了! {total}社 ({elapsed:.1f}s)\n")

    except Exception as e:
        conn.execute(
            "UPDATE sync_log SET finished_at=?, status=? WHERE id=?",
            (now_iso(), f"error: {e}", log_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EDINET DB データ収集")
    parser.add_argument("--no-financials", action="store_true", help="財務データをスキップ")
    parser.add_argument("--with-analysis", action="store_true", help="AI分析も取得（API多消費）")
    parser.add_argument("--limit", type=int, default=None, help="テスト用: 取得企業数を制限")
    parser.add_argument("--concurrency", type=int, default=3, help="同時リクエスト数")
    args = parser.parse_args()

    asyncio.run(run_full_sync(
        fetch_financials_flag=not args.no_financials,
        fetch_analysis_flag=args.with_analysis,
        concurrency=args.concurrency,
        limit=args.limit,
    ))
