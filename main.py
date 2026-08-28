import requests
import pandas as pd
import time
import datetime
import os
import uuid
import json
import requests
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, abort, session, redirect, url_for
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import yfinance as yf

# =========================================================
# 1. INITIALIZE FLASK APP & SECURITY
# =========================================================
app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "KFX_Super_Secret_Key_2026") 

# =========================================================
# 2. DATABASE CONFIGURATION
# =========================================================
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres.faivtufcdphtmnfcbqjl:llhcKet2GtYKjfRj@aws-1-eu-west-1.pooler.supabase.com:5432/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ADMIN_EMAIL = "bakarekehinde383@gmail.com"
FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY", "FLWSECK_TEST-YOUR_ACTUAL_SECRET_KEY_HERE")
FLW_SECRET_HASH = os.environ.get("FLW_SECRET_HASH", "KFX_Webhook_Secure_2026")

# UPGRADED DATABASE: Includes Profile, Verification, AND Password Reset
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    
    # Verification & Security
    is_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(10), nullable=True)
    reset_token = db.Column(db.String(100), nullable=True) # <-- NEW COLUMN
    
    customer_code = db.Column(db.String(50), nullable=True)
    has_active_sub = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

macro_cache = {"dxy": 0.00, "us10y": 0.00, "us2y": 0.00, "vix": 0.00, "yield_curve": 0.00, "last_updated": 0}
news_cache = {"articles": [], "last_updated": 0}


# =========================================================
# 3. EMAIL SENDING ENGINE (VIA BREVO API)
# =========================================================
def send_verification_email(to_email, code):
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_USERNAME")
    
    if not api_key or not sender_email:
        print("API Key or Sender Email missing in Render!")
        return False
        
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": "KFX Global", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "Your KFX Verification Code",
        "textContent": f"Hello,\n\nWelcome to KFX Global. Your verification code is: {code}\n\nPlease enter this code on the website to verify your account.\n\nBest regards,\nKFX Security Team"
    }
    
    try:
        # Uses standard HTTPS (port 443), which Render's free tier allows!
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # 201 means "Created/Queued successfully" in Brevo's system
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"Brevo API Error: {response.text}")
            return False
    except Exception as e:
        print(f"Failed to reach email API: {e}")
        return False


def send_welcome_email(to_email, user_name):
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_USERNAME")
    
    if not api_key or not sender_email:
        print("API Key or Sender Email missing in Render!")
        return False
        
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": "KFX Global", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "Welcome to KFX Global! 🚀",
        "textContent": f"Hello {user_name},\n\nWelcome to KFX Global! Your email has been successfully verified and your account is secure.\n\nYou are just one step away from full access to the KFX Gold Intelligence Tool. Once your subscription is activated, you will be able to log in and view the live terminal.\n\nIf you have any questions or need assistance, simply reply to this email.\n\nWelcome to the winning team!\n\nBest regards,\nThe KFX Global Team"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"Brevo API Error (Welcome): {response.text}")
            return False
    except Exception as e:
        print(f"Failed to reach email API (Welcome): {e}")
        return False


def send_payment_success_email(to_email, user_name):
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_USERNAME")
    
    if not api_key or not sender_email:
        print("API Key or Sender Email missing in Render!")
        return False
        
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": "KFX Global", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "Payment Successful! Access Granted 🚀",
        "textContent": f"Hello {user_name},\n\nYour payment was successful and your premium subscription is now ACTIVE!\n\nYou now have full, unrestricted access to the KFX Gold Intelligence Tool.\n\nClick here to log in and enter the terminal:\nhttps://kfx-gold-intelligence-tool.onrender.com/\n\nWelcome to the winning team. Let's get to work!\n\nBest regards,\nThe KFX Global Team"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"Brevo API Error (Payment): {response.text}")
            return False
    except Exception as e:
        print(f"Failed to reach email API (Payment): {e}")
        return False


def send_reset_email(to_email, reset_link):
    api_key = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("MAIL_USERNAME")
    
    if not api_key or not sender_email:
        print("API Key or Sender Email missing! Check logs for reset link.")
        print(f"--- LINK FOR {to_email} ---: {reset_link}")
        return False
        
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": "KFX Global", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "KFX Password Reset Request",
        "textContent": f"Hello,\n\nWe received a request to reset your password. Click the secure link below to create a new password:\n\n{reset_link}\n\nIf you did not request this, please ignore this email. Your account remains secure.\n\nBest regards,\nKFX Security Team"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"Brevo API Error: {response.text}")
            return False
    except Exception as e:
        print(f"Failed to reach email API: {e}")
        return False


# =========================================================
# 4. FRONTEND PAGE ROUTES
# =========================================================

@app.route('/')
def serve_landing_page():
    if 'user_email' in session:
        return redirect(url_for('serve_dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')
    
@app.route('/verify', methods=['GET'])
def verify_page():
    return render_template('verify.html')

@app.route('/forgot-password')
def forgot_password_page():
    return render_template('forgot-password.html')

@app.route('/reset-password/<token>')
def reset_password_page(token):
    user = Student.query.filter_by(reset_token=token).first()
    if not user:
        return "Invalid or expired reset link. Please request a new one.", 400
    return render_template('reset-password.html', token=token)

@app.route('/dashboard')
def serve_dashboard():
    if 'user_email' not in session:
        return redirect(url_for('serve_landing_page'))
    return render_template('index.html')

# =========================================================
# 5. AUTHENTICATION, REGISTRATION & RESET
# =========================================================
@app.route('/login.html')
def login_page():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({"error": "Please enter both email and password."}), 400

    is_admin = (email == ADMIN_EMAIL.strip().lower())
    if is_admin:
        session['user_email'] = email
        session['is_admin'] = True
        # NEW: Added "email": email so the frontend can save it for the dashboard
        return jsonify({"message": "Admin login successful", "redirect_url": "/dashboard", "email": email}), 200

    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({"error": "Account not found. Please sign up."}), 404

    if not student.password_hash or not check_password_hash(student.password_hash, password):
        return jsonify({"error": "Invalid password."}), 401
        
    if not student.is_verified:
        return jsonify({"error": "Please verify your email first.", "redirect_url": f"/verify?email={email}"}), 403

    if not student.has_active_sub:
        return jsonify({"error": "Subscription inactive. Please renew your plan."}), 403

    session['user_email'] = email
    session['is_admin'] = False
    # NEW: Added "email": email so the frontend can save it for the dashboard
    return jsonify({"message": "Login successful", "redirect_url": "/dashboard", "email": email}), 200

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for('serve_landing_page'))

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    full_name = data.get('full_name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password or not full_name:
        return jsonify({"error": "Please fill in all required fields."}), 400
        
    student = Student.query.filter_by(email=email).first()
    if student:
        return jsonify({"error": "Account already exists. Please log in."}), 400

    hashed_pw = generate_password_hash(password)
    otp_code = str(random.randint(100000, 999999))
    
    new_student = Student(
        full_name=full_name,
        phone_number=phone_number,
        email=email, 
        password_hash=hashed_pw, 
        is_verified=False,
        verification_code=otp_code,
        has_active_sub=False
    )
    db.session.add(new_student)
    db.session.commit()
    
    email_sent = send_verification_email(email, otp_code)
    
    if email_sent:
        return jsonify({"message": "Profile created! Please check your email for the verification code.", "redirect_url": f"/verify?email={email}"}), 200
    else:
        return jsonify({"error": "Account created, but failed to send verification email. Contact admin."}), 500


@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    
    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({"error": "User not found."}), 404
        
    if student.is_verified:
        return jsonify({"message": "Already verified!"}), 200
        
    if student.verification_code == code:
        student.is_verified = True
        student.verification_code = None 
        db.session.commit()
        
        # 👇 The newly added Welcome Email trigger
        send_welcome_email(student.email, student.full_name)
        
        try:
            tx_ref = f"KFX-{uuid.uuid4().hex[:8]}"
            sub_price = os.environ.get("KFX_SUB_PRICE", "150000")
            payload = {
                "tx_ref": tx_ref,
                "amount": sub_price,
                "currency": "NGN",
                "payment_plan": "165914",
                "redirect_url": "https://kfx-gold-intelligence-tool.onrender.com/",
                "customer": {"email": email, "name": student.full_name},
                "customizations": {"title": "KFX Gold Intelligence Tool", "description": "Premium Subscription"}
            }
            headers = {"Authorization": f"Bearer {FLW_SECRET_KEY}", "Content-Type": "application/json"}
            response = requests.post("https://api.flutterwave.com/v3/payments", json=payload, headers=headers)
            res_data = response.json()
            
            if res_data.get("status") == "success":
                return jsonify({"message": "Verified! Redirecting to payment...", "checkout_url": res_data["data"]["link"]}), 200
        except Exception as e:
            return jsonify({"error": "Verified, but gateway failed."}), 500
            
    return jsonify({"error": "Invalid verification code."}), 400


@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    user = Student.query.filter_by(email=email).first()
    if user:
        token = str(uuid.uuid4())
        user.reset_token = token
        db.session.commit()
        
        # Request.host_url gets the live link from Render automatically
        reset_link = f"{request.host_url}reset-password/{token}"
        
        send_reset_email(email, reset_link)
        
    return jsonify({"message": "If that email exists, a reset link has been sent."}), 200

@app.route('/api/reset-password/<token>', methods=['POST'])
def api_reset_password(token):
    data = request.get_json()
    new_password = data.get('password')
    
    user = Student.query.filter_by(reset_token=token).first()
    if not user:
        return jsonify({"error": "Invalid token"}), 400
        
    user.password_hash = generate_password_hash(new_password) 
    user.reset_token = None
    db.session.commit()
    
    return jsonify({"message": "Password updated successfully!"}), 200

# =========================================================
# 6. FLUTTERWAVE WEBHOOK
# =========================================================
@app.route('/api/flutterwave-webhook', methods=['POST'])
def flutterwave_webhook():
    # 1. Verify the request is actually from Flutterwave
    signature = request.headers.get("verif-hash")
    if not signature or signature != FLW_SECRET_HASH:
        abort(401)
        
    event_data = request.json or {}
    event_type = event_data.get("event")
    data = event_data.get("data", {})
    
    # 2. Find the customer's email in the payload
    email = data.get("customer", {}).get("email")
    if not email:
        return jsonify({"status": "ignored"}), 200
        
    email_clean = email.strip().lower()
    student = Student.query.filter_by(email=email_clean).first()
    
    # 3. The Gatekeeper Logic
    if student:
        # Turn ON access if they paid successfully
        if event_type == "charge.completed" and data.get("status") == "successful":
            student.has_active_sub = True
            db.session.commit()
            
            # 👇 The newly added Access Granted Email trigger
            send_payment_success_email(student.email, student.full_name)
            
        # Turn OFF access if they cancel or their billing expires
        elif event_type == "subscription.cancelled":
            student.has_active_sub = False
            db.session.commit()
            
    return jsonify({"status": "success"}), 200

     
    
# =========================================================
# 6. KFX INTELLIGENCE FUNCTIONS (LEAVE THESE EXACTLY AS THEY ARE)
# =========================================================


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
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            response = requests.get(url, headers=headers, timeout=10)
            
            # This will print the exact block message if Forex Factory rejects your server!
            if response.status_code != 200:
                print(f"NEWS FEED BLOCKED! Status Code: {response.status_code}")
                print(f"Response: {response.text[:250]}")
            
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
                    except Exception as e:
                        # Prints if the date format is weird
                        print(f"Date parsing error for {event.get('title')}: {e}")
           
            news_cache["articles"] = articles[:4]
            news_cache["last_updated"] = current_time
            
        except Exception as e:
            # THIS IS WHY YOUR LOGS WERE EMPTY! Now it will print the crash.
            print(f"CRITICAL NEWS FEED ERROR: {e}")
           
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
        if df is None or len(df) < 14:
            return {"rsi": 50.0, "ema50": 0.0, "ema200": 0.0, "bias": "NEUTRAL"}
        
        # Calculate RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1]))
        
        # Calculate EMAs using available data up to span limits
        span_50 = min(50, len(df))
        span_200 = min(200, len(df))
        
        ema50 = df['Close'].ewm(span=span_50, adjust=False).mean().iloc[-1]
        ema200 = df['Close'].ewm(span=span_200, adjust=False).mean().iloc[-1]
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


from datetime import datetime, timezone
import requests
import pandas as pd

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
import requests
import pandas as pd

# Global memory stores for instant delivery and smart fetching
GLOBAL_GOLD_CACHE = None
LAST_H1_CACHE = pd.DataFrame()
LAST_D1_CACHE = pd.DataFrame()
LAST_HOUR_FETCHED = None

# =========================================================
# BACKGROUND WORKER (ACTIVE HOURS STRATEGY)
# Runs every 60s: Fast updates during London/NY. Sleeps during Asia.
# =========================================================
def update_gold_cache():
    global GLOBAL_GOLD_CACHE, LAST_H1_CACHE, LAST_D1_CACHE, LAST_HOUR_FETCHED
    
    current_utc = datetime.now(timezone.utc)
    
    # 1. Active Hours Check (Runs 07:00 UTC to 19:00 UTC)
    if current_utc.weekday() >= 5 or not (7 <= current_utc.hour < 19):
        print("😴 Asian Session or Weekend - Background Worker Sleeping...")
        return
        
    print("🔄 Running Active Hours Live Fetch (Every 60s)...")
    
    symbol = "XAUUSD"
    TWELVE_DATA_API_KEY = "b48758c67cbf475eb87bbc197505060a"
    
    try:
        macro = get_macro_data()
        news = get_news_data()
        session_data = get_killzone()

        def fetch_twelve_data(interval, outputsize):
            url = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}"
            try:
                response = requests.get(url, timeout=10).json()
                if 'values' not in response:
                    print(f"⚠️ Twelve Data Limit/Error on {interval}: {response}")
                    return pd.DataFrame()
                
                df = pd.DataFrame(response['values'])
                df = df.iloc[::-1]
                df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].astype(float)
                df['volume'] = df['volume'].astype(float) if 'volume' in df.columns else 0.0
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
                return df
            except Exception as e:
                print(f"Twelve Data Fetch Error: {e}")
                return pd.DataFrame()

        # 2. SMART FETCH: Fetch 1H & Daily only once per hour to save API credits!
        if LAST_HOUR_FETCHED != current_utc.hour or LAST_H1_CACHE.empty or LAST_D1_CACHE.empty:
            print("⏳ Fetching 1H and Daily Data (Costs 2 Credits)...")
            LAST_D1_CACHE = fetch_twelve_data(interval="1day", outputsize=30)
            LAST_H1_CACHE = fetch_twelve_data(interval="1h", outputsize=250)
            LAST_HOUR_FETCHED = current_utc.hour
            
        rates_d1 = LAST_D1_CACHE
        rates_h1 = LAST_H1_CACHE
        
        # 3. LIVE FETCH: Always fetch 15M every 60 seconds (Costs 1 Credit)
        rates_m15 = fetch_twelve_data(interval="15min", outputsize=200)

        # Failsafe if API fails
        if rates_h1.empty or rates_d1.empty or rates_m15.empty:
            print("⚠️ Twelve Data unavailable. Retaining last valid cache.")
            return

        current_price = float(rates_m15['Close'].iloc[-1])
        today_d1 = rates_d1.iloc[-1]

        d1_range = float(today_d1['High'] - today_d1['Low'])
        adr_14 = float((rates_d1['High'] - rates_d1['Low']).tail(14).mean())
        
        if not rates_h1.empty:
            recent_high = float(rates_h1['High'].tail(14).max())
            recent_low = float(rates_h1['Low'].tail(14).min())
            price_range_1h = recent_high - recent_low
        else:
            price_range_1h = 10.0

        h4_data = calculate_flow_yf(rates_h1.tail(16))
        h1_data = calculate_flow_yf(rates_h1.tail(4))
        m15_data = calculate_flow_yf(rates_m15.tail(4))

        fast_bull = round((h1_data["bull"] + m15_data["bull"]) / 2, 1)
        fast_bear = round(100.0 - fast_bull, 1)
        fast_flow_data = {"bull": fast_bull, "bear": fast_bear}

        close_prices = rates_h1['Close']
        span_50 = min(50, len(close_prices))
        span_200 = min(200, len(close_prices))

        ema_50 = float(close_prices.ewm(span=span_50, adjust=False).mean().iloc[-1])
        ema_200 = float(close_prices.ewm(span=span_200, adjust=False).mean().iloc[-1])

        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty else 50.0

        if current_price > ema_50 and ema_50 > ema_200:
            tech_bias = "BULLISH"
        elif current_price < ema_50 and ema_50 < ema_200:
            tech_bias = "BEARISH"
        else:
            tech_bias = "NEUTRAL"

        score = 50.0
        if tech_bias == "BULLISH": score += 12.0
        elif tech_bias == "BEARISH": score -= 12.0

        tape_edge = (fast_bull - 50.0) * 0.40
        score += tape_edge

        us10y_val = macro.get('us10y', 0.0)
        dxy_val = macro.get('dxy', 0.0)
        if us10y_val < 4.20 and dxy_val < 104.50: score += 5.0
        elif us10y_val > 4.50 or dxy_val > 105.50: score -= 5.0

        if rsi_14 > 75: score = min(score, 57.0)
        elif rsi_14 < 25: score = max(score, 43.0)

        total_score = int(max(0, min(100, round(score))))

        if rsi_14 > 75:
            action, ladder, color, bias = "MANAGE: BULLISH EXHAUSTION", "MANAGE", "text-yellow-400", "EXHAUSTED BULLISH"
            narrative = "RSI > 75 indicating overbought conditions. Lock in partial profits."
        elif rsi_14 < 25:
            action, ladder, color, bias = "MANAGE: BEARISH EXHAUSTION", "MANAGE", "text-yellow-400", "EXHAUSTED BEARISH"
            narrative = "RSI < 25 indicating oversold extension. High probability of mean-reversion move."
        elif total_score >= 58:
            action, ladder, color, bias = "ACT: HEAVY BULLISH FLOW - EXECUTE LONG", "ACT", "text-emerald-400", "BULLISH"
            narrative = "Intraday tape and technicals align for long execution. Enter on 15m pullback."
        elif total_score >= 53:
            action, ladder, color, bias = "PREPARE: BUYERS ACCUMULATING", "PREPARE", "text-orange-400", "LEANING BULLISH"
            narrative = "Bullish momentum building. Wait for 15m tape confirmation."
        elif total_score <= 42:
            action, ladder, color, bias = "ACT: HEAVY BEARISH FLOW - EXECUTE SHORT", "ACT", "text-red-400", "BEARISH"
            narrative = "Intraday sellers dominate tape. Technicals align for short execution."
        elif total_score <= 47:
            action, ladder, color, bias = "PREPARE: SELLERS ACCUMULATING", "PREPARE", "text-orange-400", "LEANING BEARISH"
            narrative = "Bearish momentum building. Wait for 15m breakdown."
        else:
            action, ladder, color, bias = "OBSERVE: NEUTRAL RANGE", "OBSERVE", "text-slate-400", "NEUTRAL"
            narrative = "Synthesis score balanced inside session. Stand aside and protect capital."

        posture = {"score": total_score, "bias": bias, "action": action, "narrative": narrative, "ladder_state": ladder, "color": color}

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
            round(score_yield, 1), round(score_curve, 1), round(score_vix, 1), round(score_dxy, 1),
            round(score_4h, 1), round(score_fast, 1), round(score_range, 1), round(score_macro_edge, 1)
        ]

        GLOBAL_GOLD_CACHE = {
            "symbol": symbol,
            "bid": round(current_price, 2),
            "dxy": round(float(dxy_val), 2),
            "tnx": round(float(us10y_val), 3),
            "bull_flow": fast_bull,
            "bear_flow": fast_bear,
            "multi_flow": {
                "h4": h4_data,
                "h2": calculate_flow_yf(rates_h1.tail(2)),
                "fast": fast_flow_data
            },
            "posture": posture,
            "macro": macro,
            "session": session_data,
            "radar_data": synthesis_8_factors,
            "news": news,
            "technicals": {
                "rsi": round(rsi_14, 2),
                "ema50": round(ema_50, 2),
                "ema200": round(ema_200, 2),
                "bias": tech_bias
            }
        }
        print("✅ Live Gold Cache Successfully Updated!")

    except Exception as e:
        print(f"❌ Background worker error: {e}")

# Start APScheduler (Every 60 seconds)
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(func=update_gold_cache, trigger="interval", seconds=60)
scheduler.start()

# Initial fetch on startup
update_gold_cache()


# ---------------------------------------------------------
# ROUTE 4: GATED API ENDPOINT (GOLD DATA)
# ---------------------------------------------------------
@app.route('/api/gold')
def get_gold_price():
    user_email = session.get('user_email') or request.headers.get('Authorization')
    if not user_email:
        return jsonify({"error": "Unauthorized. Please enter your email."}), 401
 
    clean_email = user_email.strip().lower()
    if clean_email == "bakarekehinde383@gmail.com" or (ADMIN_EMAIL and clean_email == str(ADMIN_EMAIL).strip().lower()):
        pass
    else:
        student = Student.query.filter_by(email=clean_email).first()
        if not student or not student.has_active_sub:
            return jsonify({"error": "Subscription expired or inactive.", "status": "PAYMENT_REQUIRED"}), 403

    now_utc = datetime.now(timezone.utc)
    current_day = now_utc.weekday()
    
    # 1. Weekly Market Close Rules
    if current_day == 5 or (current_day == 6 and now_utc.hour < 21):
        macro = get_macro_data()
        news = get_news_data()
        return jsonify({
            "bid": "CLOSED",
            "dxy": macro.get('dxy', 0.0),
            "tnx": macro.get('us10y', 0.0),
            "bull_flow": 50.0,
            "bear_flow": 50.0,
            "multi_flow": {"h4": {"bull": 50.0, "bear": 50.0}, "fast": {"bull": 50.0, "bear": 50.0}},
            "posture": {
                "score": 0, "bias": "MARKET CLOSED", "action": "SYSTEM LOCKDOWN: WEEKEND",
                "narrative": "Global markets are currently closed. The KFX Engine will resume at Sunday open.",
                "ladder_state": "OBSERVE", "color": "text-slate-500"
            },
            "macro": macro, "session": {"name": "WEEKEND CLOSE", "active": False},
            "radar_data": [50.0]*8, "news": news,
            "technicals": {"rsi": "-", "ema50": "-", "ema200": "-", "bias": "CLOSED"}
        })
        
    # 2. Asian Session Sleep Mode Message
    if GLOBAL_GOLD_CACHE and not (7 <= now_utc.hour < 19):
        asian_cache = GLOBAL_GOLD_CACHE.copy()
        asian_cache['posture']['narrative'] = "ASIAN SESSION SLEEP MODE: Radar is static until London open to conserve live API limits."
        return jsonify(asian_cache), 200

    # 3. Normal Active Hours Response
    if GLOBAL_GOLD_CACHE:
        return jsonify(GLOBAL_GOLD_CACHE), 200

    # 4. Bootup Fallback
    macro = get_macro_data()
    news = get_news_data()
    return jsonify({
        "symbol": "XAUUSD", "bid": 2650.00, "dxy": macro.get('dxy', 0.0), "tnx": macro.get('us10y', 0.0),
        "bull_flow": 50.0, "bear_flow": 50.0,
        "posture": {"score": 50, "bias": "INITIALIZING", "action": "FETCHING FRESH SNAPSHOT", "narrative": "Engine warming up.", "ladder_state": "OBSERVE", "color": "text-amber-500"},
        "macro": macro, "session": get_killzone(), "radar_data": [50.0]*8, "news": news,
        "technicals": {"rsi": 50.0, "ema50": 2650.0, "ema200": 2650.0, "bias": "NEUTRAL"}
    }), 200


if __name__ == '__main__':
    print("🚀 KFX Gold Intelligence Backend Online!")
    print(f"👑 Admin Bypass Active for: {ADMIN_EMAIL if 'ADMIN_EMAIL' in locals() else 'bakarekehinde383@gmail.com'}")
    app.run(host='0.0.0.0', port=10000)
                                              
