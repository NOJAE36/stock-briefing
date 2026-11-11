import yfinance as yf
import pandas as pd
import numpy as np

# 백테스팅 대상 종목 및 시뮬레이션 설정
TARGETS = {
    "MU": {"symbol": "MU", "name": "마이크론(MU/RAM)"},
    "KODEX_LEV": {"symbol": "233740.KS", "name": "KODEX 코스닥150레버리지"},
    "YG1": {"symbol": "019210.KQ", "name": "와이지-원"},
    "ORUM": {"symbol": "475830.KQ", "name": "오름테라퓨틱"},
    "ABCLON": {"symbol": "174900.KQ", "name": "앱클론"},
}

# 탐색할 파라미터 그리드 (RSI 기준값 / 20일선 이격도 기준값)
RSI_GRID = [28, 30, 32, 35, 38, 40, 42]
DISP_GRID = [-15.0, -12.0, -10.0, -8.0, -6.0, -5.0]

# 신규 진입 물량 스윙 청산 조건 (최대 15거래일 보유, 익절 +12%, 고점 대비 트레일링 스탑 -7%)
HOLD_DAYS = 15
TAKE_PROFIT = 12.0
TRAILING_STOP = -7.0

def compute_indicators(df):
    closes = df['Close']
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100.0 - (100.0 / (1.0 + rs))
    df['RSI'] = df['RSI'].fillna(50.0)

    df['MA20'] = closes.rolling(20).mean()
    df['DISP20'] = ((closes - df['MA20']) / df['MA20']) * 100.0

    # MACD 히스토그램 반등 여부 (C3 조건)
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sig
    df['MACD_TURN'] = hist > hist.shift(1)
    return df.dropna()

def simulate_strategy(df, rsi_cut, disp_cut):
    trades = []
    closes = df['Close'].values
    highs = df['High'].values
    rsis = df['RSI'].values
    disps = df['DISP20'].values
    macd_turns = df['MACD_TURN'].values

    i = 0
    n = len(df)
    while i < n - HOLD_DAYS:
        # 과매도(RSI 또는 이격도) + 모멘텀 턴(MACD 반등) 결합 진입
        if ((rsis[i] < rsi_cut) or (disps[i] <= disp_cut)) and macd_turns[i]:
            entry_p = closes[i]
            peak_p = entry_p
            exit_ret = 0.0

            for d in range(1, HOLD_DAYS + 1):
                curr_p = closes[i + d]
                curr_h = highs[i + d]
                if curr_h > peak_p:
                    peak_p = curr_h

                ret_from_entry = ((curr_p - entry_p) / entry_p) * 100.0
                ret_from_peak = ((curr_p - peak_p) / peak_p) * 100.0

                # 목표 익절 도달 또는 고점 대비 트레일링 스탑 발동 시 청산
                if ret_from_entry >= TAKE_PROFIT or ret_from_peak <= TRAILING_STOP or d == HOLD_DAYS:
                    exit_ret = ret_from_entry
                    i += d
                    break
            trades.append(exit_ret)
        i += 1

    if len(trades) < 3:
        return {"count": len(trades), "win_rate": 0.0, "avg_ret": -99.0, "score": -99.0}

    wins = [t for t in trades if t > 0]
    win_rate = (len(wins) / len(trades)) * 100.0
    avg_ret = float(np.mean(trades))
    # 평가 점수: 평균 수익률과 승률 가중 합산
    score = avg_ret * 1.5 + (win_rate - 50.0) * 0.1
    return {"count": len(trades), "win_rate": win_rate, "avg_ret": avg_ret, "score": score}

def main():
    print("📊 [전 종목 최근 2년 데이터 기반 맞춤 RSI / 이격도 최적화 결과]\n")
    best_config = {}

    for key, info in TARGETS.items():
        df = yf.Ticker(info["symbol"]).history(period="2y")
        if df.empty or len(df) < 60:
            print(f"⚠️ {info['name']}: 데이터 부족")
            continue

        df = compute_indicators(df)
        best = {"rsi": 38, "disp": -8.0, "win_rate": 0.0, "avg_ret": 0.0, "count": 0, "score": -999.0}

        for r in RSI_GRID:
            for d in DISP_GRID:
                res = simulate_strategy(df, r, d)
                if res["score"] > best["score"]:
                    best = {"rsi": r, "disp": d, **res}

        best_config[key] = {"rsi_cut": best["rsi"], "disp_cut": best["disp"]}
        print(f"✅ {info['name']} ({info['symbol']})")
        print(f"   ➔ 최적 기준: RSI < {best['rsi']} | 20일 이격도 <= {best['disp']}%")
        print(f"   ➔ 백테스트 성과: 총 {best['count']}회 진입 | 승률 {best['win_rate']:.1f}% | 건당 평균 {best['avg_ret']:+.2f}%\n")

    print("📋 [bot.py에 붙여넣을 CUSTOM_PARAMS 코드]")
    print("CUSTOM_PARAMS = " + repr(best_config))

if __name__ == "__main__":
    main()
