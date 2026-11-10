import os, sys, datetime, urllib.parse
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip()
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/" if '/' in GITHUB_REPO else "https://github.com/"

def get_tech_metrics(symbol):
    """종가, 등락률, 14일 Wilder RSI, 20일/60일 이평선 이격도 및 매수 시그널 계산"""
    try:
        hist = yf.Ticker(symbol).history(period="6mo")
        if hist.empty: return 0.0, 0.0, 50.0, 0.0, 0.0, "데이터 대기", "0원 (관망)"
        closes = hist['Close'].dropna()
        curr = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else curr
        pct = ((curr - prev) / prev) * 100 if prev > 0 else 0.0

        # 14일 RSI (Wilder EWM 방식 & Zero-Division 방어)
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

        # 1,000만 원 분할 매수 트리거 판정
        if rsi < 25:
            sig, cash = "🔥 3차 패닉셀 타점", "400만 원 투입 (누적 1,000만)"
        elif rsi < 30 and disp20 <= -15.0:
            sig, cash = "⚡ 2차 투매 타점", "300만 원 투입 (누적 600만)"
        elif rsi < 35 or disp20 <= -10.0:
            sig, cash = "✅ 1차 과매도 타점", "300만 원 투입 (1차 진입)"
        elif rsi > 70:
            sig, cash = "⚠️ 과열 구간", "0원 (추격매수 금지·홀딩)"
        else:
            sig, cash = "⏸ 중립·관망 구간", "0원 (현금 1,000만 대기)"

        return curr, pct, rsi, ma20, disp20, sig, cash
    except Exception as e:
        print(f"[{symbol}] 지표 계산 경고: {e}")
        return 0.0, 0.0, 50.0, 0.0, 0.0, "연산 대기", "0원"

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

    # 1. 핵심 종목 기술적 지표 및 시세 산출
    mu_p, mu_pct, mu_rsi, mu_ma20, mu_disp, mu_sig, mu_cash = get_tech_metrics("MU")
    ram_p, ram_pct, ram_rsi, ram_ma20, ram_disp, ram_sig, ram_cash = get_tech_metrics("RAM")
    kq_p, kq_pct, kq_rsi, kq_ma20, kq_disp, kq_sig, kq_cash = get_tech_metrics("233740.KS") # KODEX 코스닥150레버리지
    soxx_p, soxx_pct, *_ = get_tech_metrics("SOXX")
    krw_p, krw_pct, *_ = get_tech_metrics("KRW=X")
    if krw_p == 0: krw_p = 1380.0

    # 2. 내 RAM 수익률 계산 (평단 $10.0779 / 매입 $58,996)
    ram_ret = ((ram_p - 10.0779) / 10.0779) * 100 if ram_p > 0 else 0.0
    ram_eval = 58996 * (ram_p / 10.0779) if ram_p > 0 else 58996

    # 3. 48시간 이내 최신 뉴스 수집
    news = (get_latest_strict_news("마이크론 OR DRAM OR HBM 반도체", "[반도체/RAM]", 2) +
            get_latest_strict_news("미국 증시 금리 환율 OR 코스닥 수급", "[매크로/코스닥]", 2) +
            get_latest_strict_news("와이지-원 OR 절삭공구", "[와이지원]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론 임상", "[바이오]", 2))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a> ({x['source']} {x['time']})" for x in news]) or "• 최근 48시간 내 속보 없음"

    # 4. 모바일 HTML 대시보드 생성
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><meta http-equiv="refresh" content="1800"><title>마스터 관제탑 V3</title>
    <style>
        body{{font-family:-apple-system,sans-serif;background:#0b0f19;color:#f8fafc;margin:0;padding:14px;max-width:600px;margin:auto;}}
        .card{{background:#131c31;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-bottom:14px;}}
        h2{{font-size:0.95rem;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #1e293b;color:#38bdf8;display:flex;justify-content:space-between;}}
        .row{{display:flex;justify-content:space-between;font-size:0.84rem;margin-bottom:8px;}}
        .sig-box{{background:#1e293b;border-left:4px solid #38bdf8;padding:10px;border-radius:6px;margin-bottom:8px;font-size:0.82rem;}}
        .pos{{color:#4ade80;font-weight:bold;}} .neg{{color:#f87171;font-weight:bold;}}
        .n-item{{background:rgba(30,41,59,0.5);padding:8px 10px;border-radius:8px;margin-bottom:8px;font-size:0.82rem;}}
        .n-hd{{display:flex;justify-content:space-between;font-size:0.72rem;margin-bottom:4px;}} .tag{{color:#38bdf8;font-weight:bold;}} .meta{{color:#94a3b8;}}
        a{{color:#f1f5f9;text-decoration:none;}}
    </style></head><body>
    <h1 style="font-size:1.2rem;text-align:center;color:#38bdf8;margin-bottom:4px;">🔥 마스터 투자 관제탑 V3</h1>
    <p style="text-align:center;font-size:0.75rem;color:#94a3b8;margin-top:0;">동기화: {now_str}</p>

    <div class="card">
        <h2>🎯 1. 가용 현금 1,000만 원 기술적 투입 시그널</h2>
        <div class="sig-box">
            <b>🇺🇸 마이크론(MU) / RAM 기준</b><br>
            • MU RSI(14): <b>{mu_rsi:.1f}</b> | 20일선(${mu_ma20:.1f}) 이격: <b>{mu_disp:+.1f}%</b><br>
            • RAM RSI(14): <b>{ram_rsi:.1f}</b> | 20일선(${ram_ma20:.2f}) 이격: <b>{ram_disp:+.1f}%</b><br>
            👉 판정: <span class="pos">{mu_sig}</span> → <b>{mu_cash}</b>
        </div>
        <div class="sig-box" style="border-left-color:#c084fc;margin-bottom:0;">
            <b>🇰🇷 KODEX 코스닥150레버리지 (233740)</b> (현재 ₩{kq_p:,.0f})<br>
            • RSI(14): <b>{kq_rsi:.1f}</b> | 20일선(₩{kq_ma20:,.0f}) 이격: <b>{kq_disp:+.1f}%</b><br>
            👉 판정: <span class="pos">{kq_sig}</span> → <b>{kq_cash}</b>
        </div>
    </div>

    <div class="card">
        <h2>⚡ 2. 매크로 & 보유 포트폴리오</h2>
        <div class="row"><span>마이크론(MU) / SOXX</span><span>${mu_p:.2f} ({mu_pct:+.2f}%) / ${soxx_p:.2f}</span></div>
        <div class="row"><span>원/달러 환율</span><span>₩{krw_p:,.2f} ({krw_pct:+.2f}%)</span></div>
        <div class="row"><span>RAM (평단 $10.08)</span><span class="{'pos' if ram_ret>=0 else 'neg'}">${ram_p:.2f} ({ram_ret:+.2f}% / ${ram_eval:,.0f})</span></div>
        <div class="row"><span>코스닥150레버리지 / 와이지원</span><span class="neg">-42.81% / -25.00%</span></div>
        <div class="row"><span>오름(1·2) / 앱클론</span><span class="neg">-86.58%·-85.12% / -67.58%</span></div>
    </div>

    <div class="card"><h2>📰 3. 최근 48시간 최신 속보</h2>{news_html}</div>
    </body></html>"""

    with open("index.html", "w", encoding="utf-8") as f: f.write(html)

    # 5. 텔레그램 브리핑 전송
    tg_msg = (
        f"🔥 <b>[마스터 관제탑 V3] 기술적 지표 &amp; 시황 브리핑</b> ({now_str})\n"
        f"👉 <a href='{DASHBOARD_URL}'>모바일 웹 관제탑 열기</a>\n\n"
        f"🎯 <b>1. 현금 1,000만 원 분할매수 트리거 (RSI·이격도)</b>\n"
        f"• <b>MU</b>: RSI {mu_rsi:.1f} | 20일선 이격 {mu_disp:+.1f}% ➔ <b>{mu_sig} ({mu_cash})</b>\n"
        f"• <b>RAM</b>: RSI {ram_rsi:.1f} | 20일선 이격 {ram_disp:+.1f}%\n"
        f"• <b>코스닥150레버리지</b>: RSI {kq_rsi:.1f} | 20일선 이격 {kq_disp:+.1f}% ➔ <b>{kq_sig} ({kq_cash})</b>\n\n"
        f"💼 <b>2. 핵심 지표 &amp; RAM 현황</b>\n"
        f"• MU: ${mu_p:.2f} ({mu_pct:+.2f}%) | 환율: ₩{krw_p:,.2f}\n"
        f"• RAM: ${ram_p:.2f} ({ram_pct:+.2f}%) | 내 수익률: {ram_ret:+.2f}% (${ram_eval:,.0f})\n\n"
        f"📰 <b>3. 최근 48시간 핵심 속보</b>\n{news_tg}"
    )
    if TOKEN and CHAT_ID:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True})

if __name__ == "__main__":
    main()
