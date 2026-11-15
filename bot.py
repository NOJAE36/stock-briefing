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

PORTFOLIO = {
    "RAM": {"name": "RAM (DRAM 2X)", "symbol": "RAM", "avg_usd": 10.0779, "qty": 5854, "fallback_usd": 5.91},
    "KODEX_LEV": {"name": "코스닥150레버리지", "tickers": ["233740.KS"], "code6": "233740", "avg_krw": 6152, "qty": 3354, "fallback_krw": 4300},
    "YG1": {"name": "와이지-원", "tickers": ["019210.KQ", "019210.KS"], "code6": "019210", "avg_krw": 12910, "qty": 656, "fallback_krw": 9820},
    "ORUM1": {"name": "오름테라퓨틱(계좌1)", "tickers": ["475830.KQ", "475830.KS"], "code6": "475830", "avg_krw": 107113, "qty": 1097, "fallback_krw": 14830},
    "ORUM2": {"name": "오름테라퓨틱(계좌2)", "tickers": ["475830.KQ", "475830.KS"], "code6": "475830", "avg_krw": 96650, "qty": 256, "fallback_krw": 14830},
    "ABCLON": {"name": "앱클론", "tickers": ["174900.KQ", "174900.KS"], "code6": "174900", "avg_krw": 52735, "qty": 256, "fallback_krw": 21850},
    "CASH": {"name": "가용 현금", "eval_krw": 5173000}
}

CUSTOM_PARAMS = {
    "RAM": {"rsi_cut": 35.0, "disp_cut": -9.0},
    "KODEX_LEV": {"rsi_cut": 34.0, "disp_cut": -9.0},
    "YG1": {"rsi_cut": 38.0, "disp_cut": -7.0},
    "ORUM": {"rsi_cut": 32.0, "disp_cut": -11.0},
    "ABCLON": {"rsi_cut": 32.0, "disp_cut": -11.0}
}

NEW_TRANCHES = [
    {
        "key": "RAM",
        "mode": "LIVE",
        "name": "RAM 스윙 트랑셰",
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
        "key": "KODEX_LEV",
        "mode": "SIM",
        "name": "코스닥레버 스윙 트랑셰",
        "symbol": "233740.KS",
        "base_key": "KODEX_LEV",
        "currency": "KRW",
        "entry_date": "2026-11-16",
        "entry_price": 4050,
        "qty": 765,
        "target_pct": 12.0,
        "trail_pct": -6.0
    }
]

SEMI_PEERS = [
    {"symbol": "NVDA", "name": "엔비디아", "is_kr": False, "fallback": 142.0},
    {"symbol": "MU", "name": "마이크론", "is_kr": False, "fallback": 102.0},
    {"symbol": "005930.KS", "name": "삼성전자", "is_kr": True, "fallback": 53000},
    {"symbol": "000660.KS", "name": "SK하이닉스", "is_kr": True, "fallback": 178000}
]

KEY_EVENTS = [
    {"date": "2026-11-18", "cat": "AI·DRAM", "title": "엔비디아(NVDA) FY27 3Q 실적발표 (HBM 수요 풍향계)"},
    {"date": "2026-12-07", "cat": "바이오", "title": "미국 혈액암학회(ASH) Late-Breaking 초록 공개"},
    {"date": "2026-12-10", "cat": "매크로", "title": "미국 12월 FOMC 금리결정 및 점도표 발표"},
    {"date": "2026-12-12", "cat": "바이오", "title": "미국 혈액암학회(ASH 2026) 개막 (오름·앱클론 모멘텀)"},
    {"date": "2026-12-17", "cat": "DRAM", "title": "마이크론(MU) FY27 1Q 실적발표 (RAM 직접 모멘텀)"},
    {"date": "2027-01-08", "cat": "DRAM", "title": "삼성전자 2026 4Q 잠정실적 발표 (메모리 마진 확인)"},
    {"date": "2027-01-11", "cat": "바이오", "title": "2027 JP모건 헬스케어 컨퍼런스 (글로벌 기술이전 시즌)"},
    {"date": "2027-01-22", "cat": "DRAM", "title": "SK하이닉스 2026 4Q 실적발표 (HBM3E·HBM4 가이던스)"}
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
        "cashKrw": 5173000,
        "swingVaultKrw": 0,
        "tax": {"realizedGainKrw": 11678483, "harvestedLossKrw": 0, "cetxSold": False},
        "history": ["11/12: RAM 1차 606주($5.97) 매수 반영 완료"]
    }
    if not worker_url:
        return default_state
    try:
        resp = requests.get(f"{worker_url}?mode=state&t={CACHE_BUST}", timeout=8)
        if resp.status_code == 200:
            st = resp.json()
            if "core" in st and "YG1" in st["core"]:
                PORTFOLIO["YG1"]["qty"] = int(st["core"]["YG1"].get("qty", 656))
            if "tranches" in st:
                for tr in NEW_TRANCHES:
                    k = tr["key"]
                    if k in st["tranches"]:
                        w_tr = st["tranches"][k]
                        tr["mode"] = w_tr.get("mode", tr["mode"])
                        tr["entry_price"] = float(w_tr.get("entryPrice", tr["entry_price"]))
                        tr["qty"] = int(w_tr.get("qty", tr["qty"]))
                        tr["entry_date"] = w_tr.get("entryDate", tr["entry_date"])
            return st
    except Exception:
        pass
    return default_state

# =========================================================================
# [V10.0 신규] 네이버 투자자별 매매동향 & CMF(기관자금) & 음의복리 괴리율 엔진
# =========================================================================

def parse_signed_int(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = str(val).replace(",", "").replace(" ", "").strip()
    try:
        return int(cleaned)
    except Exception:
        return 0

def fmt_kor_qty(q):
    sign = "+" if q > 0 else ""
    if abs(q) >= 10000:
        return f"{sign}{q / 10000:.1f}만"
    return f"{sign}{q:,}"

def fetch_naver_investor_trend(code6):
    fallback = {
        "ok": False, "f1": 0, "i1": 0, "p1": 0, "f3": 0, "i3": 0,
        "f_streak": 0, "i_streak": 0, "smart_streak": 0,
        "smart_buy": False, "retail_trap": False,
        "summary": "수급 데이터 연동 대기"
    }
    if not code6:
        return fallback
    try:
        url = f"https://m.stock.naver.com/api/stock/{code6}/trend"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "Referer": "https://m.stock.naver.com/"
        }
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code != 200:
            return fallback
        raw = resp.json()
        lst = raw if isinstance(raw, list) else raw.get("datas", raw.get("result", []))
        if not isinstance(lst, list) or len(lst) == 0:
            return fallback

        rows = []
        for r in lst[:5]:
            f_val = parse_signed_int(r.get("foreignerPureBuyQuant", r.get("frgnPureBuyQuant", 0)))
            i_val = parse_signed_int(r.get("organPureBuyQuant", r.get("instPureBuyQuant", 0)))
            p_val = parse_signed_int(r.get("individualPureBuyQuant", r.get("indiPureBuyQuant", 0)))
            rows.append({"f": f_val, "i": i_val, "p": p_val})

        f1, i1, p1 = rows[0]["f"], rows[0]["i"], rows[0]["p"]
        f3 = sum(x["f"] for x in rows[:3])
        i3 = sum(x["i"] for x in rows[:3])

        f_streak, i_streak, smart_streak = 0, 0, 0
        for r in rows:
            if r["f"] > 0:
                f_streak += 1
            else:
                break
        for r in rows:
            if r["i"] > 0:
                i_streak += 1
            else:
                break
        for r in rows:
            if r["f"] > 0 or r["i"] > 0 or (r["f"] + r["i"]) > 0:
                smart_streak += 1
            else:
                break

        smart_buy = (f1 > 0 and i1 > 0) or ((f1 + i1) > 0) or ((f3 + i3) > 0 and (f1 > 0 or i1 > 0))
        retail_trap = (f1 < 0 and i1 < 0 and p1 > 0)

        if f_streak >= 3 or i_streak >= 3:
            tag = f"🔥외인·기관 {max(f_streak, i_streak)}일 연속매집!"
        elif f1 > 0 and i1 > 0:
            tag = "🟢외인·기관 양매수"
        elif retail_trap:
            tag = "⚠️개인만 매수(물타기주의)"
        elif smart_buy:
            tag = "🟢메이저 순매수 유입"
        else:
            tag = "⚪수급 중립·관망"

        summary = f"외인 {fmt_kor_qty(f1)} · 기관 {fmt_kor_qty(i1)} · 개인 {fmt_kor_qty(p1)} ({tag})"
        return {
            "ok": True, "f1": f1, "i1": i1, "p1": p1, "f3": f3, "i3": i3,
            "f_streak": f_streak, "i_streak": i_streak, "smart_streak": smart_streak,
            "smart_buy": smart_buy, "retail_trap": retail_trap, "summary": summary
        }
    except Exception:
        return fallback

def calc_cmf_20(highs, lows, closes, vols):
    n = min(20, len(closes))
    if n < 5:
        return 0.0
    mfv_sum = 0.0
    vol_sum = 0.0
    for i in range(len(closes) - n, len(closes)):
        h, l, c, v = float(highs[i]), float(lows[i]), float(closes[i]), float(vols[i])
        hl = h - l
        mfm = ((c - l) - (h - c)) / hl if hl > 0 else 0.0
        mfv_sum += mfm * v
        vol_sum += v
    return (mfv_sum / vol_sum) if vol_sum > 0 else 0.0

def calc_leverage_decay_10d(lev_closes, base_closes=None):
    if lev_closes and len(lev_closes) >= 11 and base_closes and len(base_closes) >= 11:
        lev_now, lev_10 = float(lev_closes[-1]), float(lev_closes[-11])
        base_now, base_10 = float(base_closes[-1]), float(base_closes[-11])
        if lev_10 > 0 and base_10 > 0:
            lev_ret = ((lev_now - lev_10) / lev_10) * 100.0
            base_ret = ((base_now - base_10) / base_10) * 100.0
            decay_pct = lev_ret - (base_ret * 2.0)
            badge = "🟢정상추종"
            if decay_pct <= -3.0:
                badge = "🔴음의복리 경고(단기회전 필수)"
            elif decay_pct <= -1.5:
                badge = "🟡횡보잠식 주의"
            return decay_pct, badge
    if lev_closes and len(lev_closes) >= 11:
        var_sum = 0.0
        for i in range(len(lev_closes) - 10, len(lev_closes)):
            prev_p = float(lev_closes[i - 1])
            curr_p = float(lev_closes[i])
            r = ((curr_p - prev_p) / prev_p) if prev_p > 0 else 0.0
            base_r = r / 2.0
            var_sum += (base_r * base_r)
        decay_pct = -(var_sum * 100.0)
        badge = "🟢정상추종"
        if decay_pct <= -3.0:
            badge = "🔴음의복리 경고(단기회전 필수)"
        elif decay_pct <= -1.5:
            badge = "🟡횡보잠식 주의"
        return decay_pct, badge
    return 0.0, "🟢정상추종"

def classify_bio_catalyst(title):
    pos_words = [
        "기술이전", "기술수출", "라이선스", "단일판매", "공급계약", "마일스톤",
        "임상승인", "승인", "완전관해", "초록", "ASH", "특허", "학회", "병용",
        "FDA", "식약처", "데이터", "유효성", "희귀의약품", "패스트트랙", "계약체결"
    ]
    neg_words = [
        "유상증자", "전환사채", "신주인수권", "임상중단", "임상보류", "보류",
        "기재정정", "계약해지", "해지", "반려", "부작용", "독성", "사망", "불성실공시"
    ]
    for w in neg_words:
        if w in title:
            return {
                "grade": "NEG",
                "badge_cls": "bio-neg",
                "badge_txt": "🔴 악재/희석주의",
                "action": "추매 금지 · 공시 세부조건 확인 필수"
            }
    for w in pos_words:
        if w in title:
            return {
                "grade": "POS",
                "badge_cls": "bio-pos",
                "badge_txt": "🟢 호재/모멘텀",
                "action": "거래량·수급 동반 시 스윙금고 이식 검토"
            }
    return {
        "grade": "NEU",
        "badge_cls": "bio-neu",
        "badge_txt": "🟡 일반공시/동향",
        "action": "단순 참고 · 기존 보유 비중 유지"
    }

def fetch_clinical_trials_gov():
    url = "https://clinicaltrials.gov/api/v2/studies?query.term=ORM-5029+OR+ORM-6151+OR+BMS-986497+OR+AbClon+OR+HLX22+OR+AT101&pageSize=5&sort=LastUpdatePostDate:desc"
    results = []
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200:
            studies = resp.json().get("studies", [])
            for st in studies:
                p = st.get("protocolSection", {})
                id_mod = p.get("identificationModule", {})
                st_mod = p.get("statusModule", {})
                sp_mod = p.get("sponsorCollaboratorsModule", {})

                nct_id = id_mod.get("nctId", "NCT-UNKNOWN")
                raw_title = id_mod.get("briefTitle", "Clinical Study")
                title = (raw_title[:52] + "...") if len(raw_title) > 52 else raw_title
                title = title.replace("&", "&").replace("<", "<").replace(">", ">")
                status = st_mod.get("overallStatus", "UNKNOWN")
                last_update = st_mod.get("lastUpdatePostDateStruct", {}).get("date", "확인중")
                sponsor = sp_mod.get("leadSponsor", {}).get("name", "")

                full_txt = f"{raw_title} {sponsor}".upper()
                drug_tag = "바이오 임상"
                if "ORM-6151" in full_txt or "986497" in full_txt:
                    drug_tag = "오름/BMS ORM-6151"
                elif "ORM-5029" in full_txt or "ORUM" in full_txt:
                    drug_tag = "오름 ORM-5029"
                elif "HLX22" in full_txt or "AC101" in full_txt:
                    drug_tag = "앱클론/헨리우스 HLX22"
                elif "AT101" in full_txt or "ABCLON" in full_txt:
                    drug_tag = "앱클론 AT101"

                st_cls = "bio-neu"
                st_icon = "🟡"
                if status in ("RECRUITING", "COMPLETED"):
                    st_cls = "bio-pos"
                    st_icon = "🟢"
                elif status in ("SUSPENDED", "TERMINATED", "WITHDRAWN"):
                    st_cls = "bio-neg"
                    st_icon = "🔴"

                results.append({
                    "nct_id": nct_id,
                    "drug_tag": drug_tag,
                    "title": title,
                    "status": status,
                    "st_cls": st_cls,
                    "st_icon": st_icon,
                    "last_update": last_update,
                    "link": f"https://clinicaltrials.gov/study/{nct_id}"
                })
    except Exception:
        pass
    return results

def fetch_bio_disclosures():
    items = []
    if DART_API_KEY and len(DART_API_KEY) > 10:
        try:
            d_url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&page_count=10"
            r = requests.get(d_url, timeout=6)
            if r.status_code == 200:
                for row in r.json().get("list", []):
                    corp = row.get("corp_name", "")
                    if "오름테라퓨틱" in corp or "앱클론" in corp:
                        rep_nm = row.get("report_nm", "")
                        rcp_no = row.get("rcept_no", "")
                        rcp_dt = row.get("rcept_dt", "")
                        cls_info = classify_bio_catalyst(rep_nm)
                        items.append({
                            "corp": corp,
                            "title": f"[DART공시] {rep_nm}",
                            "time": rcp_dt,
                            "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}",
                            **cls_info
                        })
        except Exception:
            pass

    queries = [
        ("오름테라퓨틱", "오름테라퓨틱 (공시 OR 임상 OR 기술이전 OR 초록 OR ASH OR ORM OR 유상증자 OR 전환사채)"),
        ("앱클론", "앱클론 (공시 OR 임상 OR 기술이전 OR 단일판매 OR AT101 OR AC101 OR HLX22 OR 특허)")
    ]
    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    for corp_name, q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=ko&gl=KR&ceid=KR:ko"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            cnt = 0
            for entry in feedparser.parse(resp.content).entries:
                if not hasattr(entry, 'published'):
                    continue
                pub_kst = parsedate_to_datetime(entry.published).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
                if (now_kst - pub_kst).total_seconds() / 3600 > 168:
                    continue
                raw_t = entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title
                clean_t = raw_t.replace('&', '&').replace('<', '<').replace('>', '>')
                cls_info = classify_bio_catalyst(clean_t)
                items.append({
                    "corp": corp_name,
                    "title": clean_t,
                    "time": pub_kst.strftime("%m/%d %H:%M"),
                    "link": entry.link,
                    **cls_info
                })
                cnt += 1
                if cnt >= 2:
                    break
        except Exception:
            pass
    return items[:4]

def build_bio_radar_section(swing_vault_krw, or1_m, ab_m, trials, disclosures):
    vault_man = swing_vault_krw // 10000
    or_buyable = int(max(0, swing_vault_krw) // or1_m["curr"]) if or1_m["curr"] > 0 else 0
    ab_buyable = int(max(0, swing_vault_krw) // ab_m["curr"]) if ab_m["curr"] > 0 else 0

    or_ready = (or1_m["score"] >= 3 or or1_m["vol_ratio"] >= 1.8 or or1_m["f_streak"] >= 3 or or1_m["i_streak"] >= 3)
    ab_ready = (ab_m["score"] >= 3 or ab_m["vol_ratio"] >= 1.8 or ab_m["f_streak"] >= 3 or ab_m["i_streak"] >= 3)
    or_verdict = f"🔥 캐터펄트 이식 적기! (외인{or1_m['f_streak']}일·기관{or1_m['i_streak']}일)" if or_ready else f"⏸ 대기 (외인{or1_m['f_streak']}일·기관{or1_m['i_streak']}일 매집)"
    ab_verdict = f"🔥 캐터펄트 이식 적기! (외인{ab_m['f_streak']}일·기관{ab_m['i_streak']}일)" if ab_ready else f"⏸ 대기 (외인{ab_m['f_streak']}일·기관{ab_m['i_streak']}일 매집)"
    or_v_cls = "pos" if or_ready else "sub"
    ab_v_cls = "pos" if ab_ready else "sub"

    trials_html = "".join([
        f'<div class="bio-item">'
        f'<div class="bio-hd"><span class="bio-drug">[{t["drug_tag"]}]</span>'
        f'<span class="bio-tag {t["st_cls"]}">{t["st_icon"]} {t["status"]} ({t["last_update"]})</span></div>'
        f'<a href="{t["link"]}" target="_blank"><b>{t["nct_id"]}</b> · {t["title"]}</a>'
        f'</div>'
        for t in trials
    ]) or '<div class="sub">미국 임상 DB 조회 대기 중</div>'

    disc_html = "".join([
        f'<div class="bio-item">'
        f'<div class="bio-hd"><span class="bio-tag {d["badge_cls"]}">{d["badge_txt"]} · {d["corp"]}</span>'
        f'<span class="meta">{d["time"]}</span></div>'
        f'<a href="{d["link"]}" target="_blank">{d["title"]}</a>'
        f'<div class="bio-act">💡 AI 판독: {d["action"]}</div>'
        f'</div>'
        for d in disclosures
    ]) or '<div class="sub">최근 7일 내 주요 바이오 공시·임상 변동 없음</div>'

    return f"""
        <div class="cata-box">
            <div class="sig-hd">
                <div><b>🚀 스윙금고 ➔ 바이오 캐터펄트 (3일 연속매집 감시)</b></div>
                <div class="pos" id="bio-vault-amt">금고 {vault_man:+,}만 원</div>
            </div>
            <div class="sub" style="margin-bottom:8px;">
                금고 수익 전액 이식 시: <b style="color:#c084fc;">오름 +<span id="bio-or-buyable">{or_buyable:,}</span>주</b> 또는 <b style="color:#4ade80;">앱클론 +<span id="bio-ab-buyable">{ab_buyable:,}</span>주</b> 무상 증식 가능
            </div>
            <div class="cata-grid">
                <div class="cata-cell">
                    <div class="sub">🧬 오름테라퓨틱 수급·매집</div>
                    <div style="margin:3px 0;"><b id="bio-or-blocks">{or1_m['blocks']}</b> <span class="sub">({or1_m['score']}/4) | 거래량 <b id="bio-or-vol">{or1_m['vol_ratio']:.1f}배</b></span></div>
                    <div class="{or_v_cls}" id="bio-or-verdict" style="font-size:0.71rem;">{or_verdict}</div>
                </div>
                <div class="cata-cell">
                    <div class="sub">🧬 앱클론 수급·매집</div>
                    <div style="margin:3px 0;"><b id="bio-ab-blocks">{ab_m['blocks']}</b> <span class="sub">({ab_m['score']}/4) | 거래량 <b id="bio-ab-vol">{ab_m['vol_ratio']:.1f}배</b></span></div>
                    <div class="{ab_v_cls}" id="bio-ab-verdict" style="font-size:0.71rem;">{ab_verdict}</div>
                </div>
            </div>
        </div>

        <div class="bio-sub-hd">
            <span>🔬 미국 국립보건원(ClinicalTrials.gov) 실시간 추적</span>
            <span class="sub" id="bio-ct-sync">LIVE API 연동</span>
        </div>
        <div id="bio-trials-list">
            {trials_html}
        </div>

        <div class="bio-sub-hd" style="margin-top:12px;">
            <span>📡 DART 공시 · 학회(ASH) 호악재 AI 자동 판독</span>
            <span class="sub">최근 7일 기준</span>
        </div>
        <div id="bio-disc-list">
            {disc_html}
        </div>
    """

def ensure_korean_fonts():
    reg_path = "NanumGothic-Regular.ttf"
    bold_path = "NanumGothic-Bold.ttf"
    reg_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    bold_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/nanumgothic/NanumGothic-Bold.ttf"
    try:
        if not os.path.exists(reg_path):
            r = requests.get(reg_url, timeout=10)
            if r.status_code == 200:
                with open(reg_path, "wb") as f:
                    f.write(r.content)
        if not os.path.exists(bold_path):
            r = requests.get(bold_url, timeout=10)
            if r.status_code == 200:
                with open(bold_path, "wb") as f:
                    f.write(r.content)
    except Exception:
        pass
    return reg_path, bold_path

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def make_visual_gauge(curr, low, high, length=10):
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

def fetch_semi_peers():
    results = []
    for p in SEMI_PEERS:
        sym = p["symbol"]
        curr = float(p["fallback"])
        pct = 0.0
        closes_list = []
        cmf_val = 0.0
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1mo", timeout=8)
            if not hist.empty:
                df = hist.dropna(subset=['Close'])
                if len(df) >= 1:
                    reg_curr = float(df['Close'].iloc[-1])
                    prev = float(df['Close'].iloc[-2]) if len(df) >= 2 else reg_curr
                    curr = reg_curr
                    if not p["is_kr"]:
                        try:
                            intra = t.history(period="2d", interval="5m", prepost=True, timeout=6)
                            if not intra.empty:
                                ic = intra.dropna(subset=['Close'])
                                if not ic.empty:
                                    curr = float(ic['Close'].iloc[-1])
                                    if ic.index[-1].date() > df.index[-1].date():
                                        prev = reg_curr
                        except Exception:
                            pass
                    pct = ((curr - prev) / prev) * 100.0 if prev > 0 else 0.0
                    closes_list = [float(x) for x in df['Close'].values]
                    if closes_list:
                        closes_list[-1] = curr
                    highs_list = [float(x) for x in df['High'].values]
                    lows_list = [float(x) for x in df['Low'].values]
                    vols_list = [float(x) for x in df['Volume'].values]
                    cmf_val = calc_cmf_20(highs_list, lows_list, closes_list, vols_list)
        except Exception:
            pass
        p_str = f"₩{curr:,.0f}" if p["is_kr"] else f"${curr:,.2f}"
        results.append({
            "name": p["name"], "symbol": sym.split(".")[0], "price_str": p_str,
            "pct": pct, "closes": closes_list, "cmf20": cmf_val
        })
    return results

def build_dday_section(now_kst):
    today = now_kst.date()
    html_badges, tg_lines, img_events = [], [], []
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
            f'<span class="dday-cat">[{ev["cat"]}]</span>'
            f'<span class="dday-title">{ev["title"]} <span class="sub">({ev["date"][5:]})</span></span></div>'
        )
        if len(tg_lines) < 3:
            tg_lines.append(f"• <b>[{tg_prefix}{dday_str}]</b> {ev['title']} ({ev['date'][5:]})")
        if len(img_events) < 3:
            img_events.append({"dday": dday_str, "urgent": diff <= 7, "cat": ev["cat"], "title": ev["title"], "date": ev["date"][5:]})
    return "".join(html_badges), "\n".join(tg_lines), img_events

def get_quad_verified_metrics(tickers, rsi_cut=35.0, disp_cut=-9.0, is_core_cash_target=True, inv_trend=None, base_cmf=None, base_closes=None, is_leverage=False):
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
            session_tag = "본장"

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
                                session_tag = "프리장"
                            elif 570 <= hm < 960:
                                session_tag = "본장"
                            else:
                                session_tag = "애프터"
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

            closes_list = [float(x) for x in closes.values]
            highs_list = [float(x) for x in highs.values]
            lows_list = [float(x) for x in lows.values]
            vols_list = [float(x) for x in vols.values]
            spark_prices = closes_list[-20:]

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

            self_cmf = calc_cmf_20(highs_list, lows_list, closes_list, vols_list)
            cmf = float(base_cmf) if base_cmf is not None else self_cmf

            c1_oversold = (rsi < rsi_cut) or (disp20 <= disp_cut)
            c2_support = (pct_b <= 0.18) or (curr >= ma60)
            c3_momentum = macd_turn

            f_streak, i_streak, smart_streak = 0, 0, 0
            if inv_trend and inv_trend.get("ok"):
                f_streak = inv_trend["f_streak"]
                i_streak = inv_trend["i_streak"]
                smart_streak = inv_trend["smart_streak"]
                flow_str = inv_trend["summary"]
                c4_volume = inv_trend["smart_buy"] or (vol_ratio >= 1.3 and bullish_rebound and not inv_trend["retail_trap"])
            elif sym == "RAM":
                cmf_tag = "🟢기관매집 유입" if cmf > 0.03 else ("🔴자금유출 주의" if cmf < -0.05 else "🟡중립·관망")
                flow_str = f"모체(MU) 기관자금 CMF {cmf:+.2f} ({cmf_tag})"
                c4_volume = (cmf > 0 and bullish_rebound) or (vol_ratio >= 1.2 and bullish_rebound)
            else:
                cmf_tag = "🟢스마트머니 유입" if cmf > 0.02 else "⚪수급 중립"
                flow_str = f"자금유입강도(CMF) {cmf:+.2f} ({cmf_tag})"
                c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (cmf > 0.02 and bullish_rebound)

            decay_pct, decay_badge = 0.0, ""
            if is_leverage:
                decay_pct, decay_badge = calc_leverage_decay_10d(closes_list, base_closes)

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            blocks = make_score_blocks(score, rsi)
            chk_icons = f"{'🟢' if c1_oversold else '⚫'}과매도 {'🟢' if c2_support else '⚫'}지지 {'🟢' if c3_momentum else '⚫'}MACD {'🟢' if c4_volume else '⚫'}메이저수급"

            is_buy_alert = False
            if c1_oversold and score == 4:
                sig, short_st = f"🔥 4중검증+수급 완벽타점 ({score}/4)", "진바닥(4/4)"
                cash = "잔여 시드 적극 투입 검토" if is_core_cash_target else "메이저수급 확인 (캐터펄트 이식)"
                is_buy_alert = True
            elif c1_oversold and score == 3 and (c3_momentum or c4_volume):
                sig, short_st = f"✅ 1차 검증타점 ({score}/4)", "타점진입(3/4)"
                cash = "신규 트랑셰 분할 투입" if is_core_cash_target else "수급 반등 타점 (스윙금고 이식)"
                is_buy_alert = True
            elif c1_oversold and inv_trend and inv_trend.get("retail_trap"):
                sig, short_st = f"⚠️ 개미물타기 주의 ({score}/4)", f"수급주의({score}/4)"
                cash = "외인·기관 동반매도 중 (추매 대기)"
            elif c1_oversold and score <= 2:
                sig, short_st, cash = f"⚠️ 하락칼날 주의 ({score}/4)", f"칼날주의({score}/4)", "추가매수 대기 (수급·반등 미확인)"
            elif rsi > 72:
                sig, short_st, cash = f"🚨 단기 과열 ({score}/4)", f"과열주의({score}/4)", "신규 트랑셰 익절 & 역물타기"
            else:
                sig, short_st, cash = f"⏸ 중립·관망 ({score}/4)", f"관망중({score}/4)", "스윙 트랑셰 감시 · 현금 대기"

            return {
                "curr": curr, "reg_curr": reg_curr, "pct": pct, "ext_pct": ext_pct,
                "session": session_tag, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio, "cmf": cmf,
                "c1": c1_oversold, "c2": c2_support, "c3": c3_momentum, "c4": c4_volume,
                "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": spark_prices, "closes": closes_list,
                "score": score, "blocks": blocks, "chk": chk_icons, "sig": sig, "short_st": short_st, "cash": cash, "alert": is_buy_alert,
                "flow_str": flow_str, "f_streak": f_streak, "i_streak": i_streak, "smart_streak": smart_streak,
                "decay_pct": decay_pct, "decay_badge": decay_badge
            }
        except Exception:
            continue
    return {
        "curr": 0.0, "reg_curr": 0.0, "pct": 0.0, "ext_pct": 0.0, "session": "대기",
        "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0, "cmf": 0.0,
        "c1": False, "c2": False, "c3": False, "c4": False, "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": [], "closes": [],
        "score": 0, "blocks": "⬜⬜⬜⬜", "chk": "대기", "sig": "데이터 대기", "short_st": "대기(0/4)", "cash": "0원", "alert": False,
        "flow_str": "수급 데이터 대기", "f_streak": 0, "i_streak": 0, "smart_streak": 0,
        "decay_pct": 0.0, "decay_badge": ""
    }

def evaluate_new_tranches(price_map, krw_rate):
    if not NEW_TRANCHES:
        return '<div class="sub">등록된 신규 스윙 트랑셰가 없습니다.</div>', "", False, 0, 0, 0, None

    cards_html, tg_rows = [], []
    exit_alert = False
    live_cost_krw = 0
    live_eval_krw = 0
    primary_live_data = None

    for tr in NEW_TRANCHES:
        try:
            mode = tr.get("mode", "SIM").upper()
            qty = int(tr["qty"])
            is_live = (mode == "LIVE" and qty > 0)
            sym = tr["symbol"]
            is_usd = (tr.get("currency", "KRW") == "USD")
            entry_p = float(tr["entry_price"])
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
                new_total_qty = b_qty + (qty if is_live else 0)
                blended_avg = ((b_avg * b_qty) + ((entry_p * qty) if is_live else 0)) / new_total_qty if new_total_qty > 0 else b_avg
                blended_note = f"MTS 합산: {new_total_qty:,}주 · 평단 {avg_fmt(blended_avg)}"

            if not is_live:
                badge_html = '<span class="tr-badge tr-sim">🧪 모의 프리뷰</span>'
                status_str = f"진입가 {p_fmt(entry_p)} 가정 시뮬레이션 (/매수 명령어로 실전 전환)"
                id_attr = ""
            else:
                badge_html = '<span class="tr-badge tr-live">🟢 실전 LIVE</span>'
                status_str = f"1차 반등선({p_fmt(half_target_p)}) 절반 예약매도 권장"
                id_attr = 'id="live-tranche-card"' if is_usd else ''
                if curr_p <= stop_p:
                    status_str = f"🚨 트레일링 스탑 도달! ({p_fmt(stop_p)} 이하 매도)"
                    exit_alert = True
                elif curr_p >= target_p:
                    status_str = f"🎯 목표 익절가 도달! ({p_fmt(target_p)} 익절 실행)"
                    exit_alert = True

                if primary_live_data is None:
                    primary_live_data = {
                        "name": tr["name"], "qty": qty, "entry_p": entry_p, "curr_p": curr_p,
                        "stop_p": stop_p, "target_p": target_p, "half_p": half_target_p,
                        "ret_entry": ret_entry, "pnl_str": pnl_str, "pos_pct": pos_pct,
                        "dist_stop": dist_to_stop, "dist_target": dist_to_target,
                        "blended_note": blended_note, "status_str": status_str
                    }

            ret_cls = "pos" if ret_entry >= 0 else "neg"
            is_primary = (is_live and is_usd)
            cards_html.append(f"""
                <div class="tr-box" {id_attr}>
                    <div class="sig-hd">
                        <div><b>{tr['name']}</b> (<span id="{'tr-live-qty' if is_primary else ''}">{qty:,}</span>주) {badge_html}</div>
                        <div class="{ret_cls}" id="{'tr-live-ret' if is_primary else ''}" style="font-size:0.9rem;">{ret_entry:+.2f}%</div>
                    </div>
                    <div class="range-wrap">
                        <div class="range-labels">
                            <span class="neg" id="{'tr-live-stop' if is_primary else ''}">🛡️스탑 {p_fmt(stop_p)}</span>
                            <span style="color:#38bdf8;font-weight:bold;" id="{'tr-live-curr' if is_primary else ''}">현재 {p_fmt(curr_p)}</span>
                            <span class="pos" id="{'tr-live-target' if is_primary else ''}">🎯목표 {p_fmt(target_p)}</span>
                        </div>
                        <div class="range-track">
                            <div class="range-fill" id="{'tr-live-fill' if is_primary else ''}" style="width:{pos_pct}%;"></div>
                            <div class="range-dot" id="{'tr-live-dot' if is_primary else ''}" style="left:{pos_pct}%;"></div>
                        </div>
                        <div class="range-Labels-sub">
                            <span id="{'tr-live-dist-stop' if is_primary else ''}">스탑까지 -{dist_to_stop:.1f}% 여유</span>
                            <span id="{'tr-live-dist-target' if is_primary else ''}">익절까지 +{dist_to_target:.1f}% 남음</span>
                        </div>
                    </div>
                    <div class="tr-ft">
                        <span>단독 손익: <b class="{ret_cls}" id="{'tr-live-pnl' if is_primary else ''}">{pnl_str}</b> (원금 {cost_krw//10000:,}만)</span>
                    </div>
                    <div class="sub" style="margin-top:4px;">💡 {blended_note} | <span id="{'tr-live-status' if is_primary else ''}">{status_str}</span></div>
                </div>""")

            if is_live:
                gauge_bar = make_visual_gauge(curr_p, stop_p, target_p, 10)
                tg_rows.append(
                    f"🎯 <b>[실전 스윙] {tr['name']} ({qty:,}주)</b>\n"
                    f"<blockquote>진입 {p_fmt(entry_p)} ➔ 현재 <b>{p_fmt(curr_p)} ({ret_entry:+.2f}% / {pnl_krw//10000:+,}만)</b>\n"
                    f"🛡️{p_fmt(stop_p)} <code>{gauge_bar}</code> 🎯{p_fmt(target_p)}\n"
                    f"• 익절({p_fmt(target_p)})까지 <b>+{dist_to_target:.1f}%</b> | 스탑까지 <b>-{dist_to_stop:.1f}% 여유</b>\n"
                    f"• {blended_note}</blockquote>"
                )
        except Exception:
            continue

    live_pnl_krw = live_eval_krw - live_cost_krw
    return "".join(cards_html), "\n".join(tg_rows), exit_alert, live_cost_krw, live_eval_krw, live_pnl_krw, primary_live_data

def generate_dashboard_png(out_path, now_str, krw_p, total_eval_krw, total_pnl_krw, stock_ret_pct, total_asset_ret_pct, stock_eval_krw, rem_cash_eval, swing_vault_krw, est_tax_krw, semi_peers, live_tr, stocks_info, img_events):
    reg_font_path, bold_font_path = ensure_korean_fonts()
    f_title = load_font(bold_font_path, 25)
    f_sub = load_font(reg_font_path, 15)
    f_kpi_lbl = load_font(reg_font_path, 15)
    f_kpi_val = load_font(bold_font_path, 26)
    f_kpi_sub = load_font(reg_font_path, 13)
    f_sec = load_font(bold_font_path, 19)
    f_card_b = load_font(bold_font_path, 17)
    f_card_r = load_font(reg_font_path, 14)
    f_pill = load_font(bold_font_path, 12)

    W, H = 900, 1360
    img = Image.new("RGB", (W, H), "#070b14")
    draw = ImageDraw.Draw(img)

    draw.text((28, 20), "마스터 관제탑 V10.0 (스마트머니 수급 & 음의복리 방어)", font=f_title, fill="#38bdf8")
    sync_txt = f"동기화: {now_str} | 환율 ₩{krw_p:,.1f}"
    draw.text((W - 28, 26), sync_txt, font=f_sub, fill="#94a3b8", anchor="ra")

    pnl_col = "#4ade80" if total_pnl_krw >= 0 else "#f87171"
    kpis = [
        ("총 평가자산 (1차목표 15,131만)", f"{total_eval_krw//10000:,}만 원", f"1차 전환선까지 {max(0, 15131 - total_eval_krw//10000):,}만 원", "#38bdf8"),
        ("원화 환산 총 평가손익", f"{total_pnl_krw//10000:+,}만 원", f"보유주식 수익률 {stock_ret_pct:+.2f}%", pnl_col),
        ("가용 현금 / 스윙 복리금고", f"{rem_cash_eval//10000:,}만 / {swing_vault_krw//10000:+,}만", "텔레그램 /매수·/매도 자동연동", "#4ade80"),
        ("2026 예상 해외주식 양도세", f"{est_tax_krw//10000:,}만 원", f"절세 감면액 +{(2019266 - est_tax_krw)//10000:,}만 원", "#fbbf24")
    ]
    for idx, (lbl, val, sub, col) in enumerate(kpis):
        r, c = idx // 2, idx % 2
        x0 = 28 + c * 428
        y0 = 64 + r * 100
        x1, y1 = x0 + 414, y0 + 88
        draw.rounded_rectangle([x0, y0, x1, y1], radius=12, fill="#111827", outline="#1e293b", width=2)
        draw.text((x0 + 207, y0 + 12), lbl, font=f_kpi_lbl, fill="#94a3b8", anchor="ma")
        draw.text((x0 + 207, y0 + 35), val, font=f_kpi_val, fill=col, anchor="ma")
        draw.text((x0 + 207, y0 + 66), sub, font=f_kpi_sub, fill="#64748b", anchor="ma")

    py0 = 272
    draw.text((28, py0), "글로벌 반도체 · HBM 풍향계 (RAM 선행지표)", font=f_sec, fill="#fbbf24")
    for idx, sp in enumerate(semi_peers):
        sx0 = 28 + idx * 214
        sy0_box = py0 + 28
        sx1, sy1_box = sx0 + 202, sy0_box + 64
        p_col = "#4ade80" if sp["pct"] >= 0 else "#f87171"
        draw.rounded_rectangle([sx0, sy0_box, sx1, sy1_box], radius=10, fill="#0f172a", outline="#334155", width=2)
        draw.text((sx0 + 14, sy0_box + 10), f"{sp['name']}", font=f_card_r, fill="#cbd5e1")
        draw.text((sx1 - 12, sy0_box + 10), f"{sp['pct']:+.2f}%", font=f_card_r, fill=p_col, anchor="ra")
        draw.text((sx0 + 14, sy0_box + 34), sp["price_str"], font=f_card_b, fill="#f8fafc")

    ty0 = 376
    ty1 = ty0 + 150
    draw.rounded_rectangle([28, ty0, W - 28, ty1], radius=14, fill="#142038", outline="#2dd4bf", width=2)
    if live_tr:
        tr_col = "#4ade80" if live_tr["ret_entry"] >= 0 else "#f87171"
        draw.text((48, ty0 + 14), f"[실전 LIVE] {live_tr['name']} ({live_tr['qty']:,}주 · 진입 ${live_tr['entry_p']:.2f})", font=f_sec, fill="#2dd4bf")
        draw.text((W - 48, ty0 + 14), f"현재 ${live_tr['curr_p']:.2f} ({live_tr['ret_entry']:+.2f}%)", font=f_sec, fill=tr_col, anchor="ra")

        bx0, bx1 = 56, W - 56
        by = ty0 + 74
        draw.rounded_rectangle([bx0, by - 6, bx1, by + 6], radius=6, fill="#0f172a", outline="#334155", width=1)
        fill_x = int(bx0 + (bx1 - bx0) * (live_tr["pos_pct"] / 100.0))
        if fill_x > bx0:
            draw.rounded_rectangle([bx0, by - 6, fill_x, by + 6], radius=6, fill="#38bdf8")

        half_ratio = max(0.0, min(1.0, (live_tr["half_p"] - live_tr["stop_p"]) / (live_tr["target_p"] - live_tr["stop_p"])))
        hx = int(bx0 + (bx1 - bx0) * half_ratio)
        draw.line([(hx, by - 12), (hx, by + 12)], fill="#fbbf24", width=3)
        draw.text((hx, by - 26), f"절반예약 ${live_tr['half_p']:.2f}", font=f_kpi_sub, fill="#fbbf24", anchor="ma")

        draw.ellipse([fill_x - 10, by - 10, fill_x + 10, by + 10], fill="#ffffff", outline="#38bdf8", width=4)

        draw.text((bx0, by - 26), f"스탑 ${live_tr['stop_p']:.2f} (-{live_tr['dist_stop']:.1f}% 여유)", font=f_card_r, fill="#f87171")
        draw.text((bx1, by - 26), f"목표 ${live_tr['target_p']:.2f} (+{live_tr['dist_target']:.1f}% 남음)", font=f_card_r, fill="#4ade80", anchor="ra")

        foot_txt = f"단독손익: {live_tr['pnl_str']}  |  {live_tr['blended_note']}  |  {live_tr['status_str']}"
        draw.text((48, ty0 + 110), foot_txt, font=f_card_r, fill="#e2e8f0")

    sy0 = 540
    draw.text((28, sy0), "5대 보유 종목 스마트머니 수급 · 음의복리 · 20일 추세", font=f_sec, fill="#38bdf8")

    row_y = sy0 + 30
    for st in stocks_info:
        ry0, ry1 = row_y, row_y + 118
        draw.rounded_rectangle([28, ry0, W - 28, ry1], radius=12, fill="#111827", outline="#1f2937", width=2)
        draw.rounded_rectangle([28, ry0, 36, ry1], radius=4, fill=st["color"])

        draw.text((50, ry0 + 10), f"{st['name']}  [{st['price_str']}]", font=f_card_b, fill="#f8fafc")
        r_col = "#4ade80" if st["my_ret"] >= 0 else "#f87171"
        draw.text((50, ry0 + 36), f"내 수익률: {st['my_ret']:+.1f}% | RSI {st['m']['rsi']:.1f} | 이격 {st['m']['disp']:+.1f}%", font=f_card_r, fill=r_col)

        extra_line = st["m"].get("flow_str", "")
        if st["m"].get("decay_badge"):
            extra_line += f" | 10일괴리 {st['m']['decay_pct']:+.1f}%({st['m']['decay_badge'][:6]})"
        draw.text((50, ry0 + 58), extra_line[:62], font=f_kpi_sub, fill="#cbd5e1")

        pills = [
            ("과매도", st["m"]["c1"]),
            ("지지선", st["m"]["c2"]),
            ("MACD반등", st["m"]["c3"]),
            ("메이저수급", st["m"]["c4"])
        ]
        px = 50
        py = ry0 + 84
        for p_lbl, is_on in pills:
            bg = "#14532d" if is_on else "#0f172a"
            bd = "#4ade80" if is_on else "#334155"
            fg = "#4ade80" if is_on else "#64748b"
            prefix = "ON " if is_on else "OFF "
            draw.rounded_rectangle([px, py, px + 108, py + 24], radius=6, fill=bg, outline=bd, width=1)
            draw.text((px + 54, py + 4), prefix + p_lbl, font=f_pill, fill=fg, anchor="ma")
            px += 116

        spark = st["m"].get("spark", [])
        sx0, sx1 = W - 260, W - 140
        sy_top, sy_bot = ry0 + 18, ry0 + 62
        draw.rounded_rectangle([sx0 - 8, sy_top - 6, sx1 + 8, sy_bot + 6], radius=6, fill="#0b0f19", outline="#1e293b", width=1)
        if len(spark) >= 2:
            mn, mx = min(spark), max(spark)
            rng = (mx - mn) if mx > mn else 1.0
            pts = []
            for i, val in enumerate(spark):
                x = sx0 + (i / (len(spark) - 1)) * (sx1 - sx0)
                y = sy_bot - ((val - mn) / rng) * (sy_bot - sy_top)
                pts.append((x, y))
            draw.line(pts, fill=st["color"], width=3)
            lx, ly = pts[-1]
            draw.ellipse([lx - 4, ly - 4, lx + 4, ly + 4], fill=st["color"])

        st_col = "#4ade80" if st["m"]["alert"] else ("#f87171" if st["m"]["rsi"] > 72 else "#38bdf8")
        draw.text((W - 48, ry0 + 22), st["m"]["short_st"], font=f_card_b, fill=st_col, anchor="ra")
        draw.text((W - 48, ry0 + 84), st["m"]["cash"], font=f_kpi_sub, fill="#fbbf24", anchor="ra")

        row_y += 126

    dy0 = row_y + 4
    draw.rounded_rectangle([28, dy0, W - 28, H - 16], radius=12, fill="#111827", outline="#1f2937", width=2)
    draw.text((48, dy0 + 12), "임박 핵심 일정 D-Day:", font=f_card_b, fill="#fbbf24")
    ex = 245
    for ev in img_events[:2]:
        tag_bg = "#ef4444" if ev["urgent"] else "#1e293b"
        draw.rounded_rectangle([ex, dy0 + 10, ex + 64, dy0 + 36], radius=6, fill=tag_bg)
        draw.text((ex + 32, dy0 + 15), ev["dday"], font=f_pill, fill="#ffffff", anchor="ma")
        short_t = ev["title"].split(" (")[0]
        draw.text((ex + 72, dy0 + 14), f"{short_t} ({ev['date']})", font=f_card_r, fill="#e2e8f0")
        ex += 315

    img.save(out_path, "PNG")

def calc_kr_holding(key, param_key, is_core=False, cached_m=None, inv_trend=None, base_closes=None, is_leverage=False):
    item = PORTFOLIO[key]
    if cached_m is not None:
        m = dict(cached_m)
    else:
        p_cfg = CUSTOM_PARAMS.get(param_key, {"rsi_cut": 35.0, "disp_cut": -8.0})
        m = get_quad_verified_metrics(
            item["tickers"], rsi_cut=p_cfg["rsi_cut"], disp_cut=p_cfg["disp_cut"],
            is_core_cash_target=is_core, inv_trend=inv_trend, base_closes=base_closes, is_leverage=is_leverage
        )
    curr_p = m["curr"] if m["curr"] > 0 else float(item["fallback_krw"])
    cost_krw = int(item["avg_krw"] * item["qty"])
    eval_krw = int(curr_p * item["qty"])
    pnl_krw = eval_krw - cost_krw
    ret_pct = ((curr_p - item["avg_krw"]) / item["avg_krw"]) * 100 if item["avg_krw"] > 0 else 0.0
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
            title = (entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title).replace('&', '&').replace('<', '<').replace('>', '>')
            items.append({"tag": tag, "title": title, "source": getattr(entry, 'source', {}).get('title', '주요언론'), "time": pub_kst.strftime("%m/%d %H:%M"), "link": entry.link})
            if len(items) >= max_items:
                break
    except Exception:
        pass
    return items

def render_quick_tile(key_id, short_name, m):
    tile_cls = "q-buy" if m["alert"] else ("q-hot" if "🚨" in m["sig"] else "q-wait")
    return f"""
        <div class="q-tile {tile_cls}" id="q-tile-{key_id}">
            <div class="q-name">{short_name}</div>
            <div class="q-score" id="q-score-{key_id}">{m['blocks']}</div>
            <div class="q-st" id="q-st-{key_id}">{m['short_st']}</div>
        </div>"""

def render_sig_card(key_id, title, price_badge, my_ret_str, m, border_color):
    sig_color = "pos" if m["alert"] else ("neg" if "🚨" in m["sig"] else "")
    bar_w = int((m["score"] / 4.0) * 100)
    bar_color = "#4ade80" if m["alert"] else ("#f87171" if "🚨" in m["sig"] else "#38bdf8")

    p1_cls = "pill-on" if m["c1"] else "pill-off"
    p2_cls = "pill-on" if m["c2"] else "pill-off"
    p3_cls = "pill-on" if m["c3"] else "pill-off"
    p4_cls = "pill-on" if m["c4"] else "pill-off"
    spark_svg = make_sparkline_svg(m.get("spark", []), border_color)

    decay_html = ""
    if m.get("decay_badge"):
        decay_html = f'<div class="flow-row" id="sig-decay-{key_id}">📉 <b>10일 음의복리(괴리율):</b> {m["decay_pct"]:+.2f}% <span class="badge">{m["decay_badge"]}</span></div>'

    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <div class="sig-hd">
                <div>
                    <b>{title}</b> <span id="sig-price-{key_id}">{price_badge}</span><br>
                    <span class="sub">20일 추세 & 내 수익:</span> <span id="sig-ret-{key_id}">{my_ret_str}</span>
                </div>
                <div style="text-align:right;" id="sig-spark-{key_id}">{spark_svg}</div>
            </div>
            <div class="bar-bg"><div class="bar-fill" id="sig-bar-{key_id}" style="width:{bar_w}%;background:{bar_color};"></div></div>
            <div class="metric-grid">
                <div class="m-cell"><span class="sub">RSI(14)</span><br><b id="sig-rsi-{key_id}">{m['rsi']:.1f}</b> <span class="sub">({m['rsi_cut']:.0f})</span></div>
                <div class="m-cell"><span class="sub">20일 이격</span><br><b id="sig-disp-{key_id}">{m['disp']:+.1f}%</b> <span class="sub">({m['disp_cut']:.0f}%)</span></div>
                <div class="m-cell"><span class="sub">볼린저 %B</span><br><b id="sig-pctb-{key_id}">{m['pct_b']:.2f}</b></div>
                <div class="m-cell"><span class="sub">거래량</span><br><b id="sig-vol-{key_id}">{m['vol_ratio']:.1f}배</b></div>
            </div>
            <div class="flow-row" id="sig-flow-{key_id}">👥 <b>수급:</b> {m.get('flow_str', '대기')}</div>
            {decay_html}
            <div class="pill-row">
                <span class="pill {p1_cls}" id="sig-p1-{key_id}">{'🟢' if m['c1'] else '⚫'} 과매도</span>
                <span class="pill {p2_cls}" id="sig-p2-{key_id}">{'🟢' if m['c2'] else '⚫'} 지지선</span>
                <span class="pill {p3_cls}" id="sig-p3-{key_id}">{'🟢' if m['c3'] else '⚫'} MACD↑</span>
                <span class="pill {p4_cls}" id="sig-p4-{key_id}">{'🟢' if m['c4'] else '⚫'} 메이저수급</span>
            </div>
            <div class="sig-ft">
                <span class="{sig_color}" id="sig-txt-{key_id}">{m['sig']}</span>
                <span class="warn" id="sig-cash-{key_id}">➔ {m['cash']}</span>
            </div>
        </div>"""

def main():
    now_kst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    now_str = now_kst.strftime("%Y-%m-%d %H:%M KST")

    worker_api_url = detect_cloudflare_worker_url()
    synced_state = sync_state_from_worker(worker_api_url)

    dday_html, dday_tg, img_events = build_dday_section(now_kst)
    semi_peers = fetch_semi_peers()
    mu_peer = semi_peers[1] if len(semi_peers) > 1 else {"cmf20": 0.0, "closes": []}

    # 국내 4대 종목 네이버 외국인·기관·개인 매매동향 및 코스닥150 본주(229200.KS) 수집
    kq_trend = fetch_naver_investor_trend("233740")
    yg_trend = fetch_naver_investor_trend("019210")
    or_trend = fetch_naver_investor_trend("475830")
    ab_trend = fetch_naver_investor_trend("174900")

    kq_base_closes = []
    try:
        kb_hist = yf.Ticker("229200.KS").history(period="1mo", timeout=6)
        if not kb_hist.empty:
            kq_base_closes = [float(x) for x in kb_hist['Close'].dropna().values]
    except Exception:
        pass

    ram_param = CUSTOM_PARAMS["RAM"]
    ram = get_quad_verified_metrics(
        "RAM", rsi_cut=ram_param["rsi_cut"], disp_cut=ram_param["disp_cut"],
        is_core_cash_target=True, base_cmf=mu_peer["cmf20"], base_closes=mu_peer["closes"], is_leverage=True
    )
    krw = get_quad_verified_metrics("KRW=X", is_core_cash_target=False)
    krw_p = krw["curr"] if krw["curr"] > 0 else 1334.3

    ram_cfg = PORTFOLIO["RAM"]
    ram_p = ram["curr"] if ram["curr"] > 0 else ram_cfg["fallback_usd"]
    ram_cost_usd = ram_cfg["avg_usd"] * ram_cfg["qty"]
    ram_eval_usd = ram_p * ram_cfg["qty"]
    ram_cost_krw = int(ram_cost_usd * krw_p)
    ram_eval_krw = int(ram_eval_usd * krw_p)
    ram_pnl_krw = ram_eval_krw - ram_cost_krw

    tr_ram_cfg = NEW_TRANCHES[0]
    live_ram_qty = tr_ram_cfg["qty"] if tr_ram_cfg["mode"] == "LIVE" else 0
    ram_total_qty = ram_cfg["qty"] + live_ram_qty
    ram_total_avg = ((ram_cfg["avg_usd"] * ram_cfg["qty"]) + (tr_ram_cfg["entry_price"] * live_ram_qty)) / ram_total_qty if ram_total_qty > 0 else ram_cfg["avg_usd"]
    ram_total_ret = ((ram_p - ram_total_avg) / ram_total_avg) * 100

    kq = calc_kr_holding("KODEX_LEV", "KODEX_LEV", is_core=True, inv_trend=kq_trend, base_closes=kq_base_closes, is_leverage=True)
    yg = calc_kr_holding("YG1", "YG1", is_core=False, inv_trend=yg_trend)
    or1 = calc_kr_holding("ORUM1", "ORUM", is_core=False, inv_trend=or_trend)
    or2 = calc_kr_holding("ORUM2", "ORUM", is_core=False, cached_m=or1)
    ab = calc_kr_holding("ABCLON", "ABCLON", is_core=False, inv_trend=ab_trend)

    price_map = {
        "RAM": ram_p,
        "233740.KS": kq["curr"],
        "019210.KQ": yg["curr"],
        "475830.KQ": or1["curr"],
        "174900.KQ": ab["curr"]
    }
    tranche_html, tranche_tg, tranche_alert, live_tr_cost, live_tr_eval, live_tr_pnl, primary_live_data = evaluate_new_tranches(price_map, krw_p)

    rem_cash_eval = int(synced_state.get("cashKrw", 5173000))
    swing_vault_krw = int(synced_state.get("swingVaultKrw", 0))
    tax_obj = synced_state.get("tax", {"realizedGainKrw": 11678483, "harvestedLossKrw": 0, "cetxSold": False})
    taxable_krw = max(0, int(tax_obj.get("realizedGainKrw", 11678483)) - int(tax_obj.get("harvestedLossKrw", 0)) - 2500000)
    est_tax_krw = int(round(taxable_krw * 0.22))
    saved_tax_krw = max(0, 2019266 - est_tax_krw)

    bio_trials = fetch_clinical_trials_gov()
    bio_disclosures = fetch_bio_disclosures()
    bio_radar_html = build_bio_radar_section(swing_vault_krw, or1, ab, bio_trials, bio_disclosures)

    stock_cost_krw = ram_cost_krw + kq["cost_krw"] + yg["cost_krw"] + or1["cost_krw"] + or2["cost_krw"] + ab["cost_krw"] + live_tr_cost
    stock_eval_krw = ram_eval_krw + kq["eval_krw"] + yg["eval_krw"] + or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"] + live_tr_eval
    total_pnl_krw = stock_eval_krw - stock_cost_krw
    stock_ret_pct = ((stock_eval_krw - stock_cost_krw) / stock_cost_krw) * 100.0 if stock_cost_krw > 0 else 0.0

    total_cost_krw = stock_cost_krw + rem_cash_eval
    total_eval_krw = stock_eval_krw + rem_cash_eval
    total_asset_ret_pct = ((total_eval_krw - total_cost_krw) / total_cost_krw) * 100.0 if total_cost_krw > 0 else 0.0
    bio_eval_krw = or1["eval_krw"] + or2["eval_krw"] + ab["eval_krw"]
    ram_combined_eval_krw = ram_eval_krw + live_tr_eval

    news = (get_latest_strict_news("엔비디아 실적 OR 마이크론 OR 삼성전자 HBM", "[반도체]", 2) +
            get_latest_strict_news("코스닥 수급 OR 미국 금리 환율", "[매크로]", 1) +
            get_latest_strict_news("오름테라퓨틱 OR 앱클론", "[바이오]", 1))

    news_html = "".join([f'<div class="n-item"><div class="n-hd"><span class="tag">{x["tag"]}</span><span class="meta">{x["time"]} | {x["source"]}</span></div><a href="{x["link"]}" target="_blank">{x["title"]}</a></div>' for x in news]) or '<div class="n-item">최근 48시간 내 속보 없음</div>'
    news_tg = "\n".join([f"• {x['tag']} <a href='{x['link']}'>{x['title']}</a>" for x in news]) or "• 최근 48시간 내 속보 없음"

    pnl_color = "pos" if total_pnl_krw >= 0 else "neg"
    ram_color = "pos" if ram_total_ret >= 0 else "neg"
    kq_color = "pos" if kq['ret_pct'] >= 0 else "neg"
    yg_color = "pos" if yg['ret_pct'] >= 0 else "neg"
    or1_color = "pos" if or1['ret_pct'] >= 0 else "neg"
    or2_color = "pos" if or2['ret_pct'] >= 0 else "neg"
    ab_color = "pos" if ab['ret_pct'] >= 0 else "neg"

    semi_bar_html = "".join([
        f'<div class="semi-tile" id="semi-tile-{idx}"><div class="semi-top"><span>{sp["name"]}</span><span class="{"pos" if sp["pct"]>=0 else "neg"}" id="semi-pct-{idx}">{sp["pct"]:+.2f}%</span></div><div class="semi-val" id="semi-val-{idx}">{sp["price_str"]}</div></div>'
        for idx, sp in enumerate(semi_peers)
    ])
    semi_tg_str = " | ".join([f"<b>{sp['name']}</b> {sp['pct']:+.1f}%" for sp in semi_peers])

    quick_bar_html = (
        render_quick_tile("ram", "RAM", ram) +
        render_quick_tile("kq", "코스닥레버", kq) +
        render_quick_tile("yg", "와이지-원", yg) +
        render_quick_tile("or1", "오름테라", or1) +
        render_quick_tile("ab", "앱클론", ab)
    )

    sig_cards_html = (
        render_sig_card(
            "ram", f"🇺🇸 RAM (합산 {ram_total_qty:,}주)",
            f'<span class="badge">{ram["session"]}</span> <span class="sub">${ram_p:.2f} ({ram["pct"]:+.2f}%)</span>',
            f'<span class="{ram_color}">{ram_total_ret:+.1f}% (평단 ${ram_total_avg:.2f})</span>',
            ram, "#38bdf8"
        ) +
        render_sig_card(
            "kq", "🇰🇷 KODEX 코스닥150레버리지",
            f'<span class="sub">₩{kq["curr"]:,.0f} ({kq["pct"]:+.2f}%)</span>',
            f'<span class="{kq_color}">{kq["ret_pct"]:+.1f}%</span>',
            kq, "#f87171"
        ) +
        render_sig_card(
            "yg", "🔧 와이지-원",
            f'<span class="sub">₩{yg["curr"]:,.0f} ({yg["pct"]:+.2f}%)</span>',
            f'<span class="{yg_color}">{yg["ret_pct"]:+.1f}%</span>',
            yg, "#fbbf24"
        ) +
        render_sig_card(
            "or1", "🧬 오름테라퓨틱",
            f'<span class="sub">₩{or1["curr"]:,.0f} ({or1["pct"]:+.2f}%)</span>',
            f'<span class="{or1_color}">{or1["ret_pct"]:+.1f}%</span>',
            or1, "#c084fc"
        ) +
        render_sig_card(
            "ab", "🧬 앱클론",
            f'<span class="sub">₩{ab["curr"]:,.0f} ({ab["pct"]:+.2f}%)</span>',
            f'<span class="{ab_color}">{ab["ret_pct"]:+.1f}%</span>',
            ab, "#4ade80"
        )
    )

    state_json_str = json.dumps(synced_state, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>마스터 관제탑 V10.0 Smart-Money</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script id="v8-state-backup" type="application/json">{state_json_str}</script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #070b14; color: #f8fafc; margin: 0; padding: 12px; max-width: 600px; margin: auto; }}
        .top-hd {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .top-title {{ font-size: 1.02rem; font-weight: 800; color: #38bdf8; }}
        .live-bar {{ display: flex; justify-content: space-between; align-items: center; background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 6px 10px; margin-bottom: 10px; }}
        .top-sync {{ font-size: 0.72rem; color: #94a3b8; }}
        .btn-refresh {{ background: #0284c7; color: #fff; border: none; border-radius: 6px; padding: 5px 10px; font-size: 0.72rem; font-weight: bold; cursor: pointer; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 10px; }}
        .kpi-box {{ background: linear-gradient(145deg, #131c31, #0f172a); border: 1px solid #1e293b; border-radius: 10px; padding: 10px; text-align: center; }}
        .kpi-lbl {{ font-size: 0.71rem; color: #94a3b8; margin-bottom: 3px; }}
        .kpi-val {{ font-size: 1.02rem; font-weight: 800; color: #f8fafc; }}
        .kpi-sub {{ font-size: 0.68rem; color: #64748b; margin-top: 2px; }}
        .semi-hd {{ font-size: 0.75rem; font-weight: 700; color: #fbbf24; margin-bottom: 5px; display: flex; justify-content: space-between; }}
        .semi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 12px; }}
        .semi-tile {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 7px 6px; }}
        .semi-top {{ display: flex; justify-content: space-between; font-size: 0.68rem; color: #cbd5e1; margin-bottom: 3px; }}
        .semi-val {{ font-size: 0.80rem; font-weight: 800; color: #f8fafc; }}
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
        .bar-bg {{ width: 100%; height: 5px; background: #0f172a; border-radius: 3px; overflow: hidden; margin-bottom: 8px; }}
        .bar-fill {{ height: 100%; border-radius: 3px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: #0f172a; padding: 6px; border-radius: 6px; margin-bottom: 6px; text-align: center; font-size: 0.75rem; }}
        .m-cell {{ line-height: 1.35; }}
        .flow-row {{ background: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 5px 8px; margin-bottom: 6px; font-size: 0.73rem; color: #e2e8f0; }}
        .pill-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-bottom: 8px; text-align: center; }}
        .pill {{ padding: 4px 2px; border-radius: 5px; font-size: 0.69rem; font-weight: 700; }}
        .pill-on {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.5); }}
        .pill-off {{ background: #0f172a; color: #64748b; border: 1px solid #1e293b; }}
        .sig-ft {{ display: flex; justify-content: space-between; align-items: center; padding-top: 6px; border-top: 1px solid #26334d; font-size: 0.78rem; }}
        .pos {{ color: #4ade80; font-weight: bold; }} .neg {{ color: #f87171; font-weight: bold; }} .warn {{ color: #fbbf24; font-weight: bold; }}
        .cata-box {{ background: linear-gradient(145deg, #1b1630, #0f172a); border: 1px solid #c084fc; border-left: 4px solid #c084fc; padding: 12px; border-radius: 8px; margin-bottom: 12px; font-size: 0.80rem; }}
        .cata-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; background: #090d16; padding: 8px; border-radius: 6px; text-align: center; }}
        .cata-cell {{ border: 1px solid #1e293b; border-radius: 6px; padding: 6px; }}
        .bio-sub-hd {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; font-weight: bold; color: #e2e8f0; margin-bottom: 6px; }}
        .bio-item {{ background: #161f33; border: 1px solid #26334d; padding: 8px 10px; border-radius: 8px; margin-bottom: 7px; font-size: 0.78rem; }}
        .bio-hd {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.70rem; margin-bottom: 4px; }}
        .bio-drug {{ color: #c084fc; font-weight: bold; }}
        .bio-tag {{ padding: 2px 6px; border-radius: 4px; font-size: 0.66rem; font-weight: bold; }}
        .bio-pos {{ background: rgba(74, 222, 128, 0.18); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.5); }}
        .bio-neg {{ background: rgba(248, 113, 113, 0.18); color: #f87171; border: 1px solid rgba(248, 113, 113, 0.5); }}
        .bio-neu {{ background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.4); }}
        .bio-act {{ font-size: 0.70rem; color: #fbbf24; margin-top: 4px; }}
        .n-item {{ background: #161f33; padding: 8px 10px; border-radius: 8px; margin-bottom: 8px; font-size: 0.80rem; }}
        .n-hd {{ display: flex; justify-content: space-between; font-size: 0.70rem; margin-bottom: 4px; }} .tag {{ color: #38bdf8; font-weight: bold; }} .meta {{ color: #94a3b8; }}
        a {{ color: #f1f5f9; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="top-hd">
        <div class="top-title">🛡️ 마스터 관제탑 V10.0 (Smart-Money & Decay)</div>
        <a href="dashboard_card.png" target="_blank" style="font-size:0.72rem;color:#2dd4bf;border:1px solid #2dd4bf;padding:3px 8px;border-radius:5px;">🖼️ 요약이미지 보기</a>
    </div>

    <div class="live-bar">
        <div class="top-sync" id="top-sync-text">스냅샷: {now_str} (₩{krw_p:,.1f})</div>
        <button class="btn-refresh" id="btn-live-refresh" onclick="fetchLiveDashboard()">🔄 실시간 시세 새로고침</button>
    </div>

    <div class="kpi-grid">
        <div class="kpi-box">
            <div class="kpi-lbl">총 평가자산 (1차목표 15,131만)</div>
            <div class="kpi-val" id="kpi-total-eval" style="color:#38bdf8;">{total_eval_krw//10000:,}만 원</div>
            <div class="kpi-sub" id="kpi-total-sub">1차 전환선까지 {max(0, 15131 - total_eval_krw//10000):,}만 원</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">원화 환산 총 평가손익</div>
            <div class="kpi-val {pnl_color}" id="kpi-total-pnl">{total_pnl_krw//10000:+,}만 원</div>
            <div class="kpi-sub" id="kpi-total-pnl-sub">주식 수익률 {stock_ret_pct:+.2f}%
