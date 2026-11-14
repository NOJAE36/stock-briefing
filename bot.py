import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip().lower()
EVENT_NAME = os.environ.get('GITHUB_EVENT_NAME', '').strip()

QUIET_NIGHT_MODE = True

CACHE_BUST = datetime.datetime.now().strftime("%m%d%H%M")
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/?v={CACHE_BUST}" if '/' in GITHUB_REPO else f"https://nojae36.github.io/stock-briefing/?v={CACHE_BUST}"

# [1] 기존 코어 보유 포트폴리오 (금요일 종가 $5.91 반영, 신규 606주와 합산 시 6,460주 평단 $9.6926)
PORTFOLIO = {
    "RAM": {"name": "RAM (DRAM 2X)", "symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 5.91},
    "KODEX_LEV": {"name": "코스닥150레버리지", "tickers": ["233740.KS"], "avg_krw": 6152, "qty": 3354, "fallback_krw": 4300},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "avg_krw": 12910, "qty": 656, "fallback_krw": 9820},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 107113, "qty": 1097, "fallback_krw": 14830},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 96650, "qty": 256, "fallback_krw": 14830},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "avg_krw": 52735, "qty": 256, "fallback_krw": 21850},
    "CASH": {"name": "가용 현금", "eval_krw": 10000000}
}

# [2] 종목별 백테스팅 최적화 맞춤 파라미터
CUSTOM_PARAMS = {
    "RAM": {"rsi_cut": 35.0, "disp_cut": -9.0},
    "KODEX_LEV": {"rsi_cut": 34.0, "disp_cut": -9.0},
    "YG1": {"rsi_cut": 38.0, "disp_cut": -7.0},
    "ORUM": {"rsi_cut": 32.0, "disp_cut": -11.0},
    "ABCLON": {"rsi_cut": 32.0, "disp_cut": -11.0}
}

# [3] 신규 스윙 물량(트랑셰) 리스트 (RAM 606주 $5.97 실전 LIVE 반영)
NEW_TRANCHES = [
    {
        "mode": "LIVE",
        "name": "RAM 엔비디아실적 1차",
        "symbol": "RAM",
        "base_key": "RAM",
        "currency": "USD",
        "entry_date": "2026-11-12",
        "entry_price": 5.97,
        "qty": 606,
        "target_pct": 15.0,
        "trail_pct": -7.0
    },
    {
        "mode": "SIM",
        "name": "코스닥레버리지 눌림 1차",
        "symbol": "233740.KS",
        "base_key": "KODEX_LEV",
        "currency": "KRW",
        "entry_date": "2026-11-16",
        "entry_price": 4050,
        "qty": 850,
        "target_pct": 12.0,
        "trail_pct": -6.0
    }
]

KEY_EVENTS = [
    {"date": "2026-11-18", "cat": "🔥AI·DRAM", "title": "엔비디아(NVDA) FY27 3Q 실적발표 (HBM 수요 풍향계)"},
    {"date": "2026-12-10", "cat": "🏦매크로", "title": "미국 12월 FOMC 금리결정 및 점도표 발표"},
    {"date": "2026-12-12", "cat": "🧬바이오", "title": "미국 혈액암학회(ASH 2026) 개막 (오름·앱클론 모멘텀)"},
    {"date": "2026-12-17", "cat": "💾DRAM", "title": "마이크론(MU) FY27 1Q 실적발표 (RAM 직접 모멘텀)"},
    {"date": "2027-01-08", "cat": "💾DRAM", "title": "삼성전자 2026 4Q 잠정실적 발표 (메모리 마진 확인)"},
    {"date": "2027-01-11", "cat": "🧬바이오", "title": "2027 JP모건 헬스케어 컨퍼런스 (글로벌 기술이전 시즌)"},
    {"date": "2027-01-22", "cat": "💾DRAM", "title": "SK하이닉스 2026 4Q 실적발표 (HBM3E·HBM4 가이던스)"}
]

def make_visual_gauge(curr, low, high, length=10):
    if high <= low:
        return "[" + "─" * length + "]"
    ratio = (curr - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    idx = int(round(ratio * (length - 1)))
    bar = ""
    for i in range(length):
        if i < idx:
            bar += "━"
        elif i == idx:
            bar += "●"
        else:
            bar += "─"
    return f"[{bar}]"

def make_score_blocks(score, rsi):
    if rsi > 72:
        return "🟥🟥🟥🟥"
    filled = "🟩" * score
    empty = "⬜" * (4 - score)
    return filled + empty

def make_sparkline_svg(prices, color="#38bdf8"):
    if not prices or len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng = (mx - mn) if mx > mn else 1.0
    w, h = 86, 28
    pts = []
    for i, p in enumerate(prices):
        x = (i / (len(prices) - 1)) * (w - 8) + 4
        y = h - 4 - ((p - mn) / rng) * (h - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = pts[-1].split(",")
    poly = " ".join(pts)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="overflow:visible;">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" points="{poly}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="3" fill="{color}"/>'
        f'</svg>'
    )

def build_dday_section(now_kst):
    today = now_kst.date()
    html_badges, tg_lines = [], []
    for ev in KEY_EVENTS:
        ev_date = datetime.date.fromisoformat(ev["date"])
        diff = (ev_date - today).days
        if diff < 0:
            continue
        dday_str = "D-DAY" if diff == 0 else f"D-{diff}"
        urgent_cls = "dday-urgent" if diff <= 7 else "dday-normal"
        tg_prefix = "🔥" if diff <= 7 else ""
        html_badges.append(
            f'<div class="dday-row"><span class="dday-tag {urgent_cls}">{dday_str}</span>'
            f'<span class="dday-cat">{ev["cat"]}</span>'
            f'<span class="dday-title">{ev["title"]} <span class="sub">({ev["date"][5:]})</span></span></div>'
        )
        if len(tg_lines) < 4:
            tg_lines.append(f"• <b>[{tg_prefix}{dday_str}]</b> {ev['cat']} {ev['title']} ({ev['date'][5:]})")
    return "".join(html_badges), "\n".join(tg_lines)

def get_quad_verified_metrics(tickers, rsi_cut=35.0, disp_cut=-9.0, is_core_cash_target=True):
    if isinstance(tickers, str):
        tickers = [tickers]
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="6mo", timeout=10)
            if hist.empty:
                continue
            df = hist.dropna(subset=['Close']).copy()
            if len(df) < 5:
                continue

            reg_curr = float(df['Close'].iloc[-1])
            reg_prev = float(df['Close'].iloc[-2]) if len(df) >= 2 else reg_curr
            curr = reg_curr
            prev = reg_prev
            session_tag = "☀️본장"

            if not sym.endswith(('.KS', '.KQ')) and sym != 'KRW=X':
                try:
                    intra = t.history(period="5d", interval="5m", prepost=True, timeout=10)
                    if not intra.empty:
                        intra_clean = intra.dropna(subset=['Close'])
                        if not intra_clean.empty:
                            curr = float(intra_clean['Close'].iloc[-1])
                            last_ts = intra_clean.index[-1]
                            hm = last_ts.hour * 60 + last_ts.minute
                            if 240 <= hm < 570:
                                session_tag = "🌅프리장"
                            elif 570 <= hm < 960:
                                session_tag = "☀️본장"
                            else:
                                session_tag = "🌙애프터"
                            if last_ts.date() > df.index[-1].date():
                                prev = reg_curr
                            df.iloc[-1, df.columns.get_loc('Close')] = curr
                except Exception:
                    pass

            closes = df['Close']
            opens = df['Open'] if 'Open' in df else closes
            highs = df['High'] if 'High' in df else closes
            lows = df['Low'] if 'Low' in df else closes
            vols = df['Volume'] if 'Volume' in df else closes * 0

            spark_prices = [float(x) for x in closes.tail(20).values]

            pct = ((curr - prev) / prev) * 100 if prev > 0 else 0.0
            ext_pct = ((curr - reg_curr) / reg_curr) * 100 if reg_curr > 0 else 0.0

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

            c1_oversold = (rsi < rsi_cut) or (disp20 <= disp_cut)
            c2_support = (pct_b <= 0.18) or (curr >= ma60)
            c3_momentum = macd_turn
            c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (bullish_rebound and rsi < (rsi_cut - 6.0))

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            blocks = make_score_blocks(score, rsi)
            chk_icons = f"{'🟢' if c1_oversold else '⚫'}과매도 {'🟢' if c2_support else '⚫'}지지 {'🟢' if c3_momentum else '⚫'}MACD {'🟢' if c4_volume else '⚫'}수급"

            is_buy_alert = False
            if c1_oversold and score == 4:
                sig, short_st = f"🔥 4중검증 완벽타점 ({score}/4)", "🔥진바닥"
                cash = "잔여 시드 517만 원 투입 검토" if is_core_cash_target else "진바닥 강세 전환 (분할 추매)"
                is_buy_alert = True
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig, short_st = f"✅ 1차 검증타점 ({score}/4)", "✅타점진입"
                cash = "신규 트랑셰 300만 원 투입" if is_core_cash_target else "단기 반등 타점 (소액 스윙)"
                is_buy_alert = True
            elif c1_oversold and score <= 2:
                sig, short_st, cash = f"⚠️ 하락칼날 주의 ({score}/4)", "⚠️칼날주의", "추가매수 대기 (반등 미확인)"
            elif rsi > 72:
                sig, short_st, cash = f"🚨 단기 과열 ({score}/4)", "🚨과열주의", "신규 606주 익절 & 기존분 역물타기"
            else:
                sig, short_st, cash = f"⏸ 중립·관망 ({score}/4)", "⏸관망중", "1차 606주 감시 · 잔여현금 대기"

            return {
                "curr": curr, "reg_curr": reg_curr, "pct": pct, "ext_pct": ext_pct,
                "session": session_tag, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio,
                "c1": c1_oversold, "c2": c2_support, "c3": c3_momentum, "c4": c4_volume,
                "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": spark_prices,
                "score": score, "blocks": blocks, "chk": chk_icons, "sig": sig, "short_st": short_st, "cash": cash, "alert": is_buy_alert
            }
        except Exception:
            continue
    return {
        "curr": 0.0, "reg_curr": 0.0, "pct": 0.0, "ext_pct": 0.0, "session": "대기",
        "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0,
        "c1": False, "c2": False, "c3": False, "c4": False, "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": [],
        "score": 0, "blocks": "⬜⬜⬜⬜", "chk": "대기", "sig": "데이터 대기", "short_st": "⏸대기", "cash": "0원", "alert": False
    }

def evaluate_new_tranches(price_map, krw_rate):
    if not NEW_TRANCHES:
        return '<div class="sub">등록된 신규 스윙 트랑셰가 없습니다.</div>', "", False, 0, 0, 0

    cards_html, tg_rows = [], []
    exit_alert = False
    live_cost_krw = 0
    live_eval_krw = 0

    for tr in NEW_TRANCHES:
        try:
            mode = tr.get("mode", "SIM").upper()
            is_live = (mode == "LIVE")
            sym = tr["symbol"]
            is_usd = (tr.get("currency", "KRW") == "USD")
            entry_p = float(tr["entry_price"])
            qty = int(tr["qty"])
            target_pct = float(tr["target_pct"])
            trail_pct = float(tr["trail_pct"])

            curr_p = float(price_map.get(sym, entry_p))
            peak_p = max(curr_p, entry_p)

            if is_live:
                try:
                    hist = yf.Ticker(sym).history(start=tr["entry_date"], timeout=8)
                    if not hist.empty:
                        peak_p = max(float(hist['High'].max()), curr_p, entry_p)
                except Exception:
                    pass

            target_p = entry_p * (1.0 + target_pct / 100.0)
            stop_p = peak_p * (1.0 + trail_pct / 100.0)
            half_target_p = entry_p * 1.12

            ret_entry = ((curr_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            dist_to_target = ((target_p - curr_p
