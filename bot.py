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

# [기본 포트폴리오] Worker에서 무코드 장부(state)를 불러오면 자동으로 덮어씌워짐
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
        "version": "9.5",
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
# [V9.5 신규 1 & 2] 네이버 금융 외국인·기관·개인 매매동향 & 3일 연속 매집 감시 엔진
# =========================================================================

def parse_kor_quant(v):
    if isinstance(v, (int, float)):
        return int(v)
    if not v:
        return 0
    clean = str(v).replace(",", "").replace("+", "").strip()
    try:
        return int(clean)
    except Exception:
        return 0

def fmt_quant_kor(q):
    abs_val = abs(q)
    sign = "+" if q > 0 else ("-" if q < 0 else "")
    if abs_val >= 10000:
        return f"{sign}{abs_val / 10000:.1f}만주"
    return f"{sign}{abs_val:,}주"

def fetch_kr_investor_trend(code6):
    default_res = {
        "frgn": 0, "orgn": 0, "indv": 0,
        "smart_net": 0, "is_smart_inflow": False, "is_twin_buy": False,
        "streak3d": False, "streak_type": "",
        "summary_text": "수급 집계 대기", "badge_text": "⚪ 수급대기"
    }
    try:
        url = f"https://m.stock.naver.com/api/stock/{code6}/trend"
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
        resp = requests.get(url, headers=headers, timeout=6)
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

        streak3d = False
        streak_type = ""
        if len(lst) >= 3:
            f1 = parse_kor_quant(lst[1].get("foreignerPureBuyQuant"))
            f2 = parse_kor_quant(lst[2].get("foreignerPureBuyQuant"))
            o1 = parse_kor_quant(lst[1].get("organPureBuyQuant"))
            o2 = parse_kor_quant(lst[2].get("organPureBuyQuant"))

            if frgn0 > 0 and f1 > 0 and f2 > 0 and orgn0 > 0 and o1 > 0 and o2 > 0:
                streak3d = True
                streak_type = "🔥외인·기관 3일연속 쌍끌이!"
            elif frgn0 > 0 and f1 > 0 and f2 > 0:
                streak3d = True
                streak_type = "🔥외국인 3일연속 매집!"
            elif orgn0 > 0 and o1 > 0 and o2 > 0:
                streak3d = True
                streak_type = "🔥기관(투신·사모) 3일연속 매집!"
            elif smart_net > 0 and (f1 + o1) > 0 and (f2 + o2) > 0:
                streak3d = True
                streak_type = "✅메이저 합산 3일연속 순매수"

        badge_text = "⚪ 개인주도(메이저매도)"
        if streak3d:
            badge_text = streak_type
        elif is_twin_buy:
            badge_text = "🟢 외인·기관 양매수 유입"
        elif frgn0 > 0 and smart_net > 0:
            badge_text = "🟢 외국인 순매수 주도"
        elif orgn0 > 0 and smart_net > 0:
            badge_text = "🟢 기관 순매수 주도"
        elif frgn0 > 0 or orgn0 > 0:
            badge_text = "🟡 외인·기관 수급 공방"

        summary_text = f"외인 {fmt_quant_kor(frgn0)} · 기관 {fmt_quant_kor(orgn0)} · 개인 {fmt_quant_kor(indv0)}"
        return {
            "frgn": frgn0, "orgn": orgn0, "indv": indv0,
            "smart_net": smart_net, "is_smart_inflow": is_smart_inflow, "is_twin_buy": is_twin_buy,
            "streak3d": streak3d, "streak_type": streak_type,
            "summary_text": summary_text, "badge_text": badge_text
        }
    except Exception:
        return default_res

# =========================================================================
# [V9.5 신규 3] 2배 레버리지 ETF 10거래일 음의 복리(변동성 잠식 / 괴리율) 계산기
# =========================================================================

def calc_leverage_decay(lev_ret_10d, base_ret_10d, base_name):
    expected_2x = base_ret_10d * 2.0
    decay_gap = lev_ret_10d - expected_2x
    status = "🟢 정상 추적"
    warn_level = "NORMAL"
    if decay_gap <= -2.0:
        status = "⚠️ 음의복리 잠식주의 (단기스윙 권장)"
        warn_level = "WARN"
    elif decay_gap >= 1.0:
        status = "🔥 양의복리 추세 탄력"
        warn_level = "GOOD"
    summary = f"10일 누적: ETF {lev_ret_10d:+.1f}% vs {base_name}×2 ({expected_2x:+.1f}%) ➔ 괴리 {decay_gap:+.2f}%p [{status}]"
    return {
        "levRet10d": lev_ret_10d,
        "baseRet10d": base_ret_10d,
        "expected2x": expected_2x,
        "decayGap": decay_gap,
        "status": status,
        "warnLevel": warn_level,
        "summary": summary
    }

# =========================================================================
# 바이오 임상(ClinicalTrials.gov) & 공시 호악재 판독 엔진
# =========================================================================

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
                "action": "거래량(1.8배↑) 동반 시 스윙금고 이식 검토"
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
                title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
                clean_t = raw_t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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

    or_ready = (or1_m["score"] >= 3 or or1_m["vol_ratio"] >= 1.8 or or1_m.get("streak3d", False))
    ab_ready = (ab_m["score"] >= 3 or ab_m["vol_ratio"] >= 1.8 or ab_m.get("streak3d", False))
    or_verdict = "🔥 캐터펄트 이식 적기! (수급/타점 충족)" if or_ready else f"⏸ 대기 ({or1_m.get('flow_badge', '수급대기')})"
    ab_verdict = "🔥 캐터펄트 이식 적기! (수급/타점 충족)" if ab_ready else f"⏸ 대기 ({ab_m.get('flow_badge', '수급대기')})"
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
                <div><b>🚀 스마트머니 3일 매집 &amp; 캐터펄트 이식 신호등</b></div>
                <div class="pos" id="bio-vault-amt">금고 {vault_man:+,}만 원</div>
            </div>
            <div class="sub" style="margin-bottom:8px;">
                금고 수익 전액 이식 시: <b style="color:#c084fc;">오름 +<span id="bio-or-buyable">{or_buyable:,}</span>주</b> 또는 <b style="color:#4ade80;">앱클론 +<span id="bio-ab-buyable">{ab_buyable:,}</span>주</b> 무상 증식 가능
            </div>
            <div class="cata-grid">
                <div class="cata-cell">
                    <div class="sub">🧬 오름테라퓨틱 (수급·타점)</div>
                    <div style="margin:3px 0;"><b id="bio-or-blocks">{or1_m['blocks']}</b> <span class="sub">({or1_m['score']}/4) | 거래량 <b id="bio-or-vol">{or1_m['vol_ratio']:.1f}배</b></span></div>
                    <div class="sub" id="bio-or-flow" style="font-size:0.68rem;margin-bottom:2px;">{or1_m.get('flow_summary', '')}</div>
                    <div class="{or_v_cls}" id="bio-or-verdict" style="font-size:0.72rem;">{or_verdict}</div>
                </div>
                <div class="cata-cell">
                    <div class="sub">🧬 앱클론 (수급·타점)</div>
                    <div style="margin:3px 0;"><b id="bio-ab-blocks">{ab_m['blocks']}</b> <span class="sub">({ab_m['score']}/4) | 거래량 <b id="bio-ab-vol">{ab_m['vol_ratio']:.1f}배</b></span></div>
                    <div class="sub" id="bio-ab-flow" style="font-size:0.68rem;margin-bottom:2px;">{ab_m.get('flow_summary', '')}</div>
                    <div class="{ab_v_cls}" id="bio-ab-verdict" style="font-size:0.72rem;">{ab_verdict}</div>
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

def fetch_peer_with_cmf(sym, name, is_kr, fallback):
    curr = float(fallback)
    pct = 0.0
    ret10d = 0.0
    cmf20 = 0.0
    try:
        t = yf.Ticker(sym)
        hist = t.history(period="1mo", timeout=8)
        if not hist.empty:
            df = hist.dropna(subset=['Close']).copy()
            if len(df) >= 1:
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
                if len(df) >= 11:
                    c10 = float(df['Close'].iloc[-11])
                    ret10d = ((curr - c10) / c10) * 100.0 if c10 > 0 else pct
                else:
                    ret10d = pct

                # 20일 CMF (Chaikin Money Flow) 계산
                sub = df.tail(20)
                mfv_sum = 0.0
                vol_sum = 0.0
                for _, row in sub.iterrows():
                    hi = float(row.get('High', row['Close']))
                    lo = float(row.get('Low', row['Close']))
                    cl = float(row['Close'])
                    vl = float(row.get('Volume', 0.0))
                    hl = hi - lo
                    mfm = (((cl - lo) - (hi - cl)) / hl) if hl > 0 else 0.0
                    mfv_sum += mfm * vl
                    vol_sum += vl
                cmf20 = (mfv_sum / vol_sum) if vol_sum > 0 else 0.0
    except Exception:
        pass
    p_str = f"₩{curr:,.0f}" if is_kr else f"${curr:,.2f}"
    return {"name": name, "symbol": sym.split(".")[0], "price": curr, "price_str": p_str, "pct": pct, "ret10d": ret10d, "cmf20": cmf20}

def fetch_semi_peers():
    return [fetch_peer_with_cmf(p["symbol"], p["name"], p["is_kr"], p["fallback"]) for p in SEMI_PEERS]

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

def get_quad_verified_metrics(tickers, rsi_cut=35.0, disp_cut=-9.0, is_core_cash_target=True, extra_supply=None):
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

            spark_prices = [float(x) for x in closes.tail(20).values]

            pct = ((curr - prev) / prev) * 100 if prev > 0 else 0.0
            ext_pct = ((curr - reg_curr) / reg_curr) * 100 if reg_curr > 0 else 0.0
            if len(closes) >= 11:
                c10 = float(closes.iloc[-11])
                ret10d = ((curr - c10) / c10) * 100.0 if c10 > 0 else pct
            else:
                ret10d = pct

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

            # [V9.5 핵심] 4번 스위치에 외인·기관 매매동향 및 마이크론(MU) 기관 자금흐름(CMF) 통합
            c4_volume = (vol_ratio >= 1.2 and bullish_rebound) or (bullish_rebound and rsi < (rsi_cut - 6.0))
            flow_summary = f"거래량 {vol_ratio:.1f}배"
            flow_badge = "🟢 거래량유입" if vol_ratio >= 1.2 else "⚪ 수급보통"
            streak3d = False
            decay_info = None

            if extra_supply:
                if "inv_trend" in extra_supply and extra_supply["inv_trend"]:
                    tr = extra_supply["inv_trend"]
                    flow_summary = tr["summary_text"]
                    flow_badge = tr["badge_text"]
                    streak3d = tr["streak3d"]
                    c4_volume = streak3d or (tr["is_smart_inflow"] and (bullish_rebound or vol_ratio >= 1.0)) or (vol_ratio >= 1.6 and bullish_rebound)
                if "mu_cmf20" in extra_supply and extra_supply["mu_cmf20"] is not None:
                    cmf = float(extra_supply["mu_cmf20"])
                    cmf_tag = "🟢MU기관매집 강함" if cmf >= 0.08 else ("🟢MU자금유입 우위" if cmf >= 0 else "🔴MU자금이탈 주의")
                    flow_summary = f"모체 MU 기관자금(CMF): {cmf:+.2f}"
                    flow_badge = cmf_tag
                    c4_volume = (cmf >= 0 and bullish_rebound) or (vol_ratio >= 1.2 and bullish_rebound)
                if "base_ret10d" in extra_supply and extra_supply["base_ret10d"] is not None:
                    decay_info = calc_leverage_decay(ret10d, float(extra_supply["base_ret10d"]), extra_supply.get("base_name", "기초지수"))

            score = int(c1_oversold) + int(c2_support) + int(c3_momentum) + int(c4_volume)
            blocks = make_score_blocks(score, rsi)
            chk_icons = f"{'🟢' if c1_oversold else '⚫'}과매도 {'🟢' if c2_support else '⚫'}지지 {'🟢' if c3_momentum else '⚫'}MACD {'🟢' if c4_volume else '⚫'}실수급"

            is_buy_alert = False
            if c1_oversold and score == 4:
                sig, short_st = f"🔥 4중검증 완벽타점 ({score}/4)", "진바닥(4/4)"
                cash = "잔여 시드 적극 투입 검토" if is_core_cash_target else "진바닥 강세 전환 (캐터펄트 이식)"
                is_buy_alert = True
            elif (c1_oversold and score == 3 and (c3_momentum or c4_volume)) or (streak3d and score >= 2):
                sig = f"🔥 3일연속 매집타점 ({score}/4)" if streak3d else f"✅ 1차 검증타점 ({score}/4)"
                short_st = f"3일매집({score}/4)" if streak3d else "타점진입(3/4)"
                cash = "신규 트랑셰 분할 투입" if is_core_cash_target else "메이저 매집 확인 (스윙금고 이식)"
                is_buy_alert = True
            elif c1_oversold and score <= 2:
                sig, short_st, cash = f"⚠️ 하락칼날·수급부재 ({score}/4)", f"칼날주의({score}/4)", "외인·기관 수급 유입 전까지 추매 대기"
            elif rsi > 72:
                sig, short_st, cash = f"🚨 단기 과열 ({score}/4)", f"과열주의({score}/4)", "신규 트랑셰 익절 & 역물타기"
            else:
                sig, short_st, cash = f"⏸ 중립·관망 ({score}/4)", f"관망중({score}/4)", "스윙 트랑셰 감시 · 현금 대기"

            return {
                "curr": curr, "reg_curr": reg_curr, "pct": pct, "ext_pct": ext_pct, "ret10d": ret10d,
                "session": session_tag, "rsi": rsi, "ma20": ma20, "disp": disp20,
                "pct_b": pct_b, "macd_turn": macd_turn, "vol_ratio": vol_ratio,
                "c1": c1_oversold, "c2": c2_support, "c3": c3_momentum, "c4": c4_volume,
                "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": spark_prices,
                "score": score, "blocks": blocks, "chk": chk_icons, "sig": sig, "short_st": short_st, "cash": cash, "alert": is_buy_alert,
                "flow_summary": flow_summary, "flow_badge": flow_badge, "streak3d": streak3d, "decay_info": decay_info
            }
        except Exception:
            continue
    return {
        "curr": 0.0, "reg_curr": 0.0, "pct": 0.0, "ext_pct": 0.0, "ret10d": 0.0, "session": "대기",
        "rsi": 50.0, "ma20": 0.0, "disp": 0.0, "pct_b": 0.5, "macd_turn": False, "vol_ratio": 1.0,
        "c1": False, "c2": False, "c3": False, "c4": False, "rsi_cut": rsi_cut, "disp_cut": disp_cut, "spark": [],
        "score": 0, "blocks": "⬜⬜⬜⬜", "chk": "대기", "sig": "데이터 대기", "short_st": "대기(0/4)", "cash": "0원", "alert": False,
        "flow_summary": "수급 대기", "flow_badge": "⚪ 수급대기", "streak3d": False, "decay_info": None
    }

def evaluate_new_tranches(price_map, krw_rate, decay_map):
    if not NEW_TRANCHES:
        return '<div class="sub">등록된 신규 스윙 트랑셰가 없습니다.</div>', "", False, 0, 0, 0, None

    cards_html, tg_rows = [], []
    exit_alert = False
    live_cost_krw = 0
    live_eval_krw = 0
    primary_live_data = None

    for tr in NEW_TRANCHES:
        try:
            k = tr["key"]
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

            decay_obj = decay_map.get(k)
            decay_html = f'<div class="sub" style="margin-top:3px;color:#cbd5e1;">📉 <span id="tr-decay-{k.lower()}">{decay_obj["summary"]}</span></div>' if decay_obj else ""
            decay_tg = f"\n• 📉 {decay_obj['summary']}" if decay_obj else ""

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
                    {decay_html}
                </div>""")

            if is_live:
                gauge_bar = make_visual_gauge(curr_p, stop_p, target_p, 10)
                tg_rows.append(
                    f"🎯 <b>[실전 스윙] {tr['name']} ({qty:,}주)</b>\n"
                    f"<blockquote>진입 {p_fmt(entry_p)} ➔ 현재 <b>{p_fmt(curr_p)} ({ret_entry:+.2f}% / {pnl_krw//10000:+,}만)</b>\n"
                    f"🛡️{p_fmt(stop_p)} <code>{gauge_bar}</code> 🎯{p_fmt(target_p)}\n"
                    f"• 익절({p_fmt(target_p)})까지 <b>+{dist_to_target:.1f}%</b> | 스탑까지 <b>-{dist_to_stop:.1f}% 여유</b>\n"
                    f"• {blended_note}{decay_tg}</blockquote>"
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
    f_kpi_val = load_font(bold_font_path, 27)
    f_kpi_sub = load_font(reg_font_path, 13)
    f_sec = load_font(bold_font_path, 19)
    f_card_b = load_font(bold_font_path, 18)
    f_card_r = load_font(reg_font_path, 14)
    f_pill = load_font(bold_font_path, 13)

    W, H = 900, 1340
    img = Image.new("RGB", (W, H), "#070b14")
    draw = ImageDraw.Draw(img)

    draw.text((28, 20), "마스터 비주얼 관제탑 V9.5 (스마트머니·괴리율·바이오)", font=f_title, fill="#38bdf8")
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
    ty1 = ty0 + 154
    draw.rounded_rectangle([28, ty0, W - 28, ty1], radius=14, fill="#142038", outline="#2dd4bf", width=2)
    if live_tr:
        tr_col = "#4ade80" if live_tr["ret_entry"] >= 0 else "#f87171"
        draw.text((48, ty0 + 14), f"[실전 LIVE] {live_tr['name']} ({live_tr['qty']:,}주 · 진입 ${live_tr['entry_p']:.2f})", font=f_sec, fill="#2dd4bf")
        draw.text((W - 48, ty0 + 14), f"현재 ${live_tr['curr_p']:.2f} ({live_tr['ret_entry']:+.2f}%)", font=f_sec, fill=tr_col, anchor="ra")

        bx0, bx1 = 56, W - 56
        by = ty0 + 76
        draw.rounded_rectangle([bx0, by - 6, bx1, by + 6], radius=6, fill="#0f172a", outline="#334155", width=1)
        fill_x = int(bx0 + (bx1 - bx0) * (live_tr["pos_pct"] / 100.0))
        if fill_x > bx0:
            draw.rounded_rectangle([bx0, by - 6, fill_x, by + 6], radius=6, fill="#38bdf8")

        half_ratio = max(0.0, min(1.0, (live_tr["half_p"] - live_tr["stop_p"]) / (live_tr["target_p"] - live_tr["stop_p"])))
        hx = int(bx0 + (bx1 - bx0) * half_ratio)
        draw.line([(hx, by - 12), (hx, by + 12)], fill="#fbbf24", width=3)
        draw.text((hx, by - 28), f"절반예약 ${live_tr['half_p']:.2f}", font=f_kpi_sub, fill="#fbbf24", anchor="ma")

        draw.ellipse([fill_x - 10, by - 10, fill_x + 10, by + 10], fill="#ffffff", outline="#38bdf8", width=4)

        draw.text((bx0, by - 28), f"스탑 ${live_tr['stop_p']:.2f} (-{live_tr['dist_stop']:.1f}% 여유)", font=f_card_r, fill="#f87171")
        draw.text((bx1, by - 28), f"목표 ${live_tr['target_p']:.2f} (+{live_tr['dist_target']:.1f}% 남음)", font=f_card_r, fill="#4ade80", anchor="ra")

        foot_txt = f"단독손익: {live_tr['pnl_str']}  |  {live_tr['blended_note']}  |  {live_tr['status_str']}"
        draw.text((48, ty0 + 114), foot_txt, font=f_card_r, fill="#e2e8f0")

    sy0 = 544
    draw.text((28, sy0), "5대 보유 종목 스마트머니 수급 & 4중 검증 스위치", font=f_sec, fill="#38bdf8")

    row_y = sy0 + 30
    for st in stocks_info:
        ry0, ry1 = row_y, row_y + 114
        draw.rounded_rectangle([28, ry0, W - 28, ry1], radius=12, fill="#111827", outline="#1f2937", width=2)
        draw.rounded_rectangle([28, ry0, 36, ry1], radius=4, fill=st["color"])

        draw.text((50, ry0 + 12), f"{st['name']}  [{st['price_str']}]", font=f_card_b, fill="#f8fafc")
        r_col = "#4ade80" if st["my_ret"] >= 0 else "#f87171"
        draw.text((50, ry0 + 38), f"내 수익: {st['my_ret']:+.1f}% | RSI {st['m']['rsi']:.1f} | 이격 {st['m']['disp']:+.1f}%", font=f_card_r, fill=r_col)
        draw.text((50, ry0 + 58), f"수급: {st['m'].get('flow_summary', '')} ({st['m'].get('flow_badge', '')})", font=f_kpi_sub, fill="#cbd5e1")

        pills = [
            ("과매도", st["m"]["c1"]),
            ("지지선", st["m"]["c2"]),
            ("MACD반등", st["m"]["c3"]),
            ("실수급", st["m"]["c4"])
        ]
        px = 50
        py = ry0 + 80
        for p_lbl, is_on in pills:
            bg = "#14532d" if is_on else "#0f172a"
            bd = "#4ade80" if is_on else "#334155"
            fg = "#4ade80" if is_on else "#64748b"
            prefix = "ON " if is_on else "OFF "
            draw.rounded_rectangle([px, py, px + 104, py + 24], radius=6, fill=bg, outline=bd, width=1)
            draw.text((px + 52, py + 4), prefix + p_lbl, font=f_pill, fill=fg, anchor="ma")
            px += 112

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
        draw.text((W - 48, ry0 + 78), st["m"]["cash"], font=f_kpi_sub, fill="#fbbf24", anchor="ra")

        row_y += 124

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

def calc_kr_holding(key, param_key, is_core=False, cached_m=None, extra_supply=None):
    item = PORTFOLIO[key]
    if cached_m is not None:
        m = dict(cached_m)
    else:
        p_cfg = CUSTOM_PARAMS.get(param_key, {"rsi_cut": 35.0, "disp_cut": -8.0})
        m = get_quad_verified_metrics(item["tickers"], rsi_cut=p_cfg["rsi_cut"], disp_cut=p_cfg["disp_cut"], is_core_cash_target=is_core, extra_supply=extra_supply)
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
            title = (entry.title.rsplit(' - ', 1)[0] if ' - ' in entry.title else entry.title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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

    decay_obj = m.get("decay_info")
    decay_row_html = f'<div class="flow-row" id="sig-decay-wrap-{key_id}">📉 <span id="sig-decay-{key_id}">{decay_obj["summary"]}</span></div>' if decay_obj else ""

    return f"""
        <div class="sig-box" style="border-left-color:{border_color};">
            <div class="sig-hd">
                <div>
                    <b>{title}</b> <span id="sig-price-{key_id}">{price_badge}</span><br>
                    <span class="sub">20일 추세 &amp; 내 수익:</span> <span id="sig-ret-{key_id}">{my_ret_str}</span>
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
            <div class="flow-row">
                👥 수급: <b id="sig-flow-{key_id}">{m.get('flow_summary', '집계중')}</b> <span class="badge" id="sig-fbadge-{key_id}">{m.get('flow_badge', '')}</span>
            </div>
            {decay_row_html}
            <div class="pill-row">
                <span class="pill {p1_cls}" id="sig-p1-{key_id}">{'🟢' if m['c1'] else '⚫'} 과매도</span>
                <span class="pill {p2_cls}" id="sig-p2-{key_id}">{'🟢' if m['c2'] else '⚫'} 지지선</span>
                <span class="pill {p3_cls}" id="sig-p3-{key_id}">{'🟢' if m['c3'] else '⚫'} MACD↑</span>
                <span class="pill {p4_cls}" id="sig-p4-{key_id}">{'🟢' if m['c4'] else '⚫'} 실수급</span>
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
    mu_peer = semi_peers[1] if len(semi_peers) > 1 else {"cmf20": 0.0, "ret10d": 0.0}
    kq_base_peer = fetch_peer_with_cmf("229200.KS", "코스닥150", True, 11500)

    # 국내 4종목 네이버 금융 매매동향(외인·기관·개인 및 3일 연속 매집) 수집
    kq_trend = fetch_kr_investor_trend("233740")
    yg_trend = fetch_kr_investor_trend("019210")
    or_trend = fetch_kr_investor_trend("475830")
    ab_trend = fetch_kr_investor_trend("174900")

    ram_param = CUSTOM_PARAMS["RAM"]
    ram = get_quad_verified_metrics(
        "RAM", rsi_cut=ram_param["rsi_cut"], disp_cut=ram_param["disp_cut"], is_core_cash_target=True,
        extra_supply={"mu_cmf20": mu_peer["cmf20"], "base_ret10d": mu_peer["ret10d"], "base_name": "MU"}
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

    kq = calc_kr_holding("KODEX_LEV", "KODEX_LEV", is_core=True, extra_supply={"inv_trend": kq_trend, "base_ret10d": kq_base_peer["ret10d"], "base_name": "코스닥150"})
    yg = calc_kr_holding("YG1", "YG1", is_core=False, extra_supply={"inv_trend": yg_trend})
    or1 = calc_kr_holding("ORUM1", "ORUM", is_core=False, extra_supply={"inv_trend": or_trend})
    or2 = calc_kr_holding("ORUM2", "ORUM", is_core=False, cached_m=or1)
    ab = calc_kr_holding("ABCLON", "ABCLON", is_core=False, extra_supply={"inv_trend": ab_trend})

    price_map = {
        "RAM": ram_p,
        "233740.KS": kq["curr"],
        "019210.KQ": yg["curr"],
        "475830.KQ": or1["curr"],
        "174900.KQ": ab["curr"]
    }
    decay_map = {
        "RAM": ram.get("decay_info"),
        "KODEX_LEV": kq.get("decay_info")
    }
    tranche_html, tranche_tg, tranche_alert, live_tr_cost, live_tr_eval, live_tr_pnl, primary_live_data = evaluate_new_tranches(price_map, krw_p, decay_map)

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
    <title>마스터 관제탑 V9.5 Smart-Money</title>
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
        .flow-row {{ background: #0b1120; border: 1px solid #1e293b; border-radius: 6px; padding: 5px 8px; margin-bottom: 6px; font-size: 0.72rem; color: #cbd5e1; }}
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
        .pill-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; margin-bottom: 8px; text-align: center; }}
        .pill {{ padding: 4px 2px; border-radius: 5px; font-size: 0.70rem; font-weight: 700; }}
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
        <div class="top-title">🛡️ 마스터 관제탑 V9.5 (스마트머니·괴리율·바이오)</div>
        <a href="dashboard_card.png" target="_blank" style="font-size:0.72rem;color:#2dd4bf;border:1px solid #2dd4bf;padding:3px 8px;border-radius:5px;">🖼️ 요약이미지 보기</a>
    </div>

    <div class="live-bar">
        <div class="top-sync" id="top-sync-text">스냅샷: {now_str} (₩{krw_p:,.1f})</div>
        <button class="btn-refresh" id="btn-live-refresh" onclick="fetchLiveDashboard()">🔄 실시간 시세·수급 새로고침</button>
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
            <div class="kpi-sub" id="kpi-total-pnl-sub">주식 수익률 {stock_ret_pct:+.2f}%</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">가용 현금 / 스윙 복리금고</div>
            <div class="kpi-val" id="kpi-cash-vault"><span style="color:#4ade80;">{rem_cash_eval//10000:,}만</span> / <span style="color:#38bdf8;">{swing_vault_krw//10000:+,}만</span></div>
            <div class="kpi-sub">텔레그램 /매수·/매도 자동반영</div>
        </div>
        <div class="kpi-box">
            <div class="kpi-lbl">2026 예상 해외주식 양도세</div>
            <div class="kpi-val" id="kpi-tax-val" style="color:#fbbf24;">{est_tax_krw//10000:,}만 원</div>
            <div class="kpi-sub" id="kpi-tax-sub">절세 감면액 +{saved_tax_krw//10000:,}만 원</div>
        </div>
    </div>

    <div class="semi-hd">
        <span>⚡ 글로벌 반도체 · HBM 4대 풍향계 (RAM 선행지표)</span>
        <span id="live-status-badge" style="color:#4ade80;">● V9.5 LIVE 연동</span>
    </div>
    <div class="semi-grid">
        {semi_bar_html}
    </div>

    <div class="q-grid">
        {quick_bar_html}
    </div>

    <div class="card">
        <h2>🛡️ 신규 스윙 트랑셰 &amp; 음의복리(괴리율) 트래커</h2>
        {tranche_html}
    </div>

    <div class="card">
        <h2>📅 핵심 일정 D-Day 트래커</h2>
        {dday_html}
    </div>

    <div class="card">
        <h2>🎯 5대 종목 스마트머니 수급 &amp; 4중 검증 스위치</h2>
        {sig_cards_html}
    </div>

    <div class="card">
        <h2>🧬 바이오 0초 레이더 (3일 매집 · 임상 DB · 공시 판독)</h2>
        {bio_radar_html}
    </div>

    <div class="card">
        <h2>💼 보유 종목 상세 평가 &amp; 포트폴리오 비중</h2>
        <div style="width:210px;margin:0 auto 12px auto;"><canvas id="pfChart"></canvas></div>
        <div class="row"><span><b>RAM 합산</b> (<span id="hold-ram-qty">{ram_total_qty:,}</span>주 · 평단 $<span id="hold-ram-avg">{ram_total_avg:.4f}</span>) <span class="badge" id="hold-ram-sess">{ram['session']}</span><br><span class="sub" id="hold-ram-sub">현재 ${ram_p:.2f} | {ram.get('flow_summary', '')}</span></span><span class="{ram_color}" id="hold-ram-val" style="text-align:right;">{ram_total_ret:+.2f}% ({(ram_pnl_krw + live_tr_pnl)//10000:+,}만)<br>${ram_p * ram_total_qty:,.0f} ({ram_combined_eval_krw//10000:,}만)</span></div>
        <div class="row"><span><b>코스닥150레버리지</b> (<span id="hold-kq-qty">{kq['qty'] if 'qty' in kq else 3354:,}</span>주)<br><span class="sub" id="hold-kq-sub">현재 ₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%) | {kq.get('flow_summary', '')}</span></span><span class="{kq_color}" id="hold-kq-val" style="text-align:right;">{kq['ret_pct']:+.2f}% ({kq['pnl_krw']//10000:+,}만)<br>{kq['eval_krw']:,}원</span></div>
        <div class="row"><span><b>와이지-원</b> (<span id="hold-yg-qty">{PORTFOLIO['YG1']['qty']:,}</span>주 · 평단 12,910원)<br><span class="sub" id="hold-yg-sub">현재 ₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%) | {yg.get('flow_summary', '')}</span></span><span class="{yg_color}" id="hold-yg-val" style="text-align:right;">{yg['ret_pct']:+.2f}% ({yg['pnl_krw']//10000:+,}만)<br>{yg['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌1)</b> (1,097주 · 평단 107,113원)<br><span class="sub" id="hold-or1-sub">현재 ₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%) | {or1.get('flow_summary', '')}</span></span><span class="{or1_color}" id="hold-or1-val" style="text-align:right;">{or1['ret_pct']:+.2f}% ({or1['pnl_krw']//10000:+,}만)<br>{or1['eval_krw']:,}원</span></div>
        <div class="row"><span><b>오름테라퓨틱(계좌2)</b> (256주 · 평단 96,650원)<br><span class="sub" id="hold-or2-sub">현재 ₩{or2['curr']:,.0f} ({or2['pct']:+.2f}%)</span></span><span class="{or2_color}" id="hold-or2-val" style="text-align:right;">{or2['ret_pct']:+.2f}% ({or2['pnl_krw']//10000:+,}만)<br>{or2['eval_krw']:,}원</span></div>
        <div class="row"><span><b>앱클론</b> (256주 · 평단 52,735원)<br><span class="sub" id="hold-ab-sub">현재 ₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%) | {ab.get('flow_summary', '')}</span></span><span class="{ab_color}" id="hold-ab-val" style="text-align:right;">{ab['ret_pct']:+.2f}% ({ab['pnl_krw']//10000:+,}만)<br>{ab['eval_krw']:,}원</span></div>
    </div>

    <div class="card"><h2>📰 최근 48시간 최신 속보</h2>{news_html}</div>

    <script>
        const WORKER_API_URL = "{worker_api_url}";

        const pfChart = new Chart(document.getElementById('pfChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['RAM(반도체)', '바이오(오름·앱클론)', '코스닥150레버리지', '잔여현금', '와이지-원'],
                datasets: [{{
                    data: [{ram_combined_eval_krw//10000}, {bio_eval_krw//10000}, {kq['eval_krw']//10000}, {rem_cash_eval//10000}, {yg['eval_krw']//10000}],
                    backgroundColor: ['#38bdf8', '#c084fc', '#f87171', '#4ade80', '#fbbf24'],
                    borderWidth: 0
                }}]
            }},
            options: {{ plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#cbd5e1', font: {{ size: 11 }} }} }} }}, cutout: '62%' }}
        }});

        function fmtMan(v) {{
            const m = Math.round(v / 10000);
            return (m >= 0 ? "+" : "") + m.toLocaleString() + "만";
        }}

        function updateSigCardDOM(keyId, m, priceHtml, retHtml) {{
            const setEl = (id, html) => {{ const e = document.getElementById(id); if (e) e.innerHTML = html; }};
            setEl("q-score-" + keyId, m.blocks);
            setEl("q-st-" + keyId, m.shortSt);
            const qt = document.getElementById("q-tile-" + keyId);
            if (qt) qt.className = "q-tile " + (m.alert ? "q-buy" : (m.rsi > 72 ? "q-hot" : "q-wait"));

            setEl("sig-price-" + keyId, priceHtml);
            setEl("sig-ret-" + keyId, retHtml);
            setEl("sig-rsi-" + keyId, m.rsi.toFixed(1));
            setEl("sig-disp-" + keyId, (m.disp >= 0 ? "+" : "") + m.disp.toFixed(1) + "%");
            setEl("sig-pctb-" + keyId, m.pctB.toFixed(2));
            setEl("sig-vol-" + keyId, m.volRatio.toFixed(1) + "배");

            if (m.flowSummary) setEl("sig-flow-" + keyId, m.flowSummary);
            if (m.flowBadge) setEl("sig-fbadge-" + keyId, m.flowBadge);
            if (m.decayInfo && m.decayInfo.summary) {{
                setEl("sig-decay-" + keyId, m.decayInfo.summary);
                setEl("tr-decay-" + (keyId === "kq" ? "kodex_lev" : keyId), m.decayInfo.summary);
            }}

            const bar = document.getElementById("sig-bar-" + keyId);
            if (bar) {{
                bar.style.width = Math.round((m.score / 4) * 100) + "%";
                bar.style.background = m.alert ? "#4ade80" : (m.rsi > 72 ? "#f87171" : "#38bdf8");
            }}

            const setPill = (pIdx, isOn, lbl) => {{
                const p = document.getElementById("sig-p" + pIdx + "-" + keyId);
                if (p) {{
                    p.className = "pill " + (isOn ? "pill-on" : "pill-off");
                    p.textContent = (isOn ? "🟢 " : "⚫ ") + lbl;
                }}
            }};
            setPill(1, m.c1, "과매도");
            setPill(2, m.c2, "지지선");
            setPill(3, m.c3, "MACD↑");
            setPill(4, m.c4, "실수급");

            const stxt = document.getElementById("sig-txt-" + keyId);
            if (stxt) {{
                stxt.className = m.alert ? "pos" : (m.rsi > 72 ? "neg" : "");
                stxt.textContent = m.sig;
            }}
            setEl("sig-cash-" + keyId, "➔ " + m.cash);
        }}

        async function fetchLiveClinicalTrials() {{
            try {{
                const url = "https://clinicaltrials.gov/api/v2/studies?query.term=ORM-5029+OR+ORM-6151+OR+BMS-986497+OR+AbClon+OR+HLX22+OR+AT101&pageSize=5&sort=LastUpdatePostDate:desc";
                const res = await fetch(url);
                if (!res.ok) return;
                const data = await res.json();
                const studies = data.studies || [];
                if (!studies.length) return;

                const htmlRows = studies.map(st => {{
                    const p = st.protocolSection || {{}};
                    const idMod = p.identificationModule || {{}};
                    const stMod = p.statusModule || {{}};
                    const spMod = p.sponsorCollaboratorsModule || {{}};
                    const nctId = idMod.nctId || "NCT";
                    const rawTitle = idMod.briefTitle || "Clinical Study";
                    const title = rawTitle.length > 52 ? rawTitle.slice(0, 52) + "..." : rawTitle;
                    const status = stMod.overallStatus || "UNKNOWN";
                    const lastUpd = (stMod.lastUpdatePostDateStruct && stMod.lastUpdatePostDateStruct.date) ? stMod.lastUpdatePostDateStruct.date : "확인중";
                    const sponsor = (spMod.leadSponsor && spMod.leadSponsor.name) ? spMod.leadSponsor.name : "";
                    const fullTxt = (rawTitle + " " + sponsor).toUpperCase();

                    let drugTag = "바이오 임상";
                    if (fullTxt.includes("ORM-6151") || fullTxt.includes("986497")) drugTag = "오름/BMS ORM-6151";
                    else if (fullTxt.includes("ORM-5029") || fullTxt.includes("ORUM")) drugTag = "오름 ORM-5029";
                    else if (fullTxt.includes("HLX22") || fullTxt.includes("AC101")) drugTag = "앱클론/헨리우스 HLX22";
                    else if (fullTxt.includes("AT101") || fullTxt.includes("ABCLON")) drugTag = "앱클론 AT101";

                    let stCls = "bio-neu", stIcon = "🟡";
                    if (status === "RECRUITING" || status === "COMPLETED") {{ stCls = "bio-pos"; stIcon = "🟢"; }}
                    else if (status === "SUSPENDED" || status === "TERMINATED" || status === "WITHDRAWN") {{ stCls = "bio-neg"; stIcon = "🔴"; }}

                    return `<div class="bio-item"><div class="bio-hd"><span class="bio-drug">[${{drugTag}}]</span><span class="bio-tag ${{stCls}}">${{stIcon}} ${{status}} (${{lastUpd}})</span></div><a href="https://clinicaltrials.gov/study/${{nctId}}" target="_blank"><b>${{nctId}}</b> · ${{title}}</a></div>`;
                }}).join("");

                const box = document.getElementById("bio-trials-list");
                if (box) box.innerHTML = htmlRows;
                const syncEl = document.getElementById("bio-ct-sync");
                if (syncEl) syncEl.textContent = "🟢 미국 임상 DB 실시간 동기화됨";
            }} catch (e) {{}}
        }}

        async function fetchLiveDashboard() {{
            fetchLiveClinicalTrials();
            if (!WORKER_API_URL) return;
            const btn = document.getElementById("btn-live-refresh");
            const badge = document.getElementById("live-status-badge");
            if (btn) btn.textContent = "⏳ 실시간 수신 중...";
            if (badge) badge.textContent = "⏳ 시세·수급·괴리율 동기화 중...";

            try {{
                const res = await fetch(WORKER_API_URL + "?mode=live&t=" + Date.now());
                const d = await res.json();

                document.getElementById("top-sync-text").textContent = "🟢 실시간: " + d.nowStr + " (₩" + d.krwRate.toFixed(1) + ")";
                document.getElementById("kpi-total-eval").textContent = Math.round(d.kpi.totalEvalKrw / 10000).toLocaleString() + "만 원";
                document.getElementById("kpi-total-sub").textContent = "1차 전환선까지 " + Math.max(0, 15131 - Math.round(d.kpi.totalEvalKrw / 10000)).toLocaleString() + "만 원";

                const pnlEl = document.getElementById("kpi-total-pnl");
                pnlEl.textContent = fmtMan(d.kpi.totalPnlKrw) + " 원";
                pnlEl.className = "kpi-val " + (d.kpi.totalPnlKrw >= 0 ? "pos" : "neg");
                document.getElementById("kpi-total-pnl-sub").textContent = "보유주식 수익률 " + (d.kpi.stockRetPct >= 0 ? "+" : "") + d.kpi.stockRetPct.toFixed(2) + "%";

                document.getElementById("kpi-cash-vault").innerHTML = `<span style="color:#4ade80;">${{Math.round(d.kpi.remCashKrw / 10000).toLocaleString()}}만</span> / <span style="color:#38bdf8;">${{fmtMan(d.kpi.swingVaultKrw)}}</span>`;
                document.getElementById("kpi-tax-val").textContent = Math.round(d.taxInfo.estTax / 10000).toLocaleString() + "만 원";
                document.getElementById("kpi-tax-sub").textContent = "절세 감면액 +" + Math.round(d.taxInfo.savedTax / 10000).toLocaleString() + "만 원";

                d.semiPeers.forEach((sp, idx) => {{
                    const pEl = document.getElementById("semi-pct-" + idx);
                    const vEl = document.getElementById("semi-val-" + idx);
                    if (pEl) {{
                        pEl.textContent = (sp.pct >= 0 ? "+" : "") + sp.pct.toFixed(2) + "%";
                        pEl.className = sp.pct >= 0 ? "pos" : "neg";
                    }}
                    if (vEl) vEl.textContent = sp.pStr;
                }});

                const tr = d.tranche;
                if (tr) {{
                    const qEl = document.getElementById("tr-live-qty");
                    if (qEl) qEl.textContent = tr.qty.toLocaleString();
                    const trRet = document.getElementById("tr-live-ret");
                    if (trRet) {{
                        trRet.textContent = (tr.retPct >= 0 ? "+" : "") + tr.retPct.toFixed(2) + "%";
                        trRet.className = tr.retPct >= 0 ? "pos" : "neg";
                    }}
                    const setTxt = (id, t) => {{ const e = document.getElementById(id); if (e) e.textContent = t; }};
                    setTxt("tr-live-stop", "🛡️스탑 $" + tr.stopP.toFixed(2));
                    setTxt("tr-live-curr", "현재 $" + tr.currP.toFixed(2));
                    setTxt("tr-live-target", "🎯목표 $" + tr.targetP.toFixed(2));
                    const fEl = document.getElementById("tr-live-fill");
                    const dEl = document.getElementById("tr-live-dot");
                    if (fEl) fEl.style.width = tr.posPct + "%";
                    if (dEl) dEl.style.left = tr.posPct + "%";
                    setTxt("tr-live-dist-stop", "스탑까지 -" + tr.distStop.toFixed(1) + "% 여유");
                    setTxt("tr-live-dist-target", "익절까지 +" + tr.distTarget.toFixed(1) + "% 남음");
                    const trPnl = document.getElementById("tr-live-pnl");
                    if (trPnl) {{
                        trPnl.textContent = (tr.pnlUsd >= 0 ? "+" : "") + tr.pnlUsd.toFixed(1) + "달러 (" + fmtMan(tr.pnlKrw) + " 원)";
                        trPnl.className = tr.retPct >= 0 ? "pos" : "neg";
                    }}
                    setTxt("tr-live-status", tr.status);
                }}

                const s = d.stocks;
                updateSigCardDOM("ram", s.ram, `<span class="badge">${{s.ram.session}}</span> <span class="sub">$${{s.ram.price.toFixed(2)}} (${{(s.ram.pct>=0?'+':'') + s.ram.pct.toFixed(2)}}%)</span>`, `<span class="${{s.ram.totalRet>=0?'pos':'neg'}}">${{(s.ram.totalRet>=0?'+':'') + s.ram.totalRet.toFixed(1)}}% (평단 $${{s.ram.totalAvg.toFixed(2)}})</span>`);
                updateSigCardDOM("kq", s.kq, `<span class="sub">₩${{Math.round(s.kq.price).toLocaleString()}} (${{(s.kq.pct>=0?'+':'') + s.kq.pct.toFixed(2)}}%)</span>`, `<span class="${{s.kq.ret>=0?'pos':'neg'}}">${{s.kq.ret.toFixed(1)}}%</span>`);
                updateSigCardDOM("yg", s.yg, `<span class="sub">₩${{Math.round(s.yg.price).toLocaleString()}} (${{(s.yg.pct>=0?'+':'') + s.yg.pct.toFixed(2)}}%)</span>`, `<span class="${{s.yg.ret>=0?'pos':'neg'}}">${{s.yg.ret.toFixed(1)}}%</span>`);
                updateSigCardDOM("or1", s.or1, `<span class="sub">₩${{Math.round(s.or1.price).toLocaleString()}} (${{(s.or1.pct>=0?'+':'') + s.or1.pct.toFixed(2)}}%)</span>`, `<span class="${{s.or1.ret>=0?'pos':'neg'}}">${{s.or1.ret.toFixed(1)}}%</span>`);
                updateSigCardDOM("ab", s.ab, `<span class="sub">₩${{Math.round(s.ab.price).toLocaleString()}} (${{(s.ab.pct>=0?'+':'') + s.ab.pct.toFixed(2)}}%)</span>`, `<span class="${{s.ab.ret>=0?'pos':'neg'}}">${{s.ab.ret.toFixed(1)}}%</span>`);

                const vaultKrw = Math.max(0, d.kpi.swingVaultKrw || 0);
                const setBioTxt = (id, t) => {{ const e = document.getElementById(id); if (e) e.textContent = t; }};
                setBioTxt("bio-vault-amt", "금고 " + fmtMan(d.kpi.swingVaultKrw) + " 원");
                setBioTxt("bio-or-buyable", s.or1.price > 0 ? Math.floor(vaultKrw / s.or1.price).toLocaleString() : "0");
                setBioTxt("bio-ab-buyable", s.ab.price > 0 ? Math.floor(vaultKrw / s.ab.price).toLocaleString() : "0");
                setBioTxt("bio-or-blocks", s.or1.blocks);
                setBioTxt("bio-or-vol", s.or1.volRatio.toFixed(1) + "배");
                setBioTxt("bio-or-flow", s.or1.flowSummary || "");
                setBioTxt("bio-ab-blocks", s.ab.blocks);
                setBioTxt("bio-ab-vol", s.ab.volRatio.toFixed(1) + "배");
                setBioTxt("bio-ab-flow", s.ab.flowSummary || "");

                const orReady = (s.or1.score >= 3 || s.or1.volRatio >= 1.8 || s.or1.streak3d);
                const abReady = (s.ab.score >= 3 || s.ab.volRatio >= 1.8 || s.ab.streak3d);
                const orVEl = document.getElementById("bio-or-verdict");
                const abVEl = document.getElementById("bio-ab-verdict");
                if (orVEl) {{
                    orVEl.textContent = orReady ? "🔥 캐터펄트 이식 적기! (" + (s.or1.flowBadge || "") + ")" : "⏸ 대기 (" + (s.or1.flowBadge || "수급대기") + ")";
                    orVEl.className = orReady ? "pos" : "sub";
                }}
                if (abVEl) {{
                    abVEl.textContent = abReady ? "🔥 캐터펄트 이식 적기! (" + (s.ab.flowBadge || "") + ")" : "⏸ 대기 (" + (s.ab.flowBadge || "수급대기") + ")";
                    abVEl.className = abReady ? "pos" : "sub";
                }}

                document.getElementById("hold-ram-qty").textContent = s.ram.totalQty.toLocaleString();
                document.getElementById("hold-ram-avg").textContent = s.ram.totalAvg.toFixed(4);
                document.getElementById("hold-ram-sess").textContent = s.ram.session;
                document.getElementById("hold-ram-sub").textContent = `현재 $${{s.ram.price.toFixed(2)}} | ${{s.ram.flowSummary || ""}}`;
                document.getElementById("hold-ram-val").innerHTML = `${{(s.ram.totalRet>=0?'+':'') + s.ram.totalRet.toFixed(2)}}% (${{fmtMan(s.ram.pnlKrw)}})<br>$${{Math.round(s.ram.evalUsd).toLocaleString()}} (${{Math.round(s.ram.evalKrw/10000).toLocaleString()}}만)`;

                pfChart.data.datasets[0].data = [
                    Math.round(d.kpi.ramEvalKrw / 10000),
                    Math.round(d.kpi.bioEvalKrw / 10000),
                    Math.round(s.kq.evalAmt / 10000),
                    Math.round(d.kpi.remCashKrw / 10000),
                    Math.round(s.yg.evalAmt / 10000)
                ];
                pfChart.update();

                if (badge) badge.textContent = "🟢 V9.5 스마트머니·괴리율 LIVE";
            }} catch (e) {{
                if (badge) badge.textContent = "⚪ 스냅샷 표시 중";
            }} finally {{
                if (btn) btn.textContent = "🔄 실시간 시세·수급 새로고침";
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
        {"name": f"US RAM ({ram_total_qty:,}주)", "price_str": f"${ram_p:.2f} ({ram['pct']:+.2f}%) {ram['session']}", "my_ret": ram_total_ret, "m": ram, "color": "#38bdf8"},
        {"name": "KR 코스닥150레버", "price_str": f"₩{kq['curr']:,.0f} ({kq['pct']:+.2f}%)", "my_ret": kq["ret_pct"], "m": kq, "color": "#f87171"},
        {"name": "KR 와이지-원", "price_str": f"₩{yg['curr']:,.0f} ({yg['pct']:+.2f}%)", "my_ret": yg["ret_pct"], "m": yg, "color": "#fbbf24"},
        {"name": "KR 오름테라퓨틱", "price_str": f"₩{or1['curr']:,.0f} ({or1['pct']:+.2f}%)", "my_ret": or1["ret_pct"], "m": or1, "color": "#c084fc"},
        {"name": "KR 앱클론", "price_str": f"₩{ab['curr']:,.0f} ({ab['pct']:+.2f}%)", "my_ret": ab["ret_pct"], "m": ab, "color": "#4ade80"}
    ]
    img_path = "dashboard_card.png"
    try:
        generate_dashboard_png(
            img_path, now_str, krw_p, total_eval_krw, total_pnl_krw,
            stock_ret_pct, total_asset_ret_pct, stock_eval_krw, rem_cash_eval,
            swing_vault_krw, est_tax_krw, semi_peers, primary_live_data, stocks_info, img_events
        )
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
    any_buy_alert = any([ram["alert"], kq["alert"], yg["alert"], or1["alert"], ab["alert"], tranche_alert]) and not is_quiet_hour

    if TOKEN and CHAT_ID and (is_scheduled_slot or is_manual_run or any_buy_alert):
        header_prefix = "🚨 <b>[긴급 타점/수급 시그널 포착!]</b>\n" if (any_buy_alert and not is_scheduled_slot and not is_manual_run) else ""
        caption_msg = (
            f"{header_prefix}🛡️ <b>[V9.5 스마트머니 &amp; 괴리율 관제 브리핑]</b>\n"
            f"⏰ {now_str} | 총자산: <b>{total_eval_krw//10000:,}만</b> (현금 {rem_cash_eval//10000:,}만 | 금고 {swing_vault_krw//10000:+,}만)\n"
            f"🧾 예상양도세: <b>{est_tax_krw//10000:,}만 원</b> (절세 +{saved_tax_krw//10000:,}만)\n"
            f"⚡ 반도체 풍향계: {semi_tg_str}\n\n"
            f"{tranche_tg}\n\n"
            f"📅 <b>[임박 일정 D-Day]</b>\n{dday_tg}\n\n"
            f"📰 <b>[최근 48시간 속보]</b>\n{news_tg}"
        )

        inline_kb = {
            "inline_keyboard": [
                [{"text": "📊 V9.5 마스터 웹 관제탑 (수급·괴리율·바이오)", "url": DASHBOARD_URL}]
            ]
        }

        sent_ok = False
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as photo_file:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                        data={
                            "chat_id": CHAT_ID,
                            "caption": caption_msg[:1020],
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(inline_kb)
                        },
                        files={"photo": photo_file},
                        timeout=15
                    )
                    sent_ok = (resp.status_code == 200)
            except Exception:
                sent_ok = False

        if not sent_ok:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": caption_msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": inline_kb
                },
                timeout=10
            )

        if is_scheduled_slot and not is_manual_run:
            with open("last_sent.txt", "w", encoding="utf-8") as lf:
                lf.write(slot_key)

if __name__ == "__main__":
    main()
