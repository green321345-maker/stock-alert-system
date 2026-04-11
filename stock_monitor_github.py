import os
import json
import requests
import pandas as pd
import yfinance as yf

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
TICKERS = [x.strip().upper() for x in os.getenv("PORTFOLIO_TICKERS", "AAPL,MSFT,NVDA").split(",") if x.strip()]
ANALYSIS_PERIOD = os.getenv("ANALYSIS_PERIOD", "1y").strip()
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "7"))
SELL_THRESHOLD = float(os.getenv("SELL_THRESHOLD", "8"))
ALERT_MODE = os.getenv("ALERT_MODE", "signals_only").strip().lower()
SHORT_ALERT = os.getenv("SHORT_ALERT", "1").strip() == "1"

def safe_float(v):
    try:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None

def fmt_price(v):
    if v is None:
        return "N/A"
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"

def send(msg: str):
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL missing")
        return
    r = requests.post(WEBHOOK, json={"content": msg[:1900]}, timeout=10)
    print("discord status:", r.status_code)
    print("discord body:", r.text[:200])

def get_ma(close_series: pd.Series, window: int):
    if close_series is None or len(close_series) < window:
        return None
    val = close_series.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None

def calc_rsi(close_series: pd.Series, period: int = 14):
    if close_series is None or len(close_series) < period + 1:
        return None
    delta = close_series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean().replace(0, 1e-9)
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None

def buy_timing_score(price, intrinsic, hist: pd.DataFrame, target_mean):
    score = 0
    close = hist["Close"].dropna() if not hist.empty and "Close" in hist.columns else pd.Series(dtype=float)
    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)
    if price is not None and intrinsic is not None:
        if price < intrinsic * 0.75:
            score += 4
        elif price < intrinsic:
            score += 2
    if price is not None and target_mean is not None and price < target_mean * 0.90:
        score += 1
    if ma50 is not None and price is not None and price > ma50:
        score += 1
    if ma50 is not None and ma200 is not None and ma50 > ma200:
        score += 2
    if rsi is not None:
        if rsi < 35:
            score += 2
        elif rsi < 50:
            score += 1
    return min(score, 10)

def sell_risk_score(price, intrinsic, hist: pd.DataFrame, target_mean):
    score = 0
    close = hist["Close"].dropna() if not hist.empty and "Close" in hist.columns else pd.Series(dtype=float)
    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)
    if price is not None and intrinsic is not None:
        if price > intrinsic * 1.25:
            score += 3
        elif price > intrinsic * 1.10:
            score += 2
    if price is not None and target_mean is not None and price > target_mean * 1.10:
        score += 2
    if rsi is not None:
        if rsi > 70:
            score += 2
        elif rsi > 60:
            score += 1
    if ma50 is not None and ma200 is not None and ma50 < ma200:
        score += 2
    return min(score, 10)

def calc_intrinsic(info, target_mean):
    try:
        eps = safe_float(info.get("trailingEps"))
        growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
        if eps is not None and growth is not None and growth > 0:
            growth = min(max(growth, 0.02), 0.15)
            future_eps = eps * ((1 + growth) ** 10)
            intrinsic = future_eps / (1.10 ** 10) * 0.70
            if intrinsic:
                return intrinsic
    except Exception:
        pass
    return target_mean

def one_line(buy_t, sell_r, price, target_mean):
    if buy_t >= 8 and sell_r <= 3:
        return "💎 강한 매수"
    if buy_t >= 7 and sell_r <= 4:
        return "🟡 매수 후보"
    if sell_r >= 8:
        return "🚨 매도 경고"
    if target_mean is not None and price is not None and target_mean > price:
        return "👀 관찰"
    return "대기"

def analyze_ticker(ticker: str):
    try:
        s = yf.Ticker(ticker)
        info = json.loads(json.dumps(s.info or {}, default=str))
        fast = json.loads(json.dumps(dict(s.fast_info) if s.fast_info else {}, default=str))
        hist = s.history(period=ANALYSIS_PERIOD, auto_adjust=False, actions=True)
    except Exception as e:
        return {"Ticker": ticker, "Error": str(e)}

    price = safe_float(fast.get("lastPrice")) or safe_float(info.get("currentPrice"))
    target_mean = safe_float(info.get("targetMeanPrice"))
    intrinsic = calc_intrinsic(info, target_mean)
    buy_score = buy_timing_score(price, intrinsic, hist, target_mean)
    sell_score = sell_risk_score(price, intrinsic, hist, target_mean)
    upside = (target_mean / price - 1) * 100 if price and target_mean else None

    return {
        "Ticker": ticker,
        "Price": price,
        "TargetMean": target_mean,
        "BuyTiming": buy_score,
        "SellRisk": sell_score,
        "Upside%": upside,
        "Decision": one_line(buy_score, sell_score, price, target_mean),
        "Error": None,
    }

def build_messages(rows):
    msgs = []
    for row in rows:
        if row.get("Error"):
            if ALERT_MODE == "all":
                msgs.append(f"{row['Ticker']} 오류")
            continue

        buy_t = row["BuyTiming"]
        sell_r = row["SellRisk"]
        price = row["Price"]
        upside = row["Upside%"]
        decision = row["Decision"]

        should_send = False
        if ALERT_MODE == "all":
            should_send = True
        elif buy_t >= BUY_THRESHOLD and sell_r <= 4:
            should_send = True
        elif sell_r >= SELL_THRESHOLD:
            should_send = True

        if not should_send:
            continue

        if SHORT_ALERT:
            if sell_r >= SELL_THRESHOLD:
                msgs.append(f"{row['Ticker']} {fmt_price(price)}$ 🚨 {decision} ({sell_r:.0f}/10)")
            else:
                tail = f" · 상방 {upside:.0f}%" if upside is not None else ""
                msgs.append(f"{row['Ticker']} {fmt_price(price)}$ {decision} ({buy_t:.0f}/10){tail}")
        else:
            msgs.append(
                f"{row['Ticker']}\n"
                f"현재가: {fmt_price(price)}\n"
                f"매수 타이밍: {buy_t}/10\n"
                f"매도 경고: {sell_r}/10\n"
                f"예상 상방: {upside:.1f}%\n"
                f"판단: {decision}"
            )
    return msgs

def main():
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL missing")

    rows = [analyze_ticker(t) for t in TICKERS]
    messages = build_messages(rows)

    if not messages:
        send(f"조건 충족 알림 없음 · 기간 {ANALYSIS_PERIOD} · 종목 {', '.join(TICKERS)}")
        return

    for msg in messages[:10]:
        send(msg)

if __name__ == "__main__":
    main()