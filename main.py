from flask import Flask, jsonify, render_template
from flask_cors import CORS
import yfinance as yf
import requests
import time
from datetime import datetime, timezone

# Initialize Flask App
app = Flask(__name__)
CORS(app)

@app.route('/')
def serve_dashboard():
    return render_template('index.html')

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
            # --- THE FIX: ADD A CUSTOM BROWSER SESSION ---
            import requests
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            # --- APPLY SESSION TO ALL MACRO TICKERS TO BYPASS YAHOO BLOCK ---
            dxy = yf.Ticker("DX-Y.NYB", session=session).history(period="1d")
            us10y = yf.Ticker("^TNX", session=session).history(period="1d")
            vix = yf.Ticker("^VIX", session=session).history(period="1d")

            us2y = yf.Ticker("US2Y=X", session=session).history(period="1d")
            if us2y.empty:
                us2y = yf.Ticker("^FVX", session=session).history(period="1d")

            # Update cache if data successfully retrieved
            if not dxy.empty:
                macro_cache["dxy"] = round(float(dxy['Close'].iloc[-1]), 2)
            if not us10y.empty:
                macro_cache["us10y"] = round(float(us10y['Close'].iloc[-1]), 3)
            if not vix.empty:
                macro_cache["vix"] = round(float(vix['Close'].iloc[-1]), 2)
            if not us2y.empty:
                macro_cache["us2y"] = round(float(us2y['Close'].iloc[-1]), 3)

            # Calculate Yield Curve (10Y - 2Y)
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


def calculate_flow_yf(hist_df):
    """
    Calculates bull/bear volume flow averaged across multiple candles
    to eliminate micro-noise and 10-second whipsaws.
    """
    if hist_df is None or hist_df.empty or len(hist_df) == 0:
        return {"bull": 50.0, "bear": 50.0}
   
    bull_scores = []
    for idx, row in hist_df.iterrows():
        total_range = row['High'] - row['Low']
        if total_range > 0:
            b = ((row['Close'] - row['Low']) / total_range) * 100.0
            bull_scores.append(b)
        else:
            bull_scores.append(50.0)
            
    if not bull_scores:
        return {"bull": 50.0, "bear": 50.0}
        
    avg_bull = max(0.0, min(100.0, sum(bull_scores) / len(bull_scores)))
    return {"bull": round(avg_bull, 1), "bear": round(100.0 - avg_bull, 1)}


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
    # 10:00 - 12:00 UTC: London Late / Pre-NY (BRIDGING THE GAP)
    elif 10.0 <= time_decimal < 12.0:
        return {
            "name": "LONDON LATE / PRE-NY",
            "vol": "MEDIUM",
            "phase": "TRANSITION",
            "desc": "London mid-day lull before NY Session opens",
            "color": "text-blue-400"
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



import time

# --- ADD THIS CACHE DEFINITION NEAR YOUR OTHER CACHES (macro_cache, news_cache) ---
gold_cache = {
    "data": None,
    "last_updated": 0
}

CACHE_TIMEOUT = 60  # Only fetch new data from Yahoo every 60 seconds


@app.route('/api/gold')
def get_gold_price():
    global gold_cache
    current_time = time.time()
    
    # 1. SERVE CACHED DATA IF FRESH
    if gold_cache["data"] is not None and (current_time - gold_cache["last_updated"] < CACHE_TIMEOUT):
        return jsonify(gold_cache["data"])

    symbol = "XAUUSD"
    try:
        # --- THE FIX: ADD A CUSTOM BROWSER SESSION ---
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # 2. Fetch live Gold Futures FIRST (Yahoo blocks futures less often)
        ticker = yf.Ticker("GC=F", session=session)
        rates_d1 = ticker.history(period="1mo", interval="1d")
        rates_h1 = ticker.history(period="5d", interval="1h")
        rates_m15 = ticker.history(period="2d", interval="15m")
       
        # 3. Fallback to Forex Spot if Futures are blocked
        if rates_d1.empty or rates_h1.empty:
            ticker = yf.Ticker("XAUUSD=X", session=session)
            rates_d1 = ticker.history(period="1mo", interval="1d")
            rates_h1 = ticker.history(period="5d", interval="1h")
            rates_m15 = ticker.history(period="2d", interval="15m")

        # 4. CRASH PREVENTION: If Yahoo completely blocked both, safely trigger the exception
        if rates_d1.empty or rates_h1.empty:
            raise ValueError("Yahoo Finance is blocking the server IP.")

        current_price = float(rates_h1['Close'].iloc[-1])
        today_d1 = rates_d1.iloc[-1]
        
        # ... [KEEP ALL YOUR INTRADAY TECHNICAL CALCULATIONS BELOW THIS EXACTLY THE SAME] ...



        # Intraday Technical Calculations
        d1_range = float(today_d1['High'] - today_d1['Low'])
       
        # ADR 14 Calculation
        adr_14 = float((rates_d1['High'] - rates_d1['Low']).tail(14).mean())
        volatility_score = 50 if adr_14 == 0 else max(0, min(100, (d1_range / adr_14) * 50))
        volume_score = min(100, (float(today_d1.get('Volume', 50000)) / 50000) * 100)

        # 1H Range calculation for Radar Axis 7
        if not rates_h1.empty:
            recent_high = float(rates_h1['High'].tail(14).max())
            recent_low = float(rates_h1['Low'].tail(14).min())
            price_range_1h = recent_high - recent_low
        else:
            price_range_1h = 10.0

        # Relative Tick Volume Calculation
        if len(rates_h1) >= 14:
            current_h1_vol = float(rates_h1['Volume'].iloc[-1])
            avg_h1_vol = float(rates_h1['Volume'].tail(14).mean())
            rel_volume = (current_h1_vol / avg_h1_vol) if avg_h1_vol > 0 else 1.0
        else:
            rel_volume = 1.0

        # Multi-Timeframe Flow Calculations (SMOOTHED OVER MULTIPLE CANDLES)
        h4_data = calculate_flow_yf(rates_h1.tail(16))      # Last 16 hours
        h1_data = calculate_flow_yf(rates_h1.tail(4))       # Last 4 hours
        m15_data = calculate_flow_yf(rates_m15.tail(4))     # Last 1 hour (4x15m candles)

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
        
        # --- DIRECTION-AWARE VOLATILITY RANGE FIX ---
        raw_range_score = get_score(price_range_1h, 5.0, 30.0, inverse=False)
        if fast_bull < 50.0:
            # Bearish trend: High range/volatility pulls the score DOWN
            score_range = 100.0 - raw_range_score
        else:
            # Bullish trend: High range/volatility pushes the score UP
            score_range = raw_range_score

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

        response_payload = {
            "symbol": symbol,
            "bid": round(current_price, 2),
            "bull_flow": round(score_macro_edge, 1),
            "bear_flow": round(100.0 - score_macro_edge, 1),
            "radar_data": synthesis_8_factors,
            "multi_flow": {
                "h4": h4_data,
                "h2": calculate_flow_yf(rates_h1.tail(2)),
                "fast": fast_flow_data
            },
            "macro": macro,
            "news": news,
            "posture": posture,
            "session": session
        }

        # 2. SAVE FRESH DATA TO CACHE
        gold_cache["data"] = response_payload
        gold_cache["last_updated"] = current_time

        return jsonify(response_payload)

    except Exception as e:
        print(f"Error in /api/gold: {e}")
        
        # 3. FAIL-SAFE: If Yahoo fails/blocks, return last known cached data instead of crashing!
        if gold_cache["data"] is not None:
            print("⚠️ Returning last known cached gold data due to API error.")
            return jsonify(gold_cache["data"])
            
        return jsonify({"error": str(e), "bid": 0.00}), 500


if __name__ == '__main__':
    print("🚀 KFX Gold Intelligence Command Backend Online!")
    print("📡 8-Factor Synthesis Engine & Institutional Killzone Active.")
    app.run(host='0.0.0.0', port=10000)


            
