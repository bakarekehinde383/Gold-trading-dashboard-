from flask import Flask, jsonify
from flask_cors import CORS
import MetaTrader5 as mt5
import yfinance as yf
import requests
import time
from datetime import datetime, timezone

# Initialize Flask App
app = Flask(__name__)
CORS(app)

# Initialize MetaTrader 5
if not mt5.initialize():
    print("Failed to initialize MT5.")
    mt5.shutdown()
    quit()

# Global Caches to throttle external API calls
macro_cache = {
    "dxy": 0.00, 
    "us10y": 0.00, 
    "us2y": 0.00,
    "vix": 0.00,
    "yield_curve": 0.00,
    "last_updated": 0
}
news_cache = {"articles": [], "last_updated": 0}


def get_score(value, min_val, max_val, inverse=False):
    """Normalizes any raw metric into a strict 0 to 100 score."""
    if max_val == min_val:
        return 50.0
    score = ((value - min_val) / (max_val - min_val)) * 100.0
    if inverse:
        score = 100.0 - score
    return max(0.0, min(100.0, score))


def get_macro_data():
    global macro_cache
    current_time = time.time()
    
    # Throttle requests to every 60 seconds
    if current_time - macro_cache["last_updated"] > 60:
        try:
            dxy = yf.Ticker("DX-Y.NYB").history(period="1d")
            us10y = yf.Ticker("^TNX").history(period="1d")
            vix = yf.Ticker("^VIX").history(period="1d")
            
            us2y = yf.Ticker("US2Y=X").history(period="1d")
            if us2y.empty:
                us2y = yf.Ticker("^FVX").history(period="1d")

            if not dxy.empty: 
                macro_cache["dxy"] = round(float(dxy['Close'].iloc[-1]), 2)
            if not us10y.empty: 
                macro_cache["us10y"] = round(float(us10y['Close'].iloc[-1]), 3)
            if not vix.empty: 
                macro_cache["vix"] = round(float(vix['Close'].iloc[-1]), 2)
            if not us2y.empty: 
                macro_cache["us2y"] = round(float(us2y['Close'].iloc[-1]), 3)
            
            if not us10y.empty and not us2y.empty:
                macro_cache["yield_curve"] = round(macro_cache["us10y"] - macro_cache["us2y"], 3)
                
            macro_cache["last_updated"] = current_time
        except Exception as e:
            print(f"Macro Data Fetch Error: {e}")
            pass
            
    return macro_cache


def get_news_data():
    global news_cache
    current_time = time.time()
    
    # Throttle news requests to every 5 minutes
    if current_time - news_cache.get("last_updated", 0) > 300:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            articles = []
            now = datetime.now(timezone.utc)
            
            for event in data:
                if event.get("country") == "USD" and event.get("impact") in ["High", "Medium"]:
                    event_date_str = event.get("date", "")
                    try:
                        event_time = datetime.fromisoformat(event_date_str)
                        time_diff = (event_time - now).total_seconds()
                        
                        if -7200 <= time_diff <= 86400:
                            impact_level = "HIGH" if event.get("impact") == "High" else "MED"
                            imminent = True if (0 <= time_diff <= 7200 and impact_level == "HIGH") else False
                            display_time = event_time.strftime("%I:%M %p")
                            
                            articles.append({
                                "title": f"[{display_time}] {event.get('title')}",
                                "source": "FOREX FACTORY",
                                "impact": impact_level,
                                "is_imminent": imminent
                            })
                    except Exception:
                        pass
            
            news_cache["articles"] = articles[:4]
            news_cache["last_updated"] = current_time
        except Exception:
            pass
            
    return news_cache.get("articles", [])


def calculate_flow(symbol, timeframe):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
    tick = mt5.symbol_info_tick(symbol)
    if rates is None or len(rates) == 0 or tick is None:
        return {"bull": 50.0, "bear": 50.0}
    total_range = rates[0]['high'] - rates[0]['low']
    bull = 50.0 if total_range == 0 else max(0, min(100, ((tick.bid - rates[0]['low']) / total_range) * 100))
    return {"bull": round(bull, 1), "bear": round(100 - bull, 1)}


def get_killzone():
    """Maps UTC time to exact ICT/Institutional Killzones and Volatility profiles."""
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    time_decimal = hour + (minute / 60.0)

    # 07:00 - 10:00 UTC: London Open Killzone
    if 7.0 <= time_decimal < 10.0:
        return {
            "name": "LONDON OPEN KILLZONE",
            "vol": "HIGH",
            "phase": "EXPANSION",
            "desc": "Judas swing / Initial liquidity sweep active",
            "color": "text-yellow-500"
        }
    # 12:00 - 16:00 UTC: NY / London Overlap (Gold Peak Volatility)
    elif 12.0 <= time_decimal < 16.0:
        return {
            "name": "NY / LONDON OVERLAP",
            "vol": "MAXIMUM",
            "phase": "PEAK FLOW",
            "desc": "Peak Institutional Gold volume window",
            "color": "text-red-500"
        }
    # 16:00 - 20:00 UTC: New York Late Session
    elif 16.0 <= time_decimal < 20.0:
        return {
            "name": "NEW YORK SESSION",
            "vol": "MEDIUM",
            "phase": "DISTRIBUTION",
            "desc": "Post-overlap continuation or retracement",
            "color": "text-blue-500"
        }
    # 00:00 - 07:00 UTC: Asian / Tokyo Session
    elif 0.0 <= time_decimal < 7.0:
        return {
            "name": "TOKYO (ASIAN) SESSION",
            "vol": "LOW",
            "phase": "ACCUMULATION",
            "desc": "Asia range formation / High liquidity build",
            "color": "text-slate-400"
        }
    # 20:00 - 24:00 UTC: Dead Zone
    else:
        return {
            "name": "DEAD ZONE / SYDNEY",
            "vol": "VERY LOW",
            "phase": "ILLIQUID",
            "desc": "Off-market hours — Spread expansion risk",
            "color": "text-slate-600"
        }


def generate_action_posture(fast_flow, volatility_score, rel_volume, macro, news, total_score, killzone):
    """
    Synthesizes volume anomalies, volatility compression, macro edge, 
    and killzone timing to determine actionable market posture.
    """
    
    # 1. HARD SAFETY RULE: IMMINENT HIGH-IMPACT NEWS LOCKOUT
    if any(n.get('is_imminent', False) for n in news):
        return {
            "action": "LOCKOUT: HIGH IMPACT NEWS IMMINENT",
            "bias": "PROTECTED",
            "ladder_state": "OBSERVE",
            "color": "text-yellow-500",
            "narrative": "System Locked. High-impact economic release dropping within 2 hours. High danger of spread widening and algorithmic whipsaws.",
            "score": total_score
        }

    # 2. VOLUME SQUEEZE DETECTION (Low Volatility + Spiking Tick Volume)
    if volatility_score < 40 and rel_volume > 1.3:
        return {
            "action": "PREPARE: VOLUME SQUEEZE IN PROGRESS",
            "bias": "ACCUMULATION",
            "ladder_state": "PREPARE",
            "color": "text-orange-500",
            "narrative": f"Price range is heavily compressed while relative tick volume is elevated ({round(rel_volume, 2)}x avg). Institutional position building underway. Await session breakout.",
            "score": total_score
        }

    # 3. VOLUME EXHAUSTION CLIMAX (Extreme Volatility + Massive Volume Spike)
    if volatility_score > 85 and rel_volume > 2.0:
        return {
            "action": "MANAGE: VOLUME EXHAUSTION DETECTED",
            "bias": "EXHAUSTION",
            "ladder_state": "MANAGE",
            "color": "text-red-400",
            "narrative": "Climactic volume spike detected at extended price levels. High probability of profit-taking or sharp mean reversion.",
            "score": total_score
        }

    # 4. DEAD ZONE / OFF-HOURS WARNING
    if killzone["vol"] == "VERY LOW":
        return {
            "action": "STAND ASIDE: ILLIQUID SESSION",
            "bias": "NEUTRAL",
            "ladder_state": "OBSERVE",
            "color": "text-slate-500",
            "narrative": "Market is in the off-hours Dead Zone. Low liquidity can cause unpredictable slippage and artificial tick noise.",
            "score": total_score
        }

    # 5. DIRECTIONAL MOMENTUM / CONVICTION POSTURE
    if total_score >= 68 or fast_flow["bull"] >= 70:
        if macro['us10y'] < 4.25 and macro['dxy'] < 105.0:
            return {
                "action": "ENGAGE: CONFIRMED BULLISH STRUCTURE",
                "bias": "BULLISH",
                "ladder_state": "ACT",
                "color": "text-emerald-500",
                "narrative": f"Global score strong at {total_score}/100. Fast tape ({fast_flow['bull']}%) aligned with supportive yield/DXY dynamics. Favorable long execution window.",
                "score": total_score
            }
        else:
            return {
                "action": "PREPARE: BULLISH FLOW vs MACRO FRICTION",
                "bias": "BULLISH",
                "ladder_state": "PREPARE",
                "color": "text-emerald-400",
                "narrative": f"Intraday flow is bullish ({fast_flow['bull']}%), but macro yields ({macro['us10y']}%) present overhead resistance. Tighten trade targets.",
                "score": total_score
            }

    elif total_score <= 32 or fast_flow["bear"] >= 70:
        if macro['dxy'] > 103.5 or macro['us10y'] > 4.25:
            return {
                "action": "ENGAGE: CONFIRMED BEARISH STRUCTURE",
                "bias": "BEARISH",
                "ladder_state": "ACT",
                "color": "text-red-500",
                "narrative": f"Global score weak at {total_score}/100. Strong Dollar/Yield environment validating aggressive sell-side pressure.",
                "score": total_score
            }
        else:
            return {
                "action": "PREPARE: BEARISH FLOW vs MACRO SUPPORT",
                "bias": "BEARISH",
                "ladder_state": "PREPARE",
                "color": "text-red-400",
                "narrative": f"Fast tape is bearish ({fast_flow['bear']}%), but macro baseline remains elevated. Counter-trend short risks present.",
                "score": total_score
            }

    # 6. DEFAULT NEUTRAL STATE
    return {
        "action": "OBSERVE: NEUTRAL RANGE",
        "bias": "NEUTRAL",
        "ladder_state": "OBSERVE",
        "color": "text-slate-400",
        "narrative": f"Synthesis score balanced at {total_score}/100 inside {killzone['name']}. No clear volume or structural expansion. Stand aside.",
        "score": total_score
    }


@app.route('/api/gold')
def get_gold_price():
    symbol = "XAUUSD"  # Change to "GOLD" if your broker uses that ticker name
    tick = mt5.symbol_info_tick(symbol)
    rates_d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 14)
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 14)
    
    if tick is None or rates_d1 is None or len(rates_d1) < 14:
        return jsonify({"error": "MT5 Data not found", "bid": 0.00})
        
    current_price = tick.bid
    today_d1 = rates_d1[-1]
    
    # Intraday Technical Calculations
    d1_range = today_d1['high'] - today_d1['low']
    bull_d1 = 50.0 if d1_range == 0 else max(0, min(100, ((current_price - today_d1['low']) / d1_range) * 100))
    bear_d1 = 100.0 - bull_d1
    
    adr_14 = sum([r['high'] - r['low'] for r in rates_d1]) / 14
    volatility_score = 50 if adr_14 == 0 else max(0, min(100, (d1_range / adr_14) * 50))
    volume_score = min(100, (today_d1['tick_volume'] / 50000) * 100)
    
    # 1H Range calculation for Radar Axis 7
    if rates_h1 is not None and len(rates_h1) > 0:
        recent_high = max(r['high'] for r in rates_h1)
        recent_low = min(r['low'] for r in rates_h1)
        price_range_1h = recent_high - recent_low
    else:
        price_range_1h = 10.0

    # Relative Tick Volume Calculation (Current H1 volume vs 14-period SMA)
    if rates_h1 is not None and len(rates_h1) >= 14:
        current_h1_vol = rates_h1[-1]['tick_volume']
        avg_h1_vol = sum(r['tick_volume'] for r in rates_h1) / 14.0
        rel_volume = (current_h1_vol / avg_h1_vol) if avg_h1_vol > 0 else 1.0
    else:
        rel_volume = 1.0

    # Multi-Timeframe Flow Calculations
    h4_data = calculate_flow(symbol, mt5.TIMEFRAME_H4)
    h1_data = calculate_flow(symbol, mt5.TIMEFRAME_H1)
    m15_data = calculate_flow(symbol, mt5.TIMEFRAME_M15)
    
    fast_bull = round((h1_data["bull"] + m15_data["bull"]) / 2, 1)
    fast_bear = round(100.0 - fast_bull, 1)
    fast_flow_data = {"bull": fast_bull, "bear": fast_bear}
    
    # Fetch Cached Macro, News & Session Data
    macro = get_macro_data()
    news = get_news_data()
    session = get_killzone()

    # --- 8-FACTOR SYNTHESIS SCORING ENGINE ---
    score_yield = get_score(macro['us10y'], 3.0, 5.5, inverse=True)
    score_curve = get_score(macro['yield_curve'], -1.0, 1.0, inverse=True)
    score_vix = get_score(macro['vix'], 12.0, 35.0, inverse=False)
    score_dxy = get_score(macro['dxy'], 98.0, 110.0, inverse=True)
    score_4h = h4_data['bull']
    score_fast = fast_bull
    score_range = get_score(price_range_1h, 5.0, 30.0, inverse=False)
    score_macro_edge = (score_yield + score_curve + score_vix + score_dxy) / 4.0

    # Calculate Central Regime Score (0-100)
    total_score = int(round(
        (score_yield + score_curve + score_vix + score_dxy + score_4h + score_fast + score_range + score_macro_edge) / 8.0
    ))

    # Action Posture Synthesis
    posture = generate_action_posture(
        fast_flow_data, 
        volatility_score, 
        rel_volume, 
        macro, 
        news, 
        total_score, 
        session
    )

    # 8-Factor Array aligned with Frontend Radar Axes
    synthesis_8_factors = [
        round(score_yield, 1),
        round(score_curve, 1),
        round(score_vix, 1),
        round(score_dxy, 1),
        round(score_4h, 1),
        round(score_fast, 1),
        round(score_range, 1),
        round(score_macro_edge, 1)
    ]

    return jsonify({
        "symbol": symbol,
        "bid": current_price,
        "bull_flow": round(score_macro_edge, 1),
        "bear_flow": round(100.0 - score_macro_edge, 1),
        "radar_data": synthesis_8_factors,
        "multi_flow": {
            "h4": h4_data,
            "h2": calculate_flow(symbol, mt5.TIMEFRAME_H2),
            "fast": fast_flow_data
        },
        "macro": macro,
        "news": news,
        "posture": posture,
        "session": session
    })


if __name__ == '__main__':
    print("🚀 KFX Gold Intelligence Command Backend Online!")
    print("📡 8-Factor Synthesis Engine & Institutional Killzone Active.")
    app.run(port=5000, debug=True)
