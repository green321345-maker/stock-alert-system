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
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send(msg):
    if not WEBHOOK:
        return
    requests.post(WEBHOOK, json={"content": msg})


def safe_float(v):
    try:
        return float(v)
    except:
        return None


def fmt_price(v):
    if v is None:
        return "N/A"
    return str(int(round(v)))


def price_unit(ticker):
    return "원" if ticker.endswith(".KS") else "달러"


def get_ma(close, w):
    return close.rolling(w).mean().iloc[-1] if len(close) >= w else None


def calc_rsi(close):
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def buy_score(price, hist):
    close = hist["Close"]
    score = 0

    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)

    if ma50 and price > ma50:
        score += 1
    if ma50 and ma200 and ma50 > ma200:
        score += 2
    if rsi is not None:
        if rsi < 35:
            score += 2
        elif rsi < 50:
            score += 1

    return score


def sell_score(price, hist):
    close = hist["Close"]
    score = 0

    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)

    if rsi is not None:
        if rsi > 70:
            score += 2
        elif rsi > 60:
            score += 1

    if ma50 and ma200 and ma50 < ma200:
        score += 2

    return score


def analyze(t):
    s = yf.Ticker(t)
    hist = s.history(period=ANALYSIS_PERIOD)

    if hist.empty:
        return None

    price = hist["Close"].iloc[-1]
    b = buy_score(price, hist)
    s_ = sell_score(price, hist)

    return {
        "price": price,
        "buy": b,
        "sell": s_
    }


def main():
    state = load_state()
    new_state = {}

    for t in TICKERS:
        data = analyze(t)
        if not data:
            continue

        prev = state.get(t, {"buy": 0, "sell": 0})

        buy_diff = data["buy"] - prev.get("buy", 0)
        sell_diff = data["sell"] - prev.get("sell", 0)

        price = fmt_price(data["price"])
        unit = price_unit(t)

        if buy_diff >= 2:
            send(f"{t} {price}{unit} · 매수 신호")

        if sell_diff >= 2:
            send(f"{t} {price}{unit} · 매도 신호")

        new_state[t] = data

    save_state(new_state)


if __name__ == "__main__":
    main()
