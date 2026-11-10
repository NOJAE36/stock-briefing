import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip()
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/" if '/' in GITHUB_REPO else "https://github.com/"

# [실제 평단가(avg_price) 및 보유 수량(qty) 100% 반영 마스터 데이터]
PORTFOLIO = {
    "RAM": {"symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 10.08},
    "KODEX_LEV": {"name": "KODEX 코스닥150레버리지", "tickers": ["233740.KS"], "avg_krw": 6152, "qty": 3354, "fallback_krw": 3880},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "avg_krw": 12910, "qty": 656, "fallback_krw": 10100},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 107113, "qty": 1097, "fallback_krw": 14430},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "avg_krw": 96650, "qty": 256, "fallback_krw": 14430},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "avg_krw": 52735, "qty": 256, "fallback_krw": 20100},
    "CASH": {"name": "가용 현금", "eval_krw": 10000000}
}

def get_tech_metrics(tickers):
    """현재가, 전일대비 등락률, RSI(14), 20일선 이격도 및 매수 시그널 반환"""
    if isinstance(tickers, str): tickers = [tickers]
    for sym in tickers:
        try:
            hist = yf.Ticker(sym).history(period="6mo")
            if hist.empty: continue
            closes = hist['Close'].dropna()
            curr = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) >= 2 else curr
            pct = ((curr - prev) / prev) * 100 if prev > 0 else 0.0

            if len(closes) >= 15:
                delta = closes.diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                last_loss = float(loss.iloc[-1])
                rsi = 100.0 if last_loss == 0 else 100.0 - (100.0 / (1.0 + (float(gain.iloc[-1]) / last_loss)))
            else: rsi = 50.0

            ma20 = float(closes.tail(20).mean())
            disp20 = ((curr - ma20) / ma20) * 100 if ma20 > 0 else 0.0

            if rsi < 25: sig, cash = "🔥 3차 패닉셀 타점", "400만 원 투입"
            elif rsi < 30 and disp20 <= -15.0: sig, cash = "⚡ 2차 투매 타점", "300만 원 투입"
            elif rsi < 35 or disp20 <= -10.0: sig, cash = "✅ 1차 과매도 타점", "300만 원 투입"
            elif rsi > 70: sig, cash = "⚠️ 단기 과열", "0원 (추격금지)"
            else: sig, cash = "⏸ 중립·관망", "0원 (현금 대기)"
            return curr, pct, rsi, ma20, disp20, sig, cash
        except Exception: continue
    return 0.0, 0.0, 50.0, 0.0, 0.0, "데이터 대기", "0원"

def calc_kr_holding(key):
    """실제 평단가와 보유 수량으로 평가금액 및 수익률 정확히 계산"""
    item = PORTFOLIO[key]
    curr_p, day_pct, rsi, ma20, disp, sig, cash = get_tech_metrics(item["tickers"])
    if curr_p <= 0:
        curr_p = float(item["fallback_krw"])
    invest_krw = item["avg_krw"] * item["qty"]
    eval_krw = int(curr_p * item["qty"])
    ret_pct = ((curr_p - item["avg_krw"]) / item["avg_krw"]) * 100
    return curr_p, day_pct, invest_krw, eval_krw, ret_pct, rsi, ma20, disp, sig, cash

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

    # 1. 해외 및 매크로 시세
    mu_p, mu_pct, mu_rsi, mu_ma20, mu_disp, mu_sig, mu_cash = get_tech_metrics("MU")
    ram_p, ram_pct, ram_rsi, ram_ma20, ram_disp, ram_sig, ram_cash = get_tech_metrics("RAM")
    soxx_p, soxx_pct, *_ = get_tech_metrics("SOXX")
    krw_p, krw_pct, *_ = get_tech_metrics("KRW=X")
    if krw_p <= 0: krw_p = 1385.0

    # 2. RAM (5,854주 / 평단 $10.0779) 및 국내 5종목 실수량 정밀 계산
    ram_cfg = PORTFOLIO["RAM"]
    if ram_p <= 0: ram_p = ram_cfg["fallback_usd"]
    ram_invest_usd = ram_cfg["avg_usd"] * ram_cfg["qty"]
    ram_eval_usd = ram_p * ram_cfg["qty"]
    ram_ret = ((ram_p - ram_cfg["avg_usd"]) / ram_cfg["avg_usd"]) * 100
    ram_eval_krw = int(ram_eval_usd * krw_p)

    kq_p, kq_pct, kq_inv, kq_eval, kq_ret, kq_rsi, kq_ma20, kq_disp, kq_sig, kq_cash = calc_kr_holding("KODEX_LEV")
    yg_p, yg_pct, yg_inv, yg_eval, yg_ret, *_ = calc_kr_holding("YG1")
    or1_p, or1_pct, or1_inv, or1_eval, or1_ret, *_ = calc_kr_holding("ORUM1")
    or2_p, or2_pct, or2_inv, or2_eval, or2_ret, *_ = calc_kr_holding("ORUM2")
    ab_p, ab_pct, ab_inv, ab_eval, ab_ret, *_ = calc_kr_holding("ABCLON")
    cash_eval = PORTFOLIO["CASH"]["eval_krw"]

    total_eval_krw = ram_eval_krw + kq_eval + yg_eval + or1_eval + or2_eval + ab_eval + cash_eval
    bio_eval_krw = or1_eval + or2_eval + ab_eval

    # 3. 48시간 이내 최신 뉴스 수집
    news = (get_latest_strict_news("마이크론 OR DRAM OR HBM 반도체", "[반도체/RAM]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로/코스닥]", 2) +
            get_latest_strict_news("와이지-원 OR 절삭공구", "[와이지원]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 2))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a> ({x['source']} {x['time']})" for x in news]) or "• 최근 48시간 내 속보 없음"

    # 4. Chart.js 도넛 차트가 포함된 모바일 HTML 대시보드 생성
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><meta http-equiv="refresh" content="1800"><title>마스터 관제탑 V4</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body{{font-family:-apple-system,sans-serif;background:#0b0f19;color:#f8fafc;margin:0;padding:14px;max-width:600px;margin:auto;}}
        .card{{background:#131c31;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-bottom:14px;}}
        h2{{font-size:0.95rem;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #1e293b;color:#38bdf8;display:flex;justify-content:space-between;}}
        .row{{display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:8px;align-items:center;}}
        .sub{{font-size:0.72rem;color:#94a3b8;}}
        .sig-box{{background:#1e293b;border-left:4px solid #38bdf8;padding:10px;border-radius:6px;margin-bottom:8px;font-size:0.81rem;line-height:1.4;}}
        .pos{{color:#4ade80;font-weight:bold;}} .neg{{color:#f87171;font-weight:bold;}}
        .n-item{{background:rgba(30,41,59,0.5);padding:8px 10px;border-radius:8px;margin-bottom:8px;font-size:0.82rem;}}
        .n-hd{{display:flex;justify-content:space-between;font-size:0.72rem;margin-bottom:4px;}} .tag{{color:#38bdf8;font-weight:bold;}} .meta{{color:#94a3b8;}}
        a{{color:#f1f5f9;text-decoration:none;}}
    </style></head><body>
    <h1 style="font-size:1.2rem;text-align:center;color:#38bdf8;margin-bottom:4px;">🔥 마스터 투자 관제탑 V4</h1>
    <p style="text-align:center;font-size:0.75rem;color:#94a3b8;margin-top:0;">동기화: {now_str} | 총 평가자산: <b>{total_eval_krw:,}원</b></p>

    <div class="card">
        <h2>📊 1. 실시간 포트폴리오 비중 (Chart.js)</h2>
        <div style="width:240px;margin:0 auto 10px auto;"><canvas id="pfChart"></canvas></div>
    </div>

    <div class="card">
        <h2>💼 2. 전 종목 실수량 · 평단가 자동 평가 현황</h2>
        <div class="row"><span><b>RAM</b> (5,854주·평단 $10.08)<br><span class="sub">현재 ${ram_p:.2f} ({ram_pct:+.2f}%)</span></span><span class="{'pos' if ram_ret>=0 else 'neg'}" style="text-align:right;">{ram_ret:+.2f}%<br>${ram_eval_usd:,.0f} ({ram_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (3,354주·평단 6,152원)<br><span class="sub">현재 ₩{kq_p:,.0f} ({kq_pct:+.2f}%)</span></span><span class="{'pos' if kq_ret>=0 else 'neg'}" style="text-align:right;">{kq_ret:+.2f}%<br>{kq_eval:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (656주·평단 12,910원)<br><span class="sub">현재 ₩{yg_p:,.0f} ({yg_pct:+.2f}%)</span></span><span class="{'pos' if yg_ret>=0 else 'neg'}" style="text-align:right;">{yg_ret:+.2f}%<br>{yg_eval:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주·평단 107,113원)<br><span class="sub">현재 ₩{or1_p:,.0f} ({or1_pct:+.2f}%)</span></span><span class="{'pos' if or1_ret>=0 else 'neg'}" style="text-align:right;">{or1_ret:+.2f}%<br>{or1_eval:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주·평단 96,650원)<br><span class="sub">현재 ₩{or2_p:,.0f} ({or2_pct:+.2f}%)</span></span><span class="{'pos' if or2_ret>=0 else 'neg'}" style="text-align:right;">{or2_ret:+.2f}%<br>{or2_eval:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주·평단 52,735원)<br><span class="sub">현재 ₩{ab_p:,.0f} ({ab_pct:+.2f}%)</span></span><span class="{'pos' if ab_ret>=0 else 'neg'}" style="text-align:right;">{ab_ret:+.2f}%<br>{ab_eval:,}원</span></div>
        <div class="row"><span><b>가용 현금 (스윙 대기)</b></span><span style="color:#38bdf8;font-weight:bold;">{cash_eval:,}원</span></div>
    </div>

    <div class="card">
        <h2>🎯 3. 현금 1,000만 원 기술적 투입 시그널</h2>
        <div class="sig-box">
            <b>🇺🇸 마이크론(MU) / RAM</b> (MU ${mu_p:.2f} | 환율 ₩{krw_p:,.1f})<br>
            • MU RSI(14): <b>{mu_rsi:.1f}</b> | 20일선 이격: <b>{mu_disp:+.1f}%</b><br>
            👉 판정: <span class="pos">{mu_sig}</span> → <b>{mu_cash}</b>
        </div>
        <div class="sig-box" style="border-left-color:#c084fc;margin-bottom:0;">
            <b>🇰🇷 KODEX 코스닥150레버리지</b><br>
            • RSI(14): <b>{kq_rsi:.1f}</b> | 20일선 이격: <b>{kq_disp:+.1f}%</b><br>
            👉 판정: <span class="pos">{kq_sig}</span> → <b>{kq_cash}</b>
        </div>
    </div>

    <div class="card"><h2>📰 4. 최근 48시간 최신 속보</h2>{news_html}</div>

    <script>
        new Chart(document.getElementById('pfChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['RAM(반도체)', '바이오(오름·앱클론)', '코스닥150레버리지', '가용현금', '와이지-원'],
                datasets: [{{
                    data: [{ram_eval_krw//10000}, {bio_eval_krw//10000}, {kq_eval//10000}, {cash_eval//10000}, {yg_eval//10000}],
                    backgroundColor: ['#38bdf8', '#c084fc', '#f87171', '#4ade80', '#fbbf24'],
                    borderWidth: 0
                }}]
            }},
            options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#cbd5e1', font: {{ size: 11 }} }} }} }}, cutout: '62%' }}
        }});
    </script>
    </body></html>"""

    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

    # 5. 텔레그램 브리핑 전송
    tg_msg = (
        f"🔥 <b>[마스터 관제탑 V4] 실수량 기반 전 종목 자동 브리핑</b>\n"
        f"⏰ {now_str} | 총자산: <b>{total_eval_krw//10000:,}만 원</b>\n"
        f"👉 <a href='{DASHBOARD_URL}'>터치하여 도넛 차트 &amp; 웹 관제탑 열기</a>\n\n"
        f"💼 <b>1. 보유 전 종목 실시간 평가 &amp; 수익률</b>\n"
        f"• <b>RAM (5,854주)</b>: ${ram_p:.2f} ({ram_pct:+.2f}%) | <b>{ram_ret:+.2f}%</b> (${ram_eval_usd:,.0f})\n"
        f"• <b>코스닥레버리지 (3,354주)</b>: ₩{kq_p:,.0f} ({kq_pct:+.2f}%) | <b>{kq_ret:+.2f}%</b> ({kq_eval:,}원)\n"
        f"• <b>와이지-원 (656주)</b>: ₩{yg_p:,.0f} ({yg_pct:+.2f}%) | <b>{yg_ret:+.2f}%</b> ({yg_eval:,}원)\n"
        f"• <b>오름 계좌1 (1,097주)</b>: ₩{or1_p:,.0f} ({or1_pct:+.2f}%) | <b>{or1_ret:+.2f}%</b> ({or1_eval:,}원)\n"
        f"• <b>오름 계좌2 (256주)</b>: ₩{or2_p:,.0f} | <b>{or2_ret:+.2f}%</b> ({or2_eval:,}원)\n"
        f"• <b>앱클론 (256주)</b>: ₩{ab_p:,.0f} ({ab_pct:+.2f}%) | <b>{ab_ret:+.2f}%</b> ({ab_eval:,}원)\n\n"
        f"🎯 <b>2. 현금 1,000만 원 기술적 타점 (RSI·이격도)</b>\n"
        f"• <b>MU</b>: RSI {mu_rsi:.1f} / 이격 {mu_disp:+.1f}% ➔ <b>{mu_sig} ({mu_cash})</b>\n"
        f"• <b>코스닥레버리지</b>: RSI {kq_rsi:.1f} / 이격 {kq_disp:+.1f}% ➔ <b>{kq_sig} ({kq_cash})</b>\n\n"
        f"📰 <b>3. 최근 48시간 핵심 속보</b>\n{news_tg}"
    )
    if TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True})

if __name__ == "__main__":
    main()
