import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip()
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/" if '/' in GITHUB_REPO else "https://heondol4011.github.io/stock-briefing/"

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
    """
    [V5 4중 교차 검증 엔진]
    1. 과매도(RSI<35 or 이격도<=-10%) | 2. 지지/볼린저(%B<=0.15 or 60일선위)
    3. 모멘텀(MACD 오실레이터 반등)   | 4. 수급(거래량 급증 + 양봉/아랫꼬리)
    """
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

            # [지표 1] 14일 Wilder RSI & 20일 이격도
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

            # [지표 2] 볼린저밴드(20, 2) %B (0 이하: 하단선 이탈)
            std20 = float(closes.tail(20).std()) if len(closes) >= 20 else 0.0
            bb_lower = ma20 - 2 * std20
            bb_upper = ma20 + 2 * std20
            pct_b = (curr - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

            # [지표 3] MACD(12,26,9) 히스토그램 반전 여부
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

            # [지표 4] 바닥권 거래량 비율 & 양봉/아랫꼬리 수급 확인
            avg_vol20 = float(vols.tail(20).mean()) if len(vols) >= 5 else 0.0
            curr_vol = float(vols.iloc[-1])
            vol_ratio = (curr_vol / avg_vol20) if avg_vol20 > 0 else 1.0

            c_open, c_high, c_low = float(opens.iloc[-1]), float(highs.iloc[-1]), float(lows.iloc[-1])
            candle_range = c_high - c_low
            lower_wick_ratio = ((min(c_open, curr) - c_low) / candle_range) if candle_range > 0 else 0.0
            bullish_rebound = (curr >= c_open) or (lower_wick_ratio >= 0.35)

            # [4중 관문 통과 여부 채점]
            c1_oversold = (rsi < 38.0) or (disp20 <= -8.0)
            c2_support = (pct_b <= 0.18) or (curr >= ma60)
            c3_momentum = macd_turn
            c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (bullish_rebound and rsi < 30.0)

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            chk_str = f"[{'O' if c1_oversold else 'X'}과매도 | {'O' if c2_support else 'X'}밴드지지 | {'O' if c3_momentum else 'X'}MACD반등 | {'O' if c4_volume else 'X'}양봉수급]"

            # 엄격한 현금 투입 판정
            if c1_oversold and score == 4:
                sig, cash = f"🔥 4중검증 완벽타점 ({score}/4)", "400만 원 즉시 투입 (진바닥 확인)"
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig, cash = f"✅ 1차 검증타점 ({score}/4)", "300만 원 분할 투입 (반등 포착)"
            elif c1_oversold and score <= 2:
                sig, cash = f"⚠️ 하락칼날 주의 ({score}/4)", "0원 대기 (과매도이나 반등수급 미확인)"
            elif rsi > 70:
                sig, cash = f"🚨 단기 과열 ({score}/4)", "0원 (추격매수 금지·차익실현 대기)"
            else:
                sig, cash = f"⏸ 중립·관망 ({score}/4)", "0원 (현금 1,000만 대기)"

            return {
                "curr": curr, "pct": pct, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio,
                "score": score, "chk": chk_str, "sig": sig, "cash": cash
            }
        except Exception as e:
            print(f"[{sym}] 지표 경고: {e}")
            continue
    return {"curr": 0.0, "pct": 0.0, "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0, "score": 0, "chk": "[대기]", "sig": "데이터 대기", "cash": "0원"}

def calc_kr_holding(key):
    item = PORTFOLIO[key]
    m = get_quad_verified_metrics(item["tickers"])
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

def main():
    now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")

    mu = get_quad_verified_metrics("MU")
    ram = get_quad_verified_metrics("RAM")
    soxx = get_quad_verified_metrics("SOXX")
    krw = get_quad_verified_metrics("KRW=X")
    krw_p = krw["curr"] if krw["curr"] > 0 else 1385.0

    ram_cfg = PORTFOLIO["RAM"]
    ram_p = ram["curr"] if ram["curr"] > 0 else ram_cfg["fallback_usd"]
    ram_eval_usd = ram_p * ram_cfg["qty"]
    ram_ret = ((ram_p - ram_cfg["avg_usd"]) / ram_cfg["avg_usd"]) * 100
    ram_eval_krw = int(ram_eval_usd * krw_p)

    kq = calc_kr_holding("KODEX_LEV")
    yg = calc_kr_holding("YG1")
    or1 = calc_kr_holding("ORUM1")
    or2 = calc_kr_holding("ORUM2")
    ab = calc_kr_holding("ABCLON")
    cash_eval = PORTFOLIO["CASH"]["eval_krw"]

    total_eval_krw = ram_eval_krw + kq["eval_krw"] + yg["eval_krw"] + or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"] + cash_eval
    bio_eval_krw = or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"]

    news = (get_latest_strict_news("마이크론 OR DRAM OR HBM 반도체", "[반도체/RAM]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로/코스닥]", 2) +
            get_latest_strict_news("와이지-원 OR 절삭공구", "[와이지원]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 2))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a> ({x['source']} {x['time']})" for x in news]) or "• 최근 48시간 내 속보 없음"

    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><meta http-equiv="refresh" content="1800"><title>마스터 관제탑 V5</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body{{font-family:-apple-system,sans-serif;background:#0b0f19;color:#f8fafc;margin:0;padding:14px;max-width:600px;margin:auto;}}
        .card{{background:#131c31;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-bottom:14px;}}
        h2{{font-size:0.95rem;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #1e293b;color:#38bdf8;display:flex;justify-content:space-between;}}
        .row{{display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:8px;align-items:center;}}
        .sub{{font-size:0.72rem;color:#94a3b8;}}
        .sig-box{{background:#1e293b;border-left:4px solid #38bdf8;padding:10px;border-radius:6px;margin-bottom:8px;font-size:0.80rem;line-height:1.45;}}
        .pos{{color:#4ade80;font-weight:bold;}} .neg{{color:#f87171;font-weight:bold;}} .warn{{color:#fbbf24;font-weight:bold;}}
        .n-item{{background:rgba(30,41,59,0.5);padding:8px 10px;border-radius:8px;margin-bottom:8px;font-size:0.82rem;}}
        .n-hd{{display:flex;justify-content:space-between;font-size:0.72rem;margin-bottom:4px;}} .tag{{color:#38bdf8;font-weight:bold;}} .meta{{color:#94a3b8;}}
        a{{color:#f1f5f9;text-decoration:none;}}
    </style></head><body>
    <h1 style="font-size:1.2rem;text-align:center;color:#38bdf8;margin-bottom:4px;">🛡️ 마스터 투자 관제탑 V5 (4중 검증)</h1>
    <p style="text-align:center;font-size:0.75rem;color:#94a3b8;margin-top:0;">동기화: {now_str} | 총 평가자산: <b>{total_eval_krw:,}원</b></p>

    <div class="card">
        <h2>🎯 1. 현금 1,000만 원 4중 교차 검증 매수 시그널</h2>
        <div class="sig-box">
            <b>🇺🇸 마이크론(MU) / RAM</b> (MU ${mu['curr']:.2f} \vert{} RAM${ram_p:.2f})<br>
            • RSI(14): <b>{mu['rsi']:.1f}</b> | 20일선 이격: <b>{mu['disp']:+.1f}%</b> | 볼린저 %B: <b>{mu['pct_b']:.2f}</b><br>
            • MACD 히스토그램: <b>{'반등 전환 ↑' if mu['macd_turn'] else '하락 진행 ↓'}</b> | 거래량(20일비): <b>{mu['vol_ratio']:.2f}배</b><br>
            • 검증: <span class="sub">{mu['chk']}</span><br>
            👉 판정: <span class="pos">{mu['sig']}</span> → <b class="warn">{mu['cash']}</b>
        </div>
        <div class="sig-box" style="border-left-color:#c084fc;margin-bottom:0;">
            <b>🇰🇷 KODEX 코스닥150레버리지</b> (현재 ₩{kq['curr']:,.0f})<br>
            • RSI(14): <b>{kq['rsi']:.1f}</b> | 20일선 이격: <b>{kq['disp']:+.1f}%</b> | 볼린저 %B: <b>{kq['pct_b']:.2f}</b><br>
            • MACD 히스토그램: <b>{'반등 전환 ↑' if kq['macd_turn'] else '하락 진행 ↓'}</b> | 거래량(20일비): <b>{kq['vol_ratio']:.2f}배</b><br>
            • 검증: <span class="sub">{kq['chk']}</span><br>
            👉 판정: <span class="pos">{kq['sig']}</span> → <b class="warn">{kq['cash']}</b>
        </div>
    </div>

    <div class="card">
        <h2>📊 2. 실시간 포트폴리오 비중 (Chart.js)</h2>
        <div style="width:230px;margin:0 auto;"><canvas id="pfChart"></canvas></div>
    </div>

    <div class="card">
        <h2>💼 3. 전 종목 실수량 · 평단가 자동 평가 현황</h2>
        <div class="row"><span><b>RAM</b> (5,854주·$10.08)<br><span class="sub">현재 ${ram_p:.2f} ({ram['pct']:+.2f}%)</span></span><span class="{'pos' if ram_ret>=0 else 'neg'}" style="text-align:right;">{ram_ret:+.2f}%<br>${ram_eval_usd:,.0f} ({ram_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (3,354주·6,152원)<br><span class="sub">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)</span></span><span class="{'pos' if kq['ret_pct']>=0 else 'neg'}" style="text-align:right;">{kq['ret_pct']:+.2f}%<br>{kq['eval_krw']:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (656주·12,910원)<br><span class="sub">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)</span></span><span class="{'pos' if yg['ret_pct']>=0 else 'neg'}" style="text-align:right;">{yg['ret_pct']:+.2f}%<br>{yg['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주·107,113원)<br><span class="sub">현재 ₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%)</span></span><span class="{'pos' if or1['ret_pct']>=0 else 'neg'}" style="text-align:right;">{or1['ret_pct']:+.2f}%<br>{or1['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주·96,650원)<br><span class="sub">현재 ₩{or2['curr']:,.0f} ({or2['pct']:+.2f}%)</span></span><span class="{'pos' if or2['ret_pct']>=0 else 'neg'}" style="text-align:right;">{or2['ret_pct']:+.2f}%<br>{or2['eval_krw']:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주·52,735원)<br><span class="sub">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)</span></span><span class="{'pos' if ab['ret_pct']>=0 else 'neg'}" style="text-align:right;">{ab['ret_pct']:+.2f}%<br>{ab['eval_krw']:,}원</span></div>
        <div class="row"><span><b>가용 현금 (4중 검증 대기)</b></span><span style="color:#38bdf8;font-weight:bold;">{cash_eval:,}원</span></div>
    </div>

    <div class="card"><h2>📰 4. 최근 48시간 최신 속보</h2>{news_html}</div>

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
    </body></html>"""

    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

    tg_msg = (
        f"🛡️ <b>[마스터 관제탑 V5] 4중 교차 검증 &amp; 포트폴리오 브리핑</b>\n"
        f"⏰ {now_str} | 총자산: <b>{total_eval_krw//10000:,}만 원</b>\n"
        f"👉 <a href='{DASHBOARD_URL}'>터치하여 도넛 차트 &amp; 4중 검증 대시보드 열기</a>\n\n"
        f"🎯 <b>1. 현금 1,000만 원 4중 검증 시그널</b>\n"
        f"• <b>MU/RAM</b>: RSI {mu['rsi']:.1f} | 이격 {mu['disp']:+.1f}% | %B {mu['pct_b']:.2f} | 거래량 {mu['vol_ratio']:.1f}배\n"
        f"  {mu['chk']}\n"
        f"  ➔ <b>{mu['sig']} : {mu['cash']}</b>\n"
        f"• <b>코스닥레버리지</b>: RSI {kq['rsi']:.1f} | 이격 {kq['disp']:+.1f}% | %B {kq['pct_b']:.2f} | 거래량 {kq['vol_ratio']:.1f}배\n"
        f"  {kq['chk']}\n"
        f"  ➔ <b>{kq['sig']} : {kq['cash']}</b>\n\n"
        f"💼 <b>2. 보유 전 종목 실시간 평가</b>\n"
        f"• <b>RAM (5,854주)</b>: ${ram_p:.2f} ({ram['pct']:+.2f}\%) \vert{} <b>{ram_ret:+.2f}\%</b> (${ram_eval_usd:,.0f})\n"
        f"• <b>코스닥레버리지 (3,354주)</b>: ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%) | <b>{kq['ret_pct']:+.2f}%</b> ({kq['eval_krw']:,}원)\n"
        f"• <b>와이지-원 (656주)</b>: ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%) | <b>{yg['ret_pct']:+.2f}%</b> ({yg['eval_krw']:,}원)\n"
        f"• <b>오름 계좌1·2</b>: ₩{or1['curr']:,.0f} | <b>{or1['ret_pct']:+.2f}%</b> / <b>{or2['ret_pct']:+.2f}%</b>\n"
        f"• <b>앱클론 (256주)</b>: ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%) | <b>{ab['ret_pct']:+.2f}%</b> ({ab['eval_krw']:,}원)\n\n"
        f"📰 <b>3. 최근 48시간 핵심 속보</b>\n{news_tg}"
    )
    if TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True})

if __name__ == "__main__":
    main()
