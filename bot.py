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

PORTFOLIO = {
    "RAM": {"name": "RAM (DRAM 2X)", "symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 10.08},
    "KODEX_LEV": {"name": "코스닥150레버리지", "tickers": ["233740.KS"], "avg_krw": 6152, "qty": 3354, "fallback_krw": 3880},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "avg_krw": 12910, "qty": 656, "fallback_krw": 10100},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 107113, "qty": 1097, "fallback_krw": 14430},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 96650, "qty": 256, "fallback_krw": 14430},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "avg_krw": 52735, "qty": 256, "fallback_krw": 20100},
    "CASH": {"name": "가용 현금", "eval_krw": 10000000}
}

# MU 제외, RAM 단독 기준값(2배 레버리지 특성 반영) 및 국내 종목 맞춤 파라미터
CUSTOM_PARAMS = {
    "RAM": {"rsi_cut": 35.0, "disp_cut": -9.0},
    "KODEX_LEV": {"rsi_cut": 34.0, "disp_cut": -9.0},
    "YG1": {"rsi_cut": 38.0, "disp_cut": -7.0},
    "ORUM": {"rsi_cut": 32.0, "disp_cut": -11.0},
    "ABCLON": {"rsi_cut": 32.0, "disp_cut": -11.0}
}

NEW_TRANCHES = [
    # {"name": "RAM 신규1차", "symbol": "RAM", "entry_date": "2026-11-15", "entry_price": 9.50, "qty": 200, "trail_pct": -7.0, "target_pct": 12.0},
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
        html_badges.append(
            f'<div class="dday-row"><span class="dday-tag {urgent_cls}">{dday_str}</span>'
            f'<span class="dday-cat">{ev["cat"]}</span>'
            f'<span class="dday-title">{ev["title"]} <span class="sub">({ev["date"][5:]})</span></span></div>'
        )
        if len(tg_lines) < 4:
            tg_lines.append(f"• <b>[{dday_str}]</b> {ev['cat']} {ev['title']} ({ev['date'][5:]})")
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
            chk_str = f"[{'O' if c1_oversold else 'X'}과매도 | {'O' if c2_support else 'X'}지지 | {'O' if c3_momentum else 'X'}MACD | {'O' if c4_volume else 'X'}수급]"

            is_buy_alert = False
            if c1_oversold and score == 4:
                sig, short_st = f"🔥 4중검증 완벽타점 ({score}/4)", "🔥진바닥"
                cash = "신규 트랑셰 400만 원 투입" if is_core_cash_target else "진바닥 강세 전환 (분할 추매)"
                is_buy_alert = True
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig, short_st = f"✅ 1차 검증타점 ({score}/4)", "✅타점진입"
                cash = "신규 트랑셰 300만 원 투입" if is_core_cash_target else "단기 반등 타점 (소액 스윙)"
                is_buy_alert = True
            elif c1_oversold and score <= 2:
                sig, short_st, cash = f"⚠️ 하락칼날 주의 ({score}/4)", "⚠️칼날주의", "0원 대기 (반등 미확인)"
            elif rsi > 72:
                sig, short_st, cash = f"🚨 단기 과열 ({score}/4)", "🚨과열주의", "추격금지 (신규물량 익절)"
            else:
                sig, short_st, cash = f"⏸ 중립·관망 ({score}/4)", "⏸관망중", "기존 물량 홀딩 · 현금 대기"

            return {
                "curr": curr, "reg_curr": reg_curr, "pct": pct, "ext_pct": ext_pct,
                "session": session_tag, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio,
                "c1": c1_oversold, "c2": c2_support, "c3": c3_momentum, "c4": c4_volume,
                "rsi_cut": rsi_cut, "disp_cut": disp_cut,
                "score": score, "chk": chk_str, "sig": sig, "short_st": short_st, "cash": cash, "alert": is_buy_alert
            }
        except Exception:
            continue
    return {
        "curr": 0.0, "reg_curr": 0.0, "pct": 0.0, "ext_pct": 0.0, "session": "대기",
        "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0,
        "c1": False, "c2": False, "c3": False, "c4": False, "rsi_cut": rsi_cut, "disp_cut": disp_cut,
        "score": 0, "chk": "[대기]", "sig": "데이터 대기", "short_st": "⏸대기", "cash": "0원", "alert": False
    }

def evaluate_new_tranches():
    if not NEW_TRANCHES:
        return '<div class="sub">현재 가용 현금으로 신규 진입한 단기 스윙 물량이 없습니다. (기존 보유 물량은 트레일링 스탑 제외)</div>', "", False
    rows_html, tg_rows = [], []
    exit_alert = False
    for tr in NEW_TRANCHES:
        try:
            hist = yf.Ticker(tr["symbol"]).history(start=tr["entry_date"], timeout=10)
            if hist.empty:
                continue
            curr_p = float(hist['Close'].iloc[-1])
            peak_p = max(float(hist['High'].max()), float(tr["entry_price"]))
            ret_entry = ((curr_p - tr["entry_price"]) / tr["entry_price"]) * 100.0
            ret_peak = ((curr_p - peak_p) / peak_p) * 100.0

            status = "🟢 스윙 보유 중"
            if ret_peak <= tr["trail_pct"]:
                status = f"🚨 트레일링 스탑 발동! (고점대비 {ret_peak:+.1f}%)"
                exit_alert = True
            elif ret_entry >= tr["target_pct"]:
                status = f"🎯 목표 익절권 도달! ({ret_entry:+.1f}%)"
                exit_alert = True

            rows_html.append(
                f'<div class="row"><span><b>{tr["name"]}</b> (진입 {tr["entry_price"]} / 고점 {peak_p:.2f})</span>'
                f'<span>수익 {ret_entry:+.1f}% | <b>{status}</b></span></div>'
            )
            tg_rows.append(f"• <b>{tr['name']}</b>: 수익 {ret_entry:+.1f}% (고점대비 {ret_peak:+.1f}%) ➔ <b>{status}</b>")
        except Exception:
            continue
    return "".join(rows_html), "\n".join(tg_rows), exit_alert

def calc_kr_holding(key, param_key, is_core=False, cached_m=None):
    item = PORTFOLIO[key]
    if cached_m is not None:
        m = dict(cached_m)
    else:
        p_cfg = CUSTOM_PARAMS.get(param_key, {"rsi_cut": 35.0, "disp_cut": -8.0})
        m = get_quad_verified_metrics(item["tickers"], rsi_cut=p_cfg["rsi_cut"], disp_cut=p_cfg["disp_cut"], is_core_cash_target=is_core)
    curr_p = m["curr"] if m["curr"] > 0 else float(item["fallback_krw"])
    eval_krw = int(curr_p * item["qty"])
    ret_pct = ((curr_p - item["avg_krw"]) / item["avg_krw"]) * 100
    m["curr"], m["eval_krw"], m["ret_pct"] = curr_p, eval_krw, ret_pct
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
            <div class="q-score">{m['score']}/4점</div>
            <div class="q-st">{m['short_st']}</div>
        </div>"""

def render_sig_card(title, price_badge, my_ret_str, m, border_color):
    sig_color = "pos" if m["alert"] else ("neg" if "🚨" in m["sig"] else "")
    bar_w = int((m["score"] / 4.0) * 100)
    bar_color = "#4ade80" if m["alert"] else ("#f87171" if "🚨" in m["sig"] else "#38bdf8")

    p1_cls = "pill-on" if m["c1"] else "pill-off"
    p2_cls = "pill-on" if m["c2"] else "pill-off"
    p3_cls = "pill-on" if m["c3"] else "pill-off"
    p4_cls = "pill-on" if m["c4"] else "pill-off"

    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <div class="sig-hd">
                <div><b>{title}</b> {price_badge}</div>
                <div class="my-ret">{my_ret_str}</div>
            </div>
            <div class="bar-bg"><div class="bar-fill" style="width:{bar_w}%;background:{bar_color};"></div></div>
            <div class="metric-grid">
                <div class="m-cell"><span class="sub">RSI(14)</span><br><b>{m['rsi']:.1f}</b> <span class="sub">(기준 {m['rsi_cut']:.0f})</span></div>
                <div class="m-cell"><span class="sub">20일 이격도</span><br><b>{m['disp']:+.1f}%</b> <span class="sub">({m['disp_cut']:.0f}%)</span></div>
                <div class="m-cell"><span class="sub">볼린저 %B</span><br><b>{m['pct_b']:.2f}</b></div>
                <div class="m-cell"><span class="sub">거래량(20일)</span><br><b>{m['vol_ratio']:.1f}배</b></div>
            </div>
            <div class="pill-row">
                <span class="pill {p1_cls}">{'🟢' if m['c1'] else '⚫'} 과매도</span>
                <span class="pill {p2_cls}">{'🟢' if m['c2'] else '⚫'} 지지선</span>
                <span class="pill {p3_cls}">{'🟢' if m['c3'] else '⚫'} MACD반등</span>
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
    tranche_html, tranche_tg, tranche_alert = evaluate_new_tranches()

    # MU 제외, RAM 단독 4중 검증 지표 산출
    ram_param = CUSTOM_PARAMS["RAM"]
    ram = get_quad_verified_metrics("RAM", rsi_cut=ram_param["rsi_cut"], disp_cut=ram_param["disp_cut"], is_core_cash_target=True)
    krw = get_quad_verified_metrics("KRW=X", is_core_cash_target=False)
    krw_p = krw["curr"] if krw["curr"] > 0 else 1385.0

    ram_cfg = PORTFOLIO["RAM"]
    ram_p = ram["curr"] if ram["curr"] > 0 else ram_cfg["fallback_usd"]
    ram_reg_p = ram["reg_curr"] if ram["reg_curr"] > 0 else ram_p
    ram_eval_usd = ram_p * ram_cfg["qty"]
    ram_ret = ((ram_p - ram_cfg["avg_usd"]) / ram_cfg["avg_usd"]) * 100
    ram_eval_krw = int(ram_eval_usd * krw_p)

    kq = calc_kr_holding("KODEX_LEV", "KODEX_LEV", is_core=True)
    yg = calc_kr_holding("YG1", "YG1", is_core=False)
    or1 = calc_kr_holding("ORUM1", "ORUM", is_core=False)
    or2 = calc_kr_holding("ORUM2", "ORUM", is_core=False, cached_m=or1)
    ab = calc_kr_holding("ABCLON", "ABCLON", is_core=False)
    cash_eval = PORTFOLIO["CASH"]["eval_krw"]

    stock_eval_krw = ram_eval_krw + kq["eval_krw"] + yg["eval_krw"] + or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"]
    total_eval_krw = stock_eval_krw + cash_eval
    bio_eval_krw = or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"]

    news = (get_latest_strict_news("마이크론 OR 삼성전자 반도체 OR SK하이닉스 HBM", "[반도체/DRAM]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로/코스닥]", 2) +
            get_latest_strict_news("와이지-원 OR 절삭공구", "[와이지원]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 2))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a> ({x['source']} {x['time']})" for x in news]) or "• 최근 48시간 내 속보 없음"

    ram_color = "pos" if ram_ret >= 0 else "neg"
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
            "🇺🇸 RAM (DRAM 2X ETF)",
            f'<span class="badge">{ram["session"]}</span> <span class="sub">${ram_p:.2f} ({ram["pct"]:+.2f}%)</span>',
            f'<span class="{ram_color}">수익 {ram_ret:+.1f}%</span>',
            ram, "#38bdf8"
        ) +
        render_sig_card(
            "🇰🇷 KODEX 코스닥150레버리지",
            f'<span class="sub">₩{kq["curr"]:,.0f} ({kq["pct"]:+.2f}%)</span>',
            f'<span class="{kq_color}">수익 {kq["ret_pct"]:+.1f}%</span>',
            kq, "#f87171"
        ) +
        render_sig_card(
            "🔧 와이지-원",
            f'<span class="sub">₩{yg["curr"]:,.0f} ({yg["pct"]:+.2f}%)</span>',
            f'<span class="{yg_color}">수익 {yg["ret_pct"]:+.1f}%</span>',
            yg, "#fbbf24"
        ) +
        render_sig_card(
            "🧬 오름테라퓨틱",
            f'<span class="sub">₩{or1["curr"]:,.0f} ({or1["pct"]:+.2f}%)</span>',
            f'<span class="{or1_color}">계좌1 {or1["ret_pct"]:+.1f}%</span>',
            or1, "#c084fc"
        ) +
        render_sig_card(
            "🧬 앱클론",
            f'<span class="sub">₩{ab["curr"]:,.0f} ({ab["pct"]:+.2f}%)</span>',
            f'<span class="{ab_color}">수익 {ab["ret_pct"]:+.1f}%</span>',
            ab, "#4ade80"
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <meta http-equiv="refresh" content="1800">
    <title>마스터 관제탑 V5.5</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #070b14; color: #f8fafc; margin: 0; padding: 12px; max-width: 600px; margin: auto; }}
        .top-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
        .top-title {{ font-size: 1.1rem; font-weight: 800; color: #38bdf8; }}
        .top-sync {{ font-size: 0.72rem; color: #94a3b8; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }}
        .kpi-box {{ background: linear-gradient(145deg, #131c31, #0f172a); border: 1px solid #1e293b; border-radius: 10px; padding: 10px 8px; text-align: center; }}
        .kpi-lbl {{ font-size: 0.70rem; color: #94a3b8; margin-bottom: 4px; }}
        .kpi-val {{ font-size: 0.95rem; font-weight: 800; color: #f8fafc; }}
        .q-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 14px; }}
        .q-tile {{ border-radius: 8px; padding: 8px 4px; text-align: center; border: 1px solid #1e293b; }}
        .q-buy {{ background: rgba(74, 222, 128, 0.15); border-color: #4ade80; }}
        .q-hot {{ background: rgba(248, 113, 113, 0.15); border-color: #f87171; }}
        .q-wait {{ background: #131c31; border-color: #1e293b; }}
        .q-name {{ font-size: 0.72rem; font-weight: 700; color: #e2e8f0; margin-bottom: 2px; }}
        .q-score {{ font-size: 0.85rem; font-weight: 800; color: #38bdf8; }}
        .q-st {{ font-size: 0.68rem; color: #cbd5e1; margin-top: 2px; }}
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
        .sig-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .my-ret {{ font-size: 0.78rem; background: #0f172a; padding: 2px 7px; border-radius: 4px; }}
        .bar-bg {{ width: 100%; height: 5px; background: #0f172a; border-radius: 3px; overflow: hidden; margin-bottom: 8px; }}
        .bar-fill {{ height: 100%; border-radius: 3px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: #0f172a; padding: 6px; border-radius: 6px; margin-bottom: 8px; text-align: center; font-size: 0.75rem; }}
        .m-cell {{ line-height: 1.3; }}
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
        <div class="top-title">🛡️ 마스터 관제탑 V5.5</div>
        <div class="top-sync">동기화: {now_str} (환율 ₩{krw_p:,.1f})</div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-box">
            <div class="kpi-lbl">총 평가자산</div>
            <div class="kpi-val" style="color:#38bdf8;">{total_eval_krw//10000:,}만 원</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">주식 평가액</div>
            <div class="kpi-val">{stock_eval_krw//10000:,}만 원</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">대기 현금</div>
            <div class="kpi-val" style="color:#4ade80;">{cash_eval//10000:,}만 원</div>
        </div>
    </div>

    <div class="q-grid">
        {quick_bar_html}
    </div>

    <div class="card">
        <h2>📅 핵심 일정 D-Day 트래커</h2>
        {dday_html}
    </div>

    <div class="card">
        <h2>🎯 5대 종목 4중 검증 타점 스위치 (RAM 단독 기준)</h2>
        {sig_cards_html}
    </div>

    <div class="card">
        <h2>🛡️ 신규 진입 물량 트레일링 스탑 감시</h2>
        {tranche_html}
    </div>

    <div class="card">
        <h2>💼 보유 종목 상세 평가 & 포트폴리오 비중</h2>
        <div style="width:210px;margin:0 auto 12px auto;"><canvas id="pfChart"></canvas></div>
        <div class="row"><span><b>RAM</b> (5,854주 · 평단 $10.08) <span class="badge">{ram['session']}</span><br><span class="sub">현재 ${ram_p:.2f} (본장 ${ram_reg_p:.2f} | 확장 {ram['ext_pct']:+.2f}%)</span></span><span class="{ram_color}" style="text-align:right;">{ram_ret:+.2f}%<br>${ram_eval_usd:,.0f} ({ram_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (3,354주 · 평단 6,152원)<br><span class="sub">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)</span></span><span class="{kq_color}" style="text-align:right;">{kq['ret_pct']:+.2f}%<br>{kq['eval_krw']:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (656주 · 평단 12,910원)<br><span class="sub">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)</span></span><span class="{yg_color}" style="text-align:right;">{yg['ret_pct']:+.2f}%<br>{yg['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주 · 평단 107,113원)<br><span class="sub">현재 ₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%)</span></span><span class="{or1_color}" style="text-align:right;">{or1['ret_pct']:+.2f}%<br>{or1['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주 · 평단 96,650원)<br><span class="sub">현재 ₩{or2['curr']:,.0f} ({or2['pct']:+.2f}%)</span></span><span class="{or2_color}" style="text-align:right;">{or2['ret_pct']:+.2f}%<br>{or2['eval_krw']:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주 · 평단 52,735원)<br><span class="sub">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)</span></span><span class="{ab_color}" style="text-align:right;">{ab['ret_pct']:+.2f}%<br>{ab['eval_krw']:,}원</span></div>
    </div>

    <div class="card"><h2>📰 최근 48시간 최신 속보</h2>{news_html}</div>

    <script>
        new Chart(document.getElementById('pfChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['RAM(반도체)', '바이오(오름·앱클론)', '코스닥150레버리지', '가용현금', '와이지-원'],
                datasets: [{{
                    data: [{ram_eval_krw//10000}, {bio_eval_krw//10000}, {kq['eval_krw']//10000}, {cash_eval//10000}, {yg['eval_krw']//10000}],
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
        header_prefix = "🚨 <b>[긴급 매수/청산 시그널 포착!]</b>\n" if (any_buy_alert and not is_scheduled_slot) else ""
        tranche_section = f"\n🛡️ <b>신규 진입 물량 트레일링 스탑</b>\n{tranche_tg}\n" if tranche_tg else ""
        tg_msg = (
            f"{header_prefix}🛡️ <b>[마스터 관제탑 V5.5] RAM 집중 &amp; 콕핏 브리핑</b>\n"
            f"⏰ {now_str} | 총자산: <b>{total_eval_krw//10000:,}만 원</b>\n"
            f"👉 <a href='{DASHBOARD_URL}'>터치하여 V5.5 콕핏 대시보드 열기</a>\n\n"
            f"📅 <b>다가오는 반도체·바이오 핵심 일정</b>\n{dday_tg}\n\n"
            f"🎯 <b>5대 종목 맞춤 4중 검증 시그널</b>\n"
            f"• <b>RAM [{ram['session']}]</b>: ${ram_p:.2f} | RSI {ram['rsi']:.1f} | 이격 {ram['disp']:+.1f}% ➔ <b>{ram['sig']}</b>\n"
            f"• <b>코스닥레버리지</b>: RSI {kq['rsi']:.1f} | 이격 {kq['disp']:+.1f}% ➔ <b>{kq['sig']}</b>\n"
            f"• <b>와이지-원</b>: RSI {yg['rsi']:.1f} | 이격 {yg['disp']:+.1f}% ➔ <b>{yg['sig']}</b>\n"
            f"• <b>오름테라퓨틱</b>: RSI {or1['rsi']:.1f} | 이격 {or1['disp']:+.1f}% ➔ <b>{or1['sig']}</b>\n"
            f"• <b>앱클론</b>: RSI {ab['rsi']:.1f} | 이격 {ab['disp']:+.1f}% ➔ <b>{ab['sig']}</b>\n"
            f"{tranche_section}\n"
            f"💼 <b>보유 종목 실시간 평가</b>\n"
            f"• <b>RAM (5,854주)</b>: ${ram_p:.2f} (확장 {ram['ext_pct']:+.2f}%) | <b>{ram_ret:+.2f}%</b> (${ram_eval_usd:,.0f})\n"
            f"• <b>코스닥레버리지</b>: ₩{kq['curr']:,.0f} | <b>{kq['ret_pct']:+.2f}%</b> ({kq['eval_krw']:,}원)\n"
            f"• <b>와이지-원</b>: ₩{yg['curr']:,.0f} | <b>{yg['ret_pct']:+.2f}%</b> ({yg['eval_krw']:,}원)\n"
            f"• <b>오름 계좌1·2</b>: ₩{or1['curr']:,.0f} | <b>{or1['ret_pct']:+.2f}%</b> / <b>{or2['ret_pct']:+.2f}%</b>\n"
            f"• <b>앱클론</b>: ₩{ab['curr']:,.0f} | <b>{ab['ret_pct']:+.2f}%</b> ({ab['eval_krw']:,}원)\n\n"
            f"📰 <b>최근 48시간 핵심 속보</b>\n{news_tg}"
        )
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)

        if is_scheduled_slot:
            with open("last_sent.txt", "w", encoding="utf-8") as lf:
                lf.write(slot_key)

if __name__ == "__main__":
    main()
