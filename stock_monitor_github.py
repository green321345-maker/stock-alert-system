import os
import requests
import yfinance as yf

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
TICKERS = os.getenv("PORTFOLIO_TICKERS", "AAPL,MSFT").split(",")

def send(msg):
    if WEBHOOK:
        requests.post(WEBHOOK, json={"content": msg})

def check():
    results = []

    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL missing")
        return

    for t in TICKERS:
        try:
            t = t.strip()
            data = yf.Ticker(t)
            price = data.fast_info.get("lastPrice")
            if price:
                results.append(f"{t}: {price}")
            else:
                results.append(f"{t}: 데이터 없음")
        except Exception as e:
            results.append(f"{t}: 오류 - {str(e)}")

    send("테스트 메시지\\n" + "\\n".join(results))

if __name__ == "__main__":
    check()
