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

def make_ visual_gauge(curr, low, high, length=10):
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
            dist_to_target = ((target_p - curr_p) / curr_p) * 100.0 if curr_p > 0 else 0.0
            dist_to_stop = ((curr_p - stop_p) / curr_p) * 100.0 if curr_p > 0 else 0.0

            pos_pct = 0
            if target_p > stop_p:
                pos_pct = int(max(3.0, min(97.0, ((curr_p - stop_p) / (target_p - stop_p)) * 100.0)))

            if is_usd:
                cost_usd = entry_p * qty
                eval_usd = curr_p * qty
                pnl_usd = eval_usd - cost_usd
                cost_krw = int(cost_usd * krw_rate)
                eval_krw = int(eval_usd * krw_rate)
                pnl_krw = eval_krw - cost_krw
                p_fmt = lambda x: f"${x:,.2f}"
                avg_fmt = lambda x: f"${x:,.4f}"
                pnl_str = f"{pnl_usd:+,.1f}달러 ({pnl_krw//10000:+,}만 원)"
            else:
                cost_krw = int(entry_p * qty)
                eval_krw = int(curr_p * qty)
                pnl_krw = eval_krw - cost_krw
                p_fmt = lambda x: f"₩{x:,.0f}"
                avg_fmt = lambda x: f"₩{x:,.0f}"
                pnl_str = f"{pnl_krw:+,}원 ({pnl_krw//10000:+,}만 원)"

            if is_live:
                live_cost_krw += cost_krw
                live_eval_krw += eval_krw

            base_key = tr.get("base_key", "")
            blended_note = ""
            if base_key in PORTFOLIO:
                b_item = PORTFOLIO[base_key]
                b_qty = b_item["qty"]
                b_avg = b_item.get("avg_usd", b_item.get("avg_krw", 0))
                new_total_qty = b_qty + qty
                blended_avg = ((b_avg * b_qty) + (entry_p * qty)) / new_total_qty
                blended_note = f"MTS 합산: {new_total_qty:,}주 · 평단 {avg_fmt(blended_avg)}"

            if not is_live:
                badge_html = '<span class="tr-badge tr-sim">🧪 모의 프리뷰</span>'
                status_str = f"진입가 {p_fmt(entry_p)} 가정 시뮬레이션"
            else:
                badge_html = '<span class="tr-badge tr-live">🟢 실전 LIVE</span>'
                status_str = f"1차 반등선({p_fmt(half_target_p)}) 303주 예약매도 권장"
                if curr_p <= stop_p:
                    status_str = f"🚨 트레일링 스탑 도달! ({p_fmt(stop_p)} 이하 매도)"
                    exit_alert = True
                elif curr_p >= target_p:
                    status_str = f"🎯 목표 익절가 도달! ({p_fmt(target_p)} 익절 실행)"
                    exit_alert = True

            ret_cls = "pos" if ret_entry >= 0 else "neg"
            cards_html.append(f"""
                <div class="tr-box">
                    <div class="sig-hd">
                        <div><b>{tr['name']}</b> ({qty:,}주) {badge_html}</div>
                        <div class="{ret_cls}" style="font-size:0.9rem;">{ret_entry:+.2f}%</div>
                    </div>
                    <div class="range-wrap">
                        <div class="range-labels">
                            <span class="neg">🛡️스탑 {p_fmt(stop_p)}</span>
                            <span style="color:#38bdf8;font-weight:bold;">현재 {p_fmt(curr_p)}</span>
                            <span class="pos">🎯목표 {p_fmt(target_p)}</span>
                        </div>
                        <div class="range-track">
                            <div class="range-fill" style="width:{pos_pct}%;"></div>
                            <div class="range-dot" style="left:{pos_pct}%;"></div>
                        </div>
                        <div class="range-Labels-sub">
                            <span>스탑까지 -{dist_to_stop:.1f}% 여유</span>
                            <span>익절까지 +{dist_to_target:.1f}% 남음</span>
                        </div>
                    </div>
                    <div class="tr-ft">
                        <span>단독 손익: <b class="{ret_cls}">{pnl_str}</b> (원금 {cost_krw//10000:,}만)</span>
                    </div>
                    <div class="sub" style="margin-top:4px;">💡 {blended_note} | {status_str}</div>
                </div>""")

            if is_live:
                gauge_bar = make_visual_gauge(curr_p, stop_p, target_p, 10)
                tg_rows.append(
                    f"🎯 <b>[실전 스윙 감시] {tr['name']} ({qty:,}주)</b>\n"
                    f"<blockquote>진입 {p_fmt(entry_p)} ➔ 현재 <b>{p_fmt(curr_p)} ({ret_entry:+.2f}% / {pnl_krw//10000:+,}만)</b>\n"
                    f"🛡️{p_fmt(stop_p)} <code>{gauge_bar}</code> 🎯{p_fmt(target_p)}\n"
                    f"• 목표({p_fmt(target_p)})까지 <b>+{dist_to_target:.1f}%</b> | 스탑({p_fmt(stop_p)})까지 <b>-{dist_to_stop:.1f}% 여유</b>\n"
                    f"• {blended_note}</blockquote>"
                )
        except Exception:
            continue

    live_pnl_krw = live_eval_krw - live_cost_krw
    return "".join(cards_html), "\n".join(tg_rows), exit_alert, live_cost_krw, live_eval_krw, live_pnl_krw

def calc_kr_holding(key, param_key, is_core=False, cached_m=None):
    item = PORTFOLIO[key]
    if cached_m is not None:
        m = dict(cached_m)
    else:
        p_cfg = CUSTOM_PARAMS.get(param_key, {"rsi_cut": 35.0, "disp_cut": -8.0})
        m = get_quad_verified_metrics(item["tickers"], rsi_cut=p_cfg["rsi_cut"], disp_cut=p_cfg["disp_cut"], is_core_cash_target=is_core)
    curr_p = m["curr"] if m["curr"] > 0 else float(item["fallback_krw"])
    cost_krw = int(item["avg_krw"] * item["qty"])
    eval_krw = int(curr_p * item["qty"])
    pnl_krw = eval_krw - cost_krw
    ret_pct = ((curr_p - item["avg_krw"]) / item["avg_krw"]) * 100
    m["curr"], m["cost_krw"], m["eval_krw"], m["pnl_krw"], m["ret_pct"] = curr_p, cost_krw, eval_krw, pnl_krw, ret_pct
    return m

def get_latest_strict_news(query, tag, max_items=2, max_hours=48):
    items = []
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        for entry in feedparser.parse(resp.content).entries:
            if not hasattr(entry, 'published'):
                continue
            pub_kst = parsedate_to_datetime(entry.published).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            if (now_kst - pub_kst).total_seconds() / 3600 > max_hours:
                continue
            title = (entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            items.append({"tag": tag, "title": title, "source": getattr(entry, 'source', {}).get('title', '주요언론'), "time": pub_kst.strftime("%m/%d %H:%M"), "link": entry.link})
            if len(items) >= max_items:
                break
    except Exception:
        pass
    return items

def render_quick_tile(short_name, m):
    tile_cls = "q-buy" if m["alert"] else ("q-hot" if "🚨" in m["sig"] else "q-wait")
    return f"""
        <div class="q-tile {tile_cls}">
            <div class="q-name">{short_name}</div>
            <div class="q-score">{m['blocks']}</div>
            <div class="q-st">{m['short_st']} ({m['score']}/4)</div>
        </div>"""

def render_sig_card(title, price_badge, my_ret_str, m, border_color):
    sig_color = "pos" if m["alert"] else ("neg" if "🚨" in m["sig"] else "")
    bar_w = int((m["score"] / 4.0) * 100)
    bar_color = "#4ade80" if m["alert"] else ("#f87171" if "🚨" in m["sig"] else "#38bdf8")

    p1_cls = "pill-on" if m["c1"] else "pill-off"
    p2_cls = "pill-on" if m["c2"] else "pill-off"
    p3_cls = "pill-on" if m["c3"] else "pill-off"
    p4_cls = "pill-on" if m["c4"] else "pill-off"
    spark_svg = make_sparkline_svg(m.get("spark", []), border_color)

    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <div class="sig-hd">
                <div>
                    <b>{title}</b> {price_badge}<br>
                    <span class="sub">20일 추세 &amp; 내 수익:</span> {my_ret_str}
                </div>
                <div style="text-align:right;">{spark_svg}</div>
            </div>
            <div class="bar-bg"><div class="bar-fill" style="width:{bar_w}%;background:{bar_color};"></div></div>
            <div class="metric-grid">
                <div class="m-cell"><span class="sub">RSI(14)</span><br><b>{m['rsi']:.1f}</b> <span class="sub">({m['rsi_cut']:.0f})</span></div>
                <div class="m-cell"><span class="sub">20일 이격</span><br><b>{m['disp']:+.1f}%</b> <span class="sub">({m['disp_cut']:.0f}%)</span></div>
                <div class="m-cell"><span class="sub">볼린저 %B</span><br><b>{m['pct_b']:.2f}</b></div>
                <div class="m-cell"><span class="sub">거래량</span><br><b>{m['vol_ratio']:.1f}배</b></div>
            </div>
            <div class="pill-row">
                <span class="pill {p1_cls}">{'🟢' if m['c1'] else '⚫'} 과매도</span>
                <span class="pill {p2_cls}">{'🟢' if m['c2'] else '⚫'} 지지선</span>
                <span class="pill {p3_cls}">{'🟢' if m['c3'] else '⚫'} MACD↑</span>
                <span class="pill {p4_cls}">{'🟢' if m['c4'] else '⚫'} 수급유입</span>
            </div>
            <div class="sig-ft">
                <span class="{sig_color}">{m['sig']}</span>
                <span class="warn">➔ {m['cash']}</span>
            </div>
        </div>"""

def main():
    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = now_kst.strftime("%Y-%m-%d %H:%M KST")

    dday_html, dday_tg = build_dday_section(now_kst)

    ram_param = CUSTOM_PARAMS["RAM"]
    ram = get_quad_verified_metrics("RAM", rsi_cut=ram_param["rsi_cut"], disp_cut=ram_param["disp_cut"], is_core_cash_target=True)
    krw = get_quad_verified_metrics("KRW=X", is_core_cash_target=False)
    krw_p = krw["curr"] if krw["curr"] > 0 else 1334.3

    ram_cfg = PORTFOLIO["RAM"]
    ram_p = ram["curr"] if ram["curr"] > 0 else ram_cfg["fallback_usd"]
    ram_reg_p = ram["reg_curr"] if ram["reg_curr"] > 0 else ram_p
    ram_cost_usd = ram_cfg["avg_usd"] * ram_cfg["qty"]
    ram_eval_usd = ram_p * ram_cfg["qty"]
    ram_ret = ((ram_p - ram_cfg["avg_usd"]) / ram_cfg["avg_usd"]) * 100
    ram_cost_krw = int(ram_cost_usd * krw_p)
    ram_eval_krw = int(ram_eval_usd * krw_p)
    ram_pnl_krw = ram_eval_krw - ram_cost_krw

    ram_total_qty = ram_cfg["qty"] + 606
    ram_total_avg = 9.6926
    ram_total_ret = ((ram_p - ram_total_avg) / ram_total_avg) * 100

    kq = calc_kr_holding("KODEX_LEV", "KODEX_LEV", is_core=True)
    yg = calc_kr_holding("YG1", "YG1", is_core=False)
    or1 = calc_kr_holding("ORUM1", "ORUM", is_core=False)
    or2 = calc_kr_holding("ORUM2", "ORUM", is_core=False, cached_m=or1)
    ab = calc_kr_holding("ABCLON", "ABCLON", is_core=False)

    price_map = {
        "RAM": ram_p,
        "233740.KS": kq["curr"],
        "019210.KQ": yg["curr"],
        "475830.KQ": or1["curr"],
        "174900.KQ": ab["curr"]
    }
    tranche_html, tranche_tg, tranche_alert, live_tr_cost, live_tr_eval, live_tr_pnl = evaluate_new_tranches(price_map, krw_p)

    base_cash = PORTFOLIO["CASH"]["eval_krw"]
    rem_cash_eval = max(0, base_cash - live_tr_cost)

    stock_cost_krw = ram_cost_krw + kq["cost_krw"] + yg["cost_krw"] + or1["cost_krw"] + or2["cost_krw"] + ab["cost_krw"] + live_tr_cost
    stock_eval_krw = ram_eval_krw + kq["eval_krw"] + yg["eval_krw"] + or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"] + live_tr_eval
    total_pnl_krw = stock_eval_krw - stock_cost_krw
    stock_ret_pct = ((stock_eval_krw - stock_cost_krw) / stock_cost_krw) * 100.0 if stock_cost_krw > 0 else 0.0

    total_cost_krw = stock_cost_krw + rem_cash_eval
    total_eval_krw = stock_eval_krw + rem_cash_eval
    total_asset_ret_pct = ((total_eval_krw - total_cost_krw) / total_cost_krw) * 100.0 if total_cost_krw > 0 else 0.0
    bio_eval_krw = or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"]
    ram_combined_eval_krw = ram_eval_krw + live_tr_eval

    news = (get_latest_strict_news("엔비디아 실적 OR 마이크론 OR 삼성전자 HBM", "[반도체/DRAM]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로/코스닥]", 2) +
            get_latest_strict_news("와이지-원 OR 절삭공구", "[와이지원]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 2))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a> ({x['time']})" for x in news]) or "• 최근 48시간 내 속보 없음"

    pnl_color = "pos" if total_pnl_krw >= 0 else "neg"
    ram_color = "pos" if ram_total_ret >= 0 else "neg"
    kq_color = "pos" if kq['ret_pct'] >= 0 else "neg"
    yg_color = "pos" if yg['ret_pct'] >= 0 else "neg"
    or1_color = "pos" if or1['ret_pct'] >= 0 else "neg"
    or2_color = "pos" if or2['ret_pct'] >= 0 else "neg"
    ab_color = "pos" if ab['ret_pct'] >= 0 else "neg"

    quick_bar_html = (
        render_quick_tile("RAM", ram) +
        render_quick_tile("코스닥레버", kq) +
        render_quick_tile("와이지-원", yg) +
        render_quick_tile("오름테라", or1) +
        render_quick_tile("앱클론", ab)
    )

    sig_cards_html = (
        render_sig_card(
            "🇺🇸 RAM (합산 6,460주)",
            f'<span class="badge">{ram["session"]}</span> <span class="sub">${ram_p:.2f} ({ram["pct"]:+.2f}%)</span>',
            f'<span class="{ram_color}">{ram_total_ret:+.1f}% (평단 $9.69)</span>',
            ram, "#38bdf8"
        ) +
        render_sig_card(
            "🇰🇷 KODEX 코스닥150레버리지",
            f'<span class="sub">₩{kq["curr"]:,.0f} ({kq["pct"]:+.2f}%)</span>',
            f'<span class="{kq_color}">{kq["ret_pct"]:+.1f}%</span>',
            kq, "#f87171"
        ) +
        render_sig_card(
            "🔧 와이지-원",
            f'<span class="sub">₩{yg["curr"]:,.0f} ({yg["pct"]:+.2f}%)</span>',
            f'<span class="{yg_color}">{yg["ret_pct"]:+.1f}%</span>',
            yg, "#fbbf24"
        ) +
        render_sig_card(
            "🧬 오름테라퓨틱",
            f'<span class="sub">₩{or1["curr"]:,.0f} ({or1["pct"]:+.2f}%)</span>',
            f'<span class="{or1_color}">{or1["ret_pct"]:+.1f}%</span>',
            or1, "#c084fc"
        ) +
        render_sig_card(
            "🧬 앱클론",
            f'<span class="sub">₩{ab["curr"]:,.0f} ({ab["pct"]:+.2f}%)</span>',
            f'<span class="{ab_color}">{ab["ret_pct"]:+.1f}%</span>',
            ab, "#4ade80"
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <meta http-equiv="refresh" content="1800">
    <title>마스터 관제탑 V6.0</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #070b14; color: #f8fafc; margin: 0; padding: 12px; max-width: 600px; margin: auto; }}
        .top-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
        .top-title {{ font-size: 1.1rem; font-weight: 800; color: #38bdf8; }}
        .top-sync {{ font-size: 0.72rem; color: #94a3b8; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; }}
        .kpi-box {{ background: linear-gradient(145deg, #131c31, #0f172a); border: 1px solid #1e293b; border-radius: 10px; padding: 10px; text-align: center; }}
        .kpi-lbl {{ font-size: 0.71rem; color: #94a3b8; margin-bottom: 3px; }}
        .kpi-val {{ font-size: 1.02rem; font-weight: 800; color: #f8fafc; }}
        .kpi-sub {{ font-size: 0.68rem; color: #64748b; margin-top: 2px; }}
        .q-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 14px; }}
        .q-tile {{ border-radius: 8px; padding: 8px 4px; text-align: center; border: 1px solid #1e293b; }}
        .q-buy {{ background: rgba(74, 222, 128, 0.15); border-color: #4ade80; }}
        .q-hot {{ background: rgba(248, 113, 113, 0.15); border-color: #f87171; }}
        .q-wait {{ background: #131c31; border-color: #1e293b; }}
        .q-name {{ font-size: 0.72rem; font-weight: 700; color: #e2e8f0; margin-bottom: 2px; }}
        .q-score {{ font-size: 0.72rem; letter-spacing: -1px; margin: 2px 0; }}
        .q-st {{ font-size: 0.66rem; color: #cbd5e1; }}
        .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
        h2 {{ font-size: 0.92rem; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #1f2937; color: #38bdf8; display: flex; justify-content: space-between; align-items: center; }}
        .row {{ display: flex; justify-content: space-between; font-size: 0.82rem; padding: 7px 0; border-bottom: 1px dashed #1f2937; align-items: center; }}
        .row:last-child {{ border-bottom: none; }}
        .sub {{ font-size: 0.72rem; color: #94a3b8; }}
        .badge {{ background: #1e293b; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-size: 0.68rem; margin-left: 4px; border: 1px solid #334155; }}
        .dday-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.78rem; }}
        .dday-tag {{ padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.70rem; min-width: 42px; text-align: center; }}
        .dday-urgent {{ background: #ef4444; color: #fff; }}
        .dday-normal {{ background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; }}
        .dday-cat {{ color: #fbbf24; font-weight: bold; font-size: 0.73rem; min-width: 66px; }}
        .dday-title {{ color: #e2e8f0; }}
        .sig-box {{ background: #161f33; border: 1px solid #26334d; border-left: 4px solid #38bdf8; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-size: 0.80rem; }}
        .tr-box {{ background: #142038; border: 1px solid #2dd4bf; border-left: 4px solid #2dd4bf; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-size: 0.80rem; }}
        .tr-badge {{ padding: 2px 6px; border-radius: 4px; font-size: 0.68rem; font-weight: bold; margin-left: 4px; }}
        .tr-sim {{ background: rgba(251, 191, 36, 0.18); color: #fbbf24; border: 1px solid #fbbf24; }}
        .tr-live {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid #4ade80; }}
        .range-wrap {{ background: #0f172a; padding: 10px; border-radius: 8px; margin: 8px 0; }}
        .range-labels {{ display: flex; justify-content: space-between; font-size: 0.75rem; margin-bottom: 6px; }}
        .range-track {{ position: relative; height: 8px; background: #1e293b; border-radius: 4px; margin-bottom: 6px; }}
        .range-fill {{ height: 100%; background: linear-gradient(90deg, #f87171, #38bdf8, #4ade80); border-radius: 4px; }}
        .range-dot {{ position: absolute; top: -4px; width: 16px; height: 16px; background: #fff; border: 3px solid #38bdf8; border-radius: 50%; transform: translateX(-50%); box-shadow: 0 0 6px rgba(56,189,248,0.8); }}
        .range-Labels-sub {{ display: flex; justify-content: space-between; font-size: 0.68rem; color: #94a3b8; }}
        .tr-ft {{ display: flex; justify-content: space-between; align-items: center; padding-top: 4px; border-top: 1px solid #26334d; font-size: 0.78rem; }}
        .sig-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .my-ret {{ font-size: 0.75rem; font-weight: bold; }}
        .bar-bg {{ width: 100%; height: 5px; background: #0f172a; border-radius: 3px; overflow: hidden; margin-bottom: 8px; }}
        .bar-fill {{ height: 100%; border-radius: 3px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: #0f172a; padding: 6px; border-radius: 6px; margin-bottom: 8px; text-align: center; font-size: 0.75rem; }}
        .m-cell {{ line-height: 1.35; }}
        .pill-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-bottom: 8px; text-align: center; }}
        .pill {{ padding: 4px 2px; border-radius: 5px; font-size: 0.70rem; font-weight: 700; }}
        .pill-on {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.5); }}
        .pill-off {{ background: #0f172a; color: #64748b; border: 1px solid #1e293b; }}
        .sig-ft {{ display: flex; justify-content: space-between; align-items: center; padding-top: 6px; border-top: 1px solid #26334d; font-size: 0.78rem; }}
        .pos {{ color: #4ade80; font-weight: bold; }} .neg {{ color: #f87171; font-weight: bold; }} .warn {{ color: #fbbf24; font-weight: bold; }}
        .n-item {{ background: #161f33; padding: 8px 10px; border-radius: 8px; margin-bottom: 8px; font-size: 0.80rem; }}
        .n-hd {{ display: flex; justify-content: space-between; font-size: 0.70rem; margin-bottom: 4px; }} .tag {{ color: #38bdf8; font-weight: bold; }} .meta {{ color: #94a3b8; }}
        a {{ color: #f1f5f9; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="top-hd">
        <div class="top-title">🛡️ 마스터 비주얼 관제탑 V6.0</div>
        <div class="top-sync">동기화: {now_str} (₩{krw_p:,.1f})</div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-box">
            <div class="kpi-lbl">총 평가자산 (1차목표 15,131만)</div>
            <div class="kpi-val" style="color:#38bdf8;">{total_eval_krw//10000:,}만 원</div>
            <div class="kpi-sub">1차 전환선까지 {max(0, 15131 - total_eval_krw//10000):,}만 원</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">원화 환산 총 평가손익</div>
            <div class="kpi-val {pnl_color}">{total_pnl_krw//10000:+,}만 원</div>
            <div class="kpi-sub">{total_pnl_krw:+,}원</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">보유 주식 합산 수익률</div>
            <div class="kpi-val {pnl_color}">{stock_ret_pct:+.2f}%</div>
            <div class="kpi-sub">현금포함 총자산 {total_asset_ret_pct:+.2f}%</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">주식 평가액 / 잔여 현금</div>
            <div class="kpi-val">{stock_eval_krw//10000:,}만 / <span style="color:#4ade80;">{rem_cash_eval//10000:,}만</span></div>
            <div class="kpi-sub">RAM 1차(606주) 실전 감시 중</div>
        </div>
    </div>

    <div class="q-grid">
        {quick_bar_html}
    </div>

    <div class="card">
        <h2>🛡️ 신규 스윙 트랑셰 위치 트래커 (스탑 ➔ 목표)</h2>
        {tranche_html}
    </div>

    <div class="card">
        <h2>📅 핵심 일정 D-Day 트래커</h2>
        {dday_html}
    </div>

    <div class="card">
        <h2>🎯 5대 종목 20일 추세 &amp; 4중 검증 스위치</h2>
        {sig_cards_html}
    </div>

    <div class="card">
        <h2>💼 보유 종목 상세 평가 &amp; 포트폴리오 비중</h2>
        <div style="width:210px;margin:0 auto 12px auto;"><canvas id="pfChart"></canvas></div>
        <div class="row"><span><b>RAM 합산</b> (6,460주 · 평단 $9.6926) <span class="badge">{ram['session']}</span><br><span class="sub">기존 5,854주($10.08) + 신규 606주($5.97) | 현재 ${ram_p:.2f}</span></span><span class="{ram_color}" style="text-align:right;">{ram_total_ret:+.2f}% ({(ram_pnl_krw + live_tr_pnl)//10000:+,}만)<br>${ram_p * ram_total_qty:,.0f} ({ram_combined_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (3,354주 · 평단 6,152원)<br><span class="sub">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)</span></span><span class="{kq_color}" style="text-align:right;">{kq['ret_pct']:+.2f}% ({kq['pnl_krw']//10000:+,}만)<br>{kq['eval_krw']:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (656주 · 평단 12,910원)<br><span class="sub">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)</span></span><span class="{yg_color}" style="text-align:right;">{yg['ret_pct']:+.2f}% ({yg['pnl_krw']//10000:+,}만)<br>{yg['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주 · 평단 107,113원)<br><span class="sub">현재 ₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%)</span></span><span class="{or1_color}" style="text-align:right;">{or1['ret_pct']:+.2f}% ({or1['pnl_krw']//10000:+,}만)<br>{or1['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주 · 평단 96,650원)<br><span class="sub">현재 ₩{or2['curr']:,.0f} ({or2['pct']:+.2f}%)</span></span><span class="{or2_color}" style="text-align:right;">{or2['ret_pct']:+.2f}% ({or2['pnl_krw']//10000:+,}만)<br>{or2['eval_krw']:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주 · 평단 52,735원)<br><span class="sub">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)</span></span><span class="{ab_color}" style="text-align:right;">{ab['ret_pct']:+.2f}% ({ab['pnl_krw']//10000:+,}만)<br>{ab['eval_krw']:,}원</span></div>
    </div>

    <div class="card"><h2>📰 최근 48시간 최신 속보</h2>{news_html}</div>

    <script>
        new Chart(document.getElementById('pfChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['RAM(반도체 6,460주)', '바이오(오름·앱클론)', '코스닥150레버리지', '잔여현금', '와이지-원'],
                datasets: [{{
                    data: [{ram_combined_eval_krw//10000}, {bio_eval_krw//10000}, {kq['eval_krw']//10000}, {rem_cash_eval//10000}, {yg['eval_krw']//10000}],
                    backgroundColor: ['#38bdf8', '#c084fc', '#f87171', '#4ade80', '#fbbf24'],
                    borderWidth: 0
                }}]
            }},
            options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#cbd5e1', font: {{ size: 11 }} }} }} }}, cutout: '62%' }}
        }});
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    today_str = now_kst.strftime("%Y-%m-%d")
    curr_hour = now_kst.hour
    slot = "AM" if (8 <= curr_hour <= 10) else ("PM" if (22 <= curr_hour <= 23) else "")
    slot_key = f"{today_str}_{slot}" if slot else ""

    last_sent = ""
    if os.path.exists("last_sent.txt"):
        with open("last_sent.txt", "r", encoding="utf-8") as lf:
            last_sent = lf.read().strip()

    is_scheduled_slot = (slot != "" and last_sent != slot_key)
    is_manual_run = (EVENT_NAME == "workflow_dispatch")
    is_quiet_hour = QUIET_NIGHT_MODE and (0 <= curr_hour <= 6)
    any_buy_alert = any([ram["alert"], kq["alert"], yg["alert"], or1["alert"], ab["alert"], tranche_alert]) and not is_quiet_hour

    if TOKEN and CHAT_ID and (is_scheduled_slot or is_manual_run or any_buy_alert):
        header_prefix = "🚨 <b>[긴급 타점/스탑 시그널 포착!]</b>\n" if (any_buy_alert and not is_scheduled_slot) else ""
        tg_msg = (
            f"{header_prefix}🛡️ <b>[V6.0 비주얼 관제탑] {now_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 총자산: <b>{total_eval_krw//10000:,}만 원</b> (잔여현금 {rem_cash_eval//10000:,}만)\n"
            f"📊 총손익: <b>{total_pnl_krw//10000:+,}만 원 ({stock_ret_pct:+.2f}%)</b> | ₩{krw_p:,.1f}\n\n"
            f"{tranche_tg}\n\n"
            f"🚦 <b>[5대 종목 4중 검증 타점 보드]</b>\n"
            f"<blockquote>🇺🇸 <b>RAM</b> (${ram_p:.2f} | {ram['pct']:+.2f}%) {ram['session']}\n"
            f"{ram['blocks']} <b>{ram['score']}/4점</b> | <b>{ram['short_st']}</b>\n"
            f"🌡️RSI {ram['rsi']:.1f}(기준35) | 📏이격 {ram['disp']:+.1f}%(-9%)\n"
            f"{ram['chk']}\n\n"
            f"🇰🇷 <b>코스닥레버</b> (₩{kq['curr']:,.0f} | {kq['pct']:+.2f}%)\n"
            f"{kq['blocks']} <b>{kq['score']}/4점</b> | <b>{kq['short_st']}</b> | RSI {kq['rsi']:.1f} | 이격 {kq['disp']:+.1f}%\n\n"
            f"🔧 <b>와이지-원</b> (₩{yg['curr']:,.0f} | {yg['pct']:+.2f}%)\n"
            f"{yg['blocks']} <b>{yg['score']}/4점</b> | <b>{yg['short_st']}</b> | RSI {yg['rsi']:.1f} | 이격 {yg['disp']:+.1f}%\n\n"
            f"🧬 <b>오름테라</b> (₩{or1['curr']:,.0f} | {or1['pct']:+.2f}%)\n"
            f"{or1['blocks']} <b>{or1['score']}/4점</b> | <b>{or1['short_st']}</b> | RSI {or1['rsi']:.1f} | 이격 {or1['disp']:+.1f}%\n\n"
            f"🧬 <b>앱클론</b> (₩{ab['curr']:,.0f} | {ab['pct']:+.2f}%)\n"
            f"{ab['blocks']} <b>{ab['score']}/4점</b> | <b>{ab['short_st']}</b> | RSI {ab['rsi']:.1f} | 이격 {ab['disp']:+.1f}%</blockquote>\n\n"
            f"📅 <b>[임박 일정 D-Day]</b>\n{dday_tg}\n\n"
            f"📰 <b>[핵심 속보]</b>\n{news_tg}"
        )

        inline_kb = {
            "inline_keyboard": [
                [{"text": "📊 V6.0 비주얼 웹 관제탑 열기 (미니차트·게이지)", "url": DASHBOARD_URL}]
            ]
        }

        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": tg_msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": inline_kb
            },
            timeout=10
        )

        if is_scheduled_slot:
            with open("last_sent.txt", "w", encoding="utf-8") as lf:
                lf.write(slot_key)

if __name__ == "__main__":
    main()
