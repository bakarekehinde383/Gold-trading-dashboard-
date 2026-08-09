import time
import datetime
from flask import Flask, jsonify, render_template, request, abort
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import uuid
import json
import os
import yfinance as yf
import requests
import time
from datetime import datetime, timezone

# Initialize Flask App
app = Flask(__name__)
CORS(app)

# --- DATABASE CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///students.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Owner / Admin Email (Full Access Bypass)
ADMIN_EMAIL = "bakarekehinde383@gmail.com"

# --- FLUTTERWAVE CONFIGURATION ---
# Fetches keys safely from Environment Variables (or falls back to placeholders)
FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY", "FLWSECK_TEST-YOUR_ACTUAL_SECRET_KEY_HERE")
FLW_SECRET_HASH = os.environ.get("FLW_SECRET_HASH", "KFX_Webhook_Secure_2026")

# Database Model for Student Subscriptions
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    customer_code = db.Column(db.String(50), nullable=True)
    has_active_sub = db.Column(db.Boolean, default=False)

# Initialize the database table on startup
with app.app_context():
    db.create_all()

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

# ---------------------------------------------------------
# ROUTE 0: KFX GLOBAL FRONT DOOR (LOGIN/PAYMENTS)
# ---------------------------------------------------------
@app.route('/')
def serve_landing_page():
    return render_template('login.html')

# ---------------------------------------------------------
# ROUTE 0.5: KFX GOLD INTELLIGENCE TOOL (DASHBOARD)
# ---------------------------------------------------------
@app.route('/dashboard')
def serve_dashboard():
    return render_template('index.html')


# ---------------------------------------------------------
# ROUTE 1: DYNAMIC CONFIG ENDPOINT (PRICE)
# ---------------------------------------------------------
@app.route('/api/config', methods=['GET'])
def get_config():
    """Serves the current subscription price from the environment to the frontend."""
    price = os.environ.get("KFX_SUB_PRICE", "15000")
    return jsonify({"price": price})


# ---------------------------------------------------------
# ROUTE 2: INITIALIZE FLUTTERWAVE PAYMENT (WITH ADMIN BYPASS)
# ---------------------------------------------------------
@app.route('/api/pay', methods=['POST'])
def initialize_payment():
    try:
        data = request.get_json() or {}
        user_email = data.get("email", "").strip().lower()

        if not user_email:
            return jsonify({"status": "error", "message": "Email is required"}), 400

        # --- ADMIN BYPASS DETECTED ---
        if user_email == "bakarekehinde383@gmail.com" or user_email==str(ADMIN_EMAIL).strip().lower():
            return jsonify({
                "status": "success", 
                "is_admin": True,
                "message": "Welcome back, Admin!",
                "checkout_url": "bypass" 
            })

        # --- REGULAR USER FLUTTERWAVE CHECKOUT ---
        tx_ref = f"KFX-GOLD-{uuid.uuid4().hex[:8]}"
        
        # Dynamically fetch the price from the server environment
        sub_price = os.environ.get("KFX_SUB_PRICE", "15000")
        
        payload = {
            "tx_ref": tx_ref,
            "amount": sub_price,  # Dynamic price applied here
            "currency": "NGN",
            # We updated this redirect URL to point directly to your new dashboard!
            "redirect_url": "https://kfx-gold-intelligence-tool.onrender.com/dashboard", 
            "customer": {
                "email": user_email,
                "name": "KFX Subscriber"
            },
            "customizations": {
                "title": "KFX Gold Intelligence Tool",
                "description": "Premium Access Subscription"
            }
        }
        
        headers = {
            "Authorization": f"Bearer {FLW_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers)
        res_data = response.json()
        
        if res_data.get("status") == "success":
            return jsonify({
                "status": "success", 
                "is_admin": False,
                "checkout_url": res_data["data"]["link"]
            })
        else:
            return jsonify({
                "status": "error", 
                "message": res_data.get("message", "Could not initialize Flutterwave payment")
            }), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------
# ROUTE 3: FLUTTERWAVE WEBHOOK LISTENER
# ---------------------------------------------------------
@app.route('/api/flutterwave-webhook', methods=['POST'])
def flutterwave_webhook():
    """Receives automated payment events directly from Flutterwave servers."""
    signature = request.headers.get("verif-hash")
    
    # Verify request signature matching your custom secret hash
    if not signature or signature != FLW_SECRET_HASH:
        print("⚠️ Unauthorized Webhook Attempt Blocked!")
        abort(401)
    
    event_data = request.json or {}
    event_type = event_data.get("event")
    data = event_data.get("data", {})
    
    email = data.get("customer", {}).get("email")
    if not email:
        return jsonify({"status": "ignored"}), 200

    email_clean = email.strip().lower()

    # Find or register student in database
    student = Student.query.filter_by(email=email_clean).first()
    if not student:
        student = Student(email=email_clean, customer_code=data.get("tx_ref"))
        db.session.add(student)

    # Process automated payment event
    if event_type == "charge.completed" and data.get("status") == "successful":
        student.has_active_sub = True
        print(f"✅ Subscription activated via Flutterwave for: {email_clean}")

    db.session.commit()
    return jsonify({"status": "success"}), 200





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
   
    # 60-second cooldown on macro queries
    if current_time - macro_cache["last_updated"] > 60:
        try:
            # Look back 5 days to safely bridge weekends and market closures
            dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
            us10y = yf.Ticker("^TNX").history(period="5d")
            vix = yf.Ticker("^VIX").history(period="5d")
           
            # Replaced US2Y=X with reliable Treasury proxies (^FVX / ^IRX)
            us2y = yf.Ticker("^FVX").history(period="5d")
            if us2y.empty:
                us2y = yf.Ticker("^IRX").history(period="5d")

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
    """Calculates bull/bear volume flow averaged across multiple candles."""
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
    """Maps UTC time to exact ICT/Institutional Killzones."""
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    time_decimal = hour + (minute / 60.0)

    if 7.0 <= time_decimal < 10.0:
        return {
            "name": "LONDON OPEN KILLZONE",
            "vol": "HIGH",
            "phase": "EXPANSION",
            "desc": "Judas swing / Initial liquidity sweep active",
            "color": "text-yellow-500"
        }
    elif 10.0 <= time_decimal < 12.0:
        return {
            "name": "LONDON LATE / PRE-NY",
            "vol": "MEDIUM",
            "phase": "TRANSITION",
            "desc": "London mid-day lull before NY Session opens",
            "color": "text-blue-400"
        }
    elif 12.0 <= time_decimal < 16.0:
        return {
            "name": "NY / LONDON OVERLAP",
            "vol": "MAXIMUM",
            "phase": "PEAK FLOW",
            "desc": "Peak Institutional Gold volume window",
            "color": "text-red-500"
        }
    elif 16.0 <= time_decimal < 20.0:
        return {
            "name": "NEW YORK SESSION",
            "vol": "MEDIUM",
            "phase": "DISTRIBUTION",
            "desc": "Post-overlap continuation or retracement",
            "color": "text-blue-500"
        }
    elif 0.0 <= time_decimal < 7.0:
        return {
            "name": "TOKYO (ASIAN) SESSION",
            "vol": "LOW",
            "phase": "ACCUMULATION",
            "desc": "Asia range formation / High liquidity build",
            "color": "text-slate-400"
        }
    else:
        return {
            "name": "DEAD ZONE / SYDNEY",
            "vol": "VERY LOW",
            "phase": "ILLIQUID",
            "desc": "Off-market hours — Spread expansion risk",
            "color": "text-slate-600"
        }


def generate_action_posture(fast_flow, volatility_score, rel_volume, macro, news, total_score, killzone):
    """Synthesizes volume anomalies, macro edge, and killzones into actionable posture."""
   
    if any(n.get('is_imminent', False) for n in news):
        return {
            "action": "LOCKOUT: HIGH IMPACT NEWS IMMINENT",
            "bias": "PROTECTED",
            "ladder_state": "OBSERVE",
            "color": "text-yellow-500",
            "narrative": "System Locked. High-impact economic release dropping within 2 hours.",
            "score": total_score
        }

    if volatility_score < 40 and rel_volume > 1.3:
        return {
            "action": "PREPARE: VOLUME SQUEEZE IN PROGRESS",
            "bias": "ACCUMULATION",
            "ladder_state": "PREPARE",
            "color": "text-orange-500",
            "narrative": f"Price range compressed while tick volume is elevated ({round(rel_volume, 2)}x avg). Institutional position building underway.",
            "score": total_score
        }

    if volatility_score > 85 and rel_volume > 2.0:
        return {
            "action": "MANAGE: VOLUME EXHAUSTION DETECTED",
            "bias": "EXHAUSTION",
            "ladder_state": "MANAGE",
            "color": "text-red-400",
            "narrative": "Climactic volume spike at extended price levels. High probability of profit-taking.",
            "score": total_score
        }

    if killzone["vol"] == "VERY LOW":
        return {
            "action": "STAND ASIDE: ILLIQUID SESSION",
            "bias": "NEUTRAL",
            "ladder_state": "OBSERVE",
            "color": "text-slate-500",
            "narrative": "Market is in the off-hours Dead Zone. Low liquidity risk.",
            "score": total_score
        }

    if total_score >= 68 or fast_flow["bull"] >= 70:
        if macro['us10y'] < 4.25 and macro['dxy'] < 105.0:
            return {
                "action": "ENGAGE: CONFIRMED BULLISH STRUCTURE",
                "bias": "BULLISH",
                "ladder_state": "ACT",
                "color": "text-emerald-500",
                "narrative": f"Global score strong at {total_score}/100. Fast tape ({fast_flow['bull']}%) aligned with yields/DXY.",
                "score": total_score
            }
        else:
            return {
                "action": "PREPARE: BULLISH FLOW vs MACRO FRICTION",
                "bias": "BULLISH",
                "ladder_state": "PREPARE",
                "color": "text-emerald-400",
                "narrative": f"Intraday flow is bullish ({fast_flow['bull']}%), but macro yields present resistance.",
                "score": total_score
            }

    elif total_score <= 32 or fast_flow["bear"] >= 70:
        if macro['dxy'] > 103.5 or macro['us10y'] > 4.25:
            return {
                "action": "ENGAGE: CONFIRMED BEARISH STRUCTURE",
                "bias": "BEARISH",
                "ladder_state": "ACT",
                "color": "text-red-500",
                "narrative": f"Global score weak at {total_score}/100. Dollar/Yield environment validating sell-side pressure.",
                "score": total_score
            }
        else:
            return {
                "action": "PREPARE: BEARISH FLOW vs MACRO SUPPORT",
                "bias": "BEARISH",
                "ladder_state": "PREPARE",
                "color": "text-red-400",
                "narrative": f"Fast tape is bearish ({fast_flow['bear']}%), but macro baseline remains elevated.",
                "score": total_score
            }

    return {
        "action": "OBSERVE: NEUTRAL RANGE",
        "bias": "NEUTRAL",
        "ladder_state": "OBSERVE",
        "color": "text-slate-400",
        "narrative": f"Synthesis score balanced at {total_score}/100 inside {killzone['name']}. Stand aside.",
        "score": total_score
    }



# ==========================================
# PHASE 1: TECHNICAL & MACRO ENGINE HELPER
# ==========================================
def calculate_technicals(df):
    try:
        if df is None or len(df) < 50:
            return {"rsi": 50.0, "ema50": 0.0, "ema200": 0.0, "bias": "NEUTRAL"}
        
        # Calculate RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1]))
        
        # Calculate EMAs
        ema50 = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = df['Close'].ewm(span=200, adjust=False).mean().iloc[-1]
        current_price = df['Close'].iloc[-1]
        
        # Determine Advanced Market Bias
        if current_price > ema50 and ema50 > ema200 and rsi < 70:
            bias = "BULLISH"
        elif current_price < ema50 and ema50 < ema200 and rsi > 30:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
            
        return {
            "rsi": round(float(rsi), 2),
            "ema50": round(float(ema50), 2),
            "ema200": round(float(ema200), 2),
            "bias": bias
        }
    except Exception as e:
        print(f"Technical Engine Error: {e}")
        return {"rsi": 50.0, "ema50": 0.0, "ema200": 0.0, "bias": "NEUTRAL"}



# ---------------------------------------------------------
# ROUTE 4: GATED API ENDPOINT (GOLD DATA)
# ---------------------------------------------------------
@app.route('/api/gold')
def get_gold_price():
    # 1. Access Authentication & Authorization Check
    user_email = request.headers.get('Authorization')
    if not user_email:
        return jsonify({"error": "Unauthorized. Please enter your email."}), 401

    clean_email = user_email.strip().lower()

    # Admin Bypass Check
    if clean_email == "bakarekehinde383@gmail.com" or (ADMIN_EMAIL and clean_email == str(ADMIN_EMAIL).strip().lower()):
        pass  # Admin granted full access
    else:
        # Student Subscription Verification
        student = Student.query.filter_by(email=clean_email).first()
        if not student or not student.has_active_sub:
            return jsonify({
                "error": "Subscription expired or inactive.",
                "status": "PAYMENT_REQUIRED"
            }), 403

    # =========================================================
    # WEEKEND LOCKDOWN CHECK (Pre-empts market math errors)
    # =========================================================
    now_utc = datetime.utcnow()
    current_day = now_utc.weekday()  # 5 = Saturday, 6 = Sunday
    
    macro = get_macro_data()
    news = get_news_data()
    session = get_killzone()

    # Lock down on Saturday or Sunday before market open (21:00 UTC)
    if current_day == 5 or (current_day == 6 and now_utc.hour < 21):
        return jsonify({
            "bid": "CLOSED",
            "dxy": macro.get('dxy', 0.0),
            "tnx": macro.get('us10y', 0.0),
            "bull_flow": 50.0,
            "bear_flow": 50.0,
            "multi_flow": {
                "h4": {"bull": 50.0, "bear": 50.0},
                "fast": {"bull": 50.0, "bear": 50.0}
            },
            "posture": {
                "score": 0,
                "bias": "MARKET CLOSED",
                "action": "SYSTEM LOCKDOWN: WEEKEND",
                "narrative": "Global markets are currently closed. The KFX Intelligence Engine will resume real-time analysis at the Sunday market open.",
                "ladder_state": "OBSERVE",
                "color": "text-slate-500"
            },
            "macro": macro,
            "session": {"name": "WEEKEND CLOSE", "active": False},
            "radar_data": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
            "news": news,
            "technicals": {
                "rsi": "-",
                "ema50": "-",
                "ema200": "-",
                "bias": "CLOSED"
            }
        })

    # 2. Main Gold Engine Calculations
    symbol = "XAUUSD"
    try:
        ticker = yf.Ticker("XAUUSD=X")
        rates_d1 = ticker.history(period="1mo", interval="1d")
        rates_h1 = ticker.history(period="5d", interval="1h")
        rates_m15 = ticker.history(period="2d", interval="15m")
       
        if rates_d1.empty or rates_h1.empty:
            ticker = yf.Ticker("GC=F")
            rates_d1 = ticker.history(period="1mo", interval="1d")
            rates_h1 = ticker.history(period="5d", interval="1h")
            rates_m15 = ticker.history(period="2d", interval="15m")

        if rates_h1.empty or rates_d1.empty:
            raise ValueError("No price data returned from provider.")

        current_price = float(rates_h1['Close'].iloc[-1])
        today_d1 = rates_d1.iloc[-1]

        d1_range = float(today_d1['High'] - today_d1['Low'])
        adr_14 = float((rates_d1['High'] - rates_d1['Low']).tail(14).mean())
        volatility_score = 50 if adr_14 == 0 else max(0, min(100, (d1_range / adr_14) * 50))

        if not rates_h1.empty:
            recent_high = float(rates_h1['High'].tail(14).max())
            recent_low = float(rates_h1['Low'].tail(14).min())
            price_range_1h = recent_high - recent_low
        else:
            price_range_1h = 10.0

        if len(rates_h1) >= 14:
            current_h1_vol = float(rates_h1['Volume'].iloc[-1])
            avg_h1_vol = float(rates_h1['Volume'].tail(14).mean())
            rel_volume = (current_h1_vol / avg_h1_vol) if avg_h1_vol > 0 else 1.0
        else:
            rel_volume = 1.0

        h4_data = calculate_flow_yf(rates_h1.tail(16))
        h1_data = calculate_flow_yf(rates_h1.tail(4))
        m15_data = calculate_flow_yf(rates_m15.tail(4))

        fast_bull = round((h1_data["bull"] + m15_data["bull"]) / 2, 1)
        fast_bear = round(100.0 - fast_bull, 1)
        fast_flow_data = {"bull": fast_bull, "bear": fast_bear}

        # =========================================================
        # TECHNICAL INDICATORS & INTRADAY SCORING ENGINE
        # =========================================================
        close_prices = rates_h1['Close']
        ema_50 = float(close_prices.ewm(span=50, adjust=False).mean().iloc[-1]) if len(close_prices) >= 50 else current_price
        ema_200 = float(close_prices.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close_prices) >= 200 else current_price

        # Calculate 14-period RSI
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty else 50.0

        # Technical Trend Alignment
        if current_price > ema_50 > ema_200:
            tech_bias = "BULLISH"
        elif current_price < ema_50 < ema_200:
            tech_bias = "BEARISH"
        else:
            tech_bias = "NEUTRAL"

        # Calculate Dynamic Intraday Score
        score = 50.0

        if tech_bias == "BULLISH":
            score += 12.0
        elif tech_bias == "BEARISH":
            score -= 12.0

        tape_edge = (fast_bull - 50.0) * 0.40
        score += tape_edge

        us10y_val = macro.get('us10y', 0.0)
        dxy_val = macro.get('dxy', 0.0)
        if us10y_val < 4.20 and dxy_val < 104.50:
            score += 5.0
        elif us10y_val > 4.50 or dxy_val > 105.50:
            score -= 5.0

        # RSI Overbought / Oversold Guardrails
        if rsi_14 > 75:
            score = min(score, 57.0)
        elif rsi_14 < 25:
            score = max(score, 43.0)

        total_score = int(max(0, min(100, round(score))))

        # Determine Action Posture based on dynamic thresholds
        if total_score >= 58:
            action = "ACT: HEAVY BULLISH FLOW - EXECUTE LONG"
            ladder = "ACT"
            color = "text-emerald-400"
            bias = "BULLISH"
            narrative = "Intraday tape and technicals align for long execution. Enter on 15m pullback."
        elif total_score >= 53:
            action = "PREPARE: BUYERS ACCUMULATING"
            ladder = "PREPARE"
            color = "text-orange-400"
            bias = "LEANING BULLISH"
            narrative = "Bullish momentum building. Wait for 15m tape confirmation."
        elif total_score <= 42:
            action = "ACT: HEAVY BEARISH FLOW - EXECUTE SHORT"
            ladder = "ACT"
            color = "text-red-400"
            bias = "BEARISH"
            narrative = "Intraday sellers dominate tape. Technicals align for short execution. Sell rallies."
        elif total_score <= 47:
            action = "PREPARE: SELLERS ACCUMULATING"
            ladder = "PREPARE"
            color = "text-orange-400"
            bias = "LEANING BEARISH"
            narrative = "Bearish momentum building. Wait for 15m breakdown."
        else:
            action = "OBSERVE: NEUTRAL RANGE"
            ladder = "OBSERVE"
            color = "text-slate-400"
            bias = "NEUTRAL"
            narrative = "Synthesis score balanced inside session. Stand aside and protect capital."

        posture = {
            "score": total_score,
            "bias": bias,
            "action": action,
            "narrative": narrative,
            "ladder_state": ladder,
            "color": color
        }

        # 8-Factor Radar Array
        score_yield = get_score(us10y_val, 3.0, 5.5, inverse=True)
        score_curve = get_score(macro.get('yield_curve', 0.0), -1.0, 1.0, inverse=True)
        score_vix = get_score(macro.get('vix', 0.0), 12.0, 35.0, inverse=False)
        score_dxy = get_score(dxy_val, 98.0, 110.0, inverse=True)
        score_4h = h4_data['bull']
        score_fast = fast_bull
        raw_range_score = get_score(price_range_1h, 5.0, 30.0, inverse=False)
        score_range = (100.0 - raw_range_score) if fast_bull < 50.0 else raw_range_score
        score_macro_edge = (score_yield + score_curve + score_vix + score_dxy) / 4.0

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
            "bid": current_price,
            "dxy": dxy_val,
            "tnx": us10y_val,
            "bull_flow": fast_bull,
            "bear_flow": fast_bear,
            "multi_flow": {
                "h4": h4_data,
                "fast": fast_flow_data
            },
            "posture": posture,
            "macro": macro,
            "session": session,
            "radar_data": synthesis_8_factors,
            "news": news,
            "technicals": {
                "rsi": round(rsi_14, 2),
                "ema50": round(ema_50, 2),
                "ema200": round(ema_200, 2),
                "bias": tech_bias
            }
        })

    except Exception as e:
        print(f"Server Error in /api/gold: {e}")
        return jsonify({"error": f"Internal engine calculation error: {e}"}), 500



        # =========================================================
        # INTRADAY TECHNICALS ENGINE (EMA 50, EMA 200, RSI 14)
        # =========================================================
        close_prices = rates_h1['Close']
        ema_50 = float(close_prices.ewm(span=50, adjust=False).mean().iloc[-1]) if len(close_prices) >= 50 else current_price
        ema_200 = float(close_prices.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close_prices) >= 200 else current_price

        # Calculate 14-period RSI
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty else 50.0

        # Technical Alignment Bias
        if current_price > ema_50 > ema_200:
            tech_bias = "BULLISH"
        elif current_price < ema_50 < ema_200:
            tech_bias = "BEARISH"
        else:
            tech_bias = "NEUTRAL"

        # =========================================================
        # INTRADAY SCORING ENGINE (FAST TAPE WEIGHTED)
        # =========================================================
        score = 50

        # 1. Technical Trend Alignment (+/- 12)
        if tech_bias == "BULLISH":
            score += 12
        elif tech_bias == "BEARISH":
            score -= 12

        # 2. Fast Tape 15M/1H Momentum (Adds up to +/- 20)
        tape_edge = (fast_bull - 50.0) * 0.40
        score += tape_edge

        # 3. Macro Soft Filter (+/- 5)
        us10y_val = macro.get('us10y', 0)
        dxy_val = macro.get('dxy', 0)
        if us10y_val < 4.20 and dxy_val < 104.50:
            score += 5
        elif us10y_val > 4.50 or dxy_val > 105.50:
            score -= 5

        # 4. RSI Risk Guardrails (Prevent execution on extreme tops/bottoms)
        if rsi_14 > 75:
            score = min(score, 57)  # Prevent BUY when overbought
        elif rsi_14 < 25:
            score = max(score, 43)  # Prevent SELL when oversold

        total_score = int(max(0, min(100, round(score))))

        # =========================================================
        # INTRADAY POSTURE & SIGNAL GENERATION
        # =========================================================
        if total_score >= 58:
            action = "ACT: HEAVY BULLISH FLOW - EXECUTE LONG"
            ladder = "ACT"
            color = "text-emerald-400"
            bias = "BULLISH"
            narrative = "Intraday tape and technicals align for long execution. Enter on 15m pullback."
        elif total_score >= 53:
            action = "PREPARE: BUYERS ACCUMULATING"
            ladder = "PREPARE"
            color = "text-orange-400"
            bias = "LEANING BULLISH"
            narrative = "Bullish momentum building. Wait for 15m tape confirmation."
        elif total_score <= 42:
            action = "ACT: HEAVY BEARISH FLOW - EXECUTE SHORT"
            ladder = "ACT"
            color = "text-red-400"
            bias = "BEARISH"
            narrative = "Intraday sellers dominate tape. Technicals align for short execution. Sell rallies."
        elif total_score <= 47:
            action = "PREPARE: SELLERS ACCUMULATING"
            ladder = "PREPARE"
            color = "text-orange-400"
            bias = "LEANING BEARISH"
            narrative = "Bearish momentum building. Wait for 15m breakdown."
        else:
            action = "OBSERVE: NEUTRAL RANGE"
            ladder = "OBSERVE"
            color = "text-slate-400"
            bias = "NEUTRAL"
            narrative = "Synthesis score balanced inside session. Stand aside and protect capital."

        posture = {
            "score": total_score,
            "bias": bias,
            "action": action,
            "narrative": narrative,
            "ladder_state": ladder,
            "color": color
        }

        # 8-Factor Radar Factors
        score_yield = get_score(us10y_val, 3.0, 5.5, inverse=True)
        score_curve = get_score(macro.get('yield_curve', 0), -1.0, 1.0, inverse=True)
        score_vix = get_score(macro.get('vix', 0), 12.0, 35.0, inverse=False)
        score_dxy = get_score(dxy_val, 98.0, 110.0, inverse=True)
        score_4h = h4_data['bull']
        score_fast = fast_bull
        raw_range_score = get_score(price_range_1h, 5.0, 30.0, inverse=False)
        score_range = (100.0 - raw_range_score) if fast_bull < 50.0 else raw_range_score
        score_macro_edge = (score_yield + score_curve + score_vix + score_dxy) / 4.0

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

        # 3. Final Payload Construction
        return jsonify({
            "bid": current_price,
            "dxy": dxy_val,
            "tnx": us10y_val,
            "bull_flow": fast_bull,
            "bear_flow": fast_bear,
            "multi_flow": {
                "h4": h4_data,
                "fast": fast_flow_data
            },
            "posture": posture,
            "macro": macro,
            "session": session,
            "radar_data": synthesis_8_factors,
            "news": news,
            "technicals": {
                "rsi": round(rsi_14, 2),
                "ema50": round(ema_50, 2),
                "ema200": round(ema_200, 2),
                "bias": tech_bias
            }
        })

    except Exception as e:
        print(f"Server Error in /api/gold: {e}")
        return jsonify({"error": "Internal engine calculation error."}), 500



        # --- NEW: FETCH MACRO & RUN TECHNICAL ENGINE ---
        try:
            # Safely extract DXY and US10Y from your existing macro data
            dxy_price = round(float(macro.get('dxy', 104.00)), 2)
            tnx_yield = round(float(macro.get('us10y', 4.250)), 3)
            
            # Run Technical Engine on your hourly Gold data
            tech_data = calculate_technicals(rates_h1) 
        except Exception as e:
            print(f"Macro/Tech fetch error: {e}")
            dxy_price = 104.00
            tnx_yield = 4.250
            tech_data = {"rsi": 50.0, "ema50": 0.0, "ema200": 0.0, "bias": "NEUTRAL"}
        # -----------------------------------------------

        return jsonify({
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
            "session": session,
            
            # --- NEW PHASE 1 DATA FIELDS EXPORTED TO FRONTEND ---
            "dxy": dxy_price,
            "tnx": tnx_yield,
            "technicals": tech_data
        })
    except Exception as e:
        print(f"Error in /api/gold: {e}")
        return jsonify({"error": str(e), "bid": 0.00}), 500


if __name__ == '__main__':
    print("🚀 KFX Gold Intelligence Backend Online!")
    print(f"👑 Admin Bypass Active for: {ADMIN_EMAIL if 'ADMIN_EMAIL' in locals() else 'bakarekehinde383@gmail.com'}")
    app.run(host='0.0.0.0', port=10000)

