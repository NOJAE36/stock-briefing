import os, sys, json, datetime, urllib.parse, subprocess
from email.utils import parsedate_to_datetime
import requests, feedparser, yfinance as yf

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
    from PIL import Image, ImageDraw, ImageFont

TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
GITHUB_REPO = os.environ.get('GITHUB_REPOSITORY', '').strip().lower()
EVENT_NAME = os.environ.get('GITHUB_EVENT_NAME', '').strip()
DART_API_KEY = os.environ.get('DART_API_KEY', '').strip()

QUIET_NIGHT_MODE = True

CACHE_BUST = datetime.datetime.now().strftime("%m%d%H%M")
DASHBOARD_URL = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/?v={CACHE_BUST}" if '/' in GITHUB_REPO else f"https://nojae36.github.io/stock-briefing/?v={CACHE_BUST}"

# [V10.0 기본 포트폴리오] 2026.11.27 종가 및 7종목(8계좌) + 현금 300만 원 확정 기준
PORTFOLIO = {
    "RAM": {"name": "RAM (DRAM 2X)", "symbol": "RAM", "avg_usd": 9.6499, "qty": 6518, "fallback_usd": 4.29},
    "VRT": {"name": "버티브홀딩스", "symbol": "VRT", "avg_usd": 244.63, "qty": 13, "fallback_usd": 178.71},
    "KODEX_LEV": {"name": "코스닥150레버리지", "tickers": ["233740.KS"], "code6": "233740", "avg_krw": 5681, "qty": 4150, "fallback_krw": 4565},
    "OKINS": {"name": "오킨스전자", "tickers": ["080580.KQ", "080580.KS"], "code6": "080580", "avg_krw": 13424, "qty": 356, "fallback_krw": 13500, "peak_krw": 13500},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "code6": "019210", "avg_krw": 12909, "qty": 656, "fallback_krw": 9730},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "code6": "475830", "avg_krw": 96653, "qty": 256, "fallback_krw": 15730},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "code6": "475830", "avg_krw": 107117, "qty": 1097, "fallback_krw": 15730},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "code6": "174900", "avg_krw": 52744, "qty": 256, "fallback_krw": 24850},
    "CASH": {"name": "가용 현금", "eval_krw": 3000000}
}

CUSTOM_PARAMS = {
    "RAM": {"rsi_cut": 35.0, "disp_cut": -9.0},
    "VRT": {"rsi_cut": 35.0, "disp_cut": -9.0},
    "KODEX_LEV": {"rsi_cut": 34.0, "disp_cut": -9.0},
    "OKINS": {"rsi_cut": 36.0, "disp_cut": -8.0},
    "YG1": {"rsi_cut": 38.0, "disp_cut": -7.0},
    "ORUM": {"rsi_cut": 32.0, "disp_cut": -11.0},
    "ABCLON": {"rsi_cut": 32.0, "disp_cut": -11.0}
}

SEMI_PEERS = [
    {"symbol": "NVDA", "name": "엔비디아", "is_kr": False, "fallback": 160.0},
    {"symbol": "MU", "name": "마이크론", "is_kr": False, "fallback": 730.0},
    {"symbol": "005930.KS", "name": "삼성전자", "is_kr": True, "fallback": 190000},
    {"symbol": "000660.KS", "name": "SK하이닉스", "is_kr": True, "fallback": 1100000}
]

KEY_EVENTS = [
    {"date": "2026-12-07", "cat": "바이오", "title": "미국 혈액암학회(ASH) Late-Breaking 초록 공개"},
    {"date": "2026-12-10", "cat": "매크로", "title": "미국 12월 FOMC 금리결정 및 점도표 발표"},
    {"date": "2026-12-12", "cat": "바이오", "title": "미국 혈액암학회(ASH 2026) 개막 (오름·앱클론)"},
    {"date": "2026-12-17", "cat": "DRAM", "title": "마이크론(MU) FY27 1Q 실적발표 (RAM 모멘텀)"},
    {"date": "2026-12-28", "cat": "절세", "title": "2026 해외주식 비과세(잔여 227만) 마감 권장일"},
    {"date": "2027-01-08", "cat": "DRAM", "title": "삼성전자 2026 4Q 잠정실적 발표"},
    {"date": "2027-01-11", "cat": "바이오", "title": "2027 JP모건 헬스케어 컨퍼런스"},
    {"date": "2027-01-22", "cat": "DRAM", "title": "SK하이닉스 2026 4Q 실적발표"}
]

def detect_cloudflare_worker_url():
    if not TOKEN:
        return ""
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=6).json()
        w_url = r.get("result", {}).get("url", "").strip()
        if w_url.startswith("https://"):
            return w_url.split("?")[0]
    except Exception:
        pass
    return ""

def sync_state_from_worker(worker_url):
    default_state = {
        "version": "10.0",
        "cashKrw": 3000000,
        "swingVaultKrw": 0,
        "tax": {"kakaoGainKrw": 660510, "miraeGainKrw": -430535, "additionalGainKrw": 0},
        "sniperTargets": {"okinsTargetKrw": 15000, "okinsTrailPct": -5.0, "ygSellKrw": 10150, "kqTrimKrw": 5100, "ramReboundUsd": 5.50},
        "history": ["11/28: V10.0 7종목(8계좌)·현금 300만·양도세 0원 리셋 반영"]
    }
    if not worker_url:
        return default_state
    try:
        resp = requests.get(f"{worker_url}?mode=state&t={CACHE_BUST}", timeout=8)
        if resp.status_code == 200:
            st = resp.json()
            if st.get("version") == "10.0" and "core" in st:
                for k, v in st["core"].items():
                    if k in PORTFOLIO:
                        PORTFOLIO[k]["qty"] = int(v.get("qty", PORTFOLIO[k]["qty"]))
                        if "avgUsd" in v:
                            PORTFOLIO[k]["avg_usd"] = float(v["avgUsd"])
                        if "avgKrw" in v:
                            PORTFOLIO[k]["avg_krw"] = float(v["avgKrw"])
                        if "peakKrw" in v:
                            PORTFOLIO[k]["peak_krw"] = float(v["peakKrw"])
                return st
    except Exception:
        pass
    return default_state

def parse_kor_quant(v):
    if isinstance(v, (int, float)):
        return int(v)
    if not v:
        return 0
    try:
        return int(str(v).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0

def fmt_quant_kor(q):
    abs_val = abs(q)
    sign = "+" if q > 0 else ("-" if q < 0 else "")
    return f"{sign}{abs_val / 10000:.1f}만주" if abs_val >= 10000 else f"{sign}{abs_val:,}주"

def fetch_kr_investor_trend(code6):
    default_res = {"frgn": 0, "orgn": 0, "indv": 0, "smart_net": 0, "is_smart_inflow": False, "streak3d": False, "streak_type": "", "summary_text": "수급 집계 대기", "badge_text": "⚪ 수급대기"}
    try:
        resp = requests.get(f"https://m.stock.naver.com/api/stock/{code6}/trend", headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}, timeout=6)
        if resp.status_code != 200:
            return default_res
        data = resp.json()
        lst = data if isinstance(data, list) else (data.get("datas") or data.get("result") or [])
        if not lst:
            return default_res

        d0 = lst[0] or {}
        frgn0 = parse_kor_quant(d0.get("foreignerPureBuyQuant"))
        orgn0 = parse_kor_quant(d0.get("organPureBuyQuant"))
        indv0 = parse_kor_quant(d0.get("individualPureBuyQuant"))
        smart_net = frgn0 + orgn0
        is_twin_buy = (frgn0 > 0 and orgn0 > 0)
        is_smart_inflow = (smart_net > 0 or frgn0 > 0 or orgn0 > 0)

        streak3d, streak_type = False, ""
        if len(lst) >= 3:
            f1, f2 = parse_kor_quant(lst[1].get("foreignerPureBuyQuant")), parse_kor_quant(lst[2].get("foreignerPureBuyQuant"))
            o1, o2 = parse_kor_quant(lst[1].get("organPureBuyQuant")), parse_kor_quant(lst[2].get("organPureBuyQuant"))
            if frgn0 > 0 and f1 > 0 and f2 > 0 and orgn0 > 0 and o1 > 0 and o2 > 0:
                streak3d, streak_type = True, "🔥외인·기관 3일 쌍끌이!"
            elif frgn0 > 0 and f1 > 0 and f2 > 0:
                streak3d, streak_type = True, "🔥외국인 3일연속 매집!"
            elif orgn0 > 0 and o1 > 0 and o2 > 0:
                streak3d, streak_type = True, "🔥기관 3일연속 매집!"
            elif smart_net > 0 and (f1 + o1) > 0 and (f2 + o2) > 0:
                streak3d, streak_type = True, "✅메이저 3일연속 순매수"

        badge_text = "⚪ 개인주도(메이저매도)"
        if streak3d:
            badge_text = streak_type
        elif is_twin_buy:
            badge_text = "🟢 외인·기관 양매수"
        elif frgn0 > 0 and smart_net > 0:
            badge_text = "🟢 외국인 순매수 주도"
        elif orgn0 > 0 and smart_net > 0:
            badge_text = "🟢 기관 순매수 주도"
        elif frgn0 > 0 or orgn0 > 0:
            badge_text = "🟡 외인·기관 공방"

        return {
            "frgn": frgn0, "orgn": orgn0, "indv": indv0, "smart_net": smart_net,
            "is_smart_inflow": is_smart_inflow, "streak3d": streak3d, "streak_type": streak_type,
            "summary_text": f"외인 {fmt_quant_kor(frgn0)} · 기관 {fmt_quant_kor(orgn0)} · 개인 {fmt_quant_kor(indv0)}",
            "badge_text": badge_text
        }
    except Exception:
        return default_res

def calc_leverage_decay(lev_ret_10d, base_ret_10d, base_name):
    expected_2x = base_ret_10d * 2.0
    decay_gap = lev_ret_10d - expected_2x
    status = "🟢 정상 추적"
    if decay_gap <= -2.0:
        status = "⚠️ 음의복리 잠식주의"
    elif decay_gap >= 1.0:
        status = "🔥 양의복리 탄력"
    return {"decayGap": decay_gap, "status": status, "summary": f"10일: ETF {lev_ret_10d:+.1f}% vs {base_name}×2 ({expected_2x:+.1f}%) ➔ 괴리 {decay_gap:+.2f}%p [{status}]"}

def classify_bio_catalyst(title):
    pos_words = ["기술이전", "기술수출", "라이선스", "단일판매", "공급계약", "마일스톤", "임상승인", "승인", "완전관해", "초록", "ASH", "특허", "학회", "병용", "FDA", "식약처", "데이터", "유효성", "희귀의약품", "패스트트랙", "계약체결"]
    neg_words = ["유상증자", "전환사채", "신주인수권", "임상중단", "임상보류", "보류", "기재정정", "계약해지", "해지", "반려", "부작용", "독성", "사망", "불성실공시"]
    for w in neg_words:
        if w in title:
            return {"badge_cls": "bio-neg", "badge_txt": "🔴 악재/희석주의", "action": "추매 금지 · 공시 세부조건 확인 필수"}
    for w in pos_words:
        if w in title:
            return {"badge_cls": "bio-pos", "badge_txt": "🟢 호재/모멘텀", "action": "거래량 동반 시 스윙금고 이식 검토"}
    return {"badge_cls": "bio-neu", "badge_txt": "🟡 일반공시/동향", "action": "단순 참고 · 기존 보유 비중 유지"}

def fetch_clinical_trials_gov():
    url = "https://clinicaltrials.gov/api/v2/studies?query.term=ORM-5029+OR+ORM-6151+OR+BMS-986497+OR+AbClon+OR+HLX22+OR+AT101&pageSize=5&sort=LastUpdatePostDate:desc"
    results = []
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200:
            for st in resp.json().get("studies", []):
                p = st.get("protocolSection", {})
                id_mod, st_mod, sp_mod = p.get("identificationModule", {}), p.get("statusModule", {}), p.get("sponsorCollaboratorsModule", {})
                nct_id = id_mod.get("nctId", "NCT")
                raw_title = id_mod.get("briefTitle", "Clinical Study")
                title = ((raw_title[:52] + "...") if len(raw_title) > 52 else raw_title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                status = st_mod.get("overallStatus", "UNKNOWN")
                last_update = st_mod.get("lastUpdatePostDateStruct", {}).get("date", "확인중")
                full_txt = f"{raw_title} {sp_mod.get('leadSponsor', {}).get('name', '')}".upper()
                drug_tag = "바이오 임상"
                if "ORM-6151" in full_txt or "986497" in full_txt:
                    drug_tag = "오름/BMS ORM-6151"
                elif "ORM-5029" in full_txt or "ORUM" in full_txt:
                    drug_tag = "오름 ORM-5029"
                elif "HLX22" in full_txt or "AC101" in full_txt:
                    drug_tag = "앱클론/헨리우스 HLX22"
                elif "AT101" in full_txt or "ABCLON" in full_txt:
                    drug_tag = "앱클론 AT101"
                st_cls, st_icon = ("bio-pos", "🟢") if status in ("RECRUITING", "COMPLETED") else (("bio-neg", "🔴") if status in ("SUSPENDED", "TERMINATED", "WITHDRAWN") else ("bio-neu", "🟡"))
                results.append({"nct_id": nct_id, "drug_tag": drug_tag, "title": title, "status": status, "st_cls": st_cls, "st_icon": st_icon, "last_update": last_update, "link": f"https://clinicaltrials.gov/study/{nct_id}"})
    except Exception:
        pass
    return results

def fetch_bio_disclosures():
    items = []
    if DART_API_KEY and len(DART_API_KEY) > 10:
        try:
            r = requests.get(f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&page_count=10", timeout=6)
            if r.status_code == 200:
                for row in r.json().get("list", []):
                    corp = row.get("corp_name", "")
                    if "오름테라퓨틱" in corp or "앱클론" in corp:
                        rep_nm = row.get("report_nm", "")
                        items.append({"corp": corp, "title": f"[DART공시] {rep_nm}", "time": row.get("rcept_dt", ""), "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no', '')}", **classify_bio_catalyst(rep_nm)})
        except Exception:
            pass

    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    for corp_name, q in [("오름테라퓨틱", "오름테라퓨틱 (공시 OR 임상 OR 기술이전 OR 초록 OR ASH OR ORM OR 유상증자 OR 전환사채)"), ("앱클론", "앱클론 (공시 OR 임상 OR 기술이전 OR 단일판매 OR AT101 OR AC101 OR HLX22 OR 특허)")]:
        try:
            resp = requests.get(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=ko&gl=KR&ceid=KR:ko", headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            cnt = 0
            for entry in feedparser.parse(resp.content).entries:
                if not hasattr(entry, 'published'):
                    continue
                pub_kst = parsedate_to_datetime(entry.published).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
                if (now_kst - pub_kst).total_seconds() / 3600 > 168:
                    continue
                clean_t = (entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                items.append({"corp": corp_name, "title": clean_t, "time": pub_kst.strftime("%m/%d %H:%M"), "link": entry.link, **classify_bio_catalyst(clean_t)})
                cnt += 1
                if cnt >= 2:
                    break
        except Exception:
            pass
    return items[:4]

def ensure_korean_fonts():
    reg_path, bold_path = "NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf"
    for path, url in [(reg_path, "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf"), (bold_path, "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Bold.ttf")]:
        try:
            if not os.path.exists(path):
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    with open(path, "wb") as f:
                        f.write(r.content)
        except Exception:
            pass
    return reg_path, bold_path

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def make_score_blocks(score, rsi):
    return "🟥🟥🟥🟥" if rsi > 72 else ("🟩" * score + "⬜" * (4 - score))

def make_sparkline_svg(prices, color="#38bdf8"):
    if not prices or len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng = (mx - mn) if mx > mn else 1.0
    w, h = 84, 26
    pts = [f"{(i / (len(prices) - 1)) * (w - 8) + 4:.1f},{h - 4 - ((p - mn) / rng) * (h - 8):.1f}" for i, p in enumerate(prices)]
    lx, ly = pts[-1].split(",")
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="overflow:visible;"><polyline fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(pts)}"/><circle cx="{lx}" cy="{ly}" r="3" fill="{color}"/></svg>'

def fetch_peer_with_cmf(sym, name, is_kr, fallback):
    curr, pct, ret10d, cmf20 = float(fallback), 0.0, 0.0, 0.0
    try:
        t = yf.Ticker(sym)
        hist = t.history(period="1mo", timeout=8)
        if not hist.empty:
            df = hist.dropna(subset=['Close']).copy()
            reg_curr = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2]) if len(df) >= 2 else reg_curr
            curr = reg_curr
            if not is_kr:
                try:
                    intra = t.history(period="2d", interval="5m", prepost=True, timeout=6)
                    if not intra.empty:
                        ic = intra.dropna(subset=['Close'])
                        if not ic.empty:
                            curr = float(ic['Close'].iloc[-1])
                            if ic.index[-1].date() > df.index[-1].date():
                                prev = reg_curr
                            df.iloc[-1, df.columns.get_loc('Close')] = curr
                except Exception:
                    pass
            pct = ((curr - prev) / prev) * 100.0 if prev > 0 else 0.0
            ret10d = ((curr - float(df['Close'].iloc[-11])) / float(df['Close'].iloc[-11])) * 100.0 if len(df) >= 11 else pct
            mfv_sum, vol_sum = 0.0, 0.0
            for _, row in df.tail(20).iterrows():
                hi, lo, cl, vl = float(row.get('High', row['Close'])), float(row.get('Low', row['Close'])), float(row['Close']), float(row.get('Volume', 0.0))
                hl = hi - lo
                mfv_sum += ((((cl - lo) - (hi - cl)) / hl) if hl > 0 else 0.0) * vl
                vol_sum += vl
            cmf20 = (mfv_sum / vol_sum) if vol_sum > 0 else 0.0
    except Exception:
        pass
    return {"name": name, "symbol": sym.split(".")[0], "price": curr, "price_str": (f"₩{curr:,.0f}" if is_kr else f"${curr:,.2f}"), "pct": pct, "ret10d": ret10d, "cmf20": cmf20}

def get_quad_verified_metrics(tickers, rsi_cut=35.0, disp_cut=-9.0, extra_supply=None):
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
            curr, prev, session_tag = reg_curr, reg_prev, "☀️본장"

            if not sym.endswith(('.KS', '.KQ')) and sym != 'KRW=X':
                try:
                    intra = t.history(period="2d", interval="5m", prepost=True, timeout=8)
                    if not intra.empty:
                        ic = intra.dropna(subset=['Close'])
                        if not ic.empty:
                            curr = float(ic['Close'].iloc[-1])
                            last_ts = ic.index[-1]
                            hm = last_ts.hour * 60 + last_ts.minute
                            session_tag = "🌅프리장" if (240 <= hm < 570) else ("☀️본장" if (570 <= hm < 960) else "🌙애프터")
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
            pct = ((curr - prev) / prev) * 100.0 if prev > 0 else 0.0
            ret10d = ((curr - float(closes.iloc[-11])) / float(closes.iloc[-11])) * 100.0 if len(closes) >= 11 else pct

            mfv_sum, vol_sum = 0.0, 0.0
            for _, row in df.tail(20).iterrows():
                hi, lo, cl, vl = float(row.get('High', row['Close'])), float(row.get('Low', row['Close'])), float(row['Close']), float(row.get('Volume', 0.0))
                hl = hi - lo
                mfv_sum += ((((cl - lo) - (hi - cl)) / hl) if hl > 0 else 0.0) * vl
                vol_sum += vl
            self_cmf20 = (mfv_sum / vol_sum) if vol_sum > 0 else 0.0

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
            disp20 = ((curr - ma20) / ma20) * 100.0 if ma20 > 0 else 0.0
            std20 = float(closes.tail(20).std()) if len(closes) >= 20 else 0.0
            pct_b = (curr - (ma20 - 2 * std20)) / (4 * std20) if std20 > 0 else 0.5

            macd_turn = False
            if len(closes) >= 26:
                macd_line = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
                macd_hist = macd_line - macd_line.ewm(span=9, adjust=False).mean()
                macd_turn = float(macd_hist.iloc[-1]) > float(macd_hist.iloc[-2])

            avg_vol20 = float(vols.tail(20).mean()) if len(vols) >= 5 else 0.0
            vol_ratio = (float(vols.iloc[-1]) / avg_vol20) if avg_vol20 > 0 else 1.0
            c_open, c_high, c_low = float(opens.iloc[-1]), float(highs.iloc[-1]), float(lows.iloc[-1])
            wick = ((min(c_open, curr) - c_low) / (c_high - c_low)) if (c_high - c_low) > 0 else 0.0
            rebound = (curr >= c_open) or (wick >= 0.35)

            c1 = (rsi < rsi_cut) or (disp20 <= disp_cut)
            c2 = (pct_b <= 0.18) or (curr >= ma60)
            c3 = macd_turn
            c4 = (vol_ratio >= 1.2 and rebound) or (rebound and rsi < (rsi_cut - 6.0))

            flow_summary = f"거래량 {vol_ratio:.1f}배"
            flow_badge = "🟢 거래량유입" if vol_ratio >= 1.2 else "⚪ 수급보통"
            streak3d, decay_info = False, None

            if extra_supply:
                if extra_supply.get("inv_trend"):
                    tr = extra_supply["inv_trend"]
                    flow_summary, flow_badge, streak3d = tr["summary_text"], tr["badge_text"], tr["streak3d"]
                    c4 = streak3d or (tr["is_smart_inflow"] and (rebound or vol_ratio >= 1.0)) or (vol_ratio >= 1.6 and rebound)
                elif extra_supply.get("mu_cmf20") is not None:
                    cmf = float(extra_supply["mu_cmf20"])
                    flow_summary = f"모체 MU 기관자금(CMF): {cmf:+.2f}"
                    flow_badge = "🟢MU기관매집" if cmf >= 0.08 else ("🟢MU자금유입" if cmf >= 0 else "🔴MU자금이탈")
                    c4 = (cmf >= 0 and rebound) or (vol_ratio >= 1.2 and rebound)
                elif extra_supply.get("use_self_cmf"):
                    flow_summary = f"기관자금(20일 CMF): {self_cmf20:+.2f}"
                    flow_badge = "🟢기관매집 강함" if self_cmf20 >= 0.08 else ("🟢자금유입 우위" if self_cmf20 >= 0 else "🔴자금이탈 주의")
                    c4 = (self_cmf20 >= 0 and rebound) or (vol_ratio >= 1.2 and rebound)
                if extra_supply.get("base_ret10d") is not None:
                    decay_info = calc_leverage_decay(ret10d, float(extra_supply["base_ret10d"]), extra_supply.get("base_name", "기초지수"))

            score = int(c1) + int(c2) + int(c3) + int(c4)
            blocks = make_score_blocks(score, rsi)
            alert = False
            if c1 and score == 4:
                sig, short_st, cash, alert = f"🔥 4중검증 진바닥 ({score}/4)", "진바닥(4/4)", "현금 300만 핵심 분할 검토", True
            elif streak3d and score >= 2:
                sig, short_st, cash, alert = f"🔥 3일연속 매집 ({score}/4)", f"3일매집({score}/4)", "메이저 연속매집 · 홀딩/추적", True
            elif c1 and score == 3 and (c3 or c4):
                sig, short_st, cash = f"✅ 1차 반등타점 ({score}/4)", "타점(3/4)", "반등 확인 · 현금비중 감안 신중"
            elif c1 and score <= 2:
                sig, short_st, cash = f"⚠️ 하락칼날 주의 ({score}/4)", f"칼날({score}/4)", "수급 유입 전 추매 금지"
            elif rsi > 72:
                sig, short_st, cash = f"🚨 단기 과열 ({score}/4)", f"과열({score}/4)", "일부 익절 · 현금비중 확보 권장"
            else:
                sig, short_st, cash = f"⏸ 중립·관망 ({score}/4)", f"관망({score}/4)", "현금 300만 보존 · 반등 대기"

            return {
                "curr": curr, "pct": pct, "session": session_tag, "rsi": rsi, "disp": disp20, "pct_b": pct_b, "vol_ratio": vol_ratio,
                "c1": c1, "c2": c2, "c3": c3, "c4": c4, "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": spark_prices,
                "score": score, "blocks": blocks, "sig": sig, "short_st": short_st, "cash": cash, "alert": alert,
                "flow_summary": flow_summary, "flow_badge": flow_badge, "streak3d": streak3d, "decay_info": decay_info
            }
        except Exception:
            continue
    return {
        "curr": 0.0, "pct": 0.0, "session": "대기", "rsi": 50.0, "disp": 0.0, "pct_b": 0.5, "vol_ratio": 1.0,
        "c1": False, "c2": False, "c3": False, "c4": False, "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": [],
        "score": 0, "blocks": "⬜⬜⬜⬜", "sig": "데이터 대기", "short_st": "대기", "cash": "대기", "alert": False,
        "flow_summary": "수급 대기", "flow_badge": "⚪ 수급대기", "streak3d": False, "decay_info": None
    }

def build_dday_section(now_kst):
    today = now_kst.date()
    html_badges, img_events = [], []
    for ev in KEY_EVENTS:
        diff = (datetime.date.fromisoformat(ev["date"]) - today).days
        if diff < 0:
            continue
        dday_str = "D-DAY" if diff == 0 else f"D-{diff}"
        urgent_cls = "dday-urgent" if diff <= 7 else "dday-normal"
        html_badges.append(f'<div class="dday-row"><span class="dday-tag {urgent_cls}">{dday_str}</span><span class="dday-cat">[{ev["cat"]}]</span><span class="dday-title">{ev["title"]} <span class="sub">({ev["date"][5:]})</span></span></div>')
        if len(img_events) < 2:
            img_events.append({"dday": dday_str, "urgent": diff <= 7, "title": ev["title"], "date": ev["date"][5:]})
    return "".join(html_badges), img_events

def generate_dashboard_png(out_path, now_str, krw_p, kpi, tax_info, semi_peers, stocks_info, img_events):
    reg_font_path, bold_font_path = ensure_korean_fonts()
    f_title = load_font(bold_font_path, 25)
    f_sub = load_font(reg_font_path, 15)
    f_kpi_lbl = load_font(reg_font_path, 14)
    f_kpi_val = load_font(bold_font_path, 26)
    f_kpi_sub = load_font(reg_font_path, 13)
    f_sec = load_font(bold_font_path, 18)
    f_card_b = load_font(bold_font_path, 17)
    f_card_r = load_font(reg_font_path, 13)
    f_pill = load_font(bold_font_path, 12)

    # [핵심 수정] 종목 수에 따른 동적 캔버스 높이 자동 산출 (7종목 하단 잘림 완벽 방지)
    W = 900
    row_h = 104
    row_gap = 8
    header_end_y = 415
    H = header_end_y + len(stocks_info) * (row_h + row_gap) + 74

    img = Image.new("RGB", (W, H), "#070b14")
    draw = ImageDraw.Draw(img)

    draw.text((28, 20), "마스터 비주얼 관제탑 V10.0 (7종목·현금300만)", font=f_title, fill="#38bdf8")
    draw.text((W - 28, 26), f"동기화: {now_str} | 환율 ₩{krw_p:,.1f}", font=f_sub, fill="#94a3b8", anchor="ra")

    pnl_col = "#4ade80" if kpi["total_pnl"] >= 0 else "#f87171"
    kpis = [
        ("총 평가자산 (주식 + 현금)", f"{kpi['total_eval']//10000:,}만 원", f"주식 {kpi['stock_eval']//10000:,}만 + 현금 {kpi['rem_cash']//10000:,}만 ({kpi['cash_ratio']:.1f}%)", "#38bdf8"),
        ("원화 환산 총 평가손익", f"{kpi['total_pnl']//10000:+,}만 원", f"보유주식 수익률 {kpi['stock_ret']:+.2f}%", pnl_col),
        ("가용 현금 / 스윙 복리금고", f"{kpi['rem_cash']//10000:,}만 / {kpi['vault']//10000:+,}만", "현금 비중 10%+ 확충 감시 중", "#4ade80"),
        ("2026 예상 해외주식 양도세", f"{tax_info['est_tax']//10000:,}만 원", f"잔여 비과세 한도 {tax_info['rem_free']//10000:,}만 원", "#fbbf24")
    ]
    for idx, (lbl, val, sub, col) in enumerate(kpis):
        r, c = idx // 2, idx % 2
        x0, y0 = 28 + c * 428, 62 + r * 96
        draw.rounded_rectangle([x0, y0, x0 + 414, y0 + 84], radius=12, fill="#111827", outline="#1e293b", width=2)
        draw.text((x0 + 207, y0 + 11), lbl, font=f_kpi_lbl, fill="#94a3b8", anchor="ma")
        draw.text((x0 + 207, y0 + 32), val, font=f_kpi_val, fill=col, anchor="ma")
        draw.text((x0 + 207, y0 + 62), sub, font=f_kpi_sub, fill="#64748b", anchor="ma")

    py0 = 262
    draw.text((28, py0), "글로벌 반도체 · HBM 풍향계", font=f_sec, fill="#fbbf24")
    for idx, sp in enumerate(semi_peers):
        sx0, sy0_box = 28 + idx * 214, py0 + 26
        p_col = "#4ade80" if sp["pct"] >= 0 else "#f87171"
        draw.rounded_rectangle([sx0, sy0_box, sx0 + 202, sy0_box + 60], radius=10, fill="#0f172a", outline="#334155", width=2)
        draw.text((sx0 + 12, sy0_box + 8), sp["name"], font=f_card_r, fill="#cbd5e1")
        draw.text((sx0 + 190, sy0_box + 8), f"{sp['pct']:+.2f}%", font=f_card_r, fill=p_col, anchor="ra")
        draw.text((sx0 + 12, sy0_box + 31), sp["price_str"], font=f_card_b, fill="#f8fafc")

    sy0 = 382
    draw.text((28, sy0), "보유 7종목 스마트머니 수급 & 4중 검증 스위치", font=f_sec, fill="#38bdf8")

    row_y = header_end_y
    for st in stocks_info:
        ry0, ry1 = row_y, row_y + row_h
        draw.rounded_rectangle([28, ry0, W - 28, ry1], radius=12, fill="#111827", outline="#1f2937", width=2)
        draw.rounded_rectangle([28, ry0, 36, ry1], radius=4, fill=st["color"])

        draw.text((50, ry0 + 10), f"{st['name']}  [{st['price_str']}]", font=f_card_b, fill="#f8fafc")
        r_col = "#4ade80" if st["my_ret"] >= 0 else "#f87171"
        draw.text((50, ry0 + 34), f"수익률 {st['my_ret']:+.1f}% | RSI {st['m']['rsi']:.1f} | 이격 {st['m']['disp']:+.1f}%", font=f_card_r, fill=r_col)
        draw.text((50, ry0 + 53), f"수급: {st['m']['flow_summary']} ({st['m']['flow_badge']})", font=f_kpi_sub, fill="#cbd5e1")

        px, py = 50, ry0 + 73
        for p_lbl, is_on in [("과매도", st["m"]["c1"]), ("지지선", st["m"]["c2"]), ("MACD↑", st["m"]["c3"]), ("실수급", st["m"]["c4"])]:
            bg, bd, fg = ("#14532d", "#4ade80", "#4ade80") if is_on else ("#0f172a", "#334155", "#64748b")
            draw.rounded_rectangle([px, py, px + 96, py + 22], radius=6, fill=bg, outline=bd, width=1)
            draw.text((px + 48, py + 4), ("ON " if is_on else "OFF ") + p_lbl, font=f_pill, fill=fg, anchor="ma")
            px += 104

        spark = st["m"].get("spark", [])
        sx0, sx1, sy_top, sy_bot = W - 255, W - 140, ry0 + 16, ry0 + 56
        draw.rounded_rectangle([sx0 - 6, sy_top - 4, sx1 + 6, sy_bot + 4], radius=6, fill="#0b0f19", outline="#1e293b", width=1)
        if len(spark) >= 2:
            mn, mx = min(spark), max(spark)
            rng = (mx - mn) if mx > mn else 1.0
            pts = [(sx0 + (i / (len(spark) - 1)) * (sx1 - sx0), sy_bot - ((val - mn) / rng) * (sy_bot - sy_top)) for i, val in enumerate(spark)]
            draw.line(pts, fill=st["color"], width=3)
            draw.ellipse([pts[-1][0] - 4, pts[-1][1] - 4, pts[-1][0] + 4, pts[-1][1] + 4], fill=st["color"])

        st_col = "#4ade80" if st["m"]["alert"] else ("#f87171" if st["m"]["rsi"] > 72 else "#38bdf8")
        draw.text((W - 46, ry0 + 18), st["m"]["short_st"], font=f_card_b, fill=st_col, anchor="ra")
        draw.text((W - 46, ry0 + 74), st["m"]["cash"], font=f_kpi_sub, fill="#fbbf24", anchor="ra")
        row_y += row_h + row_gap

    dy0 = row_y + 4
    draw.rounded_rectangle([28, dy0, W - 28, H - 14], radius=12, fill="#111827", outline="#1f2937", width=2)
    draw.text((48, dy0 + 14), "임박 핵심 일정:", font=f_card_b, fill="#fbbf24")
    ex = 195
    for ev in img_events[:2]:
        draw.rounded_rectangle([ex, dy0 + 12, ex + 58, dy0 + 36], radius=6, fill=("#ef4444" if ev["urgent"] else "#1e293b"))
        draw.text((ex + 29, dy0 + 16), ev["dday"], font=f_pill, fill="#ffffff", anchor="ma")
        draw.text((ex + 66, dy0 + 15), f"{ev['title'].split(' (')[0]} ({ev['date']})", font=f_card_r, fill="#e2e8f0")
        ex += 340

    img.save(out_path, "PNG")

def get_latest_strict_news(query, tag, max_items=2, max_hours=48):
    items = []
    try:
        resp = requests.get(f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
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

def render_quick_tile(key_id, short_name, m):
    tile_cls = "q-buy" if m["alert"] else ("q-hot" if m["rsi"] > 72 else "q-wait")
    return f'<div class="q-tile {tile_cls}" id="q-tile-{key_id}"><div class="q-name">{short_name}</div><div class="q-score" id="q-score-{key_id}">{m["blocks"]}</div><div class="q-st" id="q-st-{key_id}">{m["short_st"]}</div></div>'

def render_sig_card(key_id, title, price_badge, my_ret_str, m, border_color):
    sig_color = "pos" if m["alert"] else ("neg" if m["rsi"] > 72 else "")
    bar_w = int((m["score"] / 4.0) * 100)
    bar_color = "#4ade80" if m["alert"] else ("#f87171" if m["rsi"] > 72 else "#38bdf8")
    decay_html = f'<div class="flow-row">📉 <span id="sig-decay-{key_id}">{m["decay_info"]["summary"]}</span></div>' if m.get("decay_info") else ""
    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <div class="sig-hd">
                <div><b>{title}</b> <span id="sig-price-{key_id}">{price_badge}</span><br><span class="sub">20일 추세 &amp; 내 수익:</span> <span id="sig-ret-{key_id}">{my_ret_str}</span></div>
                <div style="text-align:right;">{make_sparkline_svg(m.get("spark", []), border_color)}</div>
            </div>
            <div class="bar-bg"><div class="bar-fill" id="sig-bar-{key_id}" style="width:{bar_w}%;background:{bar_color};"></div></div>
            <div class="metric-grid">
                <div class="m-cell"><span class="sub">RSI(14)</span><br><b id="sig-rsi-{key_id}">{m['rsi']:.1f}</b> <span class="sub">({m['rsi_cut']:.0f})</span></div>
                <div class="m-cell"><span class="sub">20일 이격</span><br><b id="sig-disp-{key_id}">{m['disp']:+.1f}%</b> <span class="sub">({m['disp_cut']:.0f}%)</span></div>
                <div class="m-cell"><span class="sub">볼린저 %B</span><br><b id="sig-pctb-{key_id}">{m['pct_b']:.2f}</b></div>
                <div class="m-cell"><span class="sub">거래량</span><br><b id="sig-vol-{key_id}">{m['vol_ratio']:.1f}배</b></div>
            </div>
            <div class="flow-row">👥 수급: <b id="sig-flow-{key_id}">{m['flow_summary']}</b> <span class="badge" id="sig-fbadge-{key_id}">{m['flow_badge']}</span></div>
            {decay_html}
            <div class="pill-row">
                <span class="pill {'pill-on' if m['c1'] else 'pill-off'}" id="sig-p1-{key_id}">{'🟢' if m['c1'] else '⚫'} 과매도</span>
                <span class="pill {'pill-on' if m['c2'] else 'pill-off'}" id="sig-p2-{key_id}">{'🟢' if m['c2'] else '⚫'} 지지선</span>
                <span class="pill {'pill-on' if m['c3'] else 'pill-off'}" id="sig-p3-{key_id}">{'🟢' if m['c3'] else '⚫'} MACD↑</span>
                <span class="pill {'pill-on' if m['c4'] else 'pill-off'}" id="sig-p4-{key_id}">{'🟢' if m['c4'] else '⚫'} 실수급</span>
            </div>
            <div class="sig-ft"><span class="{sig_color}" id="sig-txt-{key_id}">{m['sig']}</span><span class="warn" id="sig-cash-{key_id}">➔ {m['cash']}</span></div>
        </div>"""

def main():
    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = now_kst.strftime("%Y-%m-%d %H:%M KST")

    worker_api_url = detect_cloudflare_worker_url()
    synced_state = sync_state_from_worker(worker_api_url)
    dday_html, img_events = build_dday_section(now_kst)

    semi_peers = [fetch_peer_with_cmf(p["symbol"], p["name"], p["is_kr"], p["fallback"]) for p in SEMI_PEERS]
    mu_peer = semi_peers[1]
    kq_base_peer = fetch_peer_with_cmf("229200.KS", "코스닥150", True, 12000)

    kq_trend = fetch_kr_investor_trend("233740")
    ok_trend = fetch_kr_investor_trend("080580")
    yg_trend = fetch_kr_investor_trend("019210")
    or_trend = fetch_kr_investor_trend("475830")
    ab_trend = fetch_kr_investor_trend("174900")

    krw_m = get_quad_verified_metrics("KRW=X")
    krw_p = krw_m["curr"] if krw_m["curr"] > 0 else 1337.9

    ram = get_quad_verified_metrics("RAM", 35.0, -9.0, {"mu_cmf20": mu_peer["cmf20"], "base_ret10d": mu_peer["ret10d"], "base_name": "MU"})
    vrt = get_quad_verified_metrics("VRT", 35.0, -9.0, {"use_self_cmf": True})
    kq = get_quad_verified_metrics(["233740.KS"], 34.0, -9.0, {"inv_trend": kq_trend, "base_ret10d": kq_base_peer["ret10d"], "base_name": "코스닥150"})
    okins = get_quad_verified_metrics(["080580.KQ", "080580.KS"], 36.0, -8.0, {"inv_trend": ok_trend})
    yg = get_quad_verified_metrics(["019210.KQ", "019210.KS"], 38.0, -7.0, {"inv_trend": yg_trend})
    or1 = get_quad_verified_metrics(["475830.KQ", "475830.KS"], 32.0, -11.0, {"inv_trend": or_trend})
    ab = get_quad_verified_metrics(["174900.KQ", "174900.KS"], 32.0, -11.0, {"inv_trend": ab_trend})

    def enrich_us(m, key):
        cfg = PORTFOLIO[key]
        p = m["curr"] if m["curr"] > 0 else cfg["fallback_usd"]
        m["curr"] = p
        m["qty"], m["avg"] = cfg["qty"], cfg["avg_usd"]
        m["cost_krw"] = int(cfg["avg_usd"] * cfg["qty"] * krw_p)
        m["eval_usd"] = p * cfg["qty"]
        m["eval_krw"] = int(m["eval_usd"] * krw_p)
        m["pnl_krw"] = m["eval_krw"] - m["cost_krw"]
        m["ret_pct"] = ((p - cfg["avg_usd"]) / cfg["avg_usd"]) * 100.0 if cfg["avg_usd"] > 0 else 0.0
        return m

    def enrich_kr(m, key):
        cfg = PORTFOLIO[key]
        p = m["curr"] if m["curr"] > 0 else cfg["fallback_krw"]
        res = dict(m)
        res["curr"], res["qty"], res["avg"] = p, cfg["qty"], cfg["avg_krw"]
        res["cost_krw"] = int(cfg["avg_krw"] * cfg["qty"])
        res["eval_krw"] = int(p * cfg["qty"])
        res["pnl_krw"] = res["eval_krw"] - res["cost_krw"]
        res["ret_pct"] = ((p - cfg["avg_krw"]) / cfg["avg_krw"]) * 100.0 if cfg["avg_krw"] > 0 else 0.0
        return res

    ram = enrich_us(ram, "RAM")
    vrt = enrich_us(vrt, "VRT")
    kq = enrich_kr(kq, "KODEX_LEV")
    okins = enrich_kr(okins, "OKINS")
    yg = enrich_kr(yg, "YG1")
    or1_h = enrich_kr(or1, "ORUM1")
    or2_h = enrich_kr(or1, "ORUM2")
    ab = enrich_kr(ab, "ABCLON")

    rem_cash = int(synced_state.get("cashKrw", 3000000))
    vault = int(synced_state.get("swingVaultKrw", 0))
    tx = synced_state.get("tax", {"kakaoGainKrw": 660510, "miraeGainKrw": -430535, "additionalGainKrw": 0})
    net_gain = int(tx.get("kakaoGainKrw", 660510)) + int(tx.get("miraeGainKrw", -430535)) + int(tx.get("additionalGainKrw", 0))
    taxable = max(0, net_gain - 2500000)
    est_tax = int(round(taxable * 0.22))
    rem_free = max(0, 2500000 - max(0, net_gain))
    tax_info = {"net_gain": net_gain, "est_tax": est_tax, "rem_free": rem_free}

    stock_cost = ram["cost_krw"] + vrt["cost_krw"] + kq["cost_krw"] + okins["cost_krw"] + yg["cost_krw"] + or1_h["cost_krw"] + or2_h["cost_krw"] + ab["cost_krw"]
    stock_eval = ram["eval_krw"] + vrt["eval_krw"] + kq["eval_krw"] + okins["eval_krw"] + yg["eval_krw"] + or1_h["eval_krw"] + or2_h["eval_krw"] + ab["eval_krw"]
    total_pnl = stock_eval - stock_cost
    stock_ret = (total_pnl / stock_cost) * 100.0 if stock_cost > 0 else 0.0
    total_eval = stock_eval + rem_cash
    cash_ratio = (rem_cash / total_eval) * 100.0 if total_eval > 0 else 0.0
    kpi = {"total_eval": total_eval, "stock_eval": stock_eval, "total_pnl": total_pnl, "stock_ret": stock_ret, "rem_cash": rem_cash, "cash_ratio": cash_ratio, "vault": vault}

    semi_eval = ram["eval_krw"] + okins["eval_krw"] + vrt["eval_krw"]
    bio_eval = or1_h["eval_krw"] + or2_h["eval_krw"] + ab["eval_krw"]

    # 오킨스전자 수익보존 게이지 계산
    ok_peak = max(float(PORTFOLIO["OKINS"].get("peak_krw", okins["avg"])), okins["curr"], okins["avg"])
    ok_stop = int(round(ok_peak * 0.95))
    ok_target = int(synced_state.get("sniperTargets", {}).get("okinsTargetKrw", 15000))
    ok_pos = int(max(3, min(97, ((okins["curr"] - ok_stop) / (ok_target - ok_stop)) * 100))) if ok_target > ok_stop else 50

    bio_trials = fetch_clinical_trials_gov()
    bio_disc = fetch_bio_disclosures()
    trials_html = "".join([f'<div class="bio-item"><div class="bio-hd"><span class="bio-drug">[{t["drug_tag"]}]</span><span class="bio-tag {t["st_cls"]}">{t["st_icon"]} {t["status"]} ({t["last_update"]})</span></div><a href="{t["link"]}" target="_blank"><b>{t["nct_id"]}</b> · {t["title"]}</a></div>' for t in bio_trials]) or '<div class="sub">미국 임상 DB 조회 대기 중</div>'
    disc_html = "".join([f'<div class="bio-item"><div class="bio-hd"><span class="bio-tag {d["badge_cls"]}">{d["badge_txt"]} · {d["corp"]}</span><span class="meta">{d["time"]}</span></div><a href="{d["link"]}" target="_blank">{d["title"]}</a><div class="bio-act">💡 AI 판독: {d["action"]}</div></div>' for d in bio_disc]) or '<div class="sub">최근 7일 내 주요 공시 변동 없음</div>'

    news = (get_latest_strict_news("엔비디아 OR 마이크론 OR 오킨스전자 OR 버티브", "[반도체·AI]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 2))
    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'

    semi_bar_html = "".join([f'<div class="semi-tile"><div class="semi-top"><span>{sp["name"]}</span><span class="{"pos" if sp["pct"]>=0 else "neg"}" id="semi-pct-{idx}">{sp["pct"]:+.2f}%</span></div><div class="semi-val" id="semi-val-{idx}">{sp["price_str"]}</div></div>' for idx, sp in enumerate(semi_peers)])

    # 4×2 퀵 신호등 그리드 (7종목 + 현금비중 1칸)
    quick_grid_html = (
        render_quick_tile("ram", "RAM", ram) +
        render_quick_tile("vrt", "버티브", vrt) +
        render_quick_tile("kq", "코스닥레버", kq) +
        render_quick_tile("okins", "오킨스", okins) +
        render_quick_tile("yg", "와이지원", yg) +
        render_quick_tile("or1", "오름테라", or1_h) +
        render_quick_tile("ab", "앱클론", ab) +
        f'<div class="q-tile q-wait"><div class="q-name">현금비중</div><div class="q-score" style="color:#4ade80;font-weight:800;" id="q-cash-pct">{cash_ratio:.1f}%</div><div class="q-st" id="q-cash-man">{rem_cash//10000:,}만 원</div></div>'
    )

    cls_fn = lambda r: "pos" if r >= 0 else "neg"
    sig_cards_html = (
        render_sig_card("okins", f"⚡ 오킨스전자 ({okins['qty']:,}주 · 수익보존)", f'<span class="sub">₩{okins["curr"]:,.0f} ({okins["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(okins["ret_pct"])}">{okins["ret_pct"]:+.2f}%</span>', okins, "#2dd4bf") +
        render_sig_card("ram", f"🇺🇸 RAM ({ram['qty']:,}주)", f'<span class="badge">{ram["session"]}</span> <span class="sub">${ram["curr"]:.2f} ({ram["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(ram["ret_pct"])}">{ram["ret_pct"]:+.1f}%</span>', ram, "#38bdf8") +
        render_sig_card("vrt", f"🇺🇸 버티브홀딩스 VRT ({vrt['qty']}주)", f'<span class="badge">{vrt["session"]}</span> <span class="sub">${vrt["curr"]:.2f} ({vrt["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(vrt["ret_pct"])}">{vrt["ret_pct"]:+.1f}%</span>', vrt, "#60a5fa") +
        render_sig_card("kq", f"🇰🇷 코스닥150레버 ({kq['qty']:,}주)", f'<span class="sub">₩{kq["curr"]:,.0f} ({kq["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(kq["ret_pct"])}">{kq["ret_pct"]:+.1f}%</span>', kq, "#f87171") +
        render_sig_card("yg", f"🔧 와이지-원 ({yg['qty']:,}주)", f'<span class="sub">₩{yg["curr"]:,.0f} ({yg["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(yg["ret_pct"])}">{yg["ret_pct"]:+.1f}%</span>', yg, "#fbbf24") +
        render_sig_card("or1", f"🧬 오름테라퓨틱 ({or1_h['qty'] + or2_h['qty']:,}주)", f'<span class="sub">₩{or1_h["curr"]:,.0f} ({or1_h["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(or2_h["ret_pct"])}">{or2_h["ret_pct"]:+.1f}%</span>', or1_h, "#c084fc") +
        render_sig_card("ab", f"🧬 앱클론 ({ab['qty']:,}주)", f'<span class="sub">₩{ab["curr"]:,.0f} ({ab["pct"]:+.2f}%)</span>', f'<span class="{cls_fn(ab["ret_pct"])}">{ab["ret_pct"]:+.1f}%</span>', ab, "#4ade80")
    )

    state_json_str = json.dumps(synced_state, ensure_ascii=False)
    pnl_color = cls_fn(total_pnl)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>마스터 관제탑 V10.0 (7종목 3-Tab)</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script id="v10-state-backup" type="application/json">{state_json_str}</script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #070b14; color: #f8fafc; margin: 0; padding: 12px; max-width: 600px; margin: auto; }}
        .top-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .top-title {{ font-size: 1.02rem; font-weight: 800; color: #38bdf8; }}
        .live-bar {{ display: flex; justify-content: space-between; align-items: center; background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 6px 10px; margin-bottom: 10px; }}
        .top-sync {{ font-size: 0.72rem; color: #94a3b8; }}
        .btn-refresh {{ background: #0284c7; color: #fff; border: none; border-radius: 6px; padding: 5px 10px; font-size: 0.72rem; font-weight: bold; cursor: pointer; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 10px; }}
        .kpi-box {{ background: linear-gradient(145deg, #131c31, #0f172a); border: 1px solid #1e293b; border-radius: 10px; padding: 10px; text-align: center; }}
        .kpi-lbl {{ font-size: 0.70rem; color: #94a3b8; margin-bottom: 3px; }}
        .kpi-val {{ font-size: 1.02rem; font-weight: 800; color: #f8fafc; }}
        .kpi-sub {{ font-size: 0.67rem; color: #64748b; margin-top: 2px; }}
        .semi-hd {{ font-size: 0.74rem; font-weight: 700; color: #fbbf24; margin-bottom: 5px; display: flex; justify-content: space-between; }}
        .semi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 10px; }}
        .semi-tile {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 6px; }}
        .semi-top {{ display: flex; justify-content: space-between; font-size: 0.66rem; color: #cbd5e1; margin-bottom: 2px; }}
        .semi-val {{ font-size: 0.78rem; font-weight: 800; color: #f8fafc; }}
        .q-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 12px; }}
        .q-tile {{ border-radius: 8px; padding: 7px 4px; text-align: center; border: 1px solid #1e293b; }}
        .q-buy {{ background: rgba(74, 222, 128, 0.15); border-color: #4ade80; }}
        .q-hot {{ background: rgba(248, 113, 113, 0.15); border-color: #f87171; }}
        .q-wait {{ background: #131c31; border-color: #1e293b; }}
        .q-name {{ font-size: 0.71rem; font-weight: 700; color: #e2e8f0; margin-bottom: 2px; }}
        .q-score {{ font-size: 0.70rem; letter-spacing: -1px; margin: 2px 0; }}
        .q-st {{ font-size: 0.65rem; color: #cbd5e1; }}
        .tab-bar {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; position: sticky; top: 0; background: #070b14; padding: 6px 0 10px 0; z-index: 20; }}
        .tab-btn {{ background: #111827; color: #94a3b8; border: 1px solid #1f2937; border-radius: 8px; padding: 9px 4px; font-size: 0.78rem; font-weight: 700; cursor: pointer; }}
        .tab-btn.active {{ background: #0284c7; color: #fff; border-color: #38bdf8; }}
        .tab-panel {{ display: none; }}
        .tab-panel.active {{ display: block; }}
        .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 13px; margin-bottom: 12px; }}
        h2 {{ font-size: 0.90rem; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid #1f2937; color: #38bdf8; display: flex; justify-content: space-between; align-items: center; }}
        .row {{ display: flex; justify-content: space-between; font-size: 0.80rem; padding: 7px 0; border-bottom: 1px dashed #1f2937; align-items: center; }}
        .row:last-child {{ border-bottom: none; }}
        .sub {{ font-size: 0.71rem; color: #94a3b8; }}
        .badge {{ background: #1e293b; color: #38bdf8; padding: 2px 5px; border-radius: 4px; font-size: 0.66rem; margin-left: 3px; border: 1px solid #334155; }}
        .dday-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.76rem; }}
        .dday-tag {{ padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 0.68rem; min-width: 40px; text-align: center; }}
        .dday-urgent {{ background: #ef4444; color: #fff; }}
        .dday-normal {{ background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; }}
        .dday-cat {{ color: #fbbf24; font-weight: bold; font-size: 0.71rem; min-width: 52px; }}
        .sig-box {{ background: #161f33; border: 1px solid #26334d; border-left: 4px solid #38bdf8; padding: 11px; border-radius: 8px; margin-bottom: 10px; font-size: 0.79rem; }}
        .flow-row {{ background: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 5px 8px; margin-bottom: 6px; font-size: 0.71rem; color: #cbd5e1; }}
        .tr-box {{ background: #142038; border: 1px solid #2dd4bf; border-left: 4px solid #2dd4bf; padding: 11px; border-radius: 8px; font-size: 0.79rem; }}
        .range-wrap {{ background: #0f172a; padding: 9px; border-radius: 8px; margin: 7px 0; }}
        .range-labels {{ display: flex; justify-content: space-between; font-size: 0.73rem; margin-bottom: 6px; }}
        .range-track {{ position: relative; height: 8px; background: #1e293b; border-radius: 4px; }}
        .range-fill {{ height: 100%; background: linear-gradient(90deg, #f87171, #38bdf8, #4ade80); border-radius: 4px; }}
        .range-dot {{ position: absolute; top: -4px; width: 15px; height: 15px; background: #fff; border: 3px solid #38bdf8; border-radius: 50%; transform: translateX(-50%); }}
        .sig-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .bar-bg {{ width: 100%; height: 5px; background: #0f172a; border-radius: 3px; overflow: hidden; margin-bottom: 7px; }}
        .bar-fill {{ height: 100%; border-radius: 3px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: #0f172a; padding: 6px; border-radius: 6px; margin-bottom: 6px; text-align: center; font-size: 0.73rem; }}
        .pill-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 7px; text-align: center; }}
        .pill {{ padding: 4px 2px; border-radius: 5px; font-size: 0.68rem; font-weight: 700; }}
        .pill-on {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.5); }}
        .pill-off {{ background: #0f172a; color: #64748b; border: 1px solid #1e293b; }}
        .sig-ft {{ display: flex; justify-content: space-between; align-items: center; padding-top: 6px; border-top: 1px solid #26334d; font-size: 0.76rem; }}
        .pos {{ color: #4ade80; font-weight: bold; }} .neg {{ color: #f87171; font-weight: bold; }} .warn {{ color: #fbbf24; font-weight: bold; }}
        .bio-sub-hd {{ display: flex; justify-content: space-between; font-size: 0.76rem; font-weight: bold; color: #e2e8f0; margin: 10px 0 6px 0; }}
        .bio-item {{ background: #161f33; border: 1px solid #26334d; padding: 8px 10px; border-radius: 8px; margin-bottom: 7px; font-size: 0.77rem; }}
        .bio-hd {{ display: flex; justify-content: space-between; font-size: 0.69rem; margin-bottom: 4px; }}
        .bio-drug {{ color: #c084fc; font-weight: bold; }}
        .bio-tag {{ padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: bold; }}
        .bio-pos {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.5); }}
        .bio-neg {{ background: rgba(248, 113, 113, 0.18); color: #f87171; border: 1px solid rgba(248, 113, 113, 0.5); }}
        .bio-neu {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.4); }}
        .bio-act {{ font-size: 0.69rem; color: #fbbf24; margin-top: 4px; }}
        .n-item {{ background: #161f33; padding: 8px 10px; border-radius: 8px; margin-bottom: 7px; font-size: 0.78rem; }}
        .n-hd {{ display: flex; justify-content: space-between; font-size: 0.69rem; margin-bottom: 4px; }} .tag {{ color: #38bdf8; font-weight: bold; }} .meta {{ color: #94a3b8; }}
        a {{ color: #f1f5f9; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="top-hd">
        <div class="top-title">🛡️ 마스터 관제탑 V10.0 (7종목 3-Tab)</div>
        <a href="dashboard_card.png" target="_blank" style="font-size:0.71rem;color:#2dd4bf;border:1px solid #2dd4bf;padding:3px 8px;border-radius:5px;">🖼️ 요약이미지</a>
    </div>

    <div class="live-bar">
        <div class="top-sync" id="top-sync-text">스냅샷: {now_str} (₩{krw_p:,.1f})</div>
        <button class="btn-refresh" id="btn-live-refresh" onclick="fetchLiveDashboard()">🔄 실시간 새로고침</button>
    </div>

    <div class="kpi-grid">
        <div class="kpi-box">
            <div class="kpi-lbl">총 평가자산 (주식 + 현금)</div>
            <div class="kpi-val" id="kpi-total-eval" style="color:#38bdf8;">{total_eval//10000:,}만 원</div>
            <div class="kpi-sub" id="kpi-total-sub">주식 {stock_eval//10000:,}만 · 현금 {rem_cash//10000:,}만 ({cash_ratio:.1f}%)</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">원화 환산 총 평가손익</div>
            <div class="kpi-val {pnl_color}" id="kpi-total-pnl">{total_pnl//10000:+,}만 원</div>
            <div class="kpi-sub" id="kpi-total-pnl-sub">주식 수익률 {stock_ret:+.2f}%</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">가용 현금 / 스윙 복리금고</div>
            <div class="kpi-val" id="kpi-cash-vault"><span style="color:#4ade80;">{rem_cash//10000:,}만</span> / <span style="color:#38bdf8;">{vault//10000:+,}만</span></div>
            <div class="kpi-sub">텔레그램 /매수·/매도 7종목 연동</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">2026 잔여 비과세 한도</div>
            <div class="kpi-val" id="kpi-tax-val" style="color:#fbbf24;">{rem_free//10000:,}만 원</div>
            <div class="kpi-sub" id="kpi-tax-sub">예상 양도세 {est_tax//10000:,}만 (순익 {net_gain//10000:+,}만)</div>
        </div>
    </div>

    <div class="semi-hd">
        <span>⚡ 글로벌 반도체 · HBM 4대 풍향계</span>
        <span id="live-status-badge" style="color:#4ade80;">● V10.0 LIVE</span>
    </div>
    <div class="semi-grid">{semi_bar_html}</div>
    <div class="q-grid">{quick_grid_html}</div>

    <div class="tab-bar">
        <button class="tab-btn active" onclick="switchTab('tab-signals', this)">🎯 타점 · 수급</button>
        <button class="tab-btn" onclick="switchTab('tab-bio', this)">🧬 바이오 · 일정</button>
        <button class="tab-btn" onclick="switchTab('tab-holdings', this)">💼 보유 · 뉴스</button>
    </div>

    <!-- 탭 1: 타점 · 수급 -->
    <div id="tab-signals" class="tab-panel active">
        <div class="card">
            <h2>🛡️ 수익보존 &amp; 현금확보 포커스 (오킨스전자)</h2>
            <div class="tr-box">
                <div class="sig-hd">
                    <div><b>⚡ 오킨스전자 ({okins['qty']:,}주 · 평단 ₩{okins['avg']:,.0f})</b></div>
                    <div class="{cls_fn(okins['ret_pct'])}" id="ok-ret">{okins['ret_pct']:+.2f}%</div>
                </div>
                <div class="range-wrap">
                    <div class="range-labels">
                        <span class="neg" id="ok-stop">🛡️스탑 ₩{ok_stop:,}</span>
                        <span style="color:#38bdf8;font-weight:bold;" id="ok-curr">현재 ₩{okins['curr']:,.0f}</span>
                        <span class="pos" id="ok-target">🎯1차익절 ₩{ok_target:,}</span>
                    </div>
                    <div class="range-track">
                        <div class="range-fill" id="ok-fill" style="width:{ok_pos}%;"></div>
                        <div class="range-dot" id="ok-dot" style="left:{ok_pos}%;"></div>
                    </div>
                </div>
                <div class="sub">💡 와이지-원 ₩10,150+ 반등 매도 · 코스닥레버 ₩5,100+ 일부 현금화 5분 스나이퍼 연동 중</div>
            </div>
        </div>
        <div class="card">
            <h2>🎯 7종목 스마트머니 수급 &amp; 4중 검증 스위치</h2>
            {sig_cards_html}
        </div>
    </div>

    <!-- 탭 2: 바이오 · 일정 -->
    <div id="tab-bio" class="tab-panel">
        <div class="card">
            <h2>📅 2026–2027 핵심 일정 D-Day 트래커</h2>
            {dday_html}
        </div>
        <div class="card">
            <h2>🧬 바이오 0초 레이더 (미국 임상 DB &amp; 공시 AI 판독)</h2>
            <div class="bio-sub-hd"><span>🔬 ClinicalTrials.gov 실시간 파이프라인</span><span class="sub" id="bio-ct-sync">LIVE 연동</span></div>
            <div id="bio-trials-list">{trials_html}</div>
            <div class="bio-sub-hd"><span>📡 DART 공시 · 학회(ASH) 호악재 판독</span><span class="sub">최근 7일</span></div>
            <div>{disc_html}</div>
        </div>
    </div>

    <!-- 탭 3: 보유 · 뉴스 -->
    <div id="tab-holdings" class="tab-panel">
        <div class="card">
            <h2>💼 보유 8계좌 상세 평가 &amp; 자산 비중</h2>
            <div style="width:210px;margin:0 auto 12px auto;"><canvas id="pfChart"></canvas></div>
            <div class="row"><span><b>RAM (DRAM 2X)</b> (<span id="h-ram-q">{ram['qty']:,}</span>주 · $<span id="h-ram-a">{ram['avg']:.4f}</span>)<br><span class="sub" id="h-ram-s">현재 ${ram['curr']:.2f} ({ram['session']})</span></span><span class="{cls_fn(ram['ret_pct'])}" id="h-ram-v" style="text-align:right;">{ram['ret_pct']:+.2f}%<br>{ram['eval_krw']//10000:,}만 ({ram['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>코스닥150레버리지</b> (<span id="h-kq-q">{kq['qty']:,}</span>주 · ₩{kq['avg']:,.0f})<br><span class="sub" id="h-kq-s">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)</span></span><span class="{cls_fn(kq['ret_pct'])}" id="h-kq-v" style="text-align:right;">{kq['ret_pct']:+.2f}%<br>{kq['eval_krw']//10000:,}만 ({kq['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>오름테라퓨틱(계좌2)</b> ({or2_h['qty']:,}주 · ₩{or2_h['avg']:,.0f})<br><span class="sub" id="h-or2-s">현재 ₩{or2_h['curr']:,.0f} ({or2_h['pct']:+.2f}%)</span></span><span class="{cls_fn(or2_h['ret_pct'])}" id="h-or2-v" style="text-align:right;">{or2_h['ret_pct']:+.2f}%<br>{or2_h['eval_krw']//10000:,}만 ({or2_h['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>와이지-원</b> (<span id="h-yg-q">{yg['qty']:,}</span>주 · ₩{yg['avg']:,.0f})<br><span class="sub" id="h-yg-s">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)</span></span><span class="{cls_fn(yg['ret_pct'])}" id="h-yg-v" style="text-align:right;">{yg['ret_pct']:+.2f}%<br>{yg['eval_krw']//10000:,}만 ({yg['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>앱클론</b> ({ab['qty']:,}주 · ₩{ab['avg']:,.0f})<br><span class="sub" id="h-ab-s">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)</span></span><span class="{cls_fn(ab['ret_pct'])}" id="h-ab-v" style="text-align:right;">{ab['ret_pct']:+.2f}%<br>{ab['eval_krw']//10000:,}만 ({ab['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>오킨스전자</b> (<span id="h-okins-q">{okins['qty']:,}</span>주 · ₩{okins['avg']:,.0f})<br><span class="sub" id="h-okins-s">현재 ₩{okins['curr']:,.0f} ({okins['pct']:+.2f}%)</span></span><span class="{cls_fn(okins['ret_pct'])}" id="h-okins-v" style="text-align:right;">{okins['ret_pct']:+.2f}%<br>{okins['eval_krw']//10000:,}만 ({okins['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>오름테라퓨틱(계좌1)</b> ({or1_h['qty']:,}주 · ₩{or1_h['avg']:,.0f})<br><span class="sub" id="h-or1-s">현재 ₩{or1_h['curr']:,.0f} ({or1_h['pct']:+.2f}%)</span></span><span class="{cls_fn(or1_h['ret_pct'])}" id="h-or1-v" style="text-align:right;">{or1_h['ret_pct']:+.2f}%<br>{or1_h['eval_krw']//10000:,}만 ({or1_h['pnl_krw']//10000:+,}만)</span></div>
            <div class="row"><span><b>버티브홀딩스 (VRT)</b> (<span id="h-vrt-q">{vrt['qty']:,}</span>주 · ${vrt['avg']:.2f})<br><span class="sub" id="h-vrt-s">현재 ${vrt['curr']:.2f} ({vrt['session']})</span></span><span class="{cls_fn(vrt['ret_pct'])}" id="h-vrt-v" style="text-align:right;">{vrt['ret_pct']:+.2f}%<br>{vrt['eval_krw']//10000:,}만 ({vrt['pnl_krw']//10000:+,}만)</span></div>
        </div>
        <div class="card"><h2>📰 최근 48시간 핵심 속보</h2>{news_html}</div>
    </div>

    <script>
        const WORKER_API_URL = "{worker_api_url}";

        function switchTab(panelId, btn) {{
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            const panel = document.getElementById(panelId);
            if (panel) panel.classList.add('active');
            if (btn) btn.classList.add('active');
        }}

        const pfChart = new Chart(document.getElementById('pfChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['반도체·AI(RAM·오킨스·VRT)', '바이오(오름·앱클론)', '코스닥150레버리지', '와이지-원', '가용현금'],
                datasets: [{{
                    data: [{semi_eval//10000}, {bio_eval//10000}, {kq['eval_krw']//10000}, {yg['eval_krw']//10000}, {rem_cash//10000}],
                    backgroundColor: ['#38bdf8', '#c084fc', '#f87171', '#fbbf24', '#4ade80'],
                    borderWidth: 0
                }}]
            }},
            options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#cbd5e1', font: {{ size: 11 }} }} }} }}, cutout: '62%' }}
        }});

        function fmtMan(v) {{
            const m = Math.round(v / 10000);
            return (m >= 0 ? "+" : "") + m.toLocaleString() + "만";
        }}

        function setTxt(id, t) {{ const e = document.getElementById(id); if (e) e.textContent = t; }}
        function setHtml(id, h) {{ const e = document.getElementById(id); if (e) e.innerHTML = h; }}

        function updateSigCardDOM(keyId, m, priceHtml, retHtml) {{
            setHtml("q-score-" + keyId, m.blocks);
            setTxt("q-st-" + keyId, m.shortSt);
            const qt = document.getElementById("q-tile-" + keyId);
            if (qt) qt.className = "q-tile " + (m.alert ? "q-buy" : (m.rsi > 72 ? "q-hot" : "q-wait"));

            setHtml("sig-price-" + keyId, priceHtml);
            setHtml("sig-ret-" + keyId, retHtml);
            setTxt("sig-rsi-" + keyId, m.rsi.toFixed(1));
            setTxt("sig-disp-" + keyId, (m.disp >= 0 ? "+" : "") + m.disp.toFixed(1) + "%");
            setTxt("sig-pctb-" + keyId, m.pctB.toFixed(2));
            setTxt("sig-vol-" + keyId, m.volRatio.toFixed(1) + "배");
            if (m.flowSummary) setTxt("sig-flow-" + keyId, m.flowSummary);
            if (m.flowBadge) setTxt("sig-fbadge-" + keyId, m.flowBadge);
            if (m.decayInfo && m.decayInfo.summary) setTxt("sig-decay-" + keyId, m.decayInfo.summary);

            const bar = document.getElementById("sig-bar-" + keyId);
            if (bar) {{
                bar.style.width = Math.round((m.score / 4) * 100) + "%";
                bar.style.background = m.alert ? "#4ade80" : (m.rsi > 72 ? "#f87171" : "#38bdf8");
            }}
            [["1", m.c1, "과매도"], ["2", m.c2, "지지선"], ["3", m.c3, "MACD↑"], ["4", m.c4, "실수급"]].forEach(([idx, on, lbl]) => {{
                const p = document.getElementById("sig-p" + idx + "-" + keyId);
                if (p) {{ p.className = "pill " + (on ? "pill-on" : "pill-off"); p.textContent = (on ? "🟢 " : "⚫ ") + lbl; }}
            }});
            const stxt = document.getElementById("sig-txt-" + keyId);
            if (stxt) {{ stxt.className = m.alert ? "pos" : (m.rsi > 72 ? "neg" : ""); stxt.textContent = m.sig; }}
            setTxt("sig-cash-" + keyId, "➔ " + m.cash);
        }}

        async function fetchLiveDashboard() {{
            if (!WORKER_API_URL) return;
            const btn = document.getElementById("btn-live-refresh");
            const badge = document.getElementById("live-status-badge");
            if (btn) btn.textContent = "⏳ 수신 중...";
            if (badge) badge.textContent = "⏳ V10.0 실시간 동기화 중...";

            try {{
                const res = await fetch(WORKER_API_URL + "?mode=live&t=" + Date.now());
                const d = await res.json();

                setTxt("top-sync-text", "🟢 실시간: " + d.nowStr + " (₩" + d.krwRate.toFixed(1) + ")");
                setTxt("kpi-total-eval", Math.round(d.kpi.totalEvalKrw / 10000).toLocaleString() + "만 원");
                setTxt("kpi-total-sub", `주식 ${{Math.round(d.kpi.stockEvalKrw / 10000).toLocaleString()}}만 · 현금 ${{Math.round(d.kpi.remCashKrw / 10000).toLocaleString()}}만 (${{d.kpi.cashRatioPct.toFixed(1)}}%)`);

                const pnlEl = document.getElementById("kpi-total-pnl");
                if (pnlEl) {{ pnlEl.textContent = fmtMan(d.kpi.totalPnlKrw) + " 원"; pnlEl.className = "kpi-val " + (d.kpi.totalPnlKrw >= 0 ? "pos" : "neg"); }}
                setTxt("kpi-total-pnl-sub", "주식 수익률 " + (d.kpi.stockRetPct >= 0 ? "+" : "") + d.kpi.stockRetPct.toFixed(2) + "%");
                setHtml("kpi-cash-vault", `<span style="color:#4ade80;">${{Math.round(d.kpi.remCashKrw / 10000).toLocaleString()}}만</span> / <span style="color:#38bdf8;">${{fmtMan(d.kpi.swingVaultKrw)}}</span>`);
                setTxt("kpi-tax-val", Math.round(d.taxInfo.remainingFree / 10000).toLocaleString() + "만 원");
                setTxt("kpi-tax-sub", `예상 양도세 ${{Math.round(d.taxInfo.estTax / 10000)}}만 (순익 ${{fmtMan(d.taxInfo.netGain)}})`);

                setTxt("q-cash-pct", d.kpi.cashRatioPct.toFixed(1) + "%");
                setTxt("q-cash-man", Math.round(d.kpi.remCashKrw / 10000).toLocaleString() + "만 원");

                d.semiPeers.forEach((sp, idx) => {{
                    const pEl = document.getElementById("semi-pct-" + idx);
                    if (pEl) {{ pEl.textContent = (sp.pct >= 0 ? "+" : "") + sp.pct.toFixed(2) + "%"; pEl.className = sp.pct >= 0 ? "pos" : "neg"; }}
                    setTxt("semi-val-" + idx, sp.pStr);
                }});

                const s = d.stocks;
                if (d.focusOkins) {{
                    const okRetEl = document.getElementById("ok-ret");
                    if (okRetEl) {{ okRetEl.textContent = (s.okins.retPct >= 0 ? "+" : "") + s.okins.retPct.toFixed(2) + "%"; okRetEl.className = s.okins.retPct >= 0 ? "pos" : "neg"; }}
                    setTxt("ok-stop", "🛡️스탑 ₩" + d.focusOkins.stopKrw.toLocaleString());
                    setTxt("ok-curr", "현재 ₩" + Math.round(s.okins.price).toLocaleString());
                    setTxt("ok-target", "🎯1차익절 ₩" + d.focusOkins.targetKrw.toLocaleString());
                    const fEl = document.getElementById("ok-fill"), dEl = document.getElementById("ok-dot");
                    if (fEl) fEl.style.width = d.focusOkins.posPct + "%";
                    if (dEl) dEl.style.left = d.focusOkins.posPct + "%";
                }}

                updateSigCardDOM("okins", s.okins, `<span class="sub">₩${{Math.round(s.okins.price).toLocaleString()}} (${{(s.okins.pct>=0?'+':'') + s.okins.pct.toFixed(2)}}%)</span>`, `<span class="${{s.okins.retPct>=0?'pos':'neg'}}">${{(s.okins.retPct>=0?'+':'') + s.okins.retPct.toFixed(2)}}%</span>`);
                updateSigCardDOM("ram", s.ram, `<span class="badge">${{s.ram.session}}</span> <span class="sub">$${{s.ram.price.toFixed(2)}} (${{(s.ram.pct>=0?'+':'') + s.ram.pct.toFixed(2)}}%)</span>`, `<span class="${{s.ram.retPct>=0?'pos':'neg'}}">${{s.ram.retPct.toFixed(1)}}%</span>`);
                updateSigCardDOM("vrt", s.vrt, `<span class="badge">${{s.vrt.session}}</span> <span class="sub">$${{s.vrt.price.toFixed(2)}} (${{(s.vrt.pct>=0?'+':'') + s.vrt.pct.toFixed(2)}}%)</span>`, `<span class="${{s.vrt.retPct>=0?'pos':'neg'}}">${{s.vrt.retPct.toFixed(1)}}%</span>`);
                updateSigCardDOM("kq", s.kq, `<span class="sub">₩${{Math.round(s.kq.price).toLocaleString()}} (${{(s.kq.pct>=0?'+':'') + s.kq.pct.toFixed(2)}}%)</span>`, `<span class="${{s.kq.retPct>=0?'pos':'neg'}}">${{s.kq.retPct.toFixed(1)}}%</span>`);
                updateSigCardDOM("yg", s.yg, `<span class="sub">₩${{Math.round(s.yg.price).toLocaleString()}} (${{(s.yg.pct>=0?'+':'') + s.yg.pct.toFixed(2)}}%)</span>`, `<span class="${{s.yg.retPct>=0?'pos':'neg'}}">${{s.yg.retPct.toFixed(1)}}%</span>`);
                updateSigCardDOM("or1", s.or1, `<span class="sub">₩${{Math.round(s.or1.price).toLocaleString()}} (${{(s.or1.pct>=0?'+':'') + s.or1.pct.toFixed(2)}}%)</span>`, `<span class="${{s.or2.retPct>=0?'pos':'neg'}}">${{s.or2.retPct.toFixed(1)}}%</span>`);
                updateSigCardDOM("ab", s.ab, `<span class="sub">₩${{Math.round(s.ab.price).toLocaleString()}} (${{(s.ab.pct>=0?'+':'') + s.ab.pct.toFixed(2)}}%)</span>`, `<span class="${{s.ab.retPct>=0?'pos':'neg'}}">${{s.ab.retPct.toFixed(1)}}%</span>`);

                const updHold = (k, obj, isUsd) => {{
                    setTxt("h-" + k + "-q", obj.qty.toLocaleString());
                    setTxt("h-" + k + "-s", isUsd ? `현재 $${{obj.price.toFixed(2)}} (${{obj.session}})` : `현재 ₩${{Math.round(obj.price).toLocaleString()}} (${{(obj.pct>=0?'+':'') + obj.pct.toFixed(2)}}%)`);
                    const vEl = document.getElementById("h-" + k + "-v");
                    if (vEl) {{
                        vEl.className = obj.retPct >= 0 ? "pos" : "neg";
                        vEl.innerHTML = `${{(obj.retPct>=0?'+':'') + obj.retPct.toFixed(2)}}%<br>${{Math.round(obj.evalKrw/10000).toLocaleString()}}만 (${{fmtMan(obj.pnlKrw)}})`;
                    }}
                }};
                updHold("ram", s.ram, true); updHold("vrt", s.vrt, true);
                updHold("kq", s.kq, false); updHold("okins", s.okins, false);
                updHold("yg", s.yg, false); updHold("or1", s.or1, false);
                updHold("or2", s.or2, false); updHold("ab", s.ab, false);

                pfChart.data.datasets[0].data = [
                    Math.round(d.kpi.semiEvalKrw / 10000),
                    Math.round(d.kpi.bioEvalKrw / 10000),
                    Math.round(d.kpi.kqEvalKrw / 10000),
                    Math.round(d.kpi.ygEvalKrw / 10000),
                    Math.round(d.kpi.remCashKrw / 10000)
                ];
                pfChart.update();
                if (badge) badge.textContent = "🟢 V10.0 LIVE 동기화 완료";
            }} catch (e) {{
                if (badge) badge.textContent = "⚪ 스냅샷 표시 중";
            }} finally {{
                if (btn) btn.textContent = "🔄 실시간 새로고침";
            }}
        }}

        window.addEventListener("DOMContentLoaded", () => {{
            fetchLiveDashboard();
            setInterval(fetchLiveDashboard, 60000);
        }});
    </script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    stocks_info = [
        {"name": f"KR 오킨스전자 ({okins['qty']:,}주)", "price_str": f"₩{okins['curr']:,.0f} ({okins['pct']:+.2f}%)", "my_ret": okins["ret_pct"], "m": okins, "color": "#2dd4bf"},
        {"name": f"US RAM ({ram['qty']:,}주)", "price_str": f"${ram['curr']:.2f} ({ram['pct']:+.2f}%) {ram['session']}", "my_ret": ram["ret_pct"], "m": ram, "color": "#38bdf8"},
        {"name": f"US 버티브 VRT ({vrt['qty']}주)", "price_str": f"${vrt['curr']:.2f} ({vrt['pct']:+.2f}%) {vrt['session']}", "my_ret": vrt["ret_pct"], "m": vrt, "color": "#60a5fa"},
        {"name": f"KR 코스닥레버 ({kq['qty']:,}주)", "price_str": f"₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)", "my_ret": kq["ret_pct"], "m": kq, "color": "#f87171"},
        {"name": f"KR 와이지-원 ({yg['qty']:,}주)", "price_str": f"₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)", "my_ret": yg["ret_pct"], "m": yg, "color": "#fbbf24"},
        {"name": f"KR 오름테라 ({or1_h['qty'] + or2_h['qty']:,}주)", "price_str": f"₩{or1_h['curr']:,.0f} ({or1_h['pct']:+.2f}%)", "my_ret": or2_h["ret_pct"], "m": or1_h, "color": "#c084fc"},
        {"name": f"KR 앱클론 ({ab['qty']:,}주)", "price_str": f"₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)", "my_ret": ab["ret_pct"], "m": ab, "color": "#4ade80"}
    ]

    img_path = "dashboard_card.png"
    try:
        generate_dashboard_png(img_path, now_str, krw_p, kpi, tax_info, semi_peers, stocks_info, img_events)
    except Exception as e:
        print("PNG generation error:", e)

    today_str = now_kst.strftime("%Y-%m-%d")
    curr_hour = now_kst.hour
    slot = "AM" if (7 <= curr_hour <= 11) else ("PM" if (21 <= curr_hour <= 23 or curr_hour == 0) else "")
    slot_key = f"{today_str}_{slot}" if slot else ""

    last_sent = ""
    if os.path.exists("last_sent.txt"):
        with open("last_sent.txt", "r", encoding="utf-8") as lf:
            last_sent = lf.read().strip()

    is_manual_run = (EVENT_NAME == "workflow_dispatch")
    is_scheduled_slot = (not is_manual_run) and (slot != "") and (last_sent != slot_key)
    is_quiet_hour = QUIET_NIGHT_MODE and (1 <= curr_hour <= 6)
    any_buy_alert = any([ram["alert"], vrt["alert"], kq["alert"], okins["alert"], yg["alert"], or1_h["alert"], ab["alert"]]) and not is_quiet_hour

    if TOKEN and CHAT_ID and (is_scheduled_slot or is_manual_run or any_buy_alert):
        # [핵심 수정] 텔레그램 sendPhoto 캡션을 5줄(약 380자)로 경량화해 HTML 태그 절단 오류 원천 차단
        semi_tg_str = " | ".join([f"<b>{sp['name']}</b> {sp['pct']:+.1f}%" for sp in semi_peers])
        header_prefix = "🚨 <b>[긴급 수급·타점 포착!]</b>\n" if (any_buy_alert and not is_scheduled_slot and not is_manual_run) else ""
        caption_msg = (
            f"{header_prefix}🛡️ <b>[V10.0 7종목 마스터 관제 브리핑]</b>\n"
            f"⏰ {now_str} | 환율 ₩{krw_p:,.1f}\n"
            f"💰 총자산: <b>{total_eval//10000:,}만</b> (현금 {rem_cash//10000:,}만 · {cash_ratio:.1f}%)\n"
            f"🧾 2026 예상양도세: <b>{est_tax//10000:,}만</b> (잔여 비과세 {rem_free//10000:,}만)\n"
            f"⚡ 반도체: {semi_tg_str}\n"
            f"💡 오킨스(₩{okins['curr']:,.0f}, {okins['ret_pct']:+.1f}%) · RAM(${ram['curr']:.2f}) · VRT(${vrt['curr']:.2f})"
        )

        inline_kb = {
            "inline_keyboard": [
                [{"text": "📊 V10.0 3-Tab 실시간 웹 관제탑 열기", "url": DASHBOARD_URL}]
            ]
        }

        sent_ok = False
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as photo_file:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                        data={"chat_id": CHAT_ID, "caption": caption_msg, "parse_mode": "HTML", "reply_markup": json.dumps(inline_kb)},
                        files={"photo": photo_file},
                        timeout=15
                    )
                    sent_ok = (resp.status_code == 200)
            except Exception:
                sent_ok = False

        if not sent_ok:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": caption_msg, "parse_mode": "HTML", "disable_web_page_preview": True, "reply_markup": inline_kb},
                timeout=10
            )

        if is_scheduled_slot and not is_manual_run:
            with open("last_sent.txt", "w", encoding="utf-8") as lf:
                lf.write(slot_key)

if __name__ == "__main__":
    main()
