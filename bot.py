import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip()
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/" if '/' in GITHUB_REPO else "https://nojae36.github.io/stock-briefing/"

# [실제 평단가 및 보유 수량 100% 반영 마스터 데이터]
PORTFOLIO = {
    "RAM": {"symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 10.08},
    "KODEX_LEV": {"name": "KODEX 코스닥150레버리지", "tickers": ["233740.KS"], "avg_krw": 6152, "qty": 3354, "fallback_krw": 3880},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "avg_krw": 12910, "qty": 656, "fallback_krw": 10100},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 107113, "qty": 1097, "fallback_krw": 14430},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 96650, "qty": 256, "fallback_krw": 14430},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "avg_krw": 52735, "qty": 256, "fallback_krw": 20100},
    "CASH": {"name": "가용 현금", "eval_krw": 10000000}
}

def get_quad_verified_metrics(tickers):
    if isinstance(tickers, str): tickers = [tickers]
    for sym in tickers:
        try:
            hist = yf.Ticker(sym).history(period="6mo")
            if hist.empty: continue
            df = hist.dropna(subset=['Close'])
            if len(df) < 5: continue

            closes = df['Close']
            opens = df['Open'] if 'Open' in df else closes
            highs = df['High'] if 'High' in df else closes
            lows = df['Low'] if 'Low' in df else closes
            vols = df['Volume'] if 'Volume' in df else closes * 0

            curr = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) >= 2 else curr
            pct = ((curr - prev) / prev) * 100 if prev > 0 else 0.0

            if len(closes) >= 15:
                delta = closes.diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                last_loss = float(loss.iloc[-1])
                rsi = 100.0 if last_loss == 0 else 100.0 - (100.0 / (1.0 + (float(gain.iloc[-1]) / last_loss)))
            else:
                rsi = 50.0

            ma20 = float(closes.tail(20).mean())
            ma60 = float(closes.tail(60).mean())
            disp20 = ((curr - ma20) / ma20) * 100 if ma20 > 0 else 0.0

            std20 = float(closes.tail(20).std()) if len(closes) >= 20 else 0.0
            bb_lower = ma20 - 2 * std20
            bb_upper = ma20 + 2 * std20
            pct_b = (curr - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

            if len(closes) >= 26:
                ema12 = closes.ewm(span=12, adjust=False).mean()
                ema26 = closes.ewm(span=26, adjust=False).mean()
                macd_line = ema12 - ema26
                sig_line = macd_line.ewm(span=9, adjust=False).mean()
                macd_hist = macd_line - sig_line
                hist_now = float(macd_hist.iloc[-1])
                hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else hist_now
                macd_turn = hist_now > hist_prev
            else:
                macd_turn = False

            avg_vol20 = float(vols.tail(20).mean()) if len(vols) >= 5 else 0.0
            curr_vol = float(vols.iloc[-1])
            vol_ratio = (curr_vol / avg_vol20) if avg_vol20 > 0 else 1.0

            c_open, c_high, c_low = float(opens.iloc[-1]), float(highs.iloc[-1]), float(lows.iloc[-1])
            candle_range = c_high - c_low
            lower_wick_ratio = ((min(c_open, curr) - c_low) / candle_range) if candle_range > 0 else 0.0
            bullish_rebound = (curr >= c_open) or (lower_wick_ratio >= 0.35)

            c1_oversold = (rsi < 38.0) or (disp20 <= -8.0)
            c2_support = (pct_b <= 0.18) or (curr >= ma60)
            c3_momentum = macd_turn
            c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (bullish_rebound and rsi < 30.0)

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            chk_str = f"[{'O' if c1_oversold else 'X'}과매도 | {'O' if c2_support else 'X'}지지 | {'O' if c3_momentum else 'X'}MACD | {'O' if c4_volume else 'X'}수급]"

            if c1_oversold and score == 4:
                sig, cash = f"🔥 4중검증 완벽타점 ({score}/4)", "400만 원 즉시 투입 (진바닥)"
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig, cash = f"✅ 1차 검증타점 ({score}/4)", "300만 원 분할 투입 (반등)"
            elif c1_oversold and score <= 2:
                sig, cash = f"⚠️ 하락칼날 주의 ({score}/4)", "0원 대기 (수급 미확인)"
            elif rsi > 70:
                sig, cash = f"🚨 단기 과열 ({score}/4)", "0원 (추격매수 금지)"
            else:
                sig, cash = f"⏸
