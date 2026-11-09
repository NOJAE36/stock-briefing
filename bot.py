import os
import datetime
from email.utils import parsedate_to_datetime
import requests
import feedparser
import yfinance as yf

# GitHub Secrets에 숨겨둔 열쇠 불러오기
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def get_ticker_info(symbol):
    """야후 파이낸스에서 전일 종가와 등락률을 가져오는 함수"""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if len(hist) >= 2:
            close = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            diff_pct = ((close - prev) / prev) * 100
            return close, diff_pct
        elif len(hist) == 1:
            return hist['Close'].iloc[-1], 0.0
    except Exception:
        pass
    return 0.0, 0.0

def get_latest_news(query, max_items=2):
    """구글 뉴스 RSS에서 키워드별 최신 뉴스(제목, 출처, 시간, 링크) 추출"""
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    news_items = []
    
    for entry in feed.entries[:max_items]:
        # 마지막 ' - 언론사명' 분리
        title = entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title
        source = entry.source.title if 'source' in entry else "주요 언론"
        link = entry.link
        
        # 뉴스 발행 시간을 한국 시간(KST)으로 변환
        try:
            dt = parsedate_to_datetime(entry.published)
            kst_dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            pub_time = kst_dt.strftime("%m/%d %H:%M")
        except Exception:
            pub_time = "최신"
            
        news_items.append(f"• [{title}]({link}) ({source} | {pub_time})")
        
    return "\n".join(news_items) if news_items else "• 관련 최신 속보가 없습니다."

def build_briefing():
    # 한국 시간(KST) 기준 현재 시각
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

    # 4. 텔레그램 메시지 조립
    msg = (
        f"🔥 **[마스터 투자 비서] 실시간 시황 & 뉴스 브리핑**\n"
        f"⏰ 기준 시각: {now_str} (전일 종가 및 최신 뉴스)\n\n"
        f"⚡ **1. 글로벌 반도체 & 매크로 지표**\n"
        f"• 마이크론(MU): ${mu_price:.2f} ({mu_pct:+.2f}%)\n"
        f"• 반도체지수(SOXX): ${soxx_price:.2f} ({soxx_pct:+.2f}%)\n"
        f"• 원/달러 환율: ₩{krw_rate:,.2f} ({krw_pct:+.2f}%)\n\n"
        f"💼 **2. 보유 포트폴리오 핵심 점검**\n"
        f"• **RAM (2X DRAM)**: {ram_status}\n"
        f"• **KODEX 코스닥150레버리지**: -42.81% (1,177만 원) | 외인·기관 수급 주시\n"
        f"• **와이지원**: -25.00% (630만 원) | 소부장 턴어라운드 대기\n"
        f"• **오름테라퓨틱(계좌1/2)**: -86.58% (1,581만) / -85.12% (368만)\n"
        f"• **앱클론**: -67.58% (437만 원) | 임상 모멘텀 대기\n"
        f"• **가용 현금 (11월 말)**: 1,000만 원 (급락 오버슈팅 시 저점 스윙 대기)\n\n"
        f"📰 **3. 보유 종목 실시간 핵심 뉴스 (클릭 시 이동)**\n"
        f"**[반도체 / DRAM / RAM]**\n{news_semi}\n\n"
        f"**[매크로 / 미·한 증시 / 코스닥]**\n{news_macro}\n\n"
        f"**[와이지원 / 소부장]**\n{news_yg1}\n\n"
        f"**[오름테라퓨틱 / 앱클론 바이오]**\n{news_bio}\n\n"
        f"📌 *횡보장 레버리지 감쇠(Decay)를 경계하고, 현금 1,000만 원은 확실한 변곡점에만 투입하십시오.*"
    )
    return msg

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    res = requests.post(url, json=payload)
    print("전송 결과:", res.status_code, res.text)

if __name__ == "__main__":
    briefing_msg = build_briefing()
    send_telegram(briefing_msg)
