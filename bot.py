import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip().lower()
EVENT_NAME = os.environ.get('GITHUB_EVENT_NAME', '').strip()

# 텔레그램 정기 브리핑 발송 시간 (한국시간 기준 오전 8시, 밤 10시)
NOTIFY_HOURS_KST = [8, 22]

CACHE_BUST = datetime.datetime.now().strftime("%m%d%H%M")
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/?v={CACHE_BUST}" if '/' in GITHUB_REPO else f"https://nojae36.github.io/stock-briefing/?v={CACHE_BUST}"

# [1] 기존 보유 포트폴리오 (손절 로직 적용 제외 - 본전 회복 및 장기/구조적 홀딩 관리)
PORTFOLIO = {
    "RAM": {"symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 10.08},
    "KODEX_LEV": {"name": "KODEX 코스닥150레버리지", "tickers": ["233740.KS"], "avg_krw": 6152, "qty": 3354, "fallback_krw": 3880},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "avg_krw": 12910, "qty": 656, "fallback_krw": 10100},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 107113, "qty": 1097, "fallback_krw": 14430},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 96650, "qty": 256, "fallback_krw": 14430},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "avg_krw": 52735, "qty": 256, "fallback_krw": 20100},
    "CASH": {"name": "가용 현금", "eval_krw": 10000000}
}

# [2] 종목별 백테스팅 최적화 맞춤 파라미터 (RSI 기준값 / 20일선 이격도 기준값)
CUSTOM_PARAMS = {
    "MU": {"rsi_cut": 36.0, "disp_cut": -7.5},
    "KODEX_LEV": {"rsi_cut": 34.0, "disp_cut": -9.0},
    "YG1": {"rsi_cut": 38.0, "disp_cut": -7.0},
    "ORUM": {"rsi_cut": 32.0, "disp_cut": -11.0},
    "ABCLON": {"rsi_cut": 32.0, "disp_cut": -11.0},
}

# [3] 신규 진입 물량 전용 트레일링 스탑 감시 리스트 (신규 매수 시 아래 주석을 해제하고 입력)
NEW_TRANCHES = [
    # 예시: {"name": "RAM 신규1차", "symbol": "RAM", "entry_date": "2026-11-15", "entry_price": 9.50, "qty": 200, "trail_pct": -7.0, "target_pct": 12.0},
    # 예시: {"name": "코스닥레버 신규1차", "symbol": "233740.KS", "entry_date": "2026-11-18", "entry_price": 3700, "qty": 800, "trail_pct": -7.0, "target_pct": 12.0},
]

# [4] DRAM/반도체 실적 및 바이오 학회·임상 핵심 일정 (한국시간 기준)
KEY_EVENTS = [
    {"date": "2026-11-18", "cat": "🔥AI·DRAM", "title": "엔비디아(NVDA) FY27 3Q 실적발표 (HBM 수요 풍향계)"},
    {"date": "2026-12-10", "cat": "🏦매크로", "title": "미국 12월 FOMC 금리결정 및 점도표 발표"},
    {"date": "2026-12-12", "cat": "🧬바이오", "title": "미국 혈액암학회(ASH 2026) 개막 (오름·앱클론 모멘텀)"},
    {"date": "2026-12-17", "cat": "💾DRAM", "title": "마이크론(MU) FY27 1Q 실적발표 (RAM 직접 모멘텀)"},
    {"date": "2027-01-08", "cat": "💾DRAM", "title": "삼성전자 2026 4Q 잠정실적 발표 (메모리 마진 확인)"},
    {"date": "2027-01-11", "cat": "🧬바이오", "title": "2027 JP모건 헬스케어 컨퍼런스 (글로벌 기술이전 시즌)"},
    {"date": "2027-01-22", "cat": "💾DRAM", "title": "SK하이닉스 2026 4Q 실적발표 (HBM3E·HBM4 가이던스)"},
]

def build_dday_section(now_kst):
    today = now_kst.date()
    html_badges = []
    tg_lines = []
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

def get_quad_verified_metrics(tickers, rsi_cut=38.0, disp_cut=-8.0, is_core_cash_target=True):
    if isinstance(tickers, str): tickers = [tickers]
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="6mo")
            if hist.empty: continue
            df = hist.dropna(subset=['Close']).copy()
            if len(df) < 5: continue

            reg_curr = float(df['Close'].iloc[-1])
            reg_prev = float(df['Close'].iloc[-2]) if len(df) >= 2 else reg_curr
            curr = reg_curr
            prev = reg_prev
            session_tag = "☀️본장"

            if not sym.endswith(('.KS', '.KQ')) and sym != 'KRW=X':
                try:
                    intra = t.history(period="5d", interval="5m", prepost=True)
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

            # 종목별 맞춤 RSI 및 이격도 기준값 적용
            c1_oversold = (rsi < rsi_cut) or (disp20 <= disp_cut)
            c2_support = (pct_b <= 0.18) or (curr >= ma60)
            c3_momentum = macd_turn
            c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (bullish_rebound and rsi < (rsi_cut - 6.0))

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            chk_str = f"[{'O' if c1_oversold else 'X'}과매도(RSI<{rsi_cut:.0f}/이격{disp_cut:.1f}%) | {'O' if c2_support else 'X'}지지 | {'O' if c3_momentum else 'X'}MACD | {'O' if c4_volume else 'X'}수급]"

            is_buy_alert = False
            if c1_oversold and score == 4:
                sig = f"🔥 4중검증 완벽타점 ({score}/4)"
                cash = "신규 트랑셰 400만 원 투입" if is_core_cash_target else "진바닥 강세 전환 (분할 추매 유효)"
                is_buy_alert = True
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig = f"✅ 1차 검증타점 ({score}/4)"
                cash = "신규 트랑셰 300만 원 투입" if is_core_cash_target else "단기 반등 타점 (소액 스윙 유효)"
                is_buy_alert = True
            elif c1_oversold and score <= 2:
                sig, cash = f"⚠️ 하락칼날 주의 ({score}/4)", "0원 대기 (수급·반등 미확인)"
            elif rsi > 72:
                sig, cash = f"🚨 단기 과열 ({score}/4)", "신규 추격금지 (신규물량 익절 점검)"
            else:
                sig, cash = f"⏸ 중립·관망 ({score}/4)", "기존 물량 홀딩 · 현금 대기"

            return {
                "curr": curr, "reg_curr": reg_curr, "pct": pct, "ext_pct": ext_pct,
                "session": session_tag, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio,
                "score": score, "chk": chk_str, "sig": sig, "cash": cash, "alert": is_buy_alert
            }
        except Exception:
            continue
    return {"curr": 0.0, "reg_curr": 0.0, "pct": 0.0, "ext_pct": 0.0, "session": "대기", "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0, "score": 0, "chk": "[대기]", "sig": "데이터 대기", "cash": "0원", "alert": False}

def evaluate_new_tranches():
    if not NEW_TRANCHES:
        return '<div class="sub">현재 가용 현금으로 신규 진입한 단기 스윙 물량이 없습니다. (기존 보유 물량은 트레일링 스탑 제외)</div>', "", False
    rows_html = []
    tg_rows = []
    exit_alert = False
    for tr in NEW_TRANCHES:
        try:
            hist = yf.Ticker(tr["symbol"]).history(start=tr["entry_date"])
            if hist.empty: continue
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

def calc_kr_holding(key, param_key, is_core=False):
    item = PORTFOLIO[key]
    p_cfg = CUSTOM_PARAMS.get(param_key, {"rsi_cut": 38.0, "disp_cut": -8.0})
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
        now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        for entry in feedparser.parse(url).entries:
            if not hasattr(entry, 'published'): continue
            pub_kst = parsedate_to_datetime(entry.published).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            if (now_kst - pub_kst).total_seconds() / 3600 > max_hours: continue
            title = (entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            items.append({"tag": tag, "title": title, "source": getattr(entry, 'source', {}).get('title', '주요언론'), "time": pub_kst.strftime("%m/%d %H:%M"), "link": entry.link})
            if len(items) >= max_items: break
    except Exception: pass
    return items

def render_sig_card(title, price_str, m, border_color):
    sig_color = "pos" if m["alert"] else ("neg" if "🚨" in m["sig"] else "")
    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <b>{title}</b> {price_str}<br>
            • RSI(14): <b>{m['rsi']:.1f}</b> | 20일선 이격: <b>{m['disp']:+.1f}%</b> | 볼린저 %B: <b>{m['pct_b']:.2f}</b><br>
            • MACD 히스토그램: <b>{'반등 전환 ↑' if m['macd_turn'] else '하락 진행 ↓'}</b> | 거래량(20일비): <b>{m['vol_ratio']:.2f}배</b><br>
            • 맞춤검증: <span class="sub">{m['chk']}</span><br>
            👉 판정: <span class="{sig_color}">{m['sig']}</span> → <b class="warn">{m['cash']}</b>
        </div>"""

def main():
    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = now_kst.strftime("%Y-%m-%d %H:%M KST")

    dday_html, dday_tg = build_dday_section(now_kst)
    tranche_html, tranche_tg, tranche_alert = evaluate_new_tranches()

    mu_cfg = CUSTOM_PARAMS["MU"]
    mu = get_quad_verified_metrics("MU", rsi_cut=mu_cfg["rsi_cut"], disp_cut=mu_cfg["disp_cut"], is_core_cash_target=True)
    ram = get_quad_verified_metrics("RAM", rsi_cut=mu_cfg["rsi_cut"], disp_cut=mu_cfg["disp_cut"], is_core_cash_target=True)
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
    or2 = calc_kr_holding("ORUM2", "ORUM", is_core=False)
    ab = calc_kr_holding("ABCLON", "ABCLON", is_core=False)
    cash_eval = PORTFOLIO["CASH"]["eval_krw"]

    total_eval_krw = ram_eval_krw + kq["eval_krw"] + yg["eval_krw"] + or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"] + cash_eval
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

    sig_cards_html = (
        render_sig_card("🇺🇸 마이크론(MU) / RAM", f'<span class="badge">{mu["session"]}</span> (MU ${mu["curr"]:.2f} | RAM ${ram_p:.2f})', mu, "#38bdf8") +
        render_sig_card("🇰🇷 KODEX 코스닥150레버리지", f"(현재 ₩{kq['curr']:,.0f} | {kq['pct']:+.2f}%)", kq, "#f87171") +
        render_sig_card("🔧 와이지-원", f"(현재 ₩{yg['curr']:,.0f} | {yg['pct']:+.2f}%)", yg, "#fbbf24") +
        render_sig_card("🧬 오름테라퓨틱", f"(현재 ₩{or1['curr']:,.0f} | {or1['pct']:+.2f}%)", or1, "#c084fc") +
        render_sig_card("🧬 앱클론", f"(현재 ₩{ab['curr']:,.0f} | {ab['pct']:+.2f}%)", ab, "#4ade80")
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <meta http-equiv="refresh" content="1800">
    <title>마스터 관제탑 V5.4</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #0b0f19; color: #f8fafc; margin: 0; padding: 14px; max-width: 600px; margin: auto; }}
        .card {{ background: #131c31; border: 1px solid #1e293b; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
        h2 {{ font-size: 0.95rem; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #1e293b; color: #38bdf8; display: flex; justify-content: space-between; }}
        .row {{ display: flex; justify-content: space-between; font-size: 0.82rem; margin-bottom: 8px; align-items: center; }}
        .sub {{ font-size: 0.72rem; color: #94a3b8; }}
        .badge {{ background: #334155; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-size: 0.70rem; margin-left: 4px; }}
        .dday-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.80rem; }}
        .dday-tag {{ padding: 2px 7px; border-radius: 4px; font-weight: bold; font-size: 0.72rem; min-width: 44px; text-align: center; }}
        .dday-urgent {{ background: #ef4444; color: #fff; }}
        .dday-normal {{ background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; }}
        .dday-cat {{ color: #fbbf24; font-weight: bold; font-size: 0.75rem; min-width: 68px; }}
        .dday-title {{ color: #e2e8f0; }}
        .sig-box {{ background: #1e293b; border-left: 4px solid #38bdf8; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 0.80rem; line-height: 1.45; }}
        .pos {{ color: #4ade80; font-weight: bold; }} .neg {{ color: #f87171; font-weight: bold; }} .warn {{ color: #fbbf24; font-weight: bold; }}
        .n-item {{ background: rgba(30,41,59,0.5); padding: 8px 10px; border-radius: 8px; margin-bottom: 8px; font-size: 0.82rem; }}
        .n-hd {{ display: flex; justify-content: space-between; font-size: 0.72rem; margin-bottom: 4px; }} .tag {{ color: #38bdf8; font-weight: bold; }} .meta {{ color: #94a3b8; }}
        a {{ color: #f1f5f9; text-decoration: none; }}
    </style>
</head>
<body>
    <h1 style="font-size:1.2rem;text-align:center;color:#38bdf8;margin-bottom:4px;">🛡️ 마스터 투자 관제탑 V5.4</h1>
    <p style="text-align:center;font-size:0.75rem;color:#94a3b8;margin-top:0;">동기화: {now_str} | 총 평가자산: <b>{total_eval_krw:,}원</b></p>

    <div class="card">
        <h2>📅 0. DRAM 반도체 실적 & 바이오 임상 D-Day 트래커</h2>
        {dday_html}
    </div>

    <div class="card">
        <h2>🎯 1. 종목별 맞춤 파라미터 4중 검증 매수 시그널</h2>
        {sig_cards_html}
    </div>

    <div class="card">
        <h2>🛡️ 2. 신규 진입 물량 전용 트레일링 스탑 감시</h2>
        {tranche_html}
    </div>

    <div class="card">
        <h2>📊 3. 실시간 포트폴리오 비중 (Chart.js)</h2>
        <div style="width:230px;margin:0 auto;"><canvas id="pfChart"></canvas></div>
    </div>

    <div class="card">
        <h2>💼 4. 기존 보유 종목 실수량 평가 현황 (홀딩 관리)</h2>
        <div class="row"><span><b>RAM</b> (5,854주·$10.08) <span class="badge">{ram['session']}</span><br><span class="sub">현재 ${ram_p:.2f} (본장 ${ram_reg_p:.2f} | 확장 {ram['ext_pct']:+.2f}%)</span></span><span class="{ram_color}" style="text-align:right;">{ram_ret:+.2f}%<br>${ram_eval_usd:,.0f} ({ram_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (3,354주·6,152원)<br><span class="sub">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)</span></span><span class="{kq_color}" style="text-align:right;">{kq['ret_pct']:+.2f}%<br>{kq['eval_krw']:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (656주·12,910원)<br><span class="sub">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)</span></span><span class="{yg_color}" style="text-align:right;">{yg['ret_pct']:+.2f}%<br>{yg['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주·107,113원)<br><span class="sub">현재 ₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%)</span></span><span class="{or1_color}" style="text-align:right;">{or1['ret_pct']:+.2f}%<br>{or1['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주·96,650원)<br><span class="sub">현재 ₩{or2['curr']:,.0f} ({or2['pct']:+.2f}%)</span></span><span class="{or2_color}" style="text-align:right;">{or2['ret_pct']:+.2f}%<br>{or2['eval_krw']:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주·52,735원)<br><span class="sub">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)</span></span><span class="{ab_color}" style="text-align:right;">{ab['ret_pct']:+.2f}%<br>{ab['eval_krw']:,}원</span></div>
        <div class="row"><span><b>가용 현금 (신규 타점 대기)</b></span><span style="color:#38bdf8;font-weight:bold;">{cash_eval:,}원</span></div>
    </div>

    <div class="card"><h2>📰 5. 최근 48시간 최신 속보</h2>{news_html}</div>

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

    any_buy_alert = any([mu["alert"], kq["alert"], yg["alert"], or1["alert"], ab["alert"], tranche_alert])
    is_scheduled_hour = (now_kst.hour in NOTIFY_HOURS_KST)
    is_manual_run = (EVENT_NAME == "workflow_dispatch")

    if TOKEN and CHAT_ID and (is_scheduled_hour or is_manual_run or any_buy_alert):
        header_prefix = "🚨 <b>[긴급 매수/청산 시그널 포착!]</b>\n" if (any_buy_alert and not is_scheduled_hour) else ""
        tranche_section = f"\n🛡️ <b>신규 진입 물량 트레일링 스탑</b>\n{tranche_tg}\n" if tranche_tg else ""
        tg_msg = (
            f"{header_prefix}🛡️ <b>[마스터 관제탑 V5.4] 맞춤 타점 &amp; D-Day 브리핑</b>\n"
            f"⏰ {now_str} | 총자산: <b>{total_eval_krw//10000:,}만 원</b>\n"
            f"👉 <a href='{DASHBOARD_URL}'>터치하여 D-Day &amp; 4중 검증 대시보드 열기</a>\n\n"
            f"📅 <b>다가오는 반도체·바이오 핵심 일정</b>\n{dday_tg}\n\n"
            f"🎯 <b>종목별 맞춤 4중 검증 시그널</b>\n"
            f"• <b>MU/RAM [{mu['session']}]</b>: RSI {mu['rsi']:.1f} | 이격 {mu['disp']:+.1f}% ➔ <b>{mu['sig']}</b>\n"
            f"• <b>코스닥레버리지</b>: RSI {kq['rsi']:.1f} | 이격 {kq['disp']:+.1f}% ➔ <b>{kq['sig']}</b>\n"
            f"• <b>와이지-원</b>: RSI {yg['rsi']:.1f} | 이격 {yg['disp']:+.1f}% ➔ <b>{yg['sig']}</b>\n"
            f"• <b>오름테라퓨틱</b>: RSI {or1['rsi']:.1f} | 이격 {or1['disp']:+.1f}% ➔ <b>{or1['sig']}</b>\n"
            f"• <b>앱클론</b>: RSI {ab['rsi']:.1f} | 이격 {ab['disp']:+.1f}% ➔ <b>{ab['sig']}</b>\n"
            f"{tranche_section}\n"
            f"📰 <b>최근 48시간 핵심 속보</b>\n{news_tg}"
        )
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True})

if __name__ == "__main__":
    main()
