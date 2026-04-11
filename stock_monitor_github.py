import os
import requests
import yfinance as yf

WEBHOOK = os.getenv("https://discord.com/api/webhooks/1492557189032710397/Mof5dG8AvxwWvWwT17GnHH3L9zdVUISar9wzIEaINt2pC36EbPBiQgn4b6x4mT_QkdGE")
TICKERS = os.getenv("PORTFOLIO_TICKERS", "AAPL,MSFT").split(",")

def send(msg):
    if WEBHOOK:
        requests.post(WEBHOOK, json={"content": msg})

def check():
    results = []
    for t in TICKERS:
        try:
            data = yf.Ticker(t)
            price = data.fast_info.get("lastPrice")
            if price:
                results.append(f"{t}: {price}")
            else:
                results.append(f"{t}: 데이터 없음")
        except Exception as e:
            results.append(f"{t}: 오류")

    # 👉 무조건 보내게 변경
    send("\n".join(results))

if __name__ == "__main__":
    check()
