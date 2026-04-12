"""
투자 분석 시스템 - 완전 통합본
=================================

이 애플리케이션은 Streamlit을 사용하여 종목 분석, 목표가/해설, 재무제표, 주주수익률,
포트폴리오 관리, 시장 스캔 및 간단한 백테스트 기능을 한 화면에서 제공하는 종합 투자 도구입니다.

주요 특징:

* **종목 검색과 분석** – 입력한 종목에 대해 가격, 시가총액, 버핏/린치 점수, PEG, 내재가치(여러 방식),
  매수 타이밍/매도 경고 점수, 가치 구간(저평가/적정/고평가), 목표가 및 상승/하락여력 등을 계산하여
  보여줍니다. 또한 버핏/린치 필터를 통과 여부와 이유까지 확인할 수 있습니다.
* **목표가 및 해설 탭** – 야후/핀허브 목표가를 종합하여 평균·최고·최저 및 상승/하락여력을
  보여주고, 목표가가 어떻게 산출됐는지 합리적인 이유를 서술합니다.
* **재무제표/현금흐름표** – 연간/분기 손익계산서, 재무상태표, 현금흐름표를 테이블 형태로 볼 수
  있습니다. 기본적으로 첫 20행만 보여주며 필요 시 확대할 수 있습니다.
* **주주수익률 표** – 1·3·5·10년 기간별 배당이 반영된 주주수익률과 CAGR을 제공합니다.
* **포트폴리오 관리** – 종목을 포트폴리오에 추가하고, 점수를 기반으로 권장 비중과 투입금을
  계산합니다. 포트폴리오 비우기 기능도 제공됩니다.
* **시장 스캔** – 미국과 한국의 넓은 유니버스를 대상으로 빠르게 후보를 골라 점수화하고,
  자본 규모와 시가총액 필터에 따라 상위 종목을 추천합니다. 스캔 결과에서 TOP PICK과
  추천 포트폴리오까지 확인할 수 있습니다.
* **간단 백테스트** – MA50/MA200 골든크로스 전략과 buy&hold 전략을 비교하는 백테스트를
  제공합니다. 과거 적합도를 빠르게 확인할 수 있습니다.

사용자는 분석 기간(1y, 3y, 5y, 10y), 투자금, 시장 스캔 범위(자동/미국/한국/미국+한국),
시가총액 밴드 필터, 스캔 후보 수, 최소 점수, 상위 표시 수를 조절할 수 있습니다. 또한
Finnhub API 키를 입력하면 목표가 데이터의 정확도가 향상됩니다.

이 스크립트는 한국어를 기본으로 하고, 모든 표기와 설명을 한글로 제공하여 국내 투자자가
이해하기 쉽도록 설계했습니다.
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import json
import os
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1492557189032710397/Mof5dG8AvxwWvWwT17GnHH3L9zdVUISar9wzIEaINt2pC36EbPBiQgn4b6x4mT_QkdGE'

def send_discord_message(message: str) -> bool:
    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=5,
        )
        return 200 <= response.status_code < 300
    except Exception:
        return False


def send_discord_alert_once(key: str, message: str) -> bool:
    if "discord_alert_sent" not in st.session_state:
        st.session_state.discord_alert_sent = set()

    if key in st.session_state.discord_alert_sent:
        return False

    ok = send_discord_message(message)
    if ok:
        st.session_state.discord_alert_sent.add(key)
    return ok


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
MONITOR_CONFIG_PATH = "monitor_config.json"


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def default_monitor_config():
    return {
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "analysis_period": "1y",
        "movement_threshold": 1,
        "enable_buy_alert": True,
        "enable_sell_alert": True,
    }


def load_monitor_config_from_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return default_monitor_config(), None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MONITOR_CONFIG_PATH}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=github_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def save_monitor_config_to_github(config: dict, sha: str | None):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GITHUB_TOKEN 또는 GITHUB_REPO 환경변수가 비어 있습니다.")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MONITOR_CONFIG_PATH}"
    body = {
        "message": "Update monitor_config.json from stock app",
        "content": base64.b64encode(
            json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    r = requests.put(url, headers=github_headers(), json=body, timeout=20)
    r.raise_for_status()
    return r.json()



try:
    from pykrx import stock as pykrx_stock  # 한국 시장 전체 조회용
except Exception:
    pykrx_stock = None

# =========================================================
# UI 설정
# =========================================================
st.set_page_config(page_title="투자 분석 시스템", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

# 사용자 정의 스타일 (가독성 향상)
st.markdown(
    """
    <style>
        html, body, [class*="css"] {
            font-size: 20px !important;
            line-height: 1.6 !important;
            font-weight: 650 !important;
        }
        h1 {
            font-size: 2.6rem !important;
            font-weight: 900 !important;
            letter-spacing: -0.03em;
        }
        h2 {
            font-size: 2.0rem !important;
            font-weight: 850 !important;
            letter-spacing: -0.02em;
        }
        h3 {
            font-size: 1.6rem !important;
            font-weight: 800 !important;
        }
        p, li, label, div, span {
            font-size: 1.0rem !important;
            font-weight: 650 !important;
        }
        .stApp {
            background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
            color: #172554;
        }
        #MainMenu, footer {
            display: none !important;
        }
        header[data-testid="stHeader"] {
            background: rgba(248, 251, 255, 0.92) !important;
            backdrop-filter: blur(8px);
        }
        [data-testid="stToolbar"] {
            right: 0.5rem !important;
        }
        .block-container {
            padding-top: 0.8rem !important;
        }
        section[data-testid="stSidebar"] {
            background: #eaf2ff;
            border-right: 1px solid #d9e6ff;
        }
        @media (max-width: 768px) {
            section[data-testid="stSidebar"] {
                min-width: 82vw !important;
                max-width: 82vw !important;
            }
            .block-container {
                padding-top: 0.6rem !important;
                padding-left: 0.7rem !important;
                padding-right: 0.7rem !important;
            }
        }
        section[data-testid="stSidebar"] * {
            font-size: 1.0rem !important;
            font-weight: 700 !important;
        }
        div[data-testid="stMetric"] {
            background: #ffffff;
            padding: 16px;
            border-radius: 16px;
            box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08);
            border: 1px solid #e5eefb;
            font-weight: 900 !important;
        }
        .stButton button {
            border-radius: 12px !important;
            padding: 0.6rem 1rem !important;
            font-size: 0.95rem !important;
            font-weight: 900 !important;
            color: #ffffff !important;
            background: #111827 !important;
            border: 1px solid #111827 !important;
            box-shadow: none !important;
        }
        .stButton button:hover {
            background: #374151 !important;
            border-color: #374151 !important;
            color: #ffffff !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("💎 투자 분석 시스템")
st.caption("종목 검색, 타이밍, 목표가, 재무제표, 포트폴리오, 시장 스캔, 주주수익률, 백테스트를 한 번에!")

# =========================================================
# 세션 상태 초기화
# =========================================================
if "portfolio" not in st.session_state:
    st.session_state.portfolio = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "last_ticker" not in st.session_state:
    st.session_state.last_ticker = "AAPL"
if "scan_settings_signature" not in st.session_state:
    st.session_state.scan_settings_signature = None
if "discord_alert_sent" not in st.session_state:
    st.session_state.discord_alert_sent = set()

# =========================================================
# 도우미 함수들
# =========================================================
def safe_float(v):
    """숫자가 아니거나 None이면 None 반환."""
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


def safe_int(v):
    """정수가 아니거나 None이면 None 반환."""
    try:
        if v is None:
            return None
        if pd.isna(v):
            return None
        return int(float(v))
    except Exception:
        return None


def safe_df(obj):
    """입력 객체가 DataFrame이 아니면 빈 DataFrame 반환."""
    try:
        if obj is None:
            return pd.DataFrame()
        if isinstance(obj, pd.DataFrame):
            return obj.copy()
        return pd.DataFrame(obj)
    except Exception:
        return pd.DataFrame()


def fmt_price(v):
    """가격 형식화."""
    if v is None or pd.isna(v):
        return "N/A"
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def fmt_pct(v, digits=1):
    """퍼센트 형식화."""
    if v is None or pd.isna(v):
        return "N/A"
    return f"{float(v):.{digits}f}%"


def fmt_ratio(v, digits=1):
    """배수 형식화."""
    if v is None or pd.isna(v):
        return "N/A"
    return f"{float(v):.{digits}f}x"


def fmt_market_cap(v):
    """시가총액을 단위 별로 표시."""
    if v is None or pd.isna(v):
        return "N/A"
    v = float(v)
    if abs(v) >= 1e12:
        return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.2f}M"
    return f"{v:,.0f}"


def band_from_market_cap(market_cap):
    """시가총액을 대형, 중형, 소형으로 분류."""
    if market_cap is None:
        return "unknown"
    if market_cap >= 200e9:
        return "large"
    if market_cap >= 10e9:
        return "mid"
    return "small"


def portfolio_strategy(capital):
    """투자금에 따른 전략과 시총 가중치 설정."""
    if capital < 5_000_000:
        return {
            "label": "소형/중형 성장주 중심",
            "preferred": ["small", "mid"],
            "bias": {"small": 4, "mid": 3, "large": 1, "unknown": 1},
        }
    if capital < 50_000_000:
        return {
            "label": "중형 + 대형 분산",
            "preferred": ["mid", "large"],
            "bias": {"small": 2, "mid": 4, "large": 3, "unknown": 1},
        }
    return {
        "label": "대형 우량주 중심",
        "preferred": ["large", "mid"],
        "bias": {"small": 1, "mid": 3, "large": 4, "unknown": 1},
    }


def risk_level(score):
    """매도 경고 점수에 따른 위험 수준."""
    if score >= 7:
        return "높음"
    if score >= 4:
        return "중간"
    return "낮음"


def valuation_zone(price, intrinsic, target_mean):
    """가격이 내재가치나 목표가 대비 어느 정도인지 분류."""
    if price is None:
        return "N/A"
    ref = intrinsic if intrinsic is not None else target_mean
    if ref is None:
        return "N/A"
    if price < ref * 0.85:
        return "저평가"
    if price > ref * 1.15:
        return "고평가"
    return "적정"



def one_line_summary(row: dict) -> str:
    buy_t = row.get("BuyTiming", 0) or 0
    sell_r = row.get("SellRisk", 0) or 0
    buff = row.get("Buffett", 0) or 0
    lyn = row.get("Lynch", 0) or 0
    valz = row.get("ValuationZone", "N/A")
    upside = row.get("Upside%")
    if sell_r >= 8:
        return "과열 신호가 강해서 비중 축소를 먼저 보는 편이 낫습니다."
    if buy_t >= 7 and buff >= 6 and lyn >= 5 and valz == "저평가":
        return "가치·성장·타이밍이 함께 받쳐줘서 우선순위가 높은 후보입니다."
    if buy_t >= 6 and sell_r <= 3:
        return "타이밍이 괜찮아서 분할 진입을 검토할 만합니다."
    if valz == "고평가":
        return "기업 자체는 괜찮아도 가격 부담이 보여서 서두르지 않는 편이 좋습니다."
    if upside is not None and upside < 0:
        return "공개 목표가 기준으로는 기대수익보다 방어가 더 중요해 보입니다."
    return "좋은 점과 아쉬운 점이 함께 보여서 관찰 후 판단하는 편이 좋습니다."


def score_criteria_table() -> pd.DataFrame:
    rows = [
        {"영역": "버핏 점수", "기준": "ROE > 15%, 부채비율 < 100, 마진 > 20%, FCF 양수", "배점": "최대 10점"},
        {"영역": "린치 점수", "기준": "PEG < 1 또는 2 미만, 이익성장률/매출성장률 양호", "배점": "최대 10점"},
        {"영역": "매수 타이밍", "기준": "내재가치 대비 할인, 목표가 대비 할인, MA50/MA200, RSI", "배점": "최대 10점"},
        {"영역": "매도 경고", "기준": "내재가치 대비 고평가, 목표가 상회, RSI 과열, 데드크로스", "배점": "최대 10점"},
        {"영역": "총점", "기준": "버핏 + 린치 + 매수타이밍 + 시총적합도 - 매도경고", "배점": "가감식"},
    ]
    return pd.DataFrame(rows)



def data_quality_label(row: dict) -> str:
    filled = 0
    total = 0
    for key in ["PEG", "Intrinsic", "Target Mean", "Upside%", "Downside%", "MarginSafety"]:
        total += 1
        if row.get(key) is not None:
            filled += 1
    ratio = filled / total if total else 0
    if ratio >= 0.8:
        return "높음"
    if ratio >= 0.5:
        return "보통"
    return "낮음"


def why_selected_summary(row: dict) -> str:
    parts = []
    if row.get("Buffett", 0) >= 7:
        parts.append("버핏 점수가 높음")
    if row.get("Lynch", 0) >= 7:
        parts.append("린치 점수가 높음")
    if row.get("BuyTiming", 0) >= 7:
        parts.append("매수 타이밍 우수")
    if row.get("MarginSafety") is not None and row.get("MarginSafety") >= 15:
        parts.append("안전마진 여유")
    if row.get("Upside%") is not None and row.get("Upside%") >= 15:
        parts.append("상승여력 큼")
    if not parts:
        parts.append("총점 균형이 좋음")
    return ", ".join(parts[:3])


def simple_backtest_stats(bt: pd.DataFrame) -> pd.DataFrame:
    if bt is None or bt.empty:
        return pd.DataFrame()

    def _max_drawdown(series: pd.Series) -> float:
        rolling_max = series.cummax()
        dd = series / rolling_max - 1
        return float(dd.min()) * 100

    strat_final = float(bt["Equity"].iloc[-1])
    bh_final = float(bt["BuyHold"].iloc[-1])
    strat_ret = (strat_final - 1) * 100
    bh_ret = (bh_final - 1) * 100
    excess = strat_ret - bh_ret
    rows = [
        {"항목": "전략 최종값", "값": round(strat_final, 3)},
        {"항목": "보유 최종값", "값": round(bh_final, 3)},
        {"항목": "전략 누적수익률", "값": f"{strat_ret:.1f}%"},
        {"항목": "보유 누적수익률", "값": f"{bh_ret:.1f}%"},
        {"항목": "초과수익", "값": f"{excess:.1f}%"},
        {"항목": "전략 최대낙폭", "값": f"{_max_drawdown(bt['Equity']):.1f}%"},
        {"항목": "보유 최대낙폭", "값": f"{_max_drawdown(bt['BuyHold']):.1f}%"},
    ]
    return pd.DataFrame(rows)


def alert_message(row: dict) -> str:
    buy_t = row.get("BuyTiming", 0) or 0
    sell_r = row.get("SellRisk", 0) or 0
    if buy_t >= 8 and sell_r <= 3:
        return "🔔 강한 매수 타이밍 신호"
    if buy_t >= 7 and sell_r <= 4:
        return "🔔 매수 타이밍이 들어온 편"
    if sell_r >= 8:
        return "🚨 매도 경고가 매우 강함"
    return "알림 없음"


def super_pick_label(row: dict) -> str:
    if (
        (row.get("Buffett", 0) or 0) >= 6 and
        (row.get("Lynch", 0) or 0) >= 6 and
        (row.get("MomentumScore", 0) or 0) >= 6
    ):
        return "🔥 초강력 종목"
    return ""


def portfolio_risk_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    avg_sell = float(df["SellRisk"].fillna(0).mean())
    avg_buy = float(df["BuyTiming"].fillna(0).mean())
    avg_margin = float(df["MarginSafety"].fillna(0).mean()) if "MarginSafety" in df.columns else 0.0
    high_risk_cnt = int((df["SellRisk"].fillna(0) >= 7).sum())
    super_cnt = int((df["SuperPick"] == "🔥 초강력 종목").sum()) if "SuperPick" in df.columns else 0
    if avg_sell >= 7:
        risk_label = "높음"
    elif avg_sell >= 4:
        risk_label = "보통"
    else:
        risk_label = "낮음"
    rows = [
        {"항목": "평균 매수 타이밍", "값": f"{avg_buy:.1f}/10"},
        {"항목": "평균 매도 경고", "값": f"{avg_sell:.1f}/10"},
        {"항목": "평균 안전마진", "값": f"{avg_margin:.1f}%"},
        {"항목": "고위험 종목 수", "값": high_risk_cnt},
        {"항목": "초강력 종목 수", "값": super_cnt},
        {"항목": "포트폴리오 위험 수준", "값": risk_label},
    ]
    return pd.DataFrame(rows)


def style_mix_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "StyleTags" not in df.columns:
        return pd.DataFrame()
    tags = {}
    for val in df["StyleTags"].fillna("기타"):
        for token in [x.strip() for x in str(val).split("|")]:
            if token:
                tags[token] = tags.get(token, 0) + 1
    if not tags:
        return pd.DataFrame()
    total = sum(tags.values())
    rows = [{"스타일": k, "개수": v, "비중": f"{v/total*100:.1f}%"} for k, v in sorted(tags.items(), key=lambda x: x[1], reverse=True)]
    return pd.DataFrame(rows)


def capital_outcome_table(df: pd.DataFrame, capital: float) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    base = work["TotalScore"].clip(lower=1)
    total_base = float(base.sum()) if float(base.sum()) > 0 else 0.0
    if total_base > 0:
        work["추천비중%"] = (base / total_base * 100)
    else:
        work["추천비중%"] = 100 / len(work)
    work["투입금"] = work["추천비중%"] / 100 * capital
    work["예상수익금"] = work["투입금"] * work["Upside%"].fillna(0) / 100
    work["최악손실금"] = work["투입금"] * work["Downside%"].fillna(0) / 100
    out = work[["Ticker", "투입금", "Upside%", "Downside%", "예상수익금", "최악손실금"]].copy()
    out["투입금"] = out["투입금"].round(0)
    out["예상수익금"] = out["예상수익금"].round(0)
    out["최악손실금"] = out["최악손실금"].round(0)
    out["Upside%"] = out["Upside%"].apply(fmt_pct)
    out["Downside%"] = out["Downside%"].apply(fmt_pct)
    return out


def quick_compare_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    cols = ["Ticker", "Market", "StyleTags", "Buffett", "Lynch", "MomentumScore", "MagicFormulaScore", "BuyTiming", "SellRisk", "MarginSafety", "Upside%"]
    out = df[[c for c in cols if c in df.columns]].copy()
    if "MarginSafety" in out.columns:
        out["MarginSafety"] = out["MarginSafety"].apply(fmt_pct)
    if "Upside%" in out.columns:
        out["Upside%"] = out["Upside%"].apply(fmt_pct)
    return out


# =========================================================
# 입력 영역 - 사이드바
# =========================================================
with st.sidebar:
    st.header("설정")
    analysis_period = st.selectbox("분석 기간", ["1y", "3y", "5y", "10y"], index=0)
    capital = st.number_input("투자금", min_value=0, value=1_000_000, step=100_000)
    finnhub_api_key = st.text_input("Finnhub API Key", type="password")
    market_mode = st.selectbox(
        "시장 스캔 범위",
        ["자동(자본기준)", "미국 전체 유니버스", "한국 전체 유니버스", "미국+한국 전체 유니버스"],
        index=3,
    )
    scan_band_filter = st.multiselect(
        "시장 스캔 시 시총 필터",
        ["small", "mid", "large", "unknown"],
        default=["small", "mid", "large"],
    )
    scan_limit = st.slider("스캔 후보 수", 20, 300, 120, step=10)
    min_score = st.slider("최소 총점", 0, 30, 6)
    top_n = st.slider("표시할 상위 종목 수", 5, 30, 10)
    scan_sort = st.selectbox("시장 스캔 정렬", ["총점", "상승여력", "안전마진", "모멘텀 점수", "마법공식 점수"], index=0)
    only_super_picks = st.checkbox("초강력 종목만 보기", value=False)
    discord_alerts_enabled = st.checkbox("디스코드 알림 켜기", value=True)
    discord_scan_alerts = st.checkbox("시장 스캔 알림도 보내기", value=True)

current_scan_signature = (
    analysis_period,
    market_mode,
    tuple(sorted(scan_band_filter)),
    scan_limit,
    min_score,
    top_n,
    capital,
)
if st.session_state.scan_settings_signature is not None and st.session_state.scan_settings_signature != current_scan_signature:
    st.session_state.scan_results = None
strategy = portfolio_strategy(capital)
st.info(f"현재 전략: **{strategy['label']}**")
st.caption("투자금이 작을수록 소형·중형주에 가중치를 두고, 투자금이 커질수록 대형주에 더 비중을 둡니다.")

with st.expander("점수 기준 보기"):
    st.dataframe(score_criteria_table(), use_container_width=True, hide_index=True)


col_test1, col_test2 = st.columns([1, 3])
with col_test1:
    if st.button("디스코드 테스트"):
        ok = send_discord_message("✅ 디스코드 알림 테스트 메시지입니다.")
        if ok:
            st.success("디스코드 테스트 알림을 보냈습니다.")
        else:
            st.error("디스코드 테스트 알림 전송에 실패했습니다.")
with col_test2:
    st.caption("알림이 너무 많이 가는 걸 막기 위해 같은 종목/같은 신호는 한 번만 보냅니다. 앱을 새로 실행하면 다시 보낼 수 있습니다.")

with st.expander("최근 패치 내용"):
    st.markdown("""
    - 시장 스캔이 기간 변경과 함께 다시 계산되도록 보정
    - 미국 유니버스가 비어도 fallback 종목군으로 채우도록 수정
    - 한 줄 판단 저장 버그 수정
    - 소액 투자 전략 반환 버그 수정
    - 시장 스캔에 데이터 품질, 선정 이유, 미국/한국 구분 추가
    - 총점 외에 상승여력/안전마진 정렬 옵션 추가
    - 모멘텀 점수, 마법공식 점수, 스타일 스티커 추가
    - 포트폴리오 위험 분석, 투자금 기준 기대수익/최악손실 표 추가
    - 초강력 종목 필터, 매수 타이밍 알림, 빠른 비교 기능 추가
    - 디스코드 실시간 알림, 테스트 버튼, 중복 알림 방지 추가
    - 앱 안에서 GitHub monitor_config.json을 저장하는 알림 설정 탭 추가
    - 모바일에서 상단 바가 덜 보이도록 숨김 스타일 추가
    """)

# =========================================================
# 검색 및 포트폴리오 버튼
# =========================================================
st.subheader("🔎 종목 검색")
search_c1, search_c2, search_c3, search_c4 = st.columns([3, 1, 1, 1])
with search_c1:
    ticker = st.text_input("티커 입력", st.session_state.last_ticker, key="main_ticker").strip().upper()
with search_c2:
    btn_analyze = st.button("종목 분석")
with search_c3:
    btn_add_portfolio = st.button("포트폴리오 추가")
with search_c4:
    btn_clear_portfolio = st.button("포트폴리오 비우기")

compare_text = st.text_input("빠른 비교용 티커 (쉼표로 구분)", "AAPL,MSFT,NVDA")
compare_list = [x.strip().upper() for x in compare_text.split(",") if x.strip()]

# =========================================================
# 유니버스 빌더
# =========================================================
@st.cache_data(ttl=3600)
def get_wikipedia_table(url: str) -> pd.DataFrame:
    """위키피디아 표에서 티커 목록 읽기."""
    try:
        tables = pd.read_html(url)
        if tables:
            return tables[0]
    except Exception:
        pass
    return pd.DataFrame()



US_FALLBACK_LARGE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
    "MA","UNH","LLY","XOM","AVGO","COST","WMT","PG","JNJ","HD","ABBV","KO"
]
US_FALLBACK_MID = [
    "AMD","CRM","ADBE","NFLX","QCOM","TXN","AMAT","PANW","MU","INTU",
    "UBER","SHOP","SNOW","PLTR","CRWD","ANET","KLAC","CDNS","APH","DE"
]
US_FALLBACK_SMALL = [
    "NET","ZS","OKTA","ROKU","HOOD","SOFI","RIVN","LCID","BILL","PATH",
    "FSLY","UPST","AFRM","CFLT","IONQ","RKLB","ASTS","CELH","DUOL","TTD"
]

def dedupe_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

@st.cache_data(ttl=3600)
def get_us_universe() -> list:
    """미국 대형/중형/소형주 기본 유니버스 (S&P500, 400, 600, 나스닥100)."""
    tickers = []
    urls = [
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "https://en.wikipedia.org/wiki/Nasdaq-100",
    ]
    for url in urls:
        df = get_wikipedia_table(url)
        if df.empty:
            continue
        cols = [c.lower() for c in df.columns.astype(str)]
        symbol_col = None
        for candidate in ["symbol", "ticker", "tickers"]:
            if candidate in cols:
                symbol_col = df.columns[cols.index(candidate)]
                break
        if symbol_col is None:
            continue
        for raw in df[symbol_col].dropna().tolist():
            t = str(raw).strip().upper().replace(".", "-")
            if t:
                tickers.append(t)
    if not tickers:
        tickers = US_FALLBACK_LARGE + US_FALLBACK_MID + US_FALLBACK_SMALL
    else:
        tickers.extend(US_FALLBACK_LARGE + US_FALLBACK_MID + US_FALLBACK_SMALL)
    return dedupe_keep_order(tickers)


@st.cache_data(ttl=3600)
def get_krx_universe() -> list:
    """한국 시장 전체 유니버스 (코스피/코스닥)"""
    tickers = []
    if pykrx_stock is not None:
        try:
            today = datetime.now().strftime("%Y%m%d")
            for market, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
                codes = pykrx_stock.get_market_ticker_list(today, market=market)
                for code in codes:
                    tickers.append(f"{str(code).zfill(6)}{suffix}")
        except Exception:
            pass
    if not tickers:
        # fallback 샘플 (주요 대형/중형/소형 기업)
        tickers = [
            "005930.KS", "000660.KS", "035420.KS", "051910.KS", "068270.KS", "207940.KS",
            "005380.KS", "006400.KS", "035720.KS", "066570.KS", "086790.KS", "028260.KS",
            "247540.KQ", "196170.KQ", "091990.KQ", "263750.KQ", "293490.KQ", "068760.KQ",
        ]
    # 중복 제거
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_universe(mode: str) -> list:
    """스캔 범위에 따라 유니버스 반환."""
    if mode == "미국 전체 유니버스":
        base = get_us_universe()
    elif mode == "한국 전체 유니버스":
        base = get_krx_universe()
    else:
        base = get_us_universe() + get_krx_universe()
    # 중복 제거
    seen = set()
    out = []
    for t in base:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

# =========================================================
# 데이터 가져오기
# =========================================================
@st.cache_data(ttl=120)
def fetch_snapshot(ticker: str, period: str):
    """특정 종목의 스냅샷 정보와 가격 히스토리 가져오기."""
    try:
        s = yf.Ticker(ticker)
        # info
        try:
            info = json.loads(json.dumps(s.info or {}, default=str))
        except Exception:
            info = {}
        # fast_info
        try:
            fast = json.loads(json.dumps(dict(s.fast_info) if s.fast_info else {}, default=str))
        except Exception:
            fast = {}
        # 역사 데이터
        try:
            hist = s.history(period=period, auto_adjust=False, actions=True)
        except Exception:
            hist = pd.DataFrame()
        return info, fast, hist
    except Exception:
        return {}, {}, pd.DataFrame()


def get_current_price(info: dict, fast: dict):
    return safe_float(fast.get("lastPrice")) or safe_float(info.get("currentPrice"))


def get_market_cap(info: dict, fast: dict):
    return safe_float(fast.get("marketCap")) or safe_float(info.get("marketCap"))

# =========================================================
# 목표가 / 애널리스트 데이터
# =========================================================
@st.cache_data(ttl=300)
def get_yfinance_targets(ticker: str):
    """Yahoo Finance 목표가 (평균, 최고, 최저)"""
    try:
        s = yf.Ticker(ticker)
        ap = getattr(s, "analyst_price_targets", None)
        if isinstance(ap, dict):
            return safe_float(ap.get("mean")), safe_float(ap.get("high")), safe_float(ap.get("low"))
        info = s.info or {}
        return safe_float(info.get("targetMeanPrice")), safe_float(info.get("targetHighPrice")), safe_float(info.get("targetLowPrice"))
    except Exception:
        pass
    return None, None, None


@st.cache_data(ttl=300)
def get_finnhub_targets(ticker: str, api_key: str):
    """Finnhub 목표가 (평균, 최고, 최저)"""
    if not api_key:
        return None, None, None
    try:
        url = f"https://finnhub.io/api/v1/stock/price-target?symbol={ticker}&token={api_key}"
        data = requests.get(url, timeout=8).json()
        return safe_float(data.get("targetMean")), safe_float(data.get("targetHigh")), safe_float(data.get("targetLow"))
    except Exception:
        return None, None, None


def combine_targets(*means):
    """목표가 평균값 여러 개를 평균하여 하나의 값으로."""
    vals = [v for v in means if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def analyst_source_text(has_yf: bool, has_fh: bool) -> str:
    """목표가 출처 텍스트."""
    if has_yf and has_fh:
        return "Yahoo Finance + Finnhub 공개 컨센서스"
    if has_fh:
        return "Finnhub 공개 컨센서스"
    if has_yf:
        return "Yahoo Finance 공개 컨센서스"
    return "공개 컨센서스 없음"


def analyst_count(info: dict) -> int:
    return safe_int(info.get("numberOfAnalystOpinions"))


def consensus_label(info: dict) -> str:
    return info.get("recommendationKey") or "N/A"


def target_explanation(price, target_mean, roe, margin, debt, growth, pe, recommendation_key, target_source):
    """목표가 해설 텍스트 생성."""
    parts = []
    if price is not None and target_mean is not None and price > 0:
        gap = (target_mean / price - 1) * 100
        if gap > 15:
            parts.append("목표가가 현재가보다 상당히 높은 편이라 성장 기대를 반영했을 수 있습니다.")
        elif gap < -10:
            parts.append("목표가가 현재가보다 낮게 설정되어 있어 실적 둔화나 밸류 부담을 반영했을 수 있습니다.")
        else:
            parts.append("목표가가 현재가와 비슷하여 시장의 중립적 전망이 반영됐을 가능성이 큽니다.")

    if roe is not None and roe > 0.15:
        parts.append("ROE가 높아 자본 효율이 좋은 편입니다.")
    if margin is not None and margin > 0.2:
        parts.append("이익률이 높아 가격에 긍정적으로 작용할 수 있습니다.")
    if debt is not None and debt > 100:
        parts.append("부채비율이 높으면 목표가가 보수적으로 잡힐 수 있습니다.")
    if growth is not None and growth > 0.15:
        parts.append("성장률이 높아 장기 기대가 반영됐을 수 있습니다.")
    if pe is not None:
        if pe > 30:
            parts.append("PER이 높아 이미 기대가 반영됐을 가능성이 있습니다.")
        elif pe < 15:
            parts.append("PER이 낮아 가치주로 평가될 수 있습니다.")

    if recommendation_key and recommendation_key != "N/A":
        parts.append(f"컨센서스 평가: {recommendation_key}.")
    parts.append(f"분석 출처: {target_source}.")
    if not parts:
        parts.append("공개 데이터만으로는 목표가 해설을 제공하기 어렵습니다.")
    return " ".join(parts)

# =========================================================
# 내재가치/적정가 계산
# =========================================================
def calc_peg(info: dict):
    try:
        pe = safe_float(info.get("trailingPE")) or safe_float(info.get("forwardPE"))
        growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
        if pe is not None and growth is not None and growth > 0:
            return pe / (growth * 100)
    except Exception:
        pass
    return None


def calc_intrinsic_graham_like(info: dict):
    """그레이엄식 내재가치(보수적)"""
    try:
        eps = safe_float(info.get("trailingEps"))
        growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
        if eps is None or eps <= 0 or growth is None or growth <= 0:
            return None
        growth = min(max(growth, 0.02), 0.15)
        future_eps = eps * ((1 + growth) ** 10)
        intrinsic = future_eps / (1.10 ** 10)
        return intrinsic * 0.70
    except Exception:
        return None


def calc_buffett_fair_value(info: dict):
    """버핏식 적정가."""
    try:
        eps = safe_float(info.get("trailingEps"))
        roe = safe_float(info.get("returnOnEquity")) or 0.0
        margin = safe_float(info.get("profitMargins")) or 0.0
        debt = safe_float(info.get("debtToEquity")) or 0.0
        if eps is None or eps <= 0:
            return None
        fair_pe = 15.0
        fair_pe += min(max((roe * 100 - 15) * 0.35, -5), 10)
        fair_pe += min(max(margin * 20, -3), 6)
        if debt > 100:
            fair_pe -= min((debt - 100) / 100, 5)
        fair_pe = max(8, min(fair_pe, 30))
        return eps * fair_pe * 0.85
    except Exception:
        return None


def calc_lynch_fair_value(info: dict, peg_value):
    """린치식 적정가."""
    try:
        eps = safe_float(info.get("trailingEps"))
        growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
        if eps is None or eps <= 0 or growth is None or growth <= 0:
            return None
        if peg_value is not None and peg_value > 0:
            fair_pe = min(max(growth * 100, 8), 35)
        else:
            fair_pe = min(max(growth * 100, 8), 25)
        return eps * fair_pe
    except Exception:
        return None


def calc_intrinsic_bundle(info: dict, target_mean: float):
    """여러 방식으로 내재가치를 계산하고 가능한 값 중 하나를 반환."""
    graham = calc_intrinsic_graham_like(info)
    buffett_val = calc_buffett_fair_value(info)
    lynch_val = calc_lynch_fair_value(info, calc_peg(info))
    for val, source in [
        (graham, "보수적 내재가치"),
        (buffett_val, "버핏식 적정가"),
        (lynch_val, "린치식 적정가"),
        (target_mean * 0.9 if target_mean is not None else None, "목표가 기반 보정값"),
    ]:
        if val is not None:
            return val, source
    return None, "N/A"

# =========================================================
# 점수 및 필터
# =========================================================

def momentum_score(info: dict, hist: pd.DataFrame) -> int:
    score = 0
    if hist is None or hist.empty or "Close" not in hist.columns:
        return 0
    close = hist["Close"].dropna()
    if len(close) >= 60:
        ret_6m = close.iloc[-1] / close.iloc[max(0, len(close)-126)] - 1 if len(close) > 126 else close.iloc[-1] / close.iloc[0] - 1
        ret_1y = close.iloc[-1] / close.iloc[0] - 1
        if ret_1y > 0.20:
            score += 4
        elif ret_1y > 0.10:
            score += 2
        if ret_6m > 0.10:
            score += 2
    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    price = float(close.iloc[-1]) if not close.empty else None
    if price and ma50 and price > ma50:
        score += 2
    if ma50 and ma200 and ma50 > ma200:
        score += 2
    return min(score, 10)


def magic_formula_score(info: dict) -> int:
    score = 0
    ebitda = safe_float(info.get("ebitda"))
    ev = safe_float(info.get("enterpriseValue"))
    roe = safe_float(info.get("returnOnEquity"))
    op_margin = safe_float(info.get("operatingMargins"))
    if ebitda is not None and ev is not None and ev > 0:
        ey = ebitda / ev
        if ey > 0.08:
            score += 5
        elif ey > 0.05:
            score += 3
    if roe is not None and roe > 0.15:
        score += 3
    if op_margin is not None and op_margin > 0.15:
        score += 2
    return min(score, 10)


def style_tags(row):
    tags = []
    if row.get("Buffett", 0) >= 7:
        tags.append("🟢버핏")
    if row.get("Lynch", 0) >= 7:
        tags.append("🔵린치")
    if row.get("MomentumScore", 0) >= 7:
        tags.append("🔥모멘텀")
    if row.get("MagicFormulaScore", 0) >= 7:
        tags.append("🟡마법공식")
    if row.get("RetentionRatio") is not None and row.get("RetentionRatio", 0) > 50:
        tags.append("🛡️방어")
    return " | ".join(tags) if tags else "기타"

def buffett_score(info: dict) -> int:
    score = 0
    roe = safe_float(info.get("returnOnEquity"))
    debt = safe_float(info.get("debtToEquity"))
    margin = safe_float(info.get("profitMargins"))
    fcf = safe_float(info.get("freeCashflow"))
    if roe is not None and roe > 0.15:
        score += 3
    if debt is not None and debt < 100:
        score += 2
    if margin is not None and margin > 0.20:
        score += 2
    if fcf is not None and fcf > 0:
        score += 3
    return min(score, 10)


def buffett_filter(info: dict):
    roe = safe_float(info.get("returnOnEquity"))
    debt = safe_float(info.get("debtToEquity"))
    margin = safe_float(info.get("profitMargins"))
    fcf = safe_float(info.get("freeCashflow"))
    ok = True
    reasons = []
    if roe is None or roe <= 0.15:
        ok = False
        reasons.append("ROE")
    if debt is not None and debt >= 100:
        ok = False
        reasons.append("부채")
    if margin is not None and margin <= 0.15:
        ok = False
        reasons.append("마진")
    if fcf is not None and fcf <= 0:
        ok = False
        reasons.append("FCF")
    return ok, (", ".join(reasons) if reasons else "통과")


def lynch_score(info: dict, peg_value) -> int:
    score = 0
    if peg_value is not None:
        if peg_value < 1:
            score += 5
        elif peg_value < 2:
            score += 3
    growth = safe_float(info.get("earningsGrowth"))
    revenue_growth = safe_float(info.get("revenueGrowth"))
    if growth is not None and growth > 0.15:
        score += 3
    if revenue_growth is not None and revenue_growth > 0.10:
        score += 2
    return min(score, 10)


def lynch_filter(info: dict, peg_value):
    growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
    if peg_value is None or growth is None:
        return False, "데이터 부족"
    if peg_value < 2.0 and growth > 0.10:
        return True, "통과"
    return False, "PEG/성장"


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


def get_ma(close_series: pd.Series, window: int):
    if close_series is None or len(close_series) < window:
        return None
    val = close_series.rolling(window).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def buy_timing_score(price, intrinsic, hist: pd.DataFrame, target_mean):
    score = 0
    close = hist["Close"].dropna() if not hist.empty and "Close" in hist.columns else pd.Series(dtype=float)
    ma50 = get_ma(close, 50)
    ma200 = get_ma(close, 200)
    rsi = calc_rsi(close)
    # 가격과 내재가치/목표가 비교
    if price is not None and intrinsic is not None:
        if price < intrinsic * 0.75:
            score += 4
        elif price < intrinsic:
            score += 2
    if price is not None and target_mean is not None and price < target_mean * 0.90:
        score += 1
    # 이동평균 추세
    if ma50 is not None and price is not None and price > ma50:
        score += 1
    if ma50 is not None and ma200 is not None and ma50 > ma200:
        score += 2
    # RSI 과매도 여부
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
    # 가격과 내재가치 비교
    if price is not None and intrinsic is not None:
        if price > intrinsic * 1.25:
            score += 3
        elif price > intrinsic * 1.10:
            score += 2
    if price is not None and target_mean is not None and price > target_mean * 1.10:
        score += 2
    # RSI 과매수 여부
    if rsi is not None:
        if rsi > 70:
            score += 2
        elif rsi > 60:
            score += 1
    # 이동평균 데드크로스
    if ma50 is not None and ma200 is not None and ma50 < ma200:
        score += 2
    # 52주 신고점 근접 여부
    if not close.empty and price is not None:
        window = close.tail(252) if len(close) >= 20 else close
        if not window.empty:
            high_52w = float(window.max())
            if high_52w > 0 and price >= high_52w * 0.98:
                score += 1
    return min(score, 10)


def decision_text(buy_score, sell_score, price, intrinsic):
    """매수/매도 시그널 종합 판단."""
    if buy_score >= 7 and sell_score <= 3 and price is not None and intrinsic is not None and price < intrinsic:
        return "💎 강력 매수 후보"
    if sell_score >= 7:
        return "🔴 비중 축소/매도 경고"
    if buy_score >= 5:
        return "🟡 관찰/분할매수"
    return "⚪ 대기"


def cap_fit_score(band: str) -> int:
    return strategy["bias"].get(band, strategy["bias"].get("unknown", 1))

# =========================================================
# 재무제표 / 현금흐름표
# =========================================================
@st.cache_data(ttl=300)
def get_financial_statements(ticker: str):
    """연간/분기 재무제표와 현금흐름표 가져오기."""
    try:
        s = yf.Ticker(ticker)
        return {
            "annual_income": safe_df(getattr(s, "income_stmt", None)),
            "quarterly_income": safe_df(getattr(s, "quarterly_income_stmt", None)),
            "annual_balance": safe_df(getattr(s, "balance_sheet", None)),
            "quarterly_balance": safe_df(getattr(s, "quarterly_balance_sheet", None)),
            "annual_cashflow": safe_df(getattr(s, "cashflow", None)),
            "quarterly_cashflow": safe_df(getattr(s, "quarterly_cashflow", None)),
        }
    except Exception:
        return {
            "annual_income": pd.DataFrame(),
            "quarterly_income": pd.DataFrame(),
            "annual_balance": pd.DataFrame(),
            "quarterly_balance": pd.DataFrame(),
            "annual_cashflow": pd.DataFrame(),
            "quarterly_cashflow": pd.DataFrame(),
        }


def prettify_statement(df: pd.DataFrame, max_rows: int = 20) -> pd.DataFrame:
    """재무제표 시각화를 위해 포맷 정리."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.index = out.index.astype(str)
    if out.shape[1] > 0:
        out = out.transpose()
    try:
        out = out.sort_index(axis=1)
    except Exception:
        pass
    return out.head(max_rows)


# =========================================================
# 주주수익률 (배당 반영)
# =========================================================
@st.cache_data(ttl=300)
def shareholder_return_table(ticker: str) -> pd.DataFrame:
    """1,3,5,10년 주주수익률과 CAGR 계산."""
    try:
        s = yf.Ticker(ticker)
        hist = s.history(period="10y", auto_adjust=False, actions=True)
        if hist.empty:
            return pd.DataFrame()
        series = hist["Adj Close"] if "Adj Close" in hist.columns else hist["Close"]
        series = series.dropna()
        if series.empty:
            return pd.DataFrame()
        end_price = float(series.iloc[-1])
        end_date = series.index[-1]
        rows = []
        for years in [1, 3, 5, 10]:
            start_date = end_date - pd.DateOffset(years=years)
            prior = series[series.index <= start_date]
            start_price = float(prior.iloc[-1]) if not prior.empty else float(series.iloc[0])
            total_return = (end_price / start_price - 1) * 100
            cagr = ((end_price / start_price) ** (1 / years) - 1) * 100
            rows.append({
                "기간": f"{years}년", 
                "시작가": round(start_price, 2), 
                "종료가": round(end_price, 2), 
                "주주수익률(배당반영)": round(total_return, 1), 
                "연환산수익률(CAGR)": round(cagr, 1),
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# =========================================================
# 간단 백테스트
# =========================================================
def simple_backtest(hist: pd.DataFrame) -> pd.DataFrame:
    """MA50/MA200 골든크로스 전략과 buy&hold 비교."""
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.DataFrame()
    df = hist[["Close"]].copy().dropna()
    if len(df) < 220:
        return pd.DataFrame()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    df["Signal"] = (df["MA50"] > df["MA200"]).astype(int)
    df["Return"] = df["Close"].pct_change().fillna(0)
    df["Strategy"] = df["Signal"].shift(1).fillna(0) * df["Return"]
    equity = (1 + df["Strategy"]).cumprod()
    buy_hold = (1 + df["Return"]).cumprod()
    return pd.DataFrame({"Equity": equity, "BuyHold": buy_hold})

# =========================================================
# 종목 분석 종합
# =========================================================
def analyze_ticker(ticker: str, period: str, api_key: str) -> dict:
    info, fast, hist = fetch_snapshot(ticker, period)
    p = get_current_price(info, fast)
    market_cap = get_market_cap(info, fast)
    band = band_from_market_cap(market_cap)
    market_label = "한국" if ticker.endswith(".KS") or ticker.endswith(".KQ") else "미국"
    peg_val = calc_peg(info)
    buff = buffett_score(info)
    b_ok, b_why = buffett_filter(info)
    lyn = lynch_score(info, peg_val)
    l_ok, l_why = lynch_filter(info, peg_val)
    # 목표가 정보
    yf_mean, yf_high, yf_low = get_yfinance_targets(ticker)
    fh_mean, fh_high, fh_low = get_finnhub_targets(ticker, api_key)
    target_mean = combine_targets(yf_mean, fh_mean)
    # 내재가치
    intrinsic, intrinsic_source = calc_intrinsic_bundle(info, target_mean)
    if intrinsic is None and p is not None:
        intrinsic = p
        intrinsic_source = "현재가 보정값"
    # 안전 값 보정과 추가 메트릭
    buffett_fair = calc_buffett_fair_value(info)
    lynch_fair = calc_lynch_fair_value(info, peg_val)
    if buffett_fair is None:
        buffett_fair = intrinsic
    if lynch_fair is None:
        lynch_fair = intrinsic
    # 안전마진: 내재가치와 현재가 비교
    margin_safety = None
    if p and intrinsic:
        margin_safety = (intrinsic / p - 1) * 100
    # 주주이익률: 배당 및 자사주매입 합산
    shareholder_yield = None
    div_yield = safe_float(info.get("dividendYield"))
    buyback_yield = safe_float(info.get("buybackYield"))
    if div_yield is not None:
        shareholder_yield = div_yield * 100
    if buyback_yield is not None:
        shareholder_yield = (shareholder_yield or 0) + buyback_yield * 100
    # 이익유보율: 배당성향 기반(1 - payout)
    retention_ratio = None
    payout = safe_float(info.get("payoutRatio"))
    if payout is not None:
        retention_ratio = (1 - payout) * 100
    # 타이밍 및 위험 점수
    momentum_s = momentum_score(info, hist)
    magic_s = magic_formula_score(info)
    buy_s = buy_timing_score(p, intrinsic, hist, target_mean)
    sell_s = sell_risk_score(p, intrinsic, hist, target_mean)
    fit_s = cap_fit_score(band)
    total = buff + lyn + momentum_s + magic_s + buy_s + fit_s - sell_s
    # 추가 정보
    rec_key = consensus_label(info)
    analyst_num = analyst_count(info)
    source_txt = analyst_source_text(yf_mean is not None, fh_mean is not None)
    upside = None
    downside = None
    if p is not None and target_mean is not None and p > 0:
        upside = (target_mean / p - 1) * 100
    # downside는 핀허브 낮은값 우선, 없으면 yfinance 낮은값 기준
    low_target = fh_low if fh_low is not None else yf_low
    if p is not None and low_target is not None and p > 0:
        downside = (low_target / p - 1) * 100
    # ROE/마진/부채/성장/PE for 설명
    roe = safe_float(info.get("returnOnEquity"))
    margin = safe_float(info.get("profitMargins"))
    debt = safe_float(info.get("debtToEquity"))
    growth = safe_float(info.get("earningsGrowth")) or safe_float(info.get("revenueGrowth"))
    pe_val = safe_float(info.get("trailingPE")) or safe_float(info.get("forwardPE"))
    reason = target_explanation(p, target_mean, roe, margin, debt, growth, pe_val, rec_key, source_txt)
    risk = sell_risk_score(p, intrinsic, hist, target_mean)
    risk_lvl = risk_level(risk)
    result = {
        "Ticker": ticker,
        "Price": p,
        "MarketCap": market_cap,
        "Band": band,
        "Market": market_label,
        "PEG": peg_val,
        "Buffett": buff,
        "Lynch": lyn,
        "MomentumScore": momentum_s,
        "MagicFormulaScore": magic_s,
        "Intrinsic": intrinsic,
        "IntrinsicSource": intrinsic_source,
        "BuffettFair": buffett_fair,
        "LynchFair": lynch_fair,
        "MarginSafety": margin_safety,
        "ShareholderYield": shareholder_yield,
        "RetentionRatio": retention_ratio,
        "BuyTiming": buy_s,
        "SellRisk": sell_s,
        "RiskLevel": risk_lvl,
        "Fit": fit_s,
        "TotalScore": total,
        "BuffettFilter": b_ok,
        "BuffettFilterWhy": b_why,
        "LynchFilter": l_ok,
        "LynchFilterWhy": l_why,
        "YF Target Mean": yf_mean,
        "YF Target High": yf_high,
        "YF Target Low": yf_low,
        "Finnhub Target Mean": fh_mean,
        "Finnhub Target High": fh_high,
        "Finnhub Target Low": fh_low,
        "Target Mean": target_mean,
        "Upside%": upside,
        "Downside%": downside,
        "Consensus": rec_key,
        "AnalystCount": analyst_num,
        "TargetSource": source_txt,
        "Reason": reason,
        "ValuationZone": valuation_zone(p, intrinsic, target_mean),
        "Info": info,
        "Fast": fast,
        "Hist": hist,
    }
    result["StyleTags"] = style_tags(result)
    result["AlertMessage"] = alert_message(result)
    result["SuperPick"] = super_pick_label(result)
    result["OneLineSummary"] = one_line_summary(result)
    result["DataQuality"] = data_quality_label(result)
    result["WhySelected"] = why_selected_summary(result)
    return result

# =========================================================
# 시장 스캔
# =========================================================
def scan_universe(candidates: list, period: str, api_key: str, limit: int = 120, allowed_bands=None) -> pd.DataFrame:
    """후보군을 빠르게 평가하여 상위 종목 선택."""
    quick_rows = []
    for t in candidates:
        try:
            # 후보군을 추려낼 때도 사용자가 선택한 기간을 반영해 최근 데이터를 평가합니다.
            # 기존에는 고정된 6개월 데이터를 사용했으나, 분석 기간에 맞춰 동적으로 동조하도록 수정했습니다.
            info, fast, _ = fetch_snapshot(t, period)
            p = get_current_price(info, fast)
            mc = get_market_cap(info, fast)
            if p is None or p <= 0:
                continue
            if mc is None or mc <= 0:
                continue
            band = band_from_market_cap(mc)
            if allowed_bands and band not in allowed_bands:
                continue
            qscore = cap_fit_score(band)
            quick_rows.append({"Ticker": t, "QuickScore": qscore, "MarketCap": mc, "Band": band})
        except Exception:
            continue
    if not quick_rows or len(quick_rows) < 8:
        fallback_seed = candidates[: min(max(limit, 40), len(candidates))]
        fallback_rows = []
        for t in fallback_seed:
            try:
                row = analyze_ticker(t, period, api_key)
                if row.get("Price") is not None:
                    fallback_rows.append(row)
            except Exception:
                continue
        return pd.DataFrame(fallback_rows).sort_values("TotalScore", ascending=False) if fallback_rows else pd.DataFrame()
    qdf = pd.DataFrame(quick_rows)
    qdf = qdf.sort_values(["QuickScore", "MarketCap"], ascending=[False, False]).head(limit)
    selected = qdf["Ticker"].tolist()
    detailed = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for row in ex.map(lambda x: analyze_ticker(x, period, api_key), selected):
            detailed.append(row)
    df = pd.DataFrame(detailed)
    if df.empty:
        return df
    return df.sort_values("TotalScore", ascending=False)

# =========================================================
# 버튼 동작 - 종목 분석 / 포트폴리오
# =========================================================
if btn_analyze and ticker:
    st.session_state.last_ticker = ticker
    st.session_state.last_result = analyze_ticker(ticker, analysis_period, finnhub_api_key)
if btn_add_portfolio and ticker:
    if ticker not in st.session_state.portfolio:
        st.session_state.portfolio.append(ticker)
        st.success(f"{ticker}를 포트폴리오에 추가했습니다.")
    else:
        st.info("이미 포트폴리오에 있는 종목입니다.")
if btn_clear_portfolio:
    st.session_state.portfolio = []
    st.success("포트폴리오를 비웠습니다.")
if st.button("시장 스캔 시작"):
    universe = build_universe(market_mode)
    with st.spinner(f"총 {len(universe)}개 후보 스캔 중..."):
        st.session_state.scan_results = scan_universe(
            universe,
            analysis_period,
            finnhub_api_key,
            limit=scan_limit,
            allowed_bands=scan_band_filter,
        )
    st.session_state.scan_settings_signature = current_scan_signature

# =========================================================
# 탭 구성
# =========================================================
current = st.session_state.last_result
tabs = st.tabs(["종목 분석", "목표가/해설", "재무제표", "주주수익률", "포트폴리오", "시장 스캔", "백테스트/통계", "알림 설정"])

with tabs[0]:  # 종목 분석
    st.subheader("🔍 종목 분석 결과")
    if current is None:
        st.info("티커를 입력한 후 '종목 분석' 버튼을 눌러 결과를 확인하세요.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("현재가", fmt_price(current["Price"]))
        c2.metric("시가총액", fmt_market_cap(current["MarketCap"]))
        c3.metric("버핏 점수", f"{current['Buffett']}/10")
        c4.metric("린치 점수", f"{current['Lynch']}/10")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("매수 타이밍", f"{current['BuyTiming']}/10")
        c6.metric("매도 경고", f"{current['SellRisk']}/10")
        c7.metric("총점", f"{current['TotalScore']:.1f}")
        c8.metric("밸류 구간", current["ValuationZone"])
        n1, n2, n3 = st.columns(3)
        n1.metric("모멘텀 점수", f"{current.get('MomentumScore', 0)}/10")
        n2.metric("마법공식 점수", f"{current.get('MagicFormulaScore', 0)}/10")
        n3.metric("투자 스타일", current.get("StyleTags", "기타"))
        st.write(f"판단: **{decision_text(current['BuyTiming'], current['SellRisk'], current['Price'], current['Intrinsic'])}**")
        st.caption(f"한 줄 판단: {current.get('OneLineSummary', '')}")
        if current.get("SuperPick"):
            st.success(current.get("SuperPick"))
        if current.get("AlertMessage") and current.get("AlertMessage") != "알림 없음":
            st.warning(current.get("AlertMessage"))

        if discord_alerts_enabled:
            if current.get("BuyTiming", 0) >= 7 and current.get("SellRisk", 0) <= 3:
                send_discord_alert_once(
                    f"BUY::{current['Ticker']}",
                    f"🔥 매수 타이밍 감지: {current['Ticker']}\n"
                    f"현재가: {fmt_price(current['Price'])}\n"
                    f"총점: {current['TotalScore']:.1f}\n"
                    f"스타일: {current.get('StyleTags', '기타')}\n"
                    f"한 줄 판단: {current.get('OneLineSummary', '')}"
                )
            if current.get("SellRisk", 0) >= 8:
                send_discord_alert_once(
                    f"SELL::{current['Ticker']}",
                    f"🚨 매도 경고 감지: {current['Ticker']}\n"
                    f"현재가: {fmt_price(current['Price'])}\n"
                    f"매도 경고: {current['SellRisk']}/10\n"
                    f"스타일: {current.get('StyleTags', '기타')}\n"
                    f"한 줄 판단: {current.get('OneLineSummary', '')}"
                )
            if current.get("SuperPick") == "🔥 초강력 종목":
                send_discord_alert_once(
                    f"SUPER::{current['Ticker']}",
                    f"💎 초강력 종목 발견: {current['Ticker']}\n"
                    f"현재가: {fmt_price(current['Price'])}\n"
                    f"총점: {current['TotalScore']:.1f}\n"
                    f"상승여력: {fmt_pct(current.get('Upside%'))}\n"
                    f"스타일: {current.get('StyleTags', '기타')}"
                )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("안전마진", fmt_pct(current.get("MarginSafety")))
        m2.metric("주주이익률", fmt_pct(current.get("ShareholderYield")))
        m3.metric("이익유보율", fmt_pct(current.get("RetentionRatio")))
        m4.metric("하락여력", fmt_pct(current.get("Downside%")))
        st.write({
            "버핏 필터": "통과" if current["BuffettFilter"] else f"탈락 ({current['BuffettFilterWhy']})",
            "데이터 품질": current.get("DataQuality", "N/A"),
            "선정 이유": current.get("WhySelected", ""),
            "투자 스타일": current.get("StyleTags", "기타"),
            "매수/매도 알림": current.get("AlertMessage", "알림 없음"),
            "린치 필터": "통과" if current["LynchFilter"] else f"탈락 ({current['LynchFilterWhy']})",
            "PEG": fmt_ratio(current["PEG"]),
            "내재가치": fmt_price(current["Intrinsic"]),
            "버핏식 적정가": fmt_price(current["BuffettFair"]),
            "린치식 적정가": fmt_price(current["LynchFair"]),
            "안전마진": fmt_pct(current["MarginSafety"]),
            "주주이익률": fmt_pct(current["ShareholderYield"]),
            "이익유보율": fmt_pct(current["RetentionRatio"]),
            "목표가 평균": fmt_price(current["Target Mean"]),
            "상승여력": fmt_pct(current["Upside%"]),
            "하락여력": fmt_pct(current["Downside%"]),
            "리스크 수준": current["RiskLevel"],
            "컨센서스": current["Consensus"],
            "애널리스트 수": current["AnalystCount"] if current["AnalystCount"] is not None else "N/A",
        })
        # 메시지로 결과 안내
        if current["Upside%"] is not None:
            if current["Upside%"] >= 0:
                st.success(f"목표가 기준 상승여력: {fmt_pct(current['Upside%'])}")
            else:
                st.warning(f"목표가 기준 하락여력: {fmt_pct(current['Upside%'])}")
        if current["SellRisk"] >= 7:
            st.error("매도 경고가 높습니다. 비중 조절을 권장합니다.")
        elif current["BuyTiming"] >= 7 and current["SellRisk"] <= 3:
            st.success("매수 조건이 강합니다.")
        else:
            st.info("관찰 구간입니다.")
        # 캔들 차트 및 이동평균
        hist = current["Hist"]
        if not hist.empty and "Close" in hist.columns:
            close_series = hist["Close"].dropna()
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"], name="가격",
            ))
            if len(close_series) >= 50:
                fig.add_trace(go.Scatter(x=hist.index, y=close_series.rolling(50).mean(), mode="lines", name="MA50"))
            if len(close_series) >= 200:
                fig.add_trace(go.Scatter(x=hist.index, y=close_series.rolling(200).mean(), mode="lines", name="MA200"))
            fig.update_layout(height=560, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("차트 데이터가 부족합니다.")
        if compare_list:
            compare_rows = []
            for cmp_t in compare_list[:8]:
                try:
                    compare_rows.append(analyze_ticker(cmp_t, analysis_period, finnhub_api_key))
                except Exception:
                    continue
            compare_df = pd.DataFrame(compare_rows)
            quick_df = quick_compare_table(compare_df)
            if not quick_df.empty:
                st.markdown("### 빠른 비교")
                st.dataframe(quick_df, use_container_width=True, hide_index=True)

with tabs[1]:  # 목표가/해설
    st.subheader("🎯 목표가와 해설")
    if current is None:
        st.info("먼저 종목 분석을 실행하세요.")
    else:
        st.caption(f"한 줄 판단: {current.get('OneLineSummary', '')}")
        # 목표가 요약
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("YF 목표가 평균", fmt_price(current["YF Target Mean"]))
        r2.metric("Finnhub 목표가 평균", fmt_price(current["Finnhub Target Mean"]))
        r3.metric("종합 예상 주가", fmt_price(current["Target Mean"]))
        r4.metric("컨센서스", current["Consensus"])
        st.write({
            "YF 목표가 최고": fmt_price(current["YF Target High"]),
            "YF 목표가 최저": fmt_price(current["YF Target Low"]),
            "Finnhub 목표가 최고": fmt_price(current["Finnhub Target High"]),
            "Finnhub 목표가 최저": fmt_price(current["Finnhub Target Low"]),
            "상승여력": fmt_pct(current["Upside%"]),
            "하락여력": fmt_pct(current["Downside%"]),
            "분석 출처": current["TargetSource"],
            "이유": current["Reason"],
        })
        # 적정가 비교 테이블
        comp_df = pd.DataFrame([
            {"기준": "버핏식 적정가", "값": current.get("BuffettFair")},
            {"기준": "린치식 적정가", "값": current.get("LynchFair")},
            {"기준": "보수적 내재가치", "값": current.get("Intrinsic")},
            {"기준": "애널리스트 종합 목표가", "값": current.get("Target Mean")},
        ])
        comp_df["값"] = comp_df["값"].apply(fmt_price)
        st.dataframe(comp_df, hide_index=True, use_container_width=True)
        st.caption("개별 애널리스트 이름까지는 무료 API에서 안정적으로 제공되지 않으므로, 공개 컨센서스와 이유를 표시합니다.")

with tabs[2]:  # 재무제표
    st.subheader("📚 재무제표/현금흐름표")
    if not ticker:
        st.info("티커를 입력하세요.")
    else:
        stmts = get_financial_statements(ticker)
        sub_tabs = st.tabs(["연간 손익", "분기 손익", "연간 재무상태표", "분기 재무상태표", "연간 현금흐름", "분기 현금흐름"])
        stmt_keys = [
            "annual_income", "quarterly_income", "annual_balance", "quarterly_balance", "annual_cashflow", "quarterly_cashflow",
        ]
        for tab, key in zip(sub_tabs, stmt_keys):
            with tab:
                df = prettify_statement(stmts.get(key))
                if df.empty:
                    st.warning("데이터가 없습니다.")
                else:
                    st.dataframe(df, use_container_width=True)

with tabs[3]:  # 주주수익률
    st.subheader("📅 1/3/5/10년 주주수익률")
    if not ticker:
        st.info("티커를 입력하세요.")
    else:
        ret_df = shareholder_return_table(ticker)
        if ret_df.empty:
            st.warning("수익률 데이터를 가져오지 못했습니다.")
        else:
            st.dataframe(ret_df, use_container_width=True, hide_index=True)

with tabs[4]:  # 포트폴리오
    st.subheader("💼 포트폴리오")
    st.caption(f"현재 전략: {strategy['label']}")
    if not st.session_state.portfolio:
        st.info("포트폴리오가 비어 있습니다. 종목 분석 후 추가하세요.")
    else:
        rows = []
        for t in st.session_state.portfolio:
            try:
                rows.append(analyze_ticker(t, analysis_period, finnhub_api_key))
            except Exception:
                continue
        pf_df = pd.DataFrame(rows)
        if pf_df.empty:
            st.warning("포트폴리오 정보를 계산할 수 없습니다.")
        else:
            base_scores = pf_df["TotalScore"].clip(lower=1)
            total_base = float(base_scores.sum()) if float(base_scores.sum()) > 0 else 0.0
            if total_base > 0:
                pf_df["추천비중%"] = (base_scores / total_base * 100).round(1)
            else:
                pf_df["추천비중%"] = round(100 / len(pf_df), 1)
            pf_df["권장투입금"] = (pf_df["추천비중%"] / 100 * capital).round(0)
            view = pf_df[[
                "Ticker", "StyleTags", "Band", "Price", "Buffett", "Lynch", "MomentumScore", "MagicFormulaScore", "BuyTiming", "SellRisk", "RiskLevel", "TotalScore",
                "추천비중%", "권장투입금", "Target Mean", "Upside%", "ValuationZone"
            ]].copy()
            view["Price"] = view["Price"].apply(fmt_price)
            view["Target Mean"] = view["Target Mean"].apply(fmt_price)
            view["Upside%"] = view["Upside%"].apply(fmt_pct)
            st.dataframe(view, use_container_width=True, hide_index=True)
            risk_df = portfolio_risk_table(pf_df)
            if not risk_df.empty:
                st.markdown("### 포트폴리오 위험 분석")
                st.dataframe(risk_df, use_container_width=True, hide_index=True)

            mix_df = style_mix_table(pf_df)
            if not mix_df.empty:
                st.markdown("### 스타일 분포")
                st.dataframe(mix_df, use_container_width=True, hide_index=True)

            outcome_df = capital_outcome_table(pf_df, capital)
            if not outcome_df.empty:
                st.markdown("### 내가 지금 투자하면")
                st.dataframe(outcome_df, use_container_width=True, hide_index=True)

with tabs[5]:  # 시장 스캔
    st.subheader("🌍 시장 스캔")
    if st.button("현재 설정으로 다시 스캔"):
        universe = build_universe(market_mode)
        with st.spinner(f"총 {len(universe)}개 후보를 다시 살펴보는 중..."):
            st.session_state.scan_results = scan_universe(
                universe,
                analysis_period,
                finnhub_api_key,
                limit=scan_limit,
                allowed_bands=scan_band_filter,
            )
        st.session_state.scan_settings_signature = current_scan_signature
    st.caption(f"미국은 S&P 지수, 나스닥100; 한국은 코스피/코스닥 전체에서 후보를 스캔합니다. 현재 선택한 분석 기간({analysis_period})도 스캔에 같이 반영됩니다.")
    scan_df = st.session_state.scan_results
    if scan_df is None or scan_df.empty:
        st.info("시장 스캔을 시작하세요. 기간이나 필터를 바꾸면 이전 결과는 자동으로 지워집니다.")
    else:
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("스캔 종목 수", f"{len(scan_df):,}")
        x2.metric("현재 기간", analysis_period)
        x3.metric("최고 총점", f"{scan_df['TotalScore'].max():.1f}" if not scan_df.empty else "N/A")
        us_count = int((scan_df["Market"] == "미국").sum()) if "Market" in scan_df.columns else 0
        kr_count = int((scan_df["Market"] == "한국").sum()) if "Market" in scan_df.columns else 0
        x4.metric("미국/한국", f"{us_count}/{kr_count}")
        filt = scan_df[scan_df["TotalScore"] >= min_score].copy()
        if filt.empty:
            st.warning("조건에 맞는 종목이 없습니다. 상위 종목을 보여드립니다.")
            filt = scan_df.copy()
        if only_super_picks and "SuperPick" in filt.columns:
            filt = filt[filt["SuperPick"] == "🔥 초강력 종목"].copy()
        if scan_sort == "상승여력":
            filt = filt.sort_values("Upside%", ascending=False, na_position="last").head(top_n)
        elif scan_sort == "안전마진":
            filt = filt.sort_values("MarginSafety", ascending=False, na_position="last").head(top_n)
        elif scan_sort == "모멘텀 점수":
            filt = filt.sort_values("MomentumScore", ascending=False, na_position="last").head(top_n)
        elif scan_sort == "마법공식 점수":
            filt = filt.sort_values("MagicFormulaScore", ascending=False, na_position="last").head(top_n)
        else:
            filt = filt.sort_values("TotalScore", ascending=False).head(top_n)
        disp = filt[[
            "Ticker", "Market", "Band", "StyleTags", "Price", "MarketCap", "Buffett", "Lynch", "MomentumScore", "MagicFormulaScore", "BuyTiming", "SellRisk", "RiskLevel",
            "Fit", "TotalScore", "Target Mean", "Upside%", "Downside%", "MarginSafety", "DataQuality", "WhySelected",
            "Consensus", "TargetSource", "BuffettFilter", "LynchFilter"
        ]].copy()
        disp["Price"] = disp["Price"].apply(fmt_price)
        disp["MarketCap"] = disp["MarketCap"].apply(fmt_market_cap)
        disp["Target Mean"] = disp["Target Mean"].apply(fmt_price)
        disp["Upside%"] = disp["Upside%"].apply(fmt_pct)
        disp["Downside%"] = disp["Downside%"].apply(fmt_pct)
        disp["MarginSafety"] = disp["MarginSafety"].apply(fmt_pct)
        disp["BuffettFilter"] = disp["BuffettFilter"].map({True: "통과", False: "탈락"})
        disp["LynchFilter"] = disp["LynchFilter"].map({True: "통과", False: "탈락"})
        st.dataframe(disp, use_container_width=True, hide_index=True)
        # TOP PICK 및 추천 포트폴리오
        if not filt.empty:
            st.success(f"TOP PICK: {filt.iloc[0]['Ticker']}")
            st.caption(f"한 줄 판단: {filt.iloc[0].get('OneLineSummary', '')}")
            st.caption(f"선정 이유: {filt.iloc[0].get('WhySelected', '')} | 데이터 품질: {filt.iloc[0].get('DataQuality', 'N/A')}")
            if discord_alerts_enabled and discord_scan_alerts and filt.iloc[0].get("SuperPick") == "🔥 초강력 종목":
                send_discord_alert_once(
                    f"SCAN::{filt.iloc[0]['Ticker']}",
                    f"🌍 시장 스캔 초강력 종목: {filt.iloc[0]['Ticker']}\n"
                    f"총점: {filt.iloc[0]['TotalScore']:.1f}\n"
                    f"상승여력: {fmt_pct(filt.iloc[0].get('Upside%'))}\n"
                    f"스타일: {filt.iloc[0].get('StyleTags', '기타')}\n"
                    f"선정 이유: {filt.iloc[0].get('WhySelected', '')}"
                )
            top_port = filt.head(min(5, len(filt))).copy()
            base_scores = top_port["TotalScore"].clip(lower=1)
            total_b = float(base_scores.sum()) if float(base_scores.sum()) > 0 else 0.0
            if total_b > 0:
                top_port["추천비중%"] = (base_scores / total_b * 100).round(1)
            else:
                top_port["추천비중%"] = round(100 / len(top_port), 1)
            top_port["권장투입금"] = (top_port["추천비중%"] / 100 * capital).round(0)
            st.markdown("### 상위 추천 포트폴리오")
            st.dataframe(
                top_port[["Ticker", "StyleTags", "SuperPick", "Band", "TotalScore", "추천비중%", "권장투입금", "Target Mean", "Upside%", "Downside%"]],
                use_container_width=True,
                hide_index=True,
            )

with tabs[6]:  # 백테스트
    st.subheader("🧪 간단 백테스트")
    st.caption("MA50/MA200 골든크로스 전략을 단순 비교합니다. 과거 적합성을 참고용으로 보세요.")
    if current is None:
        st.info("먼저 종목 분석을 실행하세요.")
    else:
        bt = simple_backtest(current.get("Hist"))
        if bt.empty:
            st.warning("백테스트할 데이터가 충분하지 않습니다.")
        else:
            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=bt.index, y=bt["Equity"], mode="lines", name="전략"))
            fig_bt.add_trace(go.Scatter(x=bt.index, y=bt["BuyHold"], mode="lines", name="Buy & Hold"))
            fig_bt.update_layout(height=520, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_bt, use_container_width=True)
            perf = pd.DataFrame({
                "전략": ["MA50/MA200", "Buy & Hold"],
                "최종값": [float(bt["Equity"].iloc[-1]), float(bt["BuyHold"].iloc[-1])],
            })
            st.dataframe(perf, use_container_width=True, hide_index=True)
            stats_df = simple_backtest_stats(bt)
            if not stats_df.empty:
                st.markdown("### 백테스트 통계")
                st.dataframe(stats_df, use_container_width=True, hide_index=True)


with tabs[7]:
    st.subheader("🔔 알림 설정")
    st.caption("여기서 저장하면 GitHub 자동 감시 설정 파일 monitor_config.json 이 바뀐다.")

    if not GITHUB_TOKEN or not GITHUB_REPO:
        st.warning("이 탭을 실제로 쓰려면 GITHUB_TOKEN, GITHUB_REPO 환경변수가 필요하다.")
        st.code("GITHUB_TOKEN=깃허브토큰\nGITHUB_REPO=깃허브아이디/저장소이름", language="bash")

    try:
        monitor_config, monitor_sha = load_monitor_config_from_github()
    except Exception as e:
        st.error(f"설정 파일을 불러오지 못했다: {e}")
        monitor_config, monitor_sha = default_monitor_config(), None

    tickers_text = st.text_area(
        "감시 종목",
        value=", ".join(monitor_config.get("tickers", [])),
        help="쉼표로 구분. 예: AAPL,MSFT,NVDA,005930.KS",
    )

    alert_period = st.selectbox(
        "감시 분석 기간",
        ["1y", "3y", "5y", "10y"],
        index=["1y", "3y", "5y", "10y"].index(monitor_config.get("analysis_period", "1y")),
        key="alert_period_select",
    )

    movement_threshold = st.selectbox(
        "신호 변화 기준",
        [1, 2, 3],
        index=[1, 2, 3].index(int(monitor_config.get("movement_threshold", 1))),
        help="이전 실행 대비 몇 점 이상 움직였을 때 알림을 줄지",
        key="alert_movement_threshold",
    )

    enable_buy_alert = st.checkbox(
        "매수 신호 알림",
        value=bool(monitor_config.get("enable_buy_alert", True)),
        key="enable_buy_alert_checkbox",
    )

    enable_sell_alert = st.checkbox(
        "매도 신호 알림",
        value=bool(monitor_config.get("enable_sell_alert", True)),
        key="enable_sell_alert_checkbox",
    )

    preview_tickers = [x.strip().upper() for x in tickers_text.split(",") if x.strip()]
    st.markdown("### 저장될 종목")
    st.write(preview_tickers if preview_tickers else "없음")

    example_lines = []
    for t in preview_tickers[:5]:
        unit = "원" if t.endswith(".KS") or t.endswith(".KQ") else "달러"
        example_lines.append(f"{t} 123{unit} · 매수 신호 · 매수 3 / 매도 1")
    if example_lines:
        st.markdown("### 알림 예시")
        for line in example_lines:
            st.code(line)

    if st.button("알림 설정 저장", use_container_width=True):
        new_config = {
            "tickers": preview_tickers,
            "analysis_period": alert_period,
            "movement_threshold": movement_threshold,
            "enable_buy_alert": enable_buy_alert,
            "enable_sell_alert": enable_sell_alert,
        }

        try:
            save_monitor_config_to_github(new_config, monitor_sha)
            st.success("알림 설정을 저장했다. 다음 GitHub 자동 실행부터 반영된다.")
        except Exception as e:
            st.error(f"저장 실패: {e}")

    st.markdown("### 폰에서 쓰는 방법")
    st.write(
        "이 앱을 웹으로 띄워두면 폰 브라우저에서 열고 종목을 바꿀 수 있다. "
        "알림은 디스코드 앱에서 받으면 된다."
    )
    st.write(
        "아이폰은 Safari 공유 버튼 → 홈 화면에 추가, "
        "안드로이드는 브라우저 메뉴 → 홈 화면에 추가를 쓰면 앱처럼 바로 열 수 있다."
    )


# =========================================================
# 끝
# =========================================================