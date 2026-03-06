"""
gross_profit 差分バックフィルスクリプト
gross_profit が NULL の企業だけ EDINET API から取得して更新する。
API制限を考慮し、1回あたり最大 max_companies 社まで処理する。

使い方:
  python backend/backfill_gross_profit.py              # デフォルト500社
  python backend/backfill_gross_profit.py --max 1000   # 1000社まで
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DB_PATH = Path(__file__).parent.parent / "data" / "edinet.db"
API_BASE = "https://edinetdb.jp/v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=500, help="最大処理企業数 (default: 500)")
    args = parser.parse_args()

    api_key = os.environ.get("EDINET_API_KEY", "")
    if not api_key:
        print("ERROR: EDINET_API_KEY not set in .env")
        sys.exit(1)

    headers = {"X-API-Key": api_key}
    conn = sqlite3.connect(str(DB_PATH))

    # gross_profit が NULL の企業コードを取得 (最新年度のみチェック)
    year_row = conn.execute("SELECT MAX(fiscal_year) FROM financials").fetchone()
    if not year_row or not year_row[0]:
        print("No financial data found")
        return
    latest_year = year_row[0]

    rows = conn.execute(
        """SELECT DISTINCT f.edinet_code FROM financials f
           WHERE f.fiscal_year = ? AND f.gross_profit IS NULL
           ORDER BY f.edinet_code""",
        (latest_year,),
    ).fetchall()

    remaining = [r[0] for r in rows]
    total_remaining = len(remaining)
    target = remaining[: args.max]

    print(f"gross_profit NULL: {total_remaining} companies (processing {len(target)})")

    updated = 0
    errors = 0
    rate_limited = 0

    for i, code in enumerate(target):
        try:
            r = requests.get(
                f"{API_BASE}/companies/{code}/financials",
                params={"years": 10},
                headers=headers,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                for rec in data:
                    gp = rec.get("gross_profit")
                    fy = rec.get("fiscal_year")
                    if gp is not None and fy is not None:
                        conn.execute(
                            "UPDATE financials SET gross_profit = ? WHERE edinet_code = ? AND fiscal_year = ?",
                            (gp, code, fy),
                        )
                        updated += 1
            elif r.status_code == 429:
                rate_limited += 1
                print(f"  Rate limited at {i + 1}/{len(target)}, stopping.")
                break
            elif r.status_code != 404:
                errors += 1
        except Exception:
            errors += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(target)} processed ({updated} records updated)")
            time.sleep(0.3)

    conn.commit()

    # Stats
    gp_count = conn.execute("SELECT COUNT(*) FROM financials WHERE gross_profit IS NOT NULL").fetchone()[0]
    all_count = conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0]
    still_null = conn.execute(
        "SELECT COUNT(DISTINCT edinet_code) FROM financials WHERE fiscal_year = ? AND gross_profit IS NULL",
        (latest_year,),
    ).fetchone()[0]

    print(f"\nDone! {updated} records updated, {errors} errors")
    print(f"Coverage: {gp_count}/{all_count} records ({gp_count / all_count * 100:.1f}%)")
    print(f"Still NULL (latest year): {still_null} companies")
    if rate_limited:
        print(f"Rate limited — run again later to continue.")

    conn.close()


if __name__ == "__main__":
    main()
