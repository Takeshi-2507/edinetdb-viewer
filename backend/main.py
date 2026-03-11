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
from datetime import datetime, timezone
from time import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
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


# --------------- 株価ヒストリーキャッシュ (Momentum Score 用) ---------------
_HIST_CACHE_FILE = Path(__file__).parent.parent / "data" / "hist_cache.json"
HIST_TTL = 86400  # 1日キャッシュ (日足データは当日中は変わらない)

def _load_hist_cache() -> dict[str, tuple[float, list]]:
    if _HIST_CACHE_FILE.exists():
        try:
            raw = json.loads(_HIST_CACHE_FILE.read_text(encoding="utf-8"))
            return {k: (v[0], v[1]) for k, v in raw.items()}
        except Exception:
            pass
    return {}

def _save_hist_cache(cache: dict):
    try:
        _HIST_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HIST_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8",
        )
    except Exception:
        pass

_hist_cache: dict[str, tuple[float, list]] = _load_hist_cache()
_hist_lock = threading.Lock()


def fetch_price_history(ticker: str, period: str = "1y") -> list[dict] | None:
    """yfinance で過去株価 (日足) を取得。[{date, close, volume}, ...]
    1日キャッシュ。Momentum Score 算出用。
    """
    now = time()
    with _hist_lock:
        if ticker in _hist_cache:
            ts, data = _hist_cache[ticker]
            if now - ts < HIST_TTL:
                return data

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval="1d")
        if df is None or df.empty:
            return None
        records = []
        for idx, row in df.iterrows():
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 1),
                "volume": int(row["Volume"]) if row.get("Volume") else 0,
            })
        with _hist_lock:
            _hist_cache[ticker] = (now, records)
            _save_hist_cache(_hist_cache)
        return records
    except Exception:
        # キャッシュにstaleデータがあれば返す
        with _hist_lock:
            if ticker in _hist_cache:
                return _hist_cache[ticker][1]
        return None


# --------------- TOPIX ベンチマーク (Relative Strength 用) ---------------
_topix_cache: tuple[float, list] | None = None
_topix_lock = threading.Lock()

def fetch_topix_history(period: str = "1y") -> list[dict] | None:
    """TOPIX (^TPX) の日足データを取得。RS計算のベンチマーク用。"""
    global _topix_cache
    now = time()
    with _topix_lock:
        if _topix_cache is not None:
            ts, data = _topix_cache
            if now - ts < HIST_TTL:
                return data
    try:
        import yfinance as yf
        df = yf.Ticker("^TPX").history(period=period, interval="1d")
        if df is None or df.empty:
            # TOPIX取れない場合は日経225で代替
            df = yf.Ticker("^N225").history(period=period, interval="1d")
        if df is None or df.empty:
            return None
        records = [
            {"date": idx.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 1)}
            for idx, row in df.iterrows()
        ]
        with _topix_lock:
            _topix_cache = (now, records)
        return records
    except Exception:
        with _topix_lock:
            if _topix_cache is not None:
                return _topix_cache[1]
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


def calc_quality_score(d: dict) -> tuple[float, dict]:
    """Quality スコアを計算 (0-100点)。ビジネスの質を評価。
    4指標: 粗利率(25点) + 営業利益率(30点) + ROE(25点) + CF質(20点)
    gross_profit が無い企業は 3指標フォールバック(配点再配分)。
    Returns: (score, parts_dict)
    """
    score = 0.0
    parts: dict[str, float] = {}

    # gross_margin の有無で配点を切り替え
    rev = d.get("revenue")
    gp = d.get("gross_profit")
    has_gm = gp is not None and rev and rev > 0

    if has_gm:
        # 4指標モード: gross_margin 25 + op_margin 30 + roe 25 + cf_quality 20
        w_gm, w_om, w_roe, w_cf = 25, 30, 25, 20
    else:
        # 3指標フォールバック: op_margin 35 + roe 35 + cf_quality 30
        w_gm, w_om, w_roe, w_cf = 0, 35, 35, 30

    # 粗利率 (25点): 40%以上で満点。価格決定力・ブランド力
    if has_gm:
        gm = gp / rev
        if gm > 0:
            s = max(0, min(w_gm, w_gm * min(1, gm / 0.40)))
            score += s
            parts["gross_margin"] = round(s, 1)

    # 営業利益率: 20%以上で満点
    om = d.get("operating_margin")
    if om is None:
        oi = d.get("operating_income")
        if rev and rev > 0 and oi is not None:
            om = oi / rev
    if om is not None and om > 0:
        s = max(0, min(w_om, w_om * min(1, om / 0.20)))
        score += s
        parts["operating_margin"] = round(s, 1)

    # ROE: 15%以上で満点
    roe = d.get("roe")
    if roe is not None and roe > 0:
        s = max(0, min(w_roe, w_roe * min(1, roe / 0.15)))
        score += s
        parts["roe"] = round(s, 1)

    # CF Quality: 営業CF/営業利益 >= 1.0 で満点
    cf_op = d.get("cf_operating")
    oi = d.get("operating_income")
    if cf_op is not None and oi is not None and oi > 0:
        cf_quality = cf_op / oi
        s = max(0, min(w_cf, w_cf * min(1, cf_quality / 1.0)))
        score += s
        parts["cf_quality"] = round(s, 1)

    parts["_mode"] = "4ind" if has_gm else "3ind"
    return round(score, 1), parts


# ════════════════════════════════════════════════════════════
# Phase 2 スケルトン: Momentum Score (C層)
# ════════════════════════════════════════════════════════════
def calc_momentum_score(
    d: dict,
    price_history: list[dict] | None = None,
    topix_history: list[dict] | None = None,
) -> tuple[float, dict]:
    """Momentum スコアを計算 (0-100点)。株価の勢い・テクニカル指標を評価。

    price_history: [{"date": "...", "close": 1234.0, "volume": 100000}, ...]
    topix_history: [{"date": "...", "close": 2800.0}, ...]  (RS計算用)

    5指標:
      - 移動平均乖離率 (25点): 株価 vs 75日MA
      - ゴールデンクロス (20点): 25日MA vs 75日MA
      - 相対モメンタム RS (25点): 3ヶ月リターン vs TOPIX
      - 出来高トレンド (15点): 直近20日平均出来高 vs 60日平均
      - ボラティリティ調整 (15点): 低ボラ = 安定上昇を加点
    """
    parts: dict[str, float] = {}

    if price_history is None or len(price_history) < 30:
        return 0.0, {"_status": "no_data"}

    closes = [p["close"] for p in price_history]
    volumes = [p.get("volume", 0) for p in price_history]
    n = len(closes)

    # ── 1) 移動平均乖離率 (25点) ──
    # 75日MA の上にいれば上昇トレンド。 -5%以下=0点, +10%以上=満点
    if n >= 75:
        ma75 = sum(closes[-75:]) / 75
        if ma75 > 0:
            deviation = (closes[-1] - ma75) / ma75
            # -5%で0点, +10%で25点 (線形補間)
            s = max(0.0, min(25.0, 25.0 * (deviation + 0.05) / 0.15))
            parts["ma_deviation"] = round(s, 1)

    # ── 2) ゴールデンクロス / デッドクロス (20点) ──
    # 25日MA > 75日MA → GC状態 (上昇トレンド) → 20点
    # 25日MA < 75日MA → DC状態 → 0点
    # 乖離率で段階的にスコア (微妙なGCは中間点)
    if n >= 75:
        ma25 = sum(closes[-25:]) / 25
        ma75 = sum(closes[-75:]) / 75
        if ma75 > 0:
            gc_ratio = (ma25 - ma75) / ma75  # +なら GC, -なら DC
            # -3%以下=0点, +3%以上=20点
            s = max(0.0, min(20.0, 20.0 * (gc_ratio + 0.03) / 0.06))
            parts["golden_cross"] = round(s, 1)

    # ── 3) 相対モメンタム RS (25点) ──
    # 3ヶ月リターンが TOPIX を上回っていれば加点
    if n >= 63:
        ret_3m = (closes[-1] - closes[-63]) / closes[-63] if closes[-63] > 0 else 0
        topix_ret_3m = 0.0
        if topix_history and len(topix_history) >= 63:
            tc = [t["close"] for t in topix_history]
            if tc[-63] > 0:
                topix_ret_3m = (tc[-1] - tc[-63]) / tc[-63]

        # 相対リターン = 個別 - TOPIX
        rs = ret_3m - topix_ret_3m
        # -10%以下=0点, +15%以上=25点
        s = max(0.0, min(25.0, 25.0 * (rs + 0.10) / 0.25))
        parts["relative_strength"] = round(s, 1)

    # ── 4) 出来高トレンド (15点) ──
    # 直近20日平均出来高 vs 60日平均。出来高増加=需要増の兆候
    valid_vols = [v for v in volumes if v > 0]
    if len(valid_vols) >= 60:
        vol20 = sum(valid_vols[-20:]) / 20
        vol60 = sum(valid_vols[-60:]) / 60
        if vol60 > 0:
            vol_ratio = vol20 / vol60
            # 0.8以下=0点, 1.5以上=15点
            s = max(0.0, min(15.0, 15.0 * (vol_ratio - 0.8) / 0.7))
            parts["volume_trend"] = round(s, 1)

    # ── 5) ボラティリティ調整 (15点) ──
    # 低ボラ(安定上昇)を加点。日本株の平均年率ボラは30-40%程度。
    # 25%以下=15点, 50%以上=0点 (日本株向け閾値)
    if n >= 21:
        daily_returns = []
        for i in range(-20, 0):
            if closes[i - 1] > 0:
                daily_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        if len(daily_returns) >= 15:
            mean_r = sum(daily_returns) / len(daily_returns)
            var_r = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            vol_annual = var_r ** 0.5 * (252 ** 0.5)  # 年率ボラティリティ
            # 25%以下=15点, 50%以上=0点
            s = max(0.0, min(15.0, 15.0 * (1.0 - (vol_annual - 0.25) / 0.25)))
            parts["volatility"] = round(s, 1)

    score = sum(v for k, v in parts.items() if not k.startswith("_"))
    return round(min(100.0, score), 1), parts


# ════════════════════════════════════════════════════════════
# Phase 3 スケルトン: Event Score (D層)
# ════════════════════════════════════════════════════════════
def calc_event_score(d: dict, hist_financials: list[dict] | None = None) -> tuple[float, dict]:
    """Event スコアを計算 (0-100点)。株主還元・業績トレンドを評価。

    外部APIなし。DBの財務推移データ (過去3-5年) から算出。
    hist_financials: [{fiscal_year, dividend, revenue, operating_income, ...}, ...]
                     古い順 (昇順) で渡す

    4指標:
      - 増配トレンド (25点): 直近3年で連続増配 or 大幅増配
      - 配当性向の健全さ (25点): 20-50% = 適正還元、0%=無配減点、80%超=過剰減点
      - 連続増収増益 (25点): 直近3年で増収・増益の年が多いほど加点
      - 業績加速 (25点): 直近の成長率が過去平均を上回っていれば加点

    Returns: (score, parts_dict)
    """
    parts: dict[str, float] = {}

    if hist_financials is None or len(hist_financials) < 2:
        return 0.0, {"_status": "no_data"}

    recs = hist_financials  # 古い順

    # ── 1) 増配トレンド (25点) ──
    divs = [(r.get("fiscal_year"), r.get("dividend")) for r in recs if r.get("dividend") is not None]
    if len(divs) >= 2:
        increases = 0
        for i in range(1, len(divs)):
            if divs[i][1] > divs[i - 1][1]:
                increases += 1
        recent_n = min(len(divs) - 1, 3)  # 直近3年間
        recent_increases = 0
        for i in range(len(divs) - recent_n, len(divs)):
            if divs[i][1] > divs[i - 1][1]:
                recent_increases += 1
        # 直近3年中3年連続増配=25点, 2年=17点, 1年=8点
        s = min(25.0, 25.0 * recent_increases / max(1, recent_n))
        parts["dividend_trend"] = round(s, 1)

    # ── 2) 配当性向の健全さ (25点) ──
    latest = recs[-1]
    pr = latest.get("payout_ratio")
    if pr is not None:
        if 0.15 <= pr <= 0.50:
            # 適正レンジ: 満点
            s = 25.0
        elif pr <= 0:
            # 無配 or 赤字
            s = 0.0
        elif pr < 0.15:
            # 配当少なすぎ (ケチ)
            s = max(0.0, 25.0 * pr / 0.15)
        elif pr <= 0.80:
            # やや高め (50-80%)
            s = max(0.0, 25.0 * (1.0 - (pr - 0.50) / 0.30))
        else:
            # 80%超: 過剰配当で持続性に疑問
            s = 0.0
        parts["payout_health"] = round(s, 1)

    # ── 3) 連続増収増益 (25点) ──
    recent = recs[-4:] if len(recs) >= 4 else recs  # 直近3-4年
    rev_up = 0
    oi_up = 0
    checks = 0
    for i in range(1, len(recent)):
        r_prev = recent[i - 1].get("revenue")
        r_curr = recent[i].get("revenue")
        o_prev = recent[i - 1].get("operating_income")
        o_curr = recent[i].get("operating_income")
        if r_prev and r_curr and r_curr > r_prev:
            rev_up += 1
        if o_prev and o_curr and o_curr > o_prev:
            oi_up += 1
        checks += 1
    if checks > 0:
        # 増収+増益の比率 → 25点
        combo = (rev_up + oi_up) / (checks * 2)
        s = min(25.0, 25.0 * combo)
        parts["growth_streak"] = round(s, 1)

    # ── 4) 業績加速 (25点) ──
    # 直近の成長率 vs 過去平均。加速していれば加点
    rg = d.get("revenue_growth")
    rcagr = d.get("revenue_cagr_3y")
    if rg is not None and rcagr is not None:
        if rcagr > 0:
            accel = rg / rcagr  # 1.0超なら加速
            s = max(0.0, min(25.0, 25.0 * min(2.0, accel) / 2.0))
        elif rg > 0:
            s = 20.0  # CAGRマイナスからプラス転換
        else:
            s = 0.0
        parts["acceleration"] = round(s, 1)
    elif rg is not None and rg > 0:
        # CAGRなしだが直近プラス成長
        parts["acceleration"] = 10.0

    score = sum(v for k, v in parts.items() if not k.startswith("_"))
    return round(min(100.0, score), 1), parts


# ════════════════════════════════════════════════════════════
# Phase 3 スケルトン: AI Qualitative Score (E層)
# ════════════════════════════════════════════════════════════
def calc_ai_qualitative_score(d: dict, hist_financials: list[dict] | None = None) -> tuple[float, dict]:
    """企業の質的評価スコア (0-100点)。財務安定性・信用力を数値で評価。

    外部API/LLM不要。DBのcredit_score + 財務データから算出。
    将来的にLLM分析 (有報テキスト) を追加予定。

    4指標:
      - 信用スコア (30点): EDINET DB の credit_score (0-100) を正規化
      - 財務安定性 (25点): 自己資本比率の高さ
      - 収益安定性 (25点): 過去の利益変動の小ささ (低ブレ=安定)
      - 利益の質 (20点): 特別損益に依存しない経常的利益力

    Returns: (score, parts_dict)
    """
    parts: dict[str, float] = {}

    # ── 1) 信用スコア (30点) ──
    cs = d.get("credit_score")
    if cs is not None:
        # credit_score は 0-100。そのまま30点満点に正規化
        s = max(0.0, min(30.0, 30.0 * cs / 100.0))
        parts["credit"] = round(s, 1)

    # ── 2) 財務安定性 (25点) ──
    # 自己資本比率: 50%以上=満点, 20%以下=0点
    eq = d.get("equity_ratio")
    if eq is not None:
        s = max(0.0, min(25.0, 25.0 * (eq - 0.20) / 0.30))
        parts["financial_stability"] = round(s, 1)

    # ── 3) 収益安定性 (25点) ──
    # 過去の純利益の変動係数 (CV) が小さいほど安定
    if hist_financials and len(hist_financials) >= 3:
        ni_list = [r.get("net_income") for r in hist_financials if r.get("net_income") is not None and r.get("net_income") > 0]
        if len(ni_list) >= 3:
            mean_ni = sum(ni_list) / len(ni_list)
            if mean_ni > 0:
                var_ni = sum((x - mean_ni) ** 2 for x in ni_list) / len(ni_list)
                cv = (var_ni ** 0.5) / mean_ni  # 変動係数
                # CV 0.2以下=25点 (超安定), CV 1.0以上=0点 (不安定)
                s = max(0.0, min(25.0, 25.0 * (1.0 - (cv - 0.2) / 0.8)))
                parts["earnings_stability"] = round(s, 1)

    # ── 4) 利益の質 (20点) ──
    # 経常利益/純利益 比率: 特別損益に依存していない = 質が高い
    oi = d.get("ordinary_income") or d.get("operating_income")
    ni = d.get("net_income")
    if oi is not None and ni is not None and ni > 0:
        quality_ratio = oi / ni
        if quality_ratio >= 0.8:
            # 経常利益が純利益の80%以上 → 特別利益に非依存
            s = min(20.0, 20.0)
        elif quality_ratio >= 0.5:
            s = max(0.0, 20.0 * (quality_ratio - 0.5) / 0.3)
        else:
            s = 0.0  # 特別利益頼み
        parts["earnings_quality"] = round(s, 1)

    score = sum(v for k, v in parts.items() if not k.startswith("_"))
    return round(min(100.0, score), 1), parts


# ════════════════════════════════════════════════════════════
# 統合スコア計算ヘルパー (全5層)
# ════════════════════════════════════════════════════════════
# 現在の重み: Value 60% + Quality 40% (Phase 1)
# Phase 2 以降の重み案:
#   Phase 2: Value 40% + Quality 30% + Momentum 30%
#   Phase 3: Value 30% + Quality 25% + Momentum 20% + Event 15% + AI 10%
SCORE_WEIGHTS = {
    "phase1": {"value": 0.6, "quality": 0.4},
    "phase2": {"value": 0.4, "quality": 0.3, "momentum": 0.3},
    "phase3": {"value": 0.30, "quality": 0.25, "momentum": 0.20, "event": 0.15, "ai": 0.10},
}
CURRENT_PHASE = "phase3"  # Phase 3: V30 + Q25 + M20 + D15 + E10 (重み自動再配分)


def calc_total_score(
    value: float, quality: float,
    momentum: float = 0.0, event: float = 0.0, ai: float = 0.0,
    phase: str | None = None,
) -> float:
    """全レイヤーの加重平均で統合スコアを計算。
    phase が None なら CURRENT_PHASE を使う。
    データなし (score=0) のレイヤーは重みを他レイヤーに再配分する。
    → 株価OFF時でもON時と近いスコアになる。
    """
    ph = phase or CURRENT_PHASE
    w = dict(SCORE_WEIGHTS.get(ph, SCORE_WEIGHTS["phase1"]))

    scores = {"value": value, "quality": quality, "momentum": momentum, "event": event, "ai": ai}

    # データありレイヤーの重みを集計
    active_weight = sum(w.get(k, 0) for k, v in scores.items() if v > 0 and w.get(k, 0) > 0)
    if active_weight <= 0:
        # 全部0ならValue/Qualityで計算
        return round(value * 0.6 + quality * 0.4, 1)

    # 重みを正規化 (データなしレイヤーの重みを再配分)
    total = sum(
        scores[k] * (w.get(k, 0) / active_weight)
        for k in scores
        if scores[k] > 0 and w.get(k, 0) > 0
    )
    return round(total, 1)


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
                   COALESCE(fc.fiscal_years, 0) AS fiscal_years,
                   f.per, f.roe, f.eps, f.bps, f.revenue, f.operating_income,
                   f.net_income, f.total_assets, f.cash, f.equity_ratio, f.dividend,
                   f.cf_operating, f.cf_investing, f.gross_profit,
                   r.fcf
            FROM companies c
            LEFT JOIN financials f ON f.edinet_code = c.edinet_code AND f.fiscal_year = ?
            LEFT JOIN ratios r ON r.edinet_code = c.edinet_code AND r.fiscal_year = ?
            LEFT JOIN (
                SELECT edinet_code, COUNT(*) AS fiscal_years
                FROM financials GROUP BY edinet_code
            ) fc ON fc.edinet_code = c.edinet_code
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
            q_score, q_parts = calc_quality_score(d)
            d["quality_score"] = q_score
            d["quality_parts"] = q_parts
            # Phase 2/3 スコア (未実装 → 0点、重みに影響しない)
            d["momentum_score"] = 0.0
            d["event_score"] = 0.0
            d["ai_score"] = 0.0
            d["total_score"] = calc_total_score(score, q_score)
        else:
            d["takehara_score"] = None
            d["score_parts"] = None
            d["quality_score"] = None
            d["quality_parts"] = None
            d["momentum_score"] = None
            d["event_score"] = None
            d["ai_score"] = None
            d["total_score"] = None
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
    quality = None
    momentum = None
    event = None
    ai_qual = None
    total_score = None
    if fins_list:
        latest = fins_list[0]
        score_input = {**latest, "fcf": latest_fcf}
        if latest.get("per") and latest.get("net_income") and latest["net_income"] > 0:
            score, parts = calc_takehara_score(score_input)
            takehara = {"score": score, "parts": parts}
            q_score, q_parts = calc_quality_score(score_input)
            quality = {"score": q_score, "parts": q_parts}
            # Momentum (CompanyDetail では株価履歴未取得のため0)
            momentum = {"score": 0.0, "parts": {"_status": "no_data"}}
            # Event / AI スコア (財務推移から算出)
            hist_asc = list(reversed(fins_list))  # 古い順に
            score_input_with_credit = {**score_input, "credit_score": company_dict.get("credit_score")}
            e_score, e_parts = calc_event_score(score_input_with_credit, hist_asc)
            event = {"score": e_score, "parts": e_parts}
            a_score, a_parts = calc_ai_qualitative_score(score_input_with_credit, hist_asc)
            ai_qual = {"score": a_score, "parts": a_parts}
            total_score = calc_total_score(score, q_score, 0.0, e_score, a_score)

    return {
        "company": company_dict,
        "financials": fins_list,
        "analysis": row_to_dict(analysis) if analysis else None,
        "takehara": takehara,
        "quality": quality,
        "momentum": momentum,
        "event": event,
        "ai_qualitative": ai_qual,
        "total_score": total_score,
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
    exclude_industries: str | None = Query(None, description="除外する業種(カンマ区切り 例: 機械,銀行業)"),
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
                f.gross_profit,
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
        if exclude_industries:
            ex_list = [s.strip() for s in exclude_industries.split(',') if s.strip()]
            if ex_list:
                placeholders = ','.join('?' * len(ex_list))
                base_query += f" AND c.industry NOT IN ({placeholders})"
                params.extend(ex_list)

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
            "score": ("f.per", "DESC"),  # スコアはPython側で再ソート（DESC=高い方が上）
            "total_score": ("f.per", "DESC"),
            "value_score": ("f.per", "DESC"),
            "quality_score": ("f.per", "DESC"),
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

        # Python側ソートが必要な場合は上限付き取得、それ以外はページネーション
        if need_python_sort:
            base_query += " LIMIT 2000"
            rows = conn.execute(base_query, params).fetchall()
        else:
            offset = (page - 1) * limit
            base_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(base_query, params).fetchall()

    # Event / AI スコア用: 各社の過去財務データを一括取得
    edinet_codes = list({row_to_dict(r).get("edinet_code") for r in rows if row_to_dict(r).get("edinet_code")})
    hist_map: dict[str, list[dict]] = {}  # edinet_code -> [{fiscal_year, dividend, ...}, ...]
    if edinet_codes:
        with get_db() as conn2:
            for ec in edinet_codes:
                hist_rows = conn2.execute(
                    """SELECT fiscal_year, dividend, payout_ratio, revenue,
                              operating_income, ordinary_income, net_income
                       FROM financials WHERE edinet_code = ? ORDER BY fiscal_year ASC""",
                    (ec,),
                ).fetchall()
                if hist_rows:
                    hist_map[ec] = [
                        {"fiscal_year": r[0], "dividend": r[1], "payout_ratio": r[2],
                         "revenue": r[3], "operating_income": r[4], "ordinary_income": r[5],
                         "net_income": r[6]}
                        for r in hist_rows
                    ]

    results = []
    for row in rows:
        d = row_to_dict(row)
        ec = d.get("edinet_code")
        # Value スコア (竹原式)
        value_score, value_parts = calc_takehara_score(d)
        d["takehara_score"] = value_score
        d["score_parts"] = value_parts
        # Quality スコア
        quality_score, quality_parts = calc_quality_score(d)
        d["quality_score"] = quality_score
        d["quality_parts"] = quality_parts
        # Momentum スコア (with_prices=true 時に再計算)
        momentum_score, momentum_parts = calc_momentum_score(d)
        d["momentum_score"] = momentum_score
        d["momentum_parts"] = momentum_parts
        # Event スコア (財務推移から算出)
        hist = hist_map.get(ec)
        event_score, event_parts = calc_event_score(d, hist)
        d["event_score"] = event_score
        d["event_parts"] = event_parts
        # AI定性スコア (信用力・安定性)
        ai_score, ai_parts = calc_ai_qualitative_score(d, hist)
        d["ai_score"] = ai_score
        d["ai_parts"] = ai_parts
        # 統合スコア (Phase 3: V30 Q25 M20 D15 E10, 重み自動再配分)
        d["total_score"] = calc_total_score(value_score, quality_score, momentum_score, event_score, ai_score)
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
            with ThreadPoolExecutor(max_workers=5) as executor:
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
            with ThreadPoolExecutor(max_workers=5) as executor:
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
                # total_score も再計算
                d["total_score"] = calc_total_score(
                    d["takehara_score"], d.get("quality_score", 0),
                    d.get("momentum_score", 0), d.get("event_score", 0), d.get("ai_score", 0),
                )

    # ── Momentum Score 算出 (with_prices=true 時のみ) ──
    if with_prices or has_price_sort:
        from concurrent.futures import ThreadPoolExecutor
        import time as _time2

        # TOPIX を1回だけ取得
        topix_hist = fetch_topix_history()

        def _fetch_hist(code_ticker):
            code, ticker = code_ticker
            try:
                hist = fetch_price_history(ticker)
                return code, hist
            except Exception:
                return code, None

        hist_map = {}
        items_h = list(tickers.items())
        for i in range(0, len(items_h), batch_size):
            batch = items_h[i:i + batch_size]
            with ThreadPoolExecutor(max_workers=5) as executor:
                for code, hist in executor.map(_fetch_hist, batch):
                    if hist:
                        hist_map[code] = hist
            if i + batch_size < len(items_h):
                _time2.sleep(0.3)

        # 各銘柄のMomentumスコアを再計算
        for d in results:
            code = d.get("securities_code")
            hist = hist_map.get(code)
            if hist and len(hist) >= 30:
                m_score, m_parts = calc_momentum_score(d, hist, topix_hist)
                d["momentum_score"] = m_score
                d["momentum_parts"] = m_parts
                # total_score 再計算
                d["total_score"] = calc_total_score(
                    d["takehara_score"], d.get("quality_score", 0),
                    m_score, d.get("event_score", 0), d.get("ai_score", 0),
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
        d["fake_growth_severity"] = len(flags)

        # 偽成長フラグでQualityScoreを減点 (1フラグ=-15点, 2以上=-30点)
        if flags:
            penalty = min(30, len(flags) * 15)
            d["quality_score"] = max(0, round(d.get("quality_score", 0) - penalty, 1))
            d["quality_parts"]["fake_growth_penalty"] = -penalty
            # total_score再計算
            d["total_score"] = calc_total_score(
                d["takehara_score"], d["quality_score"],
                d.get("momentum_score", 0), d.get("event_score", 0), d.get("ai_score", 0),
            )

    # 見せかけ成長株除外フィルタ
    if exclude_fake_growth:
        results = [d for d in results if not d["is_fake_growth"]]

    # Python側ソート (Noneは常に末尾)
    if need_python_sort:
        SORT_FIELD_MAP = {
            "score": "total_score",
            "total_score": "total_score",
            "value_score": "takehara_score",
            "quality_score": "quality_score",
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


# --------------- 認証 API ---------------

from pydantic import BaseModel
import jwt as pyjwt

_JWT_SECRET = os.environ.get("JWT_SECRET", "fallback_secret_change_me")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_DAYS = 7


def _load_users() -> dict[str, str]:
    """envから固定ユーザーを読み込む (user_id -> password)"""
    users = {}
    for i in range(1, 5):
        uid = os.environ.get(f"USER_{i}_ID")
        pw = os.environ.get(f"USER_{i}_PW")
        if uid and pw:
            users[uid] = pw
    return users


def _create_token(user_id: str) -> str:
    from datetime import datetime, timezone, timedelta
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=_JWT_EXPIRE_DAYS),
    }
    return pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _get_current_user(request: Request) -> str | None:
    """Authorizationヘッダーからユーザーを取得。無効なら None"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        payload = pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return payload.get("sub")
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


def _require_user(request: Request) -> str:
    """認証必須のエンドポイント用。未認証なら 401"""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return user


class LoginRequest(BaseModel):
    user_id: str
    password: str


@app.post("/api/auth/login")
def auth_login(req: LoginRequest) -> dict:
    import hashlib
    users = _load_users()
    if req.user_id not in users:
        raise HTTPException(status_code=401, detail="IDまたはパスワードが違います")
    pw_hash = hashlib.sha256(req.password.encode()).hexdigest()
    if users[req.user_id] != pw_hash:
        raise HTTPException(status_code=401, detail="IDまたはパスワードが違います")
    token = _create_token(req.user_id)
    return {"token": token, "user_id": req.user_id}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    user = _get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return {"user_id": user}


# --------------- デモトレード API ---------------


def _ensure_demo_trades_table():
    """demo_trades テーブルを user_id 付きで確保"""
    with get_db(readonly=False) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT DEFAULT '',
                user_id TEXT DEFAULT '',
                securities_code TEXT NOT NULL,
                company_name TEXT,
                trade_type TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                memo TEXT,
                created_at TEXT
            )
        """)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(demo_trades)").fetchall()]
        if "device_id" not in cols:
            conn.execute("ALTER TABLE demo_trades ADD COLUMN device_id TEXT DEFAULT ''")
        if "user_id" not in cols:
            conn.execute("ALTER TABLE demo_trades ADD COLUMN user_id TEXT DEFAULT ''")
        conn.commit()


# サーバー起動時にテーブルとインデックスを確保
def _ensure_indexes():
    """パフォーマンス用インデックスを追加"""
    with get_db(readonly=False) as conn:
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_financials_fiscal_year
              ON financials(fiscal_year);
            CREATE INDEX IF NOT EXISTS idx_financials_code_year
              ON financials(edinet_code, fiscal_year);
            CREATE INDEX IF NOT EXISTS idx_ratios_code_year
              ON ratios(edinet_code, fiscal_year);
            CREATE INDEX IF NOT EXISTS idx_demo_trades_device
              ON demo_trades(device_id);
            CREATE INDEX IF NOT EXISTS idx_demo_trades_user
              ON demo_trades(user_id);
            CREATE INDEX IF NOT EXISTS idx_companies_credit_score
              ON companies(credit_score DESC, company_name);
            CREATE INDEX IF NOT EXISTS idx_companies_securities_code
              ON companies(securities_code);
            CREATE INDEX IF NOT EXISTS idx_us_stocks_score
              ON us_stocks(takehara_score DESC);
            CREATE INDEX IF NOT EXISTS idx_us_stocks_sector
              ON us_stocks(sector);
        """)
        conn.commit()

def _ensure_us_stocks_table():
    """us_stocks テーブルを確保 (米国株DB化)"""
    with get_db(readonly=False) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS us_stocks (
                ticker TEXT PRIMARY KEY,
                company_name TEXT,
                sector TEXT,
                industry TEXT,
                price REAL,
                market_cap REAL,
                per REAL,
                pbr REAL,
                roe REAL,
                eps REAL,
                bps REAL,
                dividend REAL,
                dividend_yield REAL,
                revenue REAL,
                net_income REAL,
                operating_margin REAL,
                profit_margin REAL,
                gross_margins REAL,
                cash_ratio REAL,
                equity_ratio REAL,
                fcf REAL,
                revenue_growth REAL,
                earnings_growth REAL,
                total_debt REAL,
                beta REAL,
                debt_to_equity REAL,
                current_ratio REAL,
                payout_ratio REAL,
                roa REAL,
                hi52 REAL,
                lo52 REAL,
                value_score REAL,
                quality_score REAL,
                momentum_score REAL,
                dividend_score REAL,
                stability_score REAL,
                takehara_score REAL,
                target_per15 REAL,
                updated_at TEXT
            )
        """)
        conn.commit()


try:
    _ensure_demo_trades_table()
    _ensure_us_stocks_table()
    _ensure_indexes()
except Exception:
    pass  # DB未作成の場合はスキップ


class TradeRequest(BaseModel):
    securities_code: str
    company_name: str | None = None
    trade_type: str  # "buy" or "sell"
    trade_date: str  # "YYYY-MM-DD"
    price: float
    quantity: int
    memo: str | None = None


@app.get("/api/demo-trades")
def list_trades(request: Request) -> list[dict]:
    """デモトレード一覧（ユーザーごと）"""
    user_id = _require_user(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM demo_trades WHERE user_id = ? ORDER BY trade_date DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/api/demo-trades")
def create_trade(req: TradeRequest, request: Request) -> dict:
    """デモトレード登録"""
    from datetime import datetime, timezone
    user_id = _require_user(request)
    with get_db(readonly=False) as conn:
        conn.execute(
            """INSERT INTO demo_trades
               (user_id, securities_code, company_name, trade_type, trade_date, price, quantity, memo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, req.securities_code, req.company_name, req.trade_type,
             req.trade_date, req.price, req.quantity, req.memo,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return {"status": "ok"}


@app.delete("/api/demo-trades/{trade_id}")
def delete_trade(trade_id: int, request: Request) -> dict:
    """デモトレード削除（ユーザーIDチェック）"""
    user_id = _require_user(request)
    with get_db(readonly=False) as conn:
        conn.execute("DELETE FROM demo_trades WHERE id = ? AND user_id = ?", (trade_id, user_id))
        conn.commit()
    return {"status": "ok"}


@app.get("/api/demo-portfolio")
def demo_portfolio(request: Request) -> dict:
    """デモポートフォリオ（現在の保有状況と損益 - ユーザーごと）"""
    user_id = _require_user(request)
    with get_db() as conn:
        trades = conn.execute(
            "SELECT * FROM demo_trades WHERE user_id = ? ORDER BY trade_date ASC, id ASC",
            (user_id,),
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

    # 保有中の銘柄だけ株価を一括取得 (並列化)
    active_codes = {c: h for c, h in holdings.items() if h["total_qty"] > 0}
    ticker_map = {c: _sec_code_to_ticker(c) for c in active_codes}
    price_map: dict[str, dict | None] = {}
    from concurrent.futures import ThreadPoolExecutor
    valid_tickers = {c: t for c, t in ticker_map.items() if t}
    if valid_tickers:
        def _fetch_price(item):
            code, ticker = item
            return code, fetch_stock_price(ticker)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for code, pdata in ex.map(_fetch_price, valid_tickers.items()):
                price_map[code] = pdata

    # 損益計算
    result = []
    for code, h in holdings.items():
        if h["total_qty"] <= 0:
            h["avg_cost"] = 0
            h["current_price"] = None
            h["unrealized_pnl"] = 0
            h["pnl_pct"] = 0
        else:
            h["avg_cost"] = round(h["total_cost"] / h["total_qty"], 1)
            pdata = price_map.get(code)
            h["current_price"] = pdata["price"] if pdata else None
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
def get_alerts(request: Request) -> dict:
    """保有銘柄の売り時アラートを生成（ユーザーごと）"""
    from datetime import datetime, timezone
    user_id = _require_user(request)

    with get_db() as conn:
        # デモトレード保有数量を集計
        trades = conn.execute(
            "SELECT * FROM demo_trades WHERE user_id = ? ORDER BY trade_date ASC, id ASC",
            (user_id,),
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

    # 財務データを一括取得 + 株価を並列取得してアラート判定
    from concurrent.futures import ThreadPoolExecutor

    # EPS を一括で取得
    eps_map: dict[str, float] = {}
    with get_db() as conn:
        for code in active:
            fin_row = conn.execute(
                """SELECT f.eps FROM financials f
                   JOIN companies c ON c.edinet_code = f.edinet_code
                   WHERE c.securities_code = ? AND f.eps IS NOT NULL AND f.eps > 0
                   ORDER BY f.fiscal_year DESC LIMIT 1""",
                (code,),
            ).fetchone()
            if fin_row:
                eps_map[code] = fin_row[0]

    # 株価を並列取得
    codes_need_price = [c for c in eps_map if _sec_code_to_ticker(c)]
    price_map: dict[str, dict | None] = {}
    if codes_need_price:
        def _fetch(code):
            return code, fetch_stock_price(_sec_code_to_ticker(code))
        with ThreadPoolExecutor(max_workers=8) as ex:
            for code, pdata in ex.map(_fetch, codes_need_price):
                price_map[code] = pdata

    # アラート生成
    alerts = []
    for code in eps_map:
        h = active[code]
        avg_cost = round(h["total_cost"] / h["total_qty"], 1) if h["total_qty"] > 0 else 0
        eps = eps_map[code]
        target = round(eps * 15, 1)

        pdata = price_map.get(code)
        if not pdata or not pdata.get("price"):
            continue
        current_price = pdata["price"]
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

# 米国株ユニバース (S&P500 全銘柄)
US_STOCK_UNIVERSE = {
    # ── Information Technology ──
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AVGO": "Broadcom",
    "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe", "AMD": "AMD",
    "CSCO": "Cisco", "ACN": "Accenture", "INTC": "Intel", "IBM": "IBM",
    "QCOM": "Qualcomm", "TXN": "Texas Instruments", "INTU": "Intuit",
    "AMAT": "Applied Materials", "NOW": "ServiceNow", "PANW": "Palo Alto Networks",
    "MU": "Micron", "LRCX": "Lam Research", "KLAC": "KLA Corp",
    "SNPS": "Synopsys", "CDNS": "Cadence Design", "ADI": "Analog Devices",
    "CRWD": "CrowdStrike", "FTNT": "Fortinet", "MRVL": "Marvell Technology",
    "MSI": "Motorola Solutions", "NXPI": "NXP Semiconductors", "ON": "ON Semiconductor",
    "MPWR": "Monolithic Power", "KEYS": "Keysight Technologies",
    "HPQ": "HP Inc", "HPE": "Hewlett Packard Enterprise",
    "CTSH": "Cognizant", "IT": "Gartner", "ANSS": "Ansys",
    "CDW": "CDW", "ZBRA": "Zebra Technologies", "GLW": "Corning",
    "TYL": "Tyler Technologies", "TRMB": "Trimble",
    "PTC": "PTC", "FSLR": "First Solar", "ENPH": "Enphase Energy",
    "EPAM": "EPAM Systems", "VRSN": "VeriSign", "SWKS": "Skyworks Solutions",
    "TER": "Teradyne", "AKAM": "Akamai Technologies", "JNPR": "Juniper Networks",
    "FFIV": "F5", "GEN": "Gen Digital", "NTAP": "NetApp",
    "WDC": "Western Digital", "STX": "Seagate Technology",
    "QRVO": "Qorvo", "SEDG": "SolarEdge Technologies",
    # ── Communication Services ──
    "GOOGL": "Alphabet (A)", "GOOG": "Alphabet (C)", "META": "Meta Platforms",
    "NFLX": "Netflix", "DIS": "Disney", "CMCSA": "Comcast",
    "T": "AT&T", "VZ": "Verizon", "TMUS": "T-Mobile US",
    "CHTR": "Charter Communications", "EA": "Electronic Arts",
    "TTWO": "Take-Two Interactive", "WBD": "Warner Bros Discovery",
    "OMC": "Omnicom Group", "IPG": "Interpublic Group",
    "LYV": "Live Nation", "MTCH": "Match Group",
    "NWSA": "News Corp (A)", "NWS": "News Corp (B)", "PARA": "Paramount Global",
    "FOXA": "Fox Corp (A)", "FOX": "Fox Corp (B)",
    # ── Consumer Discretionary ──
    "AMZN": "Amazon", "TSLA": "Tesla", "HD": "Home Depot",
    "MCD": "McDonald's", "NKE": "Nike", "LOW": "Lowe's",
    "SBUX": "Starbucks", "TJX": "TJX Companies", "BKNG": "Booking Holdings",
    "ABNB": "Airbnb", "ORLY": "O'Reilly Automotive", "AZO": "AutoZone",
    "MAR": "Marriott International", "GM": "General Motors",
    "F": "Ford Motor", "ROST": "Ross Stores", "CMG": "Chipotle Mexican Grill",
    "HLT": "Hilton Worldwide", "DHI": "D.R. Horton", "LEN": "Lennar",
    "YUM": "Yum! Brands", "DKNG": "DraftKings", "EXPE": "Expedia Group",
    "EBAY": "eBay", "ULTA": "Ulta Beauty", "GPC": "Genuine Parts",
    "POOL": "Pool Corp", "PHM": "PulteGroup", "NVR": "NVR",
    "DPZ": "Domino's Pizza", "APTV": "Aptiv", "BWA": "BorgWarner",
    "CZR": "Caesars Entertainment", "MGM": "MGM Resorts",
    "BBY": "Best Buy", "GRMN": "Garmin", "TSCO": "Tractor Supply",
    "DRI": "Darden Restaurants", "LKQ": "LKQ Corp",
    "CCL": "Carnival Corp", "RCL": "Royal Caribbean",
    "WYNN": "Wynn Resorts", "LVS": "Las Vegas Sands",
    "TPR": "Tapestry", "RL": "Ralph Lauren", "HAS": "Hasbro",
    "MHK": "Mohawk Industries", "WHR": "Whirlpool",
    "NCLH": "Norwegian Cruise Line",
    # ── Consumer Staples ──
    "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "COST": "Costco", "WMT": "Walmart", "PM": "Philip Morris",
    "MO": "Altria", "MDLZ": "Mondelez", "CL": "Colgate-Palmolive",
    "KMB": "Kimberly-Clark", "GIS": "General Mills", "HSY": "Hershey",
    "SYY": "Sysco", "ADM": "Archer-Daniels-Midland",
    "STZ": "Constellation Brands", "KHC": "Kraft Heinz",
    "KR": "Kroger", "WBA": "Walgreens Boots Alliance",
    "EL": "Estee Lauder", "MNST": "Monster Beverage",
    "MKC": "McCormick", "K": "Kellanova", "CHD": "Church & Dwight",
    "SJM": "J.M. Smucker", "TSN": "Tyson Foods", "TAP": "Molson Coors",
    "CAG": "Conagra Brands", "BG": "Bunge", "HRL": "Hormel Foods",
    "CPB": "Campbell Soup", "CLX": "Clorox", "LW": "Lamb Weston",
    "BF-B": "Brown-Forman",
    # ── Health Care ──
    "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly",
    "ABBV": "AbbVie", "MRK": "Merck", "PFE": "Pfizer",
    "TMO": "Thermo Fisher", "ABT": "Abbott Laboratories", "DHR": "Danaher",
    "BMY": "Bristol-Myers Squibb", "AMGN": "Amgen", "GILD": "Gilead Sciences",
    "MDT": "Medtronic", "ELV": "Elevance Health", "ISRG": "Intuitive Surgical",
    "CVS": "CVS Health", "CI": "Cigna Group", "VRTX": "Vertex Pharmaceuticals",
    "SYK": "Stryker", "BSX": "Boston Scientific", "REGN": "Regeneron",
    "ZTS": "Zoetis", "HCA": "HCA Healthcare", "BDX": "Becton Dickinson",
    "MCK": "McKesson", "EW": "Edwards Lifesciences", "IDXX": "IDEXX Laboratories",
    "A": "Agilent Technologies", "IQV": "IQVIA", "RMD": "ResMed",
    "MTD": "Mettler-Toledo", "DXCM": "DexCom", "BAX": "Baxter International",
    "GEHC": "GE HealthCare", "BIIB": "Biogen", "MOH": "Molina Healthcare",
    "CNC": "Centene", "HUM": "Humana", "HOLX": "Hologic",
    "ALGN": "Align Technology", "PODD": "Insulet",
    "TECH": "Bio-Techne", "INCY": "Incyte",
    "VTRS": "Viatris", "CRL": "Charles River Laboratories",
    "DGX": "Quest Diagnostics", "LH": "Labcorp",
    "HSIC": "Henry Schein", "XRAY": "Dentsply Sirona",
    "OGN": "Organon", "DVA": "DaVita",
    # ── Financials ──
    "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan Chase", "V": "Visa",
    "MA": "Mastercard", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "GS": "Goldman Sachs", "MS": "Morgan Stanley", "AXP": "American Express",
    "BLK": "BlackRock", "SCHW": "Charles Schwab", "C": "Citigroup",
    "USB": "U.S. Bancorp", "PNC": "PNC Financial", "TFC": "Truist Financial",
    "AIG": "AIG", "MET": "MetLife", "PRU": "Prudential Financial",
    "ICE": "Intercontinental Exchange", "CME": "CME Group",
    "SPGI": "S&P Global", "MCO": "Moody's", "MMC": "Marsh & McLennan",
    "AON": "Aon", "CB": "Chubb", "AFL": "Aflac",
    "AJG": "Arthur J. Gallagher", "TRV": "Travelers",
    "ALL": "Allstate", "PGR": "Progressive", "MSCI": "MSCI",
    "FIS": "Fidelity National Info", "FITB": "Fifth Third Bancorp",
    "MTB": "M&T Bank", "HBAN": "Huntington Bancshares",
    "CFG": "Citizens Financial", "RF": "Regions Financial",
    "KEY": "KeyCorp", "NTRS": "Northern Trust",
    "STT": "State Street", "BK": "Bank of New York Mellon",
    "CINF": "Cincinnati Financial", "RE": "Everest Group",
    "L": "Loews", "TROW": "T. Rowe Price", "IVZ": "Invesco",
    "BEN": "Franklin Resources", "RJF": "Raymond James",
    "NDAQ": "Nasdaq", "CBOE": "Cboe Global Markets",
    "FRC": "First Republic Bank", "SIVB": "SVB Financial",
    "WRB": "W. R. Berkley", "GL": "Globe Life",
    "MKTX": "MarketAxess", "ZION": "Zions Bancorp",
    "CMA": "Comerica", "DFS": "Discover Financial",
    "SYF": "Synchrony Financial", "COF": "Capital One",
    "PYPL": "PayPal",
    # ── Industrials ──
    "CAT": "Caterpillar", "GE": "GE Aerospace", "HON": "Honeywell",
    "UNP": "Union Pacific", "RTX": "RTX Corp", "BA": "Boeing",
    "DE": "Deere & Co", "LMT": "Lockheed Martin", "UPS": "UPS",
    "ETN": "Eaton Corp", "ITW": "Illinois Tool Works",
    "EMR": "Emerson Electric", "GD": "General Dynamics",
    "NOC": "Northrop Grumman", "WM": "Waste Management",
    "CSX": "CSX", "NSC": "Norfolk Southern",
    "FDX": "FedEx", "MMM": "3M", "JCI": "Johnson Controls",
    "TT": "Trane Technologies", "PCAR": "PACCAR",
    "PH": "Parker-Hannifin", "CARR": "Carrier Global",
    "OTIS": "Otis Worldwide", "AME": "AMETEK",
    "RSG": "Republic Services", "CTAS": "Cintas",
    "FAST": "Fastenal", "VRSK": "Verisk Analytics",
    "PWR": "Quanta Services", "IR": "Ingersoll Rand",
    "XYL": "Xylem", "DOV": "Dover",
    "WAB": "Westinghouse Air Brake", "GWW": "W.W. Grainger",
    "ROK": "Rockwell Automation", "SWK": "Stanley Black & Decker",
    "HWM": "Howmet Aerospace", "IEX": "IDEX",
    "TDG": "TransDigm", "AXON": "Axon Enterprise",
    "HII": "Huntington Ingalls", "LHX": "L3Harris Technologies",
    "LDOS": "Leidos", "J": "Jacobs Solutions",
    "URI": "United Rentals", "RHI": "Robert Half",
    "MAS": "Masco", "AOS": "A.O. Smith",
    "NDSN": "Nordson", "DAL": "Delta Air Lines",
    "UAL": "United Airlines", "LUV": "Southwest Airlines",
    "AAL": "American Airlines", "PAYC": "Paycom",
    "PAYX": "Paychex", "EXPD": "Expeditors International",
    "CHRW": "C.H. Robinson", "CPRT": "Copart",
    "EFX": "Equifax", "BR": "Broadridge Financial",
    "JBHT": "J.B. Hunt Transport",
    # ── Energy ──
    "XOM": "Exxon Mobil", "CVX": "Chevron", "COP": "ConocoPhillips",
    "SLB": "Schlumberger", "EOG": "EOG Resources",
    "PSX": "Phillips 66", "VLO": "Valero Energy",
    "MPC": "Marathon Petroleum", "PXD": "Pioneer Natural Resources",
    "OXY": "Occidental Petroleum", "WMB": "Williams Companies",
    "KMI": "Kinder Morgan", "HAL": "Halliburton",
    "DVN": "Devon Energy", "FANG": "Diamondback Energy",
    "HES": "Hess", "BKR": "Baker Hughes",
    "OKE": "ONEOK", "CTRA": "Coterra Energy",
    "TRGP": "Targa Resources", "EQT": "EQT Corp",
    "APA": "APA Corp",
    # ── Materials ──
    "LIN": "Linde", "APD": "Air Products", "SHW": "Sherwin-Williams",
    "FCX": "Freeport-McMoRan", "NEM": "Newmont", "DOW": "Dow Inc",
    "ECL": "Ecolab", "DD": "DuPont", "NUE": "Nucor",
    "VMC": "Vulcan Materials", "MLM": "Martin Marietta",
    "PPG": "PPG Industries", "CE": "Celanese",
    "EMN": "Eastman Chemical", "ALB": "Albemarle",
    "CF": "CF Industries", "MOS": "Mosaic",
    "IFF": "International Flavors & Fragrances",
    "PKG": "Packaging Corp of America", "IP": "International Paper",
    "SEE": "Sealed Air", "AVY": "Avery Dennison",
    "BALL": "Ball Corp", "STLD": "Steel Dynamics",
    "AMCR": "Amcor",
    # ── Utilities ──
    "NEE": "NextEra Energy", "SO": "Southern Co", "DUK": "Duke Energy",
    "D": "Dominion Energy", "AEP": "American Electric Power",
    "EXC": "Exelon", "SRE": "Sempra Energy",
    "XEL": "Xcel Energy", "ED": "Consolidated Edison",
    "WEC": "WEC Energy Group", "ES": "Eversource Energy",
    "AWK": "American Water Works", "DTE": "DTE Energy",
    "PPL": "PPL Corp", "FE": "FirstEnergy",
    "AEE": "Ameren", "CMS": "CMS Energy",
    "CNP": "CenterPoint Energy", "ATO": "Atmos Energy",
    "EVRG": "Evergy", "ETR": "Entergy",
    "PEG": "Public Service Enterprise", "PNW": "Pinnacle West",
    "NI": "NiSource", "LNT": "Alliant Energy",
    "NRG": "NRG Energy",
    # ── Real Estate ──
    "AMT": "American Tower", "PLD": "Prologis",
    "CCI": "Crown Castle", "SPG": "Simon Property Group",
    "O": "Realty Income", "PSA": "Public Storage",
    "EQIX": "Equinix", "WELL": "Welltower",
    "DLR": "Digital Realty", "VICI": "VICI Properties",
    "AVB": "AvalonBay Communities", "EQR": "Equity Residential",
    "SBAC": "SBA Communications", "ARE": "Alexandria Real Estate",
    "WY": "Weyerhaeuser", "MAA": "Mid-America Apartment",
    "ESS": "Essex Property Trust", "INVH": "Invitation Homes",
    "VTR": "Ventas", "HST": "Host Hotels & Resorts",
    "REG": "Regency Centers", "KIM": "Kimco Realty",
    "CPT": "Camden Property", "UDR": "UDR",
    "BXP": "BXP", "PEAK": "Healthpeak Properties",
    "FRT": "Federal Realty",
}


def _fetch_us_stock_info_raw(ticker: str) -> dict | None:
    """yfinance で米国株の財務情報を取得"""
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
        gross_margins = info.get("grossMargins")
        total_cash = info.get("totalCash")
        total_assets = info.get("totalAssets") if info.get("totalAssets") else None
        total_debt = info.get("totalDebt")
        free_cash_flow = info.get("freeCashflow")
        revenue_growth = info.get("revenueGrowth")
        earnings_growth = info.get("earningsGrowth")
        sector = info.get("sector", "")
        industry = info.get("industry", "")
        # 追加: 5層スコアに必要なフィールド
        beta = info.get("beta")
        debt_to_equity = info.get("debtToEquity")  # percentage (e.g. 120 = 120%)
        current_ratio = info.get("currentRatio")
        payout_ratio = info.get("payoutRatio")
        roa = info.get("returnOnAssets")
        hi52 = info.get("fiftyTwoWeekHigh")
        lo52 = info.get("fiftyTwoWeekLow")

        # 現金比率を推定
        cash_ratio = None
        if total_cash and total_assets:
            cash_ratio = total_cash / total_assets
        elif total_cash and market_cap:
            estimated_assets = market_cap + (total_debt or 0)
            if estimated_assets > 0:
                cash_ratio = total_cash / estimated_assets

        # equity_ratio (自己資本比率) 推定
        equity_ratio = None
        shares = info.get("sharesOutstanding")
        if bps and shares and total_assets:
            equity = bps * shares
            equity_ratio = equity / total_assets
        elif debt_to_equity is not None and debt_to_equity > 0:
            equity_ratio = 1.0 / (1.0 + debt_to_equity / 100.0)

        def _r(v, d=2):
            return round(float(v), d) if v is not None else None

        data = {
            "ticker": ticker,
            "company_name": US_STOCK_UNIVERSE.get(ticker, info.get("shortName", ticker)),
            "sector": sector,
            "industry": industry,
            "price": _r(price),
            "market_cap": market_cap,
            "per": _r(per),
            "pbr": _r(pbr),
            "roe": _r(roe, 4),
            "eps": _r(eps),
            "bps": _r(bps),
            "dividend": _r(dividend),
            "dividend_yield": _r(dividend_yield, 4),
            "revenue": revenue,
            "net_income": net_income,
            "operating_margin": _r(operating_margin, 4),
            "profit_margin": _r(profit_margin, 4),
            "gross_margins": _r(gross_margins, 4),
            "cash_ratio": _r(cash_ratio, 4),
            "equity_ratio": _r(equity_ratio, 4),
            "fcf": free_cash_flow,
            "revenue_growth": _r(revenue_growth, 4),
            "earnings_growth": _r(earnings_growth, 4),
            "total_debt": total_debt,
            "beta": _r(beta),
            "debt_to_equity": _r(debt_to_equity),
            "current_ratio": _r(current_ratio),
            "payout_ratio": _r(payout_ratio, 4),
            "roa": _r(roa, 4),
            "hi52": _r(hi52),
            "lo52": _r(lo52),
        }

        return data
    except Exception as e:
        print(f"[WARN] US stock {ticker}: {e}")
        return None


# ── 米国株 5層スコアリング ──

def _us_value_score(d: dict) -> tuple[float, dict]:
    """A層: Value (割安度) 0-100点
    PER(25) + PBR(20) + ROE(20) + OPM(15) + Cash/FCF(20)
    """
    s = 0.0
    parts = {}
    per = d.get("per")
    if per and per > 0:
        v = max(0, min(25, 25 * (1 - (per - 5) / 35)))
        s += v; parts["per"] = round(v, 1)
    pbr = d.get("pbr")
    if pbr is not None and pbr > 0:
        v = max(0, min(20, 20 * (1 - (pbr - 0.3) / 4.7)))
        s += v; parts["pbr"] = round(v, 1)
    roe = d.get("roe")
    if roe and roe > 0:
        v = max(0, min(20, 20 * min(1, roe / 0.15)))
        s += v; parts["roe"] = round(v, 1)
    om = d.get("operating_margin")
    if om and om > 0:
        v = max(0, min(15, 15 * min(1, om / 0.15)))
        s += v; parts["opm"] = round(v, 1)
    cr = d.get("cash_ratio")
    fcf = d.get("fcf")
    cash_v = 0.0
    if cr and cr > 0:
        cash_v += max(0, min(10, 10 * min(1, cr / 0.3)))
    if fcf and fcf > 0:
        cash_v += 10
    parts["cash_fcf"] = round(cash_v, 1)
    s += cash_v
    return round(min(100, s), 1), parts


def _us_quality_score(d: dict) -> tuple[float, dict]:
    """B層: Quality (ビジネスの質) 0-100点
    粗利率(25) + 営業利益率(25) + ROE(25) + FCF/Revenue(25)
    """
    s = 0.0
    parts = {}
    gm = d.get("gross_margins")
    if gm and gm > 0:
        v = max(0, min(25, 25 * min(1, gm / 0.50)))
        s += v; parts["gross_margin"] = round(v, 1)
    om = d.get("operating_margin")
    if om and om > 0:
        v = max(0, min(25, 25 * min(1, om / 0.20)))
        s += v; parts["opm"] = round(v, 1)
    roe = d.get("roe")
    if roe and roe > 0:
        v = max(0, min(25, 25 * min(1, roe / 0.20)))
        s += v; parts["roe"] = round(v, 1)
    fcf = d.get("fcf")
    rev = d.get("revenue")
    if fcf and rev and rev > 0:
        fcf_ratio = fcf / rev
        v = max(0, min(25, 25 * min(1, fcf_ratio / 0.15)))
        s += v; parts["fcf_rev"] = round(v, 1)
    return round(min(100, s), 1), parts


def _us_momentum_score(d: dict) -> tuple[float, dict]:
    """C層: Growth/Momentum (成長性) 0-100点
    売上成長(30) + 利益成長(30) + 52週高値近接度(25) + ROA(15)
    """
    s = 0.0
    parts = {}
    rg = d.get("revenue_growth")
    if rg is not None:
        v = max(0, min(30, 30 * min(1, (rg + 0.05) / 0.30)))
        s += v; parts["rev_growth"] = round(v, 1)
    eg = d.get("earnings_growth")
    if eg is not None:
        v = max(0, min(30, 30 * min(1, (eg + 0.05) / 0.40)))
        s += v; parts["earn_growth"] = round(v, 1)
    price = d.get("price")
    hi52 = d.get("hi52")
    lo52 = d.get("lo52")
    if price and hi52 and lo52 and hi52 > lo52:
        proximity = (price - lo52) / (hi52 - lo52)
        v = max(0, min(25, 25 * proximity))
        s += v; parts["hi52_prox"] = round(v, 1)
    roa = d.get("roa")
    if roa and roa > 0:
        v = max(0, min(15, 15 * min(1, roa / 0.10)))
        s += v; parts["roa"] = round(v, 1)
    return round(min(100, s), 1), parts


def _us_dividend_score(d: dict) -> tuple[float, dict]:
    """D層: Dividend/Event (配当・還元) 0-100点
    配当利回り(35) + 配当性向健全度(35) + FCF正(30)
    """
    s = 0.0
    parts = {}
    dy = d.get("dividend_yield")
    if dy and dy > 0:
        v = max(0, min(35, 35 * min(1, dy / 0.04)))
        s += v; parts["div_yield"] = round(v, 1)
    pr = d.get("payout_ratio")
    if pr is not None:
        if 0.15 <= pr <= 0.60:
            v = 35.0
        elif pr <= 0:
            v = 0.0
        elif pr < 0.15:
            v = max(0, 35 * pr / 0.15)
        elif pr <= 0.85:
            v = max(0, 35 * (1 - (pr - 0.60) / 0.25))
        else:
            v = 0.0
        s += v; parts["payout"] = round(v, 1)
    fcf = d.get("fcf")
    if fcf and fcf > 0:
        s += 30; parts["fcf_pos"] = 30.0
    return round(min(100, s), 1), parts


def _us_stability_score(d: dict) -> tuple[float, dict]:
    """E層: Stability (安定性) 0-100点
    Beta(30) + D/E Ratio(35) + Current Ratio(35)
    """
    s = 0.0
    parts = {}
    beta = d.get("beta")
    if beta is not None:
        v = max(0, min(30, 30 * (1 - max(0, beta - 0.5) / 1.5)))
        s += v; parts["beta"] = round(v, 1)
    de = d.get("debt_to_equity")
    if de is not None and de >= 0:
        v = max(0, min(35, 35 * (1 - min(1, de / 200))))
        s += v; parts["de_ratio"] = round(v, 1)
    cr = d.get("current_ratio")
    if cr is not None and cr > 0:
        v = max(0, min(35, 35 * min(1, cr / 2.0)))
        s += v; parts["current"] = round(v, 1)
    return round(min(100, s), 1), parts


# 米国株5層 重み (日本株Phase3に対応)
US_SCORE_WEIGHTS = {"value": 0.30, "quality": 0.25, "momentum": 0.20, "dividend": 0.15, "stability": 0.10}


def _calc_us_total_score(
    value: float, quality: float, momentum: float, dividend: float, stability: float,
) -> float:
    """5層の加重平均 (欠損層は重み再配分)"""
    layers = {"value": value, "quality": quality, "momentum": momentum, "dividend": dividend, "stability": stability}
    active = {k: v for k, v in layers.items() if v > 0}
    if not active:
        return 0.0
    w = {k: US_SCORE_WEIGHTS[k] for k in active}
    total_w = sum(w.values())
    if total_w <= 0:
        return 0.0
    return round(sum(layers[k] * w[k] / total_w for k in active), 1)


# ── 米国株 バックグラウンドDB更新 ──

_us_update_running = False
_us_last_updated: str | None = None


def _upsert_us_stock(d: dict):
    """us_stocks テーブルに UPSERT"""
    cols = [
        "ticker", "company_name", "sector", "industry", "price", "market_cap",
        "per", "pbr", "roe", "eps", "bps", "dividend", "dividend_yield",
        "revenue", "net_income", "operating_margin", "profit_margin",
        "gross_margins", "cash_ratio", "equity_ratio", "fcf",
        "revenue_growth", "earnings_growth", "total_debt", "beta",
        "debt_to_equity", "current_ratio", "payout_ratio", "roa",
        "hi52", "lo52", "value_score", "quality_score", "momentum_score",
        "dividend_score", "stability_score", "takehara_score", "target_per15",
        "updated_at",
    ]
    vals = [d.get(c) for c in cols]
    placeholders = ",".join(["?"] * len(cols))
    update_set = ",".join(f"{c}=excluded.{c}" for c in cols if c != "ticker")
    with get_db(readonly=False) as conn:
        conn.execute(
            f"INSERT INTO us_stocks ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(ticker) DO UPDATE SET {update_set}",
            vals,
        )
        conn.commit()


def _update_us_stocks_batch():
    """バックグラウンドで全米国株データを更新"""
    global _us_update_running, _us_last_updated
    if _us_update_running:
        return
    _us_update_running = True
    try:
        tickers = list(US_STOCK_UNIVERSE.keys())
        batch_size = 5
        updated = 0
        consecutive_fails = 0
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            for ticker in batch:
                try:
                    data = _fetch_us_stock_info_raw(ticker)
                    if data and data.get("price"):
                        v_score, v_parts = _us_value_score(data)
                        q_score, q_parts = _us_quality_score(data)
                        m_score, m_parts = _us_momentum_score(data)
                        dv_score, dv_parts = _us_dividend_score(data)
                        st_score, st_parts = _us_stability_score(data)
                        total = _calc_us_total_score(v_score, q_score, m_score, dv_score, st_score)
                        targets = calc_target_prices(data.get("eps"), data.get("bps"))
                        data["value_score"] = round(v_score, 1)
                        data["quality_score"] = round(q_score, 1)
                        data["momentum_score"] = round(m_score, 1)
                        data["dividend_score"] = round(dv_score, 1)
                        data["stability_score"] = round(st_score, 1)
                        data["takehara_score"] = round(total, 1)
                        data["target_per15"] = targets.get("target_per15")
                        data["updated_at"] = datetime.now(timezone.utc).isoformat()
                        _upsert_us_stock(data)
                        updated += 1
                        consecutive_fails = 0
                    else:
                        consecutive_fails += 1
                except Exception as e:
                    print(f"[US-BG] {ticker}: {e}")
                    consecutive_fails += 1
                # Rate limit backoff
                if consecutive_fails > 10:
                    from time import sleep
                    print(f"[US-BG] Too many fails, sleeping 30s...")
                    sleep(30)
                    consecutive_fails = 0
            if i + batch_size < len(tickers):
                from time import sleep
                sleep(5)
        _us_last_updated = datetime.now(timezone.utc).isoformat()
        print(f"[US-BG] Updated {updated}/{len(tickers)} tickers at {_us_last_updated}")
    except Exception as e:
        print(f"[US-BG] Update failed: {e}")
    finally:
        _us_update_running = False


def _us_bg_scheduler():
    """6時間ごとに米国株データを更新するスケジューラ"""
    from time import sleep
    while True:
        try:
            _update_us_stocks_batch()
        except Exception as e:
            print(f"[US-BG] Scheduler error: {e}")
        sleep(6 * 3600)


# バックグラウンド更新スレッドを起動
_us_bg_thread = threading.Thread(target=_us_bg_scheduler, daemon=True, name="us-stock-updater")
_us_bg_thread.start()


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
    page: int = Query(1),
    limit: int = Query(100),
    tickers: str | None = Query(None),
) -> dict:
    """米国株スクリーニング (DB読み取り)"""
    with get_db() as conn:
        conditions = []
        params: list = []
        if per_max is not None:
            conditions.append("per IS NOT NULL AND per <= ?")
            params.append(per_max)
        if pbr_max is not None:
            conditions.append("pbr IS NOT NULL AND pbr <= ?")
            params.append(pbr_max)
        if roe_min is not None:
            conditions.append("roe IS NOT NULL AND roe >= ?")
            params.append(roe_min)
        if operating_margin_min is not None:
            conditions.append("operating_margin IS NOT NULL AND operating_margin >= ?")
            params.append(operating_margin_min)
        if fcf_positive:
            conditions.append("fcf IS NOT NULL AND fcf > 0")
        if dividend_min is not None:
            conditions.append("dividend IS NOT NULL AND dividend >= ?")
            params.append(dividend_min)
        if sector:
            conditions.append("sector = ?")
            params.append(sector)
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            placeholders = ",".join(["?"] * len(ticker_list))
            conditions.append(f"ticker IN ({placeholders})")
            params.extend(ticker_list)
        where = " AND ".join(conditions) if conditions else "1=1"
        base_where = f"price IS NOT NULL AND {where}"

        total = conn.execute(f"SELECT COUNT(*) FROM us_stocks WHERE {base_where}", params).fetchone()[0]

        sort_map = {
            "score": "takehara_score", "value_score": "value_score",
            "quality_score": "quality_score", "momentum_score": "momentum_score",
            "dividend_score": "dividend_score", "stability_score": "stability_score",
            "per": "per", "pbr": "pbr", "roe": "roe",
            "operating_margin": "operating_margin", "dividend": "dividend",
            "company_name": "company_name", "market_cap": "market_cap",
        }
        col = sort_map.get(sort_by, "takehara_score")
        desc_keys = {"score", "value_score", "quality_score", "momentum_score",
                     "dividend_score", "stability_score", "roe", "operating_margin",
                     "dividend", "market_cap"}
        desc = (sort_by in desc_keys) if sort_dir == "" else (sort_dir.lower() == "desc")
        order = "DESC" if desc else "ASC"
        offset = (page - 1) * limit

        rows = conn.execute(
            f"SELECT * FROM us_stocks WHERE {base_where} ORDER BY {col} {order} NULLS LAST LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        sectors_rows = conn.execute(
            "SELECT DISTINCT sector FROM us_stocks WHERE sector IS NOT NULL AND sector != '' ORDER BY sector"
        ).fetchall()
        universe_count = conn.execute("SELECT COUNT(*) FROM us_stocks").fetchone()[0]

    results = [dict(r) for r in rows]
    return {
        "total": total,
        "universe_size": universe_count or len(US_STOCK_UNIVERSE),
        "page": page,
        "limit": limit,
        "pages": max(1, -(-total // limit)),
        "sectors": [r[0] for r in sectors_rows],
        "updated_at": _us_last_updated,
        "updating": _us_update_running,
        "results": results,
    }


@app.get("/api/us-sectors")
def us_sectors() -> list[str]:
    """米国株セクター一覧 (DB読み取り)"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT sector FROM us_stocks WHERE sector IS NOT NULL AND sector != '' ORDER BY sector"
        ).fetchall()
    return [r[0] for r in rows]


@app.get("/api/us-screener/status")
def us_screener_status() -> dict:
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM us_stocks WHERE price IS NOT NULL").fetchone()[0]
        newest = conn.execute("SELECT MAX(updated_at) FROM us_stocks").fetchone()[0]
    return {
        "count": count,
        "universe_size": len(US_STOCK_UNIVERSE),
        "updating": _us_update_running,
        "last_updated": _us_last_updated,
        "newest_record": newest,
    }


# =====================================================================
# マーケットレジーム・ダッシュボード
# =====================================================================

# --------------- レジームテーブル作成 ---------------

def _ensure_regime_tables():
    with get_db(readonly=False) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS macro_indicators (
            date TEXT NOT NULL, indicator TEXT NOT NULL, value REAL,
            PRIMARY KEY (date, indicator))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS market_regimes (
            date TEXT PRIMARY KEY, regime TEXT NOT NULL, sub_regime TEXT,
            vix_level REAL, yield_spread REAL, sp500_trend TEXT,
            confidence REAL, details TEXT, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS strategy_models (
            strategy_id TEXT PRIMARY KEY, name_ja TEXT NOT NULL,
            description_ja TEXT, allocation TEXT, stock_criteria TEXT,
            preferred_regimes TEXT, avoid_regimes TEXT, rebalance_frequency TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS backtest_results (
            strategy_id TEXT NOT NULL, date TEXT NOT NULL, regime TEXT,
            monthly_return REAL, cumulative_return REAL,
            sp500_return REAL, sp500_cumulative REAL, drawdown REAL,
            allocation_snapshot TEXT, PRIMARY KEY (strategy_id, date))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_macro_date ON macro_indicators(date DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_macro_ind ON macro_indicators(indicator, date DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_regimes_date ON market_regimes(date DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_strat ON backtest_results(strategy_id, date)")
        conn.commit()
        # Seed strategies
        _seed_strategy_models(conn)


def _seed_strategy_models(conn):
    strategies = [
        ("all_weather", "ブリッジウォーター全天候型",
         "レイ・ダリオの全天候型ポートフォリオ。あらゆる経済環境に対応するリスクパリティ戦略。",
         json.dumps({"stocks": 30, "bonds_long": 40, "bonds_mid": 15, "gold": 7.5, "commodities": 7.5}),
         None,
         json.dumps(["trend_up", "trend_down", "range_bound", "inflation", "risk_off"]),
         json.dumps([]), "quarterly"),
        ("buffett_value", "バフェット・バリュー",
         "高ROE・低PER・安定キャッシュフローの優良企業を割安時に取得し長期保有。",
         json.dumps({"stocks": 100}),
         json.dumps({"roe_min": 0.15, "per_max": 25, "operating_margin_min": 0.10,
                      "fcf_positive": True, "sort_by": "value_score", "limit": 15}),
         json.dumps(["trend_down", "range_bound"]),
         json.dumps(["risk_off"]), "quarterly"),
        ("ark_growth", "ARK グロース",
         "破壊的イノベーション企業（AI、ロボティクス、ゲノム等）に集中投資。高成長・高ボラティリティ。",
         json.dumps({"stocks": 100}),
         json.dumps({"revenue_growth_min": 0.15,
                      "sector_prefer": ["Technology", "Communication Services", "Healthcare"],
                      "sort_by": "momentum_score", "limit": 15}),
         json.dumps(["trend_up"]),
         json.dumps(["trend_down", "risk_off"]), "monthly"),
        ("soros_macro", "ソロス・マクロ",
         "地政学リスク・金融政策を分析し局面に応じて資産配分を大胆に変更。",
         json.dumps({"stocks": 40, "gold": 20, "bonds_long": 20, "cash": 20}),
         json.dumps({"sort_by": "takehara_score", "limit": 10}),
         json.dumps(["risk_off", "inflation"]),
         json.dumps([]), "monthly"),
        ("trend_following", "トレンドフォロー",
         "移動平均線クロスオーバーに基づくトレンド追従。200SMA上の資産のみ保有。",
         json.dumps({"stocks": 100}),
         json.dumps({"sort_by": "momentum_score", "limit": 20}),
         json.dumps(["trend_up"]),
         json.dumps(["range_bound"]), "monthly"),
    ]
    for s in strategies:
        conn.execute(
            "INSERT OR IGNORE INTO strategy_models "
            "(strategy_id,name_ja,description_ja,allocation,stock_criteria,"
            "preferred_regimes,avoid_regimes,rebalance_frequency) VALUES (?,?,?,?,?,?,?,?)", s)
    conn.commit()


try:
    _ensure_regime_tables()
except Exception:
    pass


# --------------- マクロ指標取得 ---------------

MACRO_TICKERS: dict[str, str] = {
    "vix": "^VIX", "tnx": "^TNX", "fvx": "^FVX", "irx": "^IRX",
    "gold": "GC=F", "oil": "CL=F", "usd_index": "DX-Y.NYB", "sp500": "^GSPC",
    "xlk": "XLK", "xlf": "XLF", "xle": "XLE", "xli": "XLI",
    "xly": "XLY", "xlp": "XLP", "xlre": "XLRE", "xlb": "XLB",
    "xlu": "XLU", "xlv": "XLV",
}

FRED_SERIES: dict[str, str] = {
    "cpi": "CPIAUCSL", "unrate": "UNRATE", "fedfunds": "FEDFUNDS",
    "yield_spread_fred": "T10Y2Y", "hy_spread": "BAMLH0A0HYM2",
}


def _fetch_macro_history_yf(key: str, period: str = "5y") -> list[dict]:
    import yfinance as yf
    ticker = MACRO_TICKERS.get(key)
    if not ticker:
        return []
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d")
        if hist.empty:
            return []
        result = []
        for idx, row in hist.iterrows():
            result.append({"date": idx.strftime("%Y-%m-%d"), "value": round(float(row["Close"]), 4)})
        return result
    except Exception as e:
        print(f"[REGIME-BG] yfinance {key}: {e}")
        return []


def _fetch_fred_series(series_id: str, limit: int = 500) -> list[dict]:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return []
    try:
        import httpx
        resp = httpx.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series_id, "api_key": api_key,
                    "file_type": "json", "sort_order": "desc", "limit": limit},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        result = []
        for obs in resp.json().get("observations", []):
            if obs["value"] != ".":
                result.append({"date": obs["date"], "value": float(obs["value"])})
        return list(reversed(result))
    except Exception as e:
        print(f"[REGIME-BG] FRED {series_id}: {e}")
        return []


def _store_macro_indicators(indicators: dict[str, list[dict]]):
    with get_db(readonly=False) as conn:
        for key, data_list in indicators.items():
            for item in data_list:
                conn.execute(
                    "INSERT OR REPLACE INTO macro_indicators (date,indicator,value) VALUES (?,?,?)",
                    (item["date"], key, item["value"]))
        conn.commit()


def _get_latest_macro() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT indicator, value, MAX(date) AS date FROM macro_indicators GROUP BY indicator"
        ).fetchall()
    return {r["indicator"]: {"value": r["value"], "date": r["date"]} for r in rows}


def _get_macro_history(indicator: str, limit: int = 250) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, value FROM macro_indicators WHERE indicator=? ORDER BY date DESC LIMIT ?",
            (indicator, limit)).fetchall()
    return [{"date": r["date"], "value": r["value"]} for r in reversed(rows)]


# --------------- テクニカル指標ヘルパー ---------------

def _sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)


def _pct_change(values: list[float], periods: int) -> float | None:
    if len(values) < periods + 1 or values[-(periods + 1)] == 0:
        return None
    return (values[-1] - values[-(periods + 1)]) / values[-(periods + 1)]


# --------------- レジーム判定 ---------------

REGIME_LABELS = {
    "risk_off": "リスクオフ", "inflation": "インフレ局面",
    "trend_up": "上昇トレンド", "trend_down": "下降トレンド",
    "range_bound": "レンジ相場",
}
REGIME_SUB_LABELS = {
    "geopolitical_shock": "地政学ショック", "financial_stress": "金融ストレス",
    "rate_hike_cycle": "利上げサイクル", "stagflation": "スタグフレーション",
    "strong_bull": "強気相場", "early_recovery": "初期回復",
    "correction": "調整局面", "bear_market": "弱気相場",
    "consolidation": "もみ合い",
}

REGIME_RECOMMEND: dict[str, list[str]] = {
    "risk_off": ["soros_macro", "all_weather"],
    "inflation": ["soros_macro", "trend_following"],
    "trend_up": ["ark_growth", "trend_following"],
    "trend_down": ["buffett_value", "all_weather"],
    "range_bound": ["buffett_value", "all_weather"],
}


def _detect_market_regime() -> dict:
    with get_db() as conn:
        def _vals(ind: str):
            rows = conn.execute(
                "SELECT value FROM macro_indicators WHERE indicator=? ORDER BY date DESC LIMIT 250",
                (ind,)).fetchall()
            return [r["value"] for r in reversed(rows)]

        vix_v = _vals("vix")
        sp_v = _vals("sp500")
        tnx_v = _vals("tnx")
        fvx_v = _vals("fvx")
        gold_v = _vals("gold")
        oil_v = _vals("oil")
        # CPI (FRED, monthly)
        cpi_v = _vals("cpi")

    if not vix_v or not sp_v:
        return {"regime": "range_bound", "sub_regime": "consolidation",
                "regime_ja": "レンジ相場", "sub_regime_ja": "もみ合い",
                "confidence": 0, "vix_level": 0, "yield_spread": 0,
                "sp500_trend": "unknown", "scores": {}, "details": {}}

    vix_now = vix_v[-1]
    yield_spread = (tnx_v[-1] - fvx_v[-1]) if tnx_v and fvx_v else 1.0
    sp_now = sp_v[-1]
    sp_sma50 = _sma(sp_v, 50)
    sp_sma200 = _sma(sp_v, 200)
    sp_rsi_ = _rsi(sp_v)
    gold_3m = _pct_change(gold_v, 63) or 0
    oil_3m = _pct_change(oil_v, 63) or 0
    sp_hi = max(sp_v[-252:]) if len(sp_v) >= 252 else max(sp_v)
    sp_dd = (sp_now - sp_hi) / sp_hi if sp_hi else 0

    details: dict[str, Any] = {
        "vix": round(vix_now, 1),
        "yield_spread": round(yield_spread, 2),
        "sp500_sma50": round(sp_sma50, 1) if sp_sma50 else None,
        "sp500_sma200": round(sp_sma200, 1) if sp_sma200 else None,
        "sp500_rsi": round(sp_rsi_, 1) if sp_rsi_ else None,
        "sp500_drawdown": round(sp_dd * 100, 1),
        "gold_3m_pct": round(gold_3m * 100, 1),
        "oil_3m_pct": round(oil_3m * 100, 1),
    }

    scores: dict[str, float] = {}

    # --- risk_off ---
    s = 0
    sub_ro = "financial_stress"
    if vix_now > 30: s += 40
    elif vix_now > 25: s += 20
    if yield_spread < 0: s += 25
    if gold_3m > 0.10: s += 15; sub_ro = "geopolitical_shock"
    if sp_dd < -0.15: s += 20
    scores["risk_off"] = min(s, 100)

    # --- trend_down ---
    s = 0
    sub_td = "correction"
    if sp_sma200 and sp_now < sp_sma200: s += 30
    if sp_sma50 and sp_sma200 and sp_sma50 < sp_sma200: s += 25
    if vix_now > 25: s += 15
    if sp_dd < -0.20: s += 20; sub_td = "bear_market"
    elif sp_dd < -0.10: s += 10
    if sp_rsi_ and sp_rsi_ < 35: s += 10
    scores["trend_down"] = min(s, 100)

    # --- inflation ---
    s = 0
    sub_inf = "rate_hike_cycle"
    if oil_3m > 0.30 and gold_3m > 0.15: s += 40; sub_inf = "stagflation"
    elif oil_3m > 0.20: s += 25
    if gold_3m > 0.10: s += 15
    if tnx_v and tnx_v[-1] > 4.5: s += 20
    if len(cpi_v) >= 13:
        cpi_yoy = (cpi_v[-1] - cpi_v[-13]) / cpi_v[-13] if cpi_v[-13] else 0
        if cpi_yoy > 0.04: s += 30
        elif cpi_yoy > 0.03: s += 15
    scores["inflation"] = min(s, 100)

    # --- trend_up ---
    s = 0
    sub_tu = "strong_bull"
    if sp_sma50 and sp_sma200 and sp_now > sp_sma50 > sp_sma200: s += 35
    elif sp_sma200 and sp_now > sp_sma200: s += 20
    if vix_now < 20: s += 20
    elif vix_now < 25: s += 10
    if sp_rsi_ and sp_rsi_ > 55: s += 15
    if sp_dd > -0.05: s += 15
    # golden cross 検出
    if sp_sma50 and sp_sma200 and sp_sma50 > sp_sma200:
        prev50 = _sma(sp_v[:-5], 50) if len(sp_v) > 55 else None
        prev200 = _sma(sp_v[:-5], 200) if len(sp_v) > 205 else None
        if prev50 and prev200 and prev50 < prev200:
            s += 15; sub_tu = "early_recovery"
    scores["trend_up"] = min(s, 100)

    # --- range_bound ---
    s = 30
    if 15 <= vix_now <= 25: s += 20
    if sp_sma50 and sp_sma50 > 0 and abs(sp_now - sp_sma50) / sp_sma50 < 0.03: s += 20
    if sp_rsi_ and 40 <= sp_rsi_ <= 60: s += 15
    scores["range_bound"] = min(s, 100)

    regime = max(scores, key=scores.get)
    confidence = scores[regime]
    sub_map = {"risk_off": sub_ro, "trend_down": sub_td, "inflation": sub_inf,
               "trend_up": sub_tu, "range_bound": "consolidation"}

    sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_s) >= 2 and sorted_s[0][1] - sorted_s[1][1] < 10:
        details["transitional"] = True
        details["second_regime"] = sorted_s[1][0]

    sp_trend = "above_200sma" if (sp_sma200 and sp_now > sp_sma200) else "below_200sma"
    sub = sub_map.get(regime, "")
    return {
        "regime": regime, "sub_regime": sub,
        "regime_ja": REGIME_LABELS.get(regime, regime),
        "sub_regime_ja": REGIME_SUB_LABELS.get(sub, ""),
        "confidence": confidence, "vix_level": round(vix_now, 1),
        "yield_spread": round(yield_spread, 2), "sp500_trend": sp_trend,
        "scores": {k: round(v, 1) for k, v in scores.items()}, "details": details,
    }


# --------------- 銘柄シグナル検出 ---------------

def _detect_stock_signals() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker,company_name,sector,price,hi52,lo52,"
            "momentum_score,takehara_score FROM us_stocks "
            "WHERE price IS NOT NULL AND hi52 IS NOT NULL ORDER BY takehara_score DESC LIMIT 200"
        ).fetchall()
    signals = []
    for r in rows:
        p, h52, l52 = r["price"], r["hi52"], r["lo52"]
        if not p or not h52 or not l52 or h52 == 0:
            continue
        sigs = []
        if p / h52 > 0.97:
            sigs.append({"type": "52w_high", "label": "52週高値ブレイク",
                         "detail": f"高値まで{round((p/h52-1)*100,1)}%"})
        if l52 > 0 and p / l52 < 1.05:
            sigs.append({"type": "52w_low", "label": "52週安値付近",
                         "detail": f"安値から+{round((p/l52-1)*100,1)}%"})
        rng = h52 - l52
        if rng > 0:
            pos = (p - l52) / rng
            if pos > 0.90:
                sigs.append({"type": "range_top", "label": "レンジ上限",
                             "detail": f"52週レンジ{round(pos*100)}%位置"})
            elif pos < 0.10:
                sigs.append({"type": "range_bottom", "label": "レンジ下限",
                             "detail": f"52週レンジ{round(pos*100)}%位置"})
        if sigs:
            signals.append({
                "ticker": r["ticker"], "company_name": r["company_name"],
                "sector": r["sector"], "price": p, "hi52": h52, "lo52": l52,
                "momentum_score": r["momentum_score"],
                "takehara_score": r["takehara_score"], "signals": sigs,
            })
    return signals


# --------------- 戦略エンジン ---------------

STRATEGY_DEFS = {
    "all_weather": {
        "proxy": {"stocks": "^GSPC", "bonds_long": "TLT", "bonds_mid": "IEF",
                  "gold": "GC=F", "commodities": "CL=F"},
        "default": {"stocks": .30, "bonds_long": .40, "bonds_mid": .15, "gold": .075, "commodities": .075},
        "adjust": {
            "risk_off": {"stocks": .15, "bonds_long": .45, "bonds_mid": .15, "gold": .15, "commodities": .10},
            "inflation": {"stocks": .25, "bonds_long": .25, "bonds_mid": .10, "gold": .15, "commodities": .25},
        },
    },
    "buffett_value": {
        "proxy": {"stocks": "^GSPC"},
        "default": {"stocks": 1.0}, "adjust": {},
    },
    "ark_growth": {
        "proxy": {"stocks": "^GSPC"},
        "default": {"stocks": 1.0},
        "adjust": {"risk_off": {"stocks": .3, "cash": .7}, "trend_down": {"stocks": .5, "cash": .5}},
    },
    "soros_macro": {
        "proxy": {"stocks": "^GSPC", "gold": "GC=F", "bonds_long": "TLT", "commodities": "CL=F"},
        "default": {"stocks": .40, "gold": .20, "bonds_long": .20, "cash": .20},
        "adjust": {
            "risk_off": {"stocks": .0, "gold": .40, "bonds_long": .30, "cash": .30},
            "trend_up": {"stocks": .70, "gold": .10, "bonds_long": .10, "cash": .10},
            "inflation": {"stocks": .20, "gold": .30, "commodities": .30, "cash": .20},
        },
    },
    "trend_following": {
        "proxy": {"stocks": "^GSPC", "bonds_long": "TLT", "gold": "GC=F"},
        "default": {"stocks": .60, "bonds_long": .20, "gold": .20},
        "adjust": {
            "trend_down": {"stocks": .0, "bonds_long": .40, "gold": .30, "cash": .30},
            "risk_off": {"stocks": .0, "bonds_long": .30, "gold": .40, "cash": .30},
        },
    },
}


def _get_strategy_picks(strategy_id: str) -> list[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT stock_criteria FROM strategy_models WHERE strategy_id=?", (strategy_id,)
        ).fetchone()
    if not row or not row["stock_criteria"]:
        return []
    c = json.loads(row["stock_criteria"])
    conds = ["price IS NOT NULL"]
    params: list = []
    if c.get("roe_min"):
        conds.append("roe>=?"); params.append(c["roe_min"])
    if c.get("per_max"):
        conds.append("per>0 AND per<=?"); params.append(c["per_max"])
    if c.get("operating_margin_min"):
        conds.append("operating_margin>=?"); params.append(c["operating_margin_min"])
    if c.get("fcf_positive"):
        conds.append("fcf>0")
    if c.get("revenue_growth_min"):
        conds.append("revenue_growth>=?"); params.append(c["revenue_growth_min"])
    if c.get("sector_prefer"):
        ph = ",".join("?" * len(c["sector_prefer"]))
        conds.append(f"sector IN ({ph})"); params.extend(c["sector_prefer"])
    sort = c.get("sort_by", "takehara_score")
    lim = c.get("limit", 15)
    where = " AND ".join(conds)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT ticker,company_name,sector,price,per,roe,operating_margin,"
            f"dividend_yield,revenue_growth,value_score,quality_score,momentum_score,"
            f"dividend_score,stability_score,takehara_score,target_per15 "
            f"FROM us_stocks WHERE {where} ORDER BY {sort} DESC LIMIT ?",
            params + [lim]).fetchall()
    return [dict(r) for r in rows]


# --------------- バックテストエンジン ---------------

def _run_backtest(strategy_id: str):
    import yfinance as yf
    sd = STRATEGY_DEFS.get(strategy_id)
    if not sd:
        return
    tickers = set(sd["proxy"].values()) | {"^GSPC", "^VIX", "^TNX", "^FVX", "GC=F", "CL=F"}
    price_data: dict[str, dict[str, float]] = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period="10y", interval="1mo")
            if not h.empty:
                price_data[t] = {idx.strftime("%Y-%m-01"): float(row["Close"])
                                 for idx, row in h.iterrows()}
        except Exception as e:
            print(f"[REGIME-BG] BT fetch {t}: {e}")
        from time import sleep as _sl
        _sl(0.5)
    if "^GSPC" not in price_data:
        return
    months = sorted(set().union(*(d.keys() for d in price_data.values())))
    if len(months) < 12:
        return
    results = []
    cum = 1.0; sp_cum = 1.0; peak = 1.0
    for i in range(1, len(months)):
        m, pm = months[i], months[i - 1]
        # 簡易レジーム判定
        vix_val = price_data.get("^VIX", {}).get(pm, 20)
        regime = "range_bound"
        if vix_val > 30:
            regime = "risk_off"
        elif vix_val > 25:
            sp6 = price_data.get("^GSPC", {}).get(months[max(0, i - 6)], 0)
            sp_pm = price_data.get("^GSPC", {}).get(pm, 0)
            if sp6 and sp_pm < sp6 * 0.9:
                regime = "trend_down"
        elif vix_val < 20:
            sp6 = price_data.get("^GSPC", {}).get(months[max(0, i - 6)], 0)
            sp_pm = price_data.get("^GSPC", {}).get(pm, 0)
            if sp6 and sp_pm > sp6 * 1.05:
                regime = "trend_up"
        alloc = dict(sd["default"])
        if regime in sd.get("adjust", {}):
            alloc = dict(sd["adjust"][regime])
        strat_ret = 0.0
        for ac, w in alloc.items():
            if ac == "cash":
                strat_ret += w * 0.0003; continue
            proxy = sd["proxy"].get(ac)
            if not proxy or proxy not in price_data:
                continue
            cur = price_data[proxy].get(m)
            prev = price_data[proxy].get(pm)
            if cur and prev and prev > 0:
                strat_ret += w * ((cur - prev) / prev)
        sp_c = price_data["^GSPC"].get(m)
        sp_p = price_data["^GSPC"].get(pm)
        sp_ret = ((sp_c - sp_p) / sp_p) if sp_c and sp_p and sp_p > 0 else 0
        cum *= (1 + strat_ret); sp_cum *= (1 + sp_ret)
        peak = max(peak, cum)
        dd = (cum - peak) / peak
        results.append({"date": m, "regime": regime,
                        "monthly_return": round(strat_ret, 6),
                        "cumulative_return": round(cum - 1, 6),
                        "sp500_return": round(sp_ret, 6),
                        "sp500_cumulative": round(sp_cum - 1, 6),
                        "drawdown": round(dd, 6),
                        "allocation_snapshot": json.dumps(alloc)})
    with get_db(readonly=False) as conn:
        conn.execute("DELETE FROM backtest_results WHERE strategy_id=?", (strategy_id,))
        for r in results:
            conn.execute(
                "INSERT INTO backtest_results "
                "(strategy_id,date,regime,monthly_return,cumulative_return,"
                "sp500_return,sp500_cumulative,drawdown,allocation_snapshot) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (strategy_id, r["date"], r["regime"], r["monthly_return"],
                 r["cumulative_return"], r["sp500_return"], r["sp500_cumulative"],
                 r["drawdown"], r["allocation_snapshot"]))
        conn.commit()
    print(f"[REGIME-BG] Backtest {strategy_id}: {len(results)} months")


# --------------- レジームBGスレッド ---------------

_regime_update_running = False
_regime_last_updated: str | None = None
_regime_last_backtest: str | None = None


def _update_regime_data():
    global _regime_update_running, _regime_last_updated, _regime_last_backtest
    if _regime_update_running:
        return
    _regime_update_running = True
    try:
        print("[REGIME-BG] Starting macro data update...")
        from time import sleep as _sl
        all_ind: dict[str, list[dict]] = {}
        for key in MACRO_TICKERS:
            data = _fetch_macro_history_yf(key, "1y")
            if data:
                all_ind[key] = data
                print(f"[REGIME-BG] {key}: {len(data)} days")
            _sl(1)
        fred_key = os.getenv("FRED_API_KEY")
        if fred_key:
            for key, sid in FRED_SERIES.items():
                data = _fetch_fred_series(sid)
                if data:
                    all_ind[key] = data
                    print(f"[REGIME-BG] FRED {key}: {len(data)} pts")
        if all_ind:
            _store_macro_indicators(all_ind)
            print(f"[REGIME-BG] Stored {len(all_ind)} indicators")
        regime_res = _detect_market_regime()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with get_db(readonly=False) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO market_regimes "
                "(date,regime,sub_regime,vix_level,yield_spread,sp500_trend,"
                "confidence,details,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (today, regime_res["regime"], regime_res.get("sub_regime"),
                 regime_res.get("vix_level"), regime_res.get("yield_spread"),
                 regime_res.get("sp500_trend"), regime_res.get("confidence"),
                 json.dumps(regime_res.get("details", {})),
                 datetime.now(timezone.utc).isoformat()))
            conn.commit()
        print(f"[REGIME-BG] Regime: {regime_res['regime']} (conf={regime_res['confidence']})")
        should_bt = True
        if _regime_last_backtest:
            try:
                last = datetime.fromisoformat(_regime_last_backtest)
                if (datetime.now(timezone.utc) - last).days < 7:
                    should_bt = False
            except Exception:
                pass
        if should_bt:
            print("[REGIME-BG] Running backtests...")
            for sid in STRATEGY_DEFS:
                try:
                    _run_backtest(sid)
                except Exception as e:
                    print(f"[REGIME-BG] BT {sid} fail: {e}")
            _regime_last_backtest = datetime.now(timezone.utc).isoformat()
        _regime_last_updated = datetime.now(timezone.utc).isoformat()
        print(f"[REGIME-BG] Done at {_regime_last_updated}")
    except Exception as e:
        print(f"[REGIME-BG] Update failed: {e}")
        import traceback; traceback.print_exc()
    finally:
        _regime_update_running = False


def _regime_bg_scheduler():
    from time import sleep as _sl
    _sl(60)
    while True:
        try:
            _update_regime_data()
        except Exception as e:
            print(f"[REGIME-BG] Sched err: {e}")
        _sl(6 * 3600)


_regime_bg_thread = threading.Thread(target=_regime_bg_scheduler, daemon=True, name="regime-updater")
_regime_bg_thread.start()


# --------------- レジームAPI ---------------

@app.get("/api/regime/status")
def regime_status():
    with get_db() as conn:
        cnt = conn.execute("SELECT COUNT(DISTINCT indicator) FROM macro_indicators").fetchone()[0]
        rcnt = conn.execute("SELECT COUNT(*) FROM market_regimes").fetchone()[0]
    return {"updating": _regime_update_running, "last_updated": _regime_last_updated,
            "indicator_count": cnt, "regime_count": rcnt}


@app.get("/api/regime/dashboard")
def regime_dashboard(request: Request):
    _get_current_user(request)
    with get_db() as conn:
        rrow = conn.execute("SELECT * FROM market_regimes ORDER BY date DESC LIMIT 1").fetchone()
    cur_regime = None
    if rrow:
        cur_regime = {
            "date": rrow["date"], "regime": rrow["regime"],
            "regime_ja": REGIME_LABELS.get(rrow["regime"], rrow["regime"]),
            "sub_regime": rrow["sub_regime"],
            "sub_regime_ja": REGIME_SUB_LABELS.get(rrow["sub_regime"], rrow["sub_regime"] or ""),
            "vix_level": rrow["vix_level"], "yield_spread": rrow["yield_spread"],
            "sp500_trend": rrow["sp500_trend"], "confidence": rrow["confidence"],
            "details": json.loads(rrow["details"]) if rrow["details"] else {},
        }
    indicators = {}
    for key in ["vix", "tnx", "gold", "oil", "usd_index", "sp500"]:
        hist = _get_macro_history(key, 60)
        if hist:
            v = hist[-1]["value"]
            indicators[key] = {
                "current": v, "date": hist[-1]["date"],
                "sparkline": [h["value"] for h in hist[-30:]],
                "change_1d": round((v - hist[-2]["value"]) / hist[-2]["value"] * 100, 2) if len(hist) >= 2 and hist[-2]["value"] else None,
                "change_1w": round((v - hist[-6]["value"]) / hist[-6]["value"] * 100, 2) if len(hist) >= 6 and hist[-6]["value"] else None,
            }
    recommended = []
    if cur_regime:
        rn = cur_regime["regime"]
        with get_db() as conn:
            srows = conn.execute("SELECT * FROM strategy_models").fetchall()
        for sr in srows:
            pref = json.loads(sr["preferred_regimes"]) if sr["preferred_regimes"] else []
            avoid = json.loads(sr["avoid_regimes"]) if sr["avoid_regimes"] else []
            recommended.append({
                "strategy_id": sr["strategy_id"], "name_ja": sr["name_ja"],
                "description_ja": sr["description_ja"],
                "allocation": json.loads(sr["allocation"]) if sr["allocation"] else {},
                "is_recommended": rn in pref, "is_avoid": rn in avoid,
                "rebalance_frequency": sr["rebalance_frequency"],
            })
        recommended.sort(key=lambda x: (not x["is_recommended"], x["is_avoid"]))
    return {"regime": cur_regime, "indicators": indicators,
            "strategies": recommended, "updated_at": _regime_last_updated,
            "updating": _regime_update_running}


@app.get("/api/regime/indicators")
def regime_indicators_api(request: Request, indicator: str = None, limit: int = 250):
    _get_current_user(request)
    if indicator:
        return {"indicator": indicator, "data": _get_macro_history(indicator, limit)}
    result = {}
    for key in MACRO_TICKERS:
        d = _get_macro_history(key, limit)
        if d:
            result[key] = d
    return {"indicators": result}


@app.get("/api/regime/history")
def regime_history_api(request: Request, limit: int = 365):
    _get_current_user(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date,regime,sub_regime,vix_level,yield_spread,confidence,details "
            "FROM market_regimes ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        out.append({"date": r["date"], "regime": r["regime"],
                     "regime_ja": REGIME_LABELS.get(r["regime"], r["regime"]),
                     "sub_regime": r["sub_regime"],
                     "sub_regime_ja": REGIME_SUB_LABELS.get(r["sub_regime"], r["sub_regime"] or ""),
                     "vix_level": r["vix_level"], "yield_spread": r["yield_spread"],
                     "confidence": r["confidence"],
                     "details": json.loads(r["details"]) if r["details"] else {}})
    return {"regimes": list(reversed(out))}


@app.get("/api/regime/strategies")
def regime_strategies_api(request: Request):
    _get_current_user(request)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM strategy_models").fetchall()
        rr = conn.execute("SELECT regime FROM market_regimes ORDER BY date DESC LIMIT 1").fetchone()
    cr = rr["regime"] if rr else "range_bound"
    out = []
    for r in rows:
        pref = json.loads(r["preferred_regimes"]) if r["preferred_regimes"] else []
        avoid = json.loads(r["avoid_regimes"]) if r["avoid_regimes"] else []
        out.append({
            "strategy_id": r["strategy_id"], "name_ja": r["name_ja"],
            "description_ja": r["description_ja"],
            "allocation": json.loads(r["allocation"]) if r["allocation"] else {},
            "stock_criteria": json.loads(r["stock_criteria"]) if r["stock_criteria"] else None,
            "preferred_regimes": pref, "avoid_regimes": avoid,
            "is_recommended": cr in pref, "is_avoid": cr in avoid,
            "rebalance_frequency": r["rebalance_frequency"],
        })
    return {"strategies": out, "current_regime": cr}


@app.get("/api/regime/strategy/{strategy_id}")
def regime_strategy_detail(strategy_id: str, request: Request):
    _get_current_user(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM strategy_models WHERE strategy_id=?", (strategy_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    picks = _get_strategy_picks(strategy_id)
    with get_db() as conn:
        rr = conn.execute("SELECT regime FROM market_regimes ORDER BY date DESC LIMIT 1").fetchone()
    cr = rr["regime"] if rr else "range_bound"
    sd = STRATEGY_DEFS.get(strategy_id, {})
    alloc = dict(sd.get("default", {}))
    if cr in sd.get("adjust", {}):
        alloc = dict(sd["adjust"][cr])
    return {
        "strategy_id": row["strategy_id"], "name_ja": row["name_ja"],
        "description_ja": row["description_ja"],
        "base_allocation": json.loads(row["allocation"]) if row["allocation"] else {},
        "current_allocation": {k: round(v * 100, 1) for k, v in alloc.items()},
        "current_regime": cr, "picks": picks,
        "preferred_regimes": json.loads(row["preferred_regimes"]) if row["preferred_regimes"] else [],
        "avoid_regimes": json.loads(row["avoid_regimes"]) if row["avoid_regimes"] else [],
    }


@app.get("/api/regime/backtest/{strategy_id}")
def regime_backtest_api(strategy_id: str, request: Request):
    _get_current_user(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_results WHERE strategy_id=? ORDER BY date",
            (strategy_id,)).fetchall()
    if not rows:
        return {"strategy_id": strategy_id, "results": [], "summary": None}
    results = [dict(r) for r in rows]
    rets = [r["monthly_return"] for r in results if r["monthly_return"] is not None]
    cum_r = results[-1]["cumulative_return"] or 0
    sp_cum = results[-1]["sp500_cumulative"] or 0
    max_dd = min((r["drawdown"] for r in results if r["drawdown"] is not None), default=0)
    yrs = len(results) / 12
    ann = ((1 + cum_r) ** (1 / yrs) - 1) if yrs > 0 else 0
    sp_ann = ((1 + sp_cum) ** (1 / yrs) - 1) if yrs > 0 else 0
    if len(rets) > 1:
        mean_r = sum(rets) / len(rets)
        var_ = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        vol = (var_ ** 0.5) * (12 ** 0.5)
        sharpe = (ann - 0.04) / vol if vol > 0 else 0
    else:
        vol = 0; sharpe = 0
    regime_perf: dict[str, dict] = {}
    for r in results:
        rg = r["regime"] or "unknown"
        if rg not in regime_perf:
            regime_perf[rg] = {"months": 0, "total_return": 0}
        regime_perf[rg]["months"] += 1
        regime_perf[rg]["total_return"] += r["monthly_return"] or 0
    for rg in regime_perf:
        m = regime_perf[rg]["months"]
        regime_perf[rg]["avg_monthly"] = round(regime_perf[rg]["total_return"] / m * 100, 2) if m else 0
    return {"strategy_id": strategy_id, "results": results,
            "summary": {"total_return": round(cum_r * 100, 1),
                        "sp500_return": round(sp_cum * 100, 1),
                        "annualized_return": round(ann * 100, 1),
                        "sp500_annualized": round(sp_ann * 100, 1),
                        "max_drawdown": round(max_dd * 100, 1),
                        "volatility": round(vol * 100, 1),
                        "sharpe_ratio": round(sharpe, 2),
                        "months": len(results),
                        "regime_breakdown": regime_perf}}


@app.get("/api/regime/breakouts")
def regime_breakouts_api(request: Request):
    _get_current_user(request)
    signals = _detect_stock_signals()
    return {"breakouts": signals, "count": len(signals)}


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
