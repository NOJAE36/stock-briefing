import os
import sys
import datetime
import urllib.parse
from email.utils import parsedate_to_datetime
import requests
import feedparser
import yfinance as yf

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip()

# GitHub Pages 웹주소 자동 생성 (예: https://아이디.github.io/stock-briefing/)
if '/' in GITHUB_REPO:
    owner, repo_name = GITHUB_REPO.split('/')
    DASHBOARD_URL = f"https://{owner}.github.io/{repo_name}/"
else:
    DASHBOARD_URL = "https://github.com/"

def get_ticker_info(symbol):
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            close = float(hist['Close'].iloc[-1])
            prev = float(hist['Close'].iloc[-2])
            diff_pct = ((close - prev) / prev) * 100
            return close, diff_pct
        elif not hist.empty and len(hist) == 1:
            return float(hist['Close'].iloc[-1]), 0.0
    except Exception as e:
        print(f"[{symbol}] 시세 조회 경고: {e}")
    return 0.0, 0.0

def get_news_items(query, tag_label, max_items=2):
    items = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_items]:
            title = entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title
            title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            source = entry.source.title if 'source' in entry else "주요 언론"
            link = entry.link
            try:
                dt = parsedate_to_datetime(entry.published)
                kst_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
                pub_time = kst_dt.strftime("%Y-%m-%d %H:%M KST")
            except Exception:
                pub_time = "최신"
            items.append({
                "tag": tag_label,
                "title": title,
                "source": source,
                "time": pub_time,
                "link": link
            })
    except Exception as e:
        print(f"뉴스 검색 경고 ({query}): {e}")
    return items

def format_tg_news(items):
    if not items:
        return "• 관련 최신 속보가 없습니다."
    return "\n".join([f"• <a href='{x['link']}'>{x['title']}</a> ({x['source']} | {x['time'][5:16]})" for x in items])

def format_html_news(items):
    if not items:
        return '<div class="news-item"><p class="news-title">관련 최신 속보가 없습니다.</p></div>'
    html_blocks = []
    for x in items:
        html_blocks.append(f"""
        <div class="news-item">
            <div class="news-header">
                <span class="news-tag">{x['tag']}</span>
                <span class="news-meta">{x['time']} | {x['source']}</span>
            </div>
            <p class="news-title"><a href="{x['link']}" target="_blank">{x['title']}</a></p>
        </div>""")
    return "\n".join(html_blocks)

def main():
    kst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = kst_now.strftime("%Y-%m-%d %H:%M KST")

    mu_price, mu_pct = get_ticker_info("MU")
    ram_price, ram_pct = get_ticker_info("RAM")
    soxx_price, soxx_pct = get_ticker_info("SOXX")
    krw_rate, krw_pct = get_ticker_info("KRW=X")

    my_ram_avg = 10.0779
    my_ram_invest = 58996
    if ram_price > 0:
        my_ram_return = ((ram_price - my_ram_avg) / my_ram_avg) * 100
        my_ram_eval = my_ram_invest * (ram_price / my_ram_avg)
        my_ram_krw = (my_ram_eval * krw_rate / 10000) if krw_rate > 0 else 8200
        ram_tg_str = f"현재가 ${ram_price:.2f} ({ram_pct:+.2f}%) | 수익률: {my_ram_return:+.2f}% (${my_ram_eval:,.0f})"
        ram_html_str = f"${ram_price:.2f} ({my_ram_return:+.2f}% / ${my_ram_eval:,.0f} · 약 {my_ram_krw:,.0f}만 원)"
        ram_color = "positive" if my_ram_return >= 0 else "negative"
    else:
        ram_tg_str = "시세 확인 중 (평단 $10.08 / 매입 $58,996)"
        ram_html_str = "평단 $10.08 (매입 $58,996)"
        ram_color = ""

    news_semi = get_news_items("마이크론 OR DRAM OR HBM 반도체", "[반도체 / RAM]", 2)
    news_macro = get_news_items("미국 증시 금리 환율 OR 코스닥 수급", "[매크로 / 코스닥]", 2)
    news_yg1 = get_news_items("와이지-원 OR 절삭공구 반도체", "[와이지원 / 소부장]", 1)
    news_bio = get_news_items("오름테라퓨틱 OR 앱클론 임상", "[바이오 / 임상]", 2)

    all_news_html = format_html_news(news_semi + news_macro + news_yg1 + news_bio)

    mu_cls = "positive" if mu_pct >= 0 else "negative"
    soxx_cls = "positive" if soxx_pct >= 0 else "negative"

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="1800">
    <title>마스터 실시간 투자 관제탑</title>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #131c31;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #4ade80;
            --accent-red: #f87171;
            --accent-purple: #c084fc;
            --border-color: #1e293b;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            padding: 16px;
            max-width: 600px;
            margin-left: auto;
            margin-right: auto;
        }}
        header {{ text-align: center; margin-bottom: 20px; }}
        header h1 {{ font-size: 1.25rem; margin: 0 0 6px 0; color: var(--accent-blue); }}
        header p {{ font-size: 0.8rem; color: var(--text-secondary); margin: 0; }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
        }}
        .card h2 {{
            font-size: 0.95rem;
            margin-top: 0;
            margin-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .metric-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            font-size: 0.86rem;
        }}
        .metric-row:last-child {{ margin-bottom: 0; }}
        .bio-item {{
            background-color: rgba(192, 132, 252, 0.06);
            border-left: 3px solid var(--accent-purple);
            padding: 10px 12px;
            margin-bottom: 10px;
            border-radius: 0 8px 8px 0;
        }}
        .bio-item:last-child {{ margin-bottom: 0; }}
        .bio-title {{ font-size: 0.84rem; font-weight: bold; color: #f3e8ff; margin: 0 0 4px 0; }}
        .bio-desc {{ font-size: 0.78rem; color: var(--text-secondary); margin: 0; line-height: 1.35; }}
        .news-item {{
            background-color: rgba(30, 41, 59, 0.55);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 10px;
        }}
        .news-item:last-child {{ margin-bottom: 0; }}
        .news-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; gap: 6px; }}
        .news-tag {{ color: var(--accent-blue); font-weight: bold; font-size: 0.75rem; white-space: nowrap; }}
        .news-meta {{ color: var(--text-secondary); font-size: 0.68rem; background: #1e293b; padding: 2px 6px; border-radius: 4px; text-align: right; }}
        .news-title {{ font-size: 0.83rem; color: #f1f5f9; line-height: 1.4; margin: 0; }}
        .news-title a {{ color: #f1f5f9; text-decoration: none; }}
        .news-title a:hover {{ color: var(--accent-blue); text-decoration: underline; }}
        .label {{ color: var(--text-secondary); }}
        .value {{ font-weight: bold; text-align: right; }}
        .positive {{ color: var(--accent-green); }}
        .negative {{ color: var(--accent-red); }}
        .live-tag {{ background-color: rgba(74, 222, 128, 0.12); color: var(--accent-green); padding: 2px 8px; border-radius: 4px; font-size: 0.68rem; }}
    </style>
</head>
<body>
    <header>
        <h1>🔥 마스터 실시간 투자 관제탑</h1>
        <p>최근 자동 동기화: <strong>{now_str}</strong></p>
    </header>

    <div class="card">
        <h2>⚡ 1. 글로벌 반도체 & 매크로 지표 <span class="live-tag">AUTO SYNC</span></h2>
        <div class="metric-row">
            <span class="label">마이크론 (MU 종가)</span>
            <span class="value {mu_cls}">${mu_price:.2f} ({mu_pct:+.2f}%)</span>
        </div>
        <div class="metric-row">
            <span class="label">필라델피아 반도체 (SOXX)</span>
            <span class="value {soxx_cls}">${soxx_price:.2f} ({soxx_pct:+.2f}%)</span>
        </div>
        <div class="metric-row">
            <span class="label">원/달러 환율</span>
            <span class="value">₩{krw_rate:,.2f} ({krw_pct:+.2f}%)</span>
        </div>
        <div class="metric-row">
            <span class="label">DRAM 펀더멘털</span>
            <span class="value positive">AI 서버 HBM 집중 · 범용 공급 부족 지속</span>
        </div>
    </div>

    <div class="card">
        <h2>💼 2. 내 전체 포트폴리오 현황</h2>
        <div class="metric-row">
            <span class="label">RAM (평단 $10.08)</span>
            <span class="value {ram_color}">{ram_html_str}</span>
        </div>
        <div class="metric-row">
            <span class="label">KODEX 코스닥150레버리지</span>
            <span class="value negative">-42.81% (1,177만 원)</span>
        </div>
        <div class="metric-row">
            <span class="label">와이지원 (소부장)</span>
            <span class="value negative">-25.00% (630만 원)</span>
        </div>
        <div class="metric-row">
            <span class="label">오름테라퓨틱 (계좌1 / 계좌2)</span>
            <span class="value negative">-86.58% (1,581만) / -85.12% (368만)</span>
        </div>
        <div class="metric-row">
            <span class="label">앱클론</span>
            <span class="value negative">-67.58% (437만 원)</span>
        </div>
        <div class="metric-row">
            <span class="label">11월 말 가용 현금</span>
            <span class="value" style="color:var(--accent-blue);">1,000만 원 (급락 오버슈팅 저점 대기)</span>
        </div>
    </div>

    <div class="card">
        <h2>📰 3. 종목별 실시간 뉴스 (터치 시 원문 이동)</h2>
        {all_news_html}
    </div>

    <div class="card">
        <h2>🧬 4. 바이오 임상 & 마일스톤 캘린더</h2>
        <div class="bio-item">
            <p class="bio-title">오름테라퓨틱 (ORM-1153 등 DAC 파이프라인)</p>
            <p class="bio-desc">• CD123 표적 후속 파이프라인 IND 제출 및 글로벌 학회 발표 모멘텀 주시<br>• 임상 및 신규 L/O 이벤트 발생 시 계좌2부터 단계적 비중 축소 타점 조율</p>
        </div>
        <div class="bio-item">
            <p class="bio-title">앱클론 (AT101 CAR-T / AC101 파트너사 3상)</p>
            <p class="bio-desc">• AT101(네스페셀) 국내 임상 2상 데이터 및 품목허가 신청 일정 점검<br>• 중국 헨리우스 AC101 위암 글로벌 임상 3상 결과 및 마일스톤 유입 대기</p>
        </div>
    </div>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    tg_msg = (
        f"🔥 <b>[마스터 투자 비서] 실시간 시황 &amp; 뉴스 브리핑</b>\n"
        f"⏰ 기준 시각: {now_str}\n\n"
        f"🔗 <b>[모바일 관제탑 바로가기]</b>\n"
        f"👉 <a href='{DASHBOARD_URL}'>터치하여 실시간 웹 대시보드 열기</a>\n\n"
        f"⚡ <b>1. 글로벌 반도체 &amp; 매크로 지표</b>\n"
        f"• 마이크론(MU): ${mu_price:.2f} ({mu_pct:+.2f}%)\n"
        f"• 반도체지수(SOXX): ${soxx_price:.2f} ({soxx_pct:+.2f}%)\n"
        f"• 원/달러 환율: ₩{krw_rate:,.2f} ({krw_pct:+.2f}%)\n\n"
        f"💼 <b>2. 보유 포트폴리오 핵심 점검</b>\n"
        f"• <b>RAM (2X DRAM)</b>: {ram_tg_str}\n"
        f"• <b>KODEX 코스닥150레버리지</b>: -42.81% (1,177만 원)\n"
        f"• <b>와이지원</b>: -25.00% (630만 원)\n"
        f"• <b>오름테라퓨틱(계좌1/2)</b>: -86.58% / -85.12%\n"
        f"• <b>앱클론</b>: -67.58% (437만 원)\n"
        f"• <b>가용 현금</b>: 1,000만 원 (스윙 대기)\n\n"
        f"📰 <b>3. 종목별 실시간 핵심 뉴스</b>\n"
        f"<b>[반도체 / RAM]</b>\n{format_tg_news(news_semi)}\n\n"
        f"<b>[매크로 / 코스닥]</b>\n{format_tg_news(news_macro)}\n\n"
        f"<b>[와이지원 / 소부장]</b>\n{format_tg_news(news_yg1)}\n\n"
        f"<b>[오름테라퓨틱 / 앱클론 바이오]</b>\n{format_tg_news(news_bio)}"
    )

    if TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML", "disable_web_page_preview": True}
        requests.post(url, json=payload)

if __name__ == "__main__":
    main()
