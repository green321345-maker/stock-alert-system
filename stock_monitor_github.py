import json
import os
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

CONFIG_FILE = Path("monitor_config.json")
STATE_FILE = Path("state.json")
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"failed to load {path}: {e}")
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def price_unit(ticker: str) -> str:
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "원"
    return "달러"


def send_discord(message: str) -> None:
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL missing")
    r = requests.post(WEBHOOK, json={"content": message[:1900]}, timeout=10)
    print("discord status:", r.status_code)
    print("discord body:", r.text[:200])
    r.raise_for_status()


def get_ma(close: pd.Series, window: int):
    if close is None or len(close) < window:
        return None
    val = close.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def calc_rsi(close: pd.Series, period: int = 14):
    if close is None or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean().replace(0, 1e-9)
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def buy_score(price, hist: pd.DataFrame) -> int:
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


def sell_score(price, hist: pd.DataFrame) -> int:
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


def signal_text(buy: int, sell: int, buy_diff: int, sell_diff: int, enable_buy: bool, enable_sell: bool, threshold: int):
    if enable_buy and buy_diff >= threshold and buy > sell:
        return "매수 신호"
    if enable_sell and sell_diff >= threshold and sell > buy:
        return "매도 신호"
    return None


def analyze_ticker(ticker: str, analysis_period: str):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=analysis_period, auto_adjust=False, actions=True)
        if hist.empty:
            return None

        price = safe_float(hist["Close"].iloc[-1])
        buy = buy_score(price, hist)
        sell = sell_score(price, hist)

        return {
            "price": price,
            "buy": buy,
            "sell": sell,
        }
    except Exception as e:
        print(f"{ticker} analyze failed: {e}")
        return None


def main():
    config = load_json(
        CONFIG_FILE,
        {
            "tickers": ["AAPL", "MSFT", "NVDA"],
            "analysis_period": "1y",
            "movement_threshold": 1,
            "enable_buy_alert": True,
            "enable_sell_alert": True,
        },
    )
    old_state = load_json(STATE_FILE, {})
    new_state = {}

    tickers = [str(x).strip().upper() for x in config.get("tickers", []) if str(x).strip()]
    analysis_period = str(config.get("analysis_period", "1y")).strip()
    threshold = int(config.get("movement_threshold", 1))
    enable_buy = bool(config.get("enable_buy_alert", True))
    enable_sell = bool(config.get("enable_sell_alert", True))

    if not tickers:
        print("no tickers configured")
        return

    messages = []

    for ticker in tickers:
        result = analyze_ticker(ticker, analysis_period)
        if not result:
            continue

        prev = old_state.get(ticker, {"buy": 0, "sell": 0})
        buy_diff = result["buy"] - int(prev.get("buy", 0))
        sell_diff = result["sell"] - int(prev.get("sell", 0))

        signal = signal_text(
            buy=result["buy"],
            sell=result["sell"],
            buy_diff=buy_diff,
            sell_diff=sell_diff,
            enable_buy=enable_buy,
            enable_sell=enable_sell,
            threshold=threshold,
        )

        new_state[ticker] = {
            "buy": result["buy"],
            "sell": result["sell"],
            "last_signal": signal,
        }

        if signal is None:
            continue

        price = fmt_price(result["price"])
        unit = price_unit(ticker)
        messages.append(
            f"{ticker} {price}{unit} · {signal} · 매수 {result['buy']} / 매도 {result['sell']}"
        )

    save_json(STATE_FILE, new_state)

    if not messages:
        print("no alert to send")
        return

    for msg in messages:
        send_discord(msg)


if __name__ == "__main__":
    main()
