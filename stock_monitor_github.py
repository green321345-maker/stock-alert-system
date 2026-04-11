import os
import json
import requests
import pandas as pd
import yfinance as yf

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
TICKERS = [x.strip().upper() for x in os.getenv("PORTFOLIO_TICKERS", "AAPL,MSFT,NVDA").split(",") if x.strip()]
ANALYSIS_PERIOD = os.getenv("ANALYSIS_PERIOD", "1y").strip()
STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send(msg):
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL missing")
        return
    r = requests.post(WEBHOOK, json={"content": msg[:1900]}, timeout=10)
    print("discord status:", r.status_code)
    print("discord body:", r.text[:200])


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
    return f"{int(round(float(v))):,}"


def price_unit(ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "원"
    return "달러"


def get_ma(close, window):
    if close is None or len(close) < window:
        return None
    val = close.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def calc_rsi(close, period=14):
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean().replace(0, 1e-9)
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def buy_score(price, hist):
    if hist is None or hist.empty or "Close" not in hist.columns:
        return 0

    close = hist["Close"].dropna()
    score = 0

    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)

    if ma50 is not None and price is not None and price > ma50:
        score += 1

    if ma50 is not None and ma200 is not None and ma50 > ma200:
        score += 2

    if rsi is not None:
        if rsi < 35:
            score += 2
        elif rsi < 50:
            score += 1

    return score


def sell_score(price, hist):
    if hist is None or hist.empty or "Close" not in hist.columns:
        return 0

    close = hist["Close"].dropna()
    score = 0

    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)

    if rsi is not None:
        if rsi > 70:
            score += 2
        elif rsi > 60:
            score += 1

    if ma50 is not None and ma200 is not None and ma50 < ma200:
        score += 2

    return score


def analyze(ticker):
    try:
        s = yf.Ticker(ticker)
        hist = s.history(period=ANALYSIS_PERIOD, auto_adjust=False, actions=True)
        if hist.empty:
            return None

        price = safe_float(hist["Close"].iloc[-1])
        b = buy_score(price, hist)
        s_ = sell_score(price, hist)

        return {
            "price": price,
            "buy": b,
            "sell": s_,
        }
    except Exception as e:
        print(f"{ticker} error:", e)
        return None


def main():
    state = load_state()
    new_state = {}

    for ticker in TICKERS:
        data = analyze(ticker)
        if not data:
            continue

        prev = state.get(ticker, {"buy": 0, "sell": 0})

        buy_diff = data["buy"] - prev.get("buy", 0)
        sell_diff = data["sell"] - prev.get("sell", 0)

        price = fmt_price(data["price"])
        unit = price_unit(ticker)

        if buy_diff >= 1:
            send(f"{ticker} {price}{unit} · 매수 신호")

        if sell_diff >= 1:
            send(f"{ticker} {price}{unit} · 매도 신호")

        new_state[ticker] = data

    save_state(new_state)


if __name__ == "__main__":
    main()
