import os
import sys
import datetime
import urllib.parse
from email.utils import parsedate_to_datetime
import requests
import feedparser
import yfinance as yf

# GitHub Secrets에서 열쇠 불러오기 (앞뒤 공백 자동 제거)
TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

def get_ticker_info(symbol):
    """야후 파이낸스에서 전일 종가와 등락률을 안전하게 가져오는 함수"""
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
        print(f"[{symbol}] 시세 조회 중 경고 (무시 가능): {e}")
    return 0.0, 0.0

def get_latest_news(query, max_items=2):
    """구글 뉴스 RSS에서 띄어쓰기/특수문자 에러 없이 최신 뉴스 추출"""
    try:
        # 한글 및 띄어쓰기 주소 안전 변환 (에러 원천 차단)
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(url)
        news_items = []
        
        for entry in feed.entries[:max_items]:
            title = entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title
            # HTML 태그 충돌 방지용 기호 치환
            title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            source = entry.source.title if 'source' in entry else "주요 언론"
            link = entry.link
            
            try:
                dt = parsedate_to_datetime(entry.published)
                kst_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
                pub_time = kst_dt.strftime("%m/%d %H:%M")
            except Exception:
                pub_time = "최신"
                
            news_items.append(f"• <a href='{link}'>{title}</a> ({source} | {pub_time})")
            
        return "\n".join(news_items) if news_items else "• 관련 최신 속보가 없습니다."
    except Exception as e:
        print(f"뉴스 검색 경고 ({query}): {e}")
        return "• 뉴스 데이터를 불러오는 중 일시적 지연이 발생했습니다."

def build_briefing():
    kst_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = kst_now.strftime("%Y-%m-%d %H:%M KST")

    # 1. 주요 지표 및 RAM 전일 종가 수집
    mu_price, mu_pct = get_ticker_info("MU")
    ram_price, ram_pct = get_ticker_info("RAM")
    soxx_price, soxx_pct = get_ticker_info("SOXX")
    krw_rate, krw_pct = get_ticker_info("KRW=X")

    # 2. 내 RAM 포지션 실시간 계산 (평단 $10.0779 / 매입 $58,996)
    my_ram_avg = 10.0779
    my_ram_invest = 58996
    if ram_price > 0:
        my_ram_return = ((ram_price - my_ram_avg) / my_ram_avg) * 100
        my_ram_eval = my_ram_invest * (ram_price / my_ram_avg)
        ram_status = f"현재가 ${ram_price:.2f} ({ram_pct:+.2f}%) | 내 수익률: {my_ram_return:+.2f}% (${my_ram_eval:,.0f})"
    else:
        ram_status = "시세 확인 중 (평단 $10.08 / 매입 $58,996)"

    # 3. 섹터 및 보유 종목 맞춤형 실시간 뉴스 크롤링
    news_semi = get_latest_news("마이크론 OR DRAM OR HBM 반도체", 2)
    news_macro = get_latest_news("미국 증시 금리 환율 OR 코스닥 수급", 2)
    news_yg1 = get_latest_news("와이지-원 OR 절삭공구 반도체", 1)
    news_bio = get_latest_news("오름테라퓨틱 OR 앱클론 임상", 2)

    # 4. 텔레그램 메시지 조립 (안전한 HTML 포맷 사용)
    msg = (
        f"🔥 <b>[마스터 투자 비서] 실시간 시황 &amp; 뉴스 브리핑</b>\n"
        f"⏰ 기준 시각: {now_str} (전일 종가 및 최신 뉴스)\n\n"
        f"⚡ <b>1. 글로벌 반도체 &amp; 매크로 지표</b>\n"
        f"• 마이크론(MU): ${mu_price:.2f} ({mu_pct:+.2f}%)\n"
        f"• 반도체지수(SOXX): ${soxx_price:.2f} ({soxx_pct:+.2f}%)\n"
        f"• 원/달러 환율: ₩{krw_rate:,.2f} ({krw_pct:+.2f}%)\n\n"
        f"💼 <b>2. 보유 포트폴리오 핵심 점검</b>\n"
        f"• <b>RAM (2X DRAM)</b>: {ram_status}\n"
        f"• <b>KODEX 코스닥150레버리지</b>: -42.81% (1,177만 원) | 외인·기관 수급 주시\n"
        f"• <b>와이지원</b>: -25.00% (630만 원) | 소부장 턴어라운드 대기\n"
        f"• <b>오름테라퓨틱(계좌1/2)</b>: -86.58% (1,581만) / -85.12% (368만)\n"
        f"• <b>앱클론</b>: -67.58% (437만 원) | 임상 모멘텀 대기\n"
        f"• <b>가용 현금 (11월 말)</b>: 1,000만 원 (급락 오버슈팅 시 저점 스윙 대기)\n\n"
        f"📰 <b>3. 보유 종목 실시간 핵심 뉴스 (클릭 시 이동)</b>\n"
        f"<b>[반도체 / DRAM / RAM]</b>\n{news_semi}\n\n"
        f"<b>[매크로 / 미·한 증시 / 코스닥]</b>\n{news_macro}\n\n"
        f"<b>[와이지원 / 소부장]</b>\n{news_yg1}\n\n"
        f"<b>[오름테라퓨틱 / 앱클론 바이오]</b>\n{news_bio}\n\n"
        f"📌 <i>횡보장 레버리지 감쇠(Decay)를 경계하고, 현금 1,000만 원은 확실한 변곡점에만 투입하십시오.</i>"
    )
    return msg

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("❌ 에러 원인: GitHub Secrets에 TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 비어 있습니다!")
        print("Settings -> Secrets and variables -> Actions 메뉴에서 두 값의 이름을 정확히 등록했는지 확인해주세요.")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    res = requests.post(url, json=payload)
    if res.status_code != 200:
        print(f"❌ 텔레그램 전송 실패 (에러 코드 {res.status_code}): {res.text}")
        print("💡 팁: 1) 토큰값이 정확한지, 2) 텔레그램 앱에서 내가 만든 봇에게 먼저 '시작(/start)' 메시지를 보냈는지 확인하세요.")
        sys.exit(1)
    else:
        print("✅ 텔레그램 브리핑 전송이 완벽하게 성공했습니다!")

if __name__ == "__main__":
    briefing_msg = build_briefing()
    send_telegram(briefing_msg)
