import asyncio
from playwright.async_api import async_playwright 
from bs4 import BeautifulSoup
from datetime import datetime, timezone 
import re
import json
import os
import requests
import time
from dotenv import load_dotenv
import socket
from threading import Thread, current_thread
from typing import Dict, Any, List

# --- Import Flask ---
from flask import Flask, jsonify, render_template
# --------------------

# Muat variabel lingkungan dari file .env
load_dotenv()

# ================= Konstanta Telegram untuk Tombol =================
TELEGRAM_BOT_LINK = "https://t.me/myzuraisgoodbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

# ================= Telegram Configuration (Loaded from .env) =================
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except (ValueError, TypeError):
    print("⚠️ WARNING: TELEGRAM_ADMIN_ID tidak valid. Perintah admin dinonaktifkan.")
    ADMIN_ID = None

# --- X.MNIT Network Configuration ---
LOGIN_URL = "https://x.mnitnetwork.com/mauth/login" 
DASHBOARD_URL = "https://x.mnitnetwork.com/mdashboard/getnum" 
# ------------------------------------

LAST_ID = 0

# ================= Konfigurasi File Path =================
OTP_SAVE_FOLDER = os.path.join("..", "get")
OTP_SAVE_FILE = os.path.join(OTP_SAVE_FOLDER, "smc.json")
# ---------------------------------------------------------

# ================= Global State for Asyncio Loop & Command =================
GLOBAL_ASYNC_LOOP = None 
AWAITING_CREDENTIALS = False 

# ================= Utils =================

COUNTRY_EMOJI = {
    "NEPAL": "🇳🇵",
    "IVORY COAST": "🇨🇮",
    "GUINEA": "🇬🇳",
    "CENTRAL AFRIKA": "🇨🇫",
    "TOGO": "🇹🇬",
    "TAJIKISTAN": "🇹🇯",
    "BENIN": "🇧🇯",
    "SIERRA LEONE": "🇸🇱",
    "MADAGASCAR": "🇲🇬",
    "AFGANISTAN": "🇦🇫",
    "ZURA STORE": "🇮🇩"
}

def get_country_emoji(country_name: str) -> str:
    return COUNTRY_EMOJI.get(country_name.strip().upper(), "")

def create_inline_keyboard():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "➡️ GetNumber", "url": TELEGRAM_BOT_LINK},
                {"text": "👤 Admin", "url": TELEGRAM_ADMIN_LINK}
            ]
        ]
    }
    return json.dumps(keyboard)

def clean_phone_number(phone):
    if not phone: return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+') and cleaned != 'N/A':
        cleaned = '+' + cleaned
    return cleaned or phone

def mask_phone_number(phone, visible_start=4, visible_end=4):
    if not phone or phone == "N/A": return phone
    prefix = ""
    if phone.startswith('+'):
        prefix = '+'
        digits = phone[1:]
    else:
        digits = phone
        
    if len(digits) <= visible_start + visible_end:
        return phone
        
    digits = re.sub(r'[^\d]', '', digits)

    start_part = digits[:visible_start]
    end_part = digits[-visible_end:]
    mask_length = len(digits) - visible_start - visible_end
    masked_part = '*' * mask_length
    return prefix + start_part + masked_part + end_part

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    """Memformat data OTP menjadi pesan Telegram dengan emoji."""
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    masked_phone = mask_phone_number(phone, visible_start=4, visible_end=4)
    service = otp_data.get('service', 'Unknown')
    range_text = otp_data.get('range', 'N/A')
    full_message = otp_data.get('raw_message', 'N/A')
    
    emoji = get_country_emoji(range_text)
    full_message_escaped = full_message.replace('<', '&lt;').replace('>', '&gt;') 
    
    return f"""🔐 <b>New OTP Received</b>

🌍 Country: <b>{range_text} {emoji}</b>

📱 Number: <code>{masked_phone}</code>
🌐 Service: <b>{service}</b>
🔢 OTP: <code>{otp}</code>

FULL MESSAGES:
<blockquote>{full_message_escaped}</blockquote>"""

def extract_otp_from_text(text):
    if not text: return None
    patterns = [ 
        r'<#>\s*([\d\s-]+)\s*—',  
        r'code[:\s]*([\d\s-]+)',  
        r'verification[:\s]*([\d\s-]+)', 
        r'otp[:\s]*([\d\s-]+)',   
        r'pin[:\s]*([\d\s-]+)',   
        r'\b(\d{3}[- ]?\d{3})\b', 
        r'\b(\d{8})\b', 
        r'\b(\d{6})\b', 
        r'\b(\d{5})\b', 
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            matched_otp_raw = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            matched_otp = re.sub(r'[^\d]', '', matched_otp_raw)
            if len(matched_otp) == 4:
                try:
                    if 2000 <= int(matched_otp) <= 2099: continue 
                except ValueError: continue 
            if matched_otp: return matched_otp
    return None

def clean_service_name(service):
    if not service: return "Unknown"
    maps = {
        'facebook': 'Facebook',
        'whatsapp': 'WhatsApp',
        'instagram': 'Instagram',
        'telegram': 'Telegram',
        'google': 'Google',
        'twitter': 'Twitter',
        'linkedin': 'LinkedIn',
        'tiktok': 'TikTok', 
        'mnitnetwork': 'M-NIT Network',
        'laz+nxcar': 'Facebook',
    }
    s_lower = service.strip().lower()
    for k, v in maps.items():
        if k in s_lower: return v
    if s_lower in ['ваш', 'your', 'service', 'code', 'pin']:
        return "Unknown Service"
    return service.strip().title()

def get_status_message(stats):
    return f"""🤖 <b>Bot Status</b>

⚡ Status: <b>{stats['status']}</b>
🌐 Login Status: <b>{'✅ Logged In' if monitor.is_logged_in else '❌ Awaiting Login'}</b>
⏱️ Uptime: <code>{stats['uptime']}</code>
📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>
🔍 Last Check: <code>{stats['last_check']}</code>
💾 Cache Size: <code>{stats['cache_size']} items</code>
📅 Last Cache Reset (GMT): <code>{stats['last_cleanup_gmt_date']}</code>

<i>Bot is running</i>"""

def save_otp_to_json(otp_data: Dict[str, Any]):
    if not os.path.exists(OTP_SAVE_FOLDER):
        os.makedirs(OTP_SAVE_FOLDER)
    data_to_save = {
        "Number": otp_data.get('phone', 'N/A'),
        "OTP": otp_data.get('otp', 'N/A'),
        "FullMessage": otp_data.get('raw_message', 'N/A')
    }
    try:
        existing_data = []
        if os.path.exists(OTP_SAVE_FILE) and os.stat(OTP_SAVE_FILE).st_size > 0:
            with open(OTP_SAVE_FILE, 'r') as f:
                try:
                    existing_data = json.load(f)
                    if not isinstance(existing_data, list): existing_data = []
                except json.JSONDecodeError: existing_data = []
        existing_data.append(data_to_save)
        with open(OTP_SAVE_FILE, 'w') as f:
            json.dump(existing_data, f, indent=2)
    except Exception as e:
        print(f"❌ ERROR: Failed to save OTP to JSON file {OTP_SAVE_FILE}: {e}")

class OTPFilter:
    CLEANUP_KEY = '__LAST_CLEANUP_GMT__' 
    def __init__(self, file='otp_cache.json'): 
        self.file = file
        self.cache = self._load()
        self.last_cleanup_date_gmt = self.cache.pop(self.CLEANUP_KEY, '19700101') 
        self._cleanup() 
    def _load(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.file):
            try:
                if os.stat(self.file).st_size > 0:
                    with open(self.file, 'r') as f: return json.load(f)
                else: return {}
            except: return {}
        return {}
    def _save(self): 
        temp_cache = self.cache.copy()
        temp_cache[self.CLEANUP_KEY] = self.last_cleanup_date_gmt
        json.dump(temp_cache, open(self.file,'w'), indent=2)
    def _cleanup(self):
        now_gmt = datetime.now(timezone.utc).strftime('%Y%m%d')
        if now_gmt > self.last_cleanup_date_gmt:
            self.cache = {} 
            self.last_cleanup_date_gmt = now_gmt
            self._save()
        else: self._save()
    def key(self, d: Dict[str, Any]) -> str: 
        return f"{d.get('otp')}_{d.get('phone')}"
    def is_dup(self, d: Dict[str, Any]) -> bool:
        self._cleanup() 
        key = self.key(d)
        if not key or key.split('_')[0] == 'None': return False 
        return key in self.cache
    def add(self, d: Dict[str, Any]):
        key = self.key(d)
        if not key or key.split('_')[0] == 'None': return
        self.cache[key] = {'timestamp':datetime.now().isoformat()} 
        self._save()
    def filter(self, lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for d in lst:
            if d.get('otp') and d.get('phone') != 'N/A':
                if not self.is_dup(d):
                    out.append(d)
                    self.add(d) 
        return out

otp_filter = OTPFilter()

def send_tg(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use: return
    payload = {'chat_id': chat_id_to_use, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard:
        payload['reply_markup'] = create_inline_keyboard()
    try:
        requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", data=payload, timeout=15)
    except: pass

def send_photo_tg(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use: return False
    url = f"https://api.telegram.org/bot{BOT}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use, 'caption': caption, 'parse_mode': 'HTML'}
            response = requests.post(url, files=files, data=data, timeout=20)
        return response.ok
    except: return False

# ================= Scraper & Monitor Class =================

class SMSMonitor:
    def __init__(self, url=DASHBOARD_URL): 
        self.url = url
        self.browser = None
        self.page = None
        self.is_logged_in = False 
        self._temp_username = None 
        self._temp_password = None 

    async def initialize(self, p_instance):
        self.browser = await p_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = self.browser.contexts[0]
        # UPDATE: Memberikan izin clipboard
        await context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.page = await context.new_page()
        print("✅ Playwright page connected successfully.")

    async def check_url_login_status(self) -> bool:
        if not self.page:
            self.is_logged_in = False
            return False
        try:
            current_url = self.page.url
            self.is_logged_in = current_url.startswith("https://x.mnitnetwork.com/mdashboard")
        except:
            self.is_logged_in = False
        return self.is_logged_in

    async def login(self):
        if not self.page: raise Exception("Page not initialized.")
        u, p = self._temp_username, self._temp_password
        if not u or not p: raise Exception("No credentials.")
        await self.page.goto(LOGIN_URL, wait_until='load', timeout=15000) 
        await self.page.wait_for_selector('input[type="email"]', timeout=10000) 
        await self.page.type('input[type="email"]', u, delay=100) 
        await self.page.type('input[type="password"]', p, delay=100)
        await self.page.click('button[type="submit"]') 
        try:
            await self.page.wait_for_url(re.compile(r".*/mdashboard.*"), timeout=30000) 
            self.is_logged_in = True
            self._temp_username = self._temp_password = None
            return True
        except Exception as e:
            self.is_logged_in = False
            shot = f"fail_{int(time.time())}.png"
            await self.page.screenshot(path=shot)
            send_photo_tg(shot, f"❌ Login Fail: {str(e)[:100]}", ADMIN_ID)
            if os.path.exists(shot): os.remove(shot)
            raise e

    async def login_and_notify(self, admin_chat_id):
        try:
            if await self.login():
                send_tg("✅ Login success! Use /startnew", target_chat_id=admin_chat_id)
        except Exception as e:
            send_tg(f"❌ Login Failed: {str(e)}", target_chat_id=admin_chat_id)

    # 🎯 UPDATE LOGIKA FETCH SMS (Script Asli Anda di-update untuk Handle Clipboard)
    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page or not self.is_logged_in: return []
        if self.page.url != self.url:
            try: await self.page.goto(self.url, wait_until='domcontentloaded')
            except: return []

        # Ambil semua baris tabel
        rows = await self.page.query_selector_all("tbody tr")
        messages = []

        for row in rows:
            # Cari indikator status success
            status_el = await row.query_selector("span.uppercase")
            status_text = await status_el.inner_text() if status_el else ""
            if "SUCCESS" not in status_text.upper(): continue

            # Ambil Nomor HP & OTP Mentah dari layar
            phone_el = await row.query_selector("span.font-mono")
            phone_raw = await phone_el.inner_text() if phone_el else "N/A"
            
            otp_el = await row.query_selector("span.tracking-widest")
            otp_raw = await otp_el.inner_text() if otp_el else ""

            country_el = await row.query_selector("td:nth-child(2) span")
            country_text = await country_el.inner_text() if country_el else "N/A"

            # KLIK TOMBOL COPY UNTUK MENDAPATKAN PESAN FULL
            raw_message_full = f"OTP: {otp_raw}" # Fallback
            copy_btn = await row.query_selector("button[title*='Copy']")
            if copy_btn:
                try:
                    await copy_btn.click()
                    await asyncio.sleep(0.5) # Jeda agar JS selesai copy
                    raw_message_full = await self.page.evaluate("navigator.clipboard.readText()")
                except: pass

            # Ekstrak OTP dari pesan yang baru didapat
            otp = extract_otp_from_text(raw_message_full) or otp_raw
            
            if otp and phone_raw != 'N/A':
                messages.append({
                    "otp": otp,
                    "phone": clean_phone_number(phone_raw),
                    "service": clean_service_name(raw_message_full),
                    "range": country_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "raw_message": raw_message_full
                })
        return messages

    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page or not self.is_logged_in: return False
        shot = f"shot_{int(time.time())}.png"
        try:
            await self.page.reload(wait_until='networkidle') 
            await self.page.screenshot(path=shot, full_page=True)
            send_photo_tg(shot, f"📸 Refreshed at {datetime.now().strftime('%H:%M:%S')}", admin_chat_id)
            return True
        except: return False
        finally:
            if os.path.exists(shot): os.remove(shot)

monitor = SMSMonitor()

# ================= Status & Loop (Struktur Asli Anda) =================
start = time.time()
total_sent = 0
BOT_STATUS = {"status": "Init", "uptime": "--", "total_otps_sent": 0, "last_check": "Never", "cache_size": 0, "monitoring_active": False, "last_cleanup_gmt_date": "N/A"}

def update_global_status():
    global total_sent
    uptime_sec = time.time() - start
    BOT_STATUS["uptime"] = f"{int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] and monitor.is_logged_in else "Paused"
    BOT_STATUS["last_cleanup_gmt_date"] = otp_filter.last_cleanup_date_gmt 
    return BOT_STATUS

def check_cmd(stats):
    global LAST_ID, AWAITING_CREDENTIALS
    if not ADMIN_ID: return
    try:
        upd = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=5).json()
        for u in upd.get("result",[]):
            LAST_ID = u["update_id"]
            msg = u.get("message",{})
            text, user_id, chat_id = msg.get("text",""), msg.get("from",{}).get("id"), msg.get("chat",{}).get("id")
            if user_id != ADMIN_ID: continue

            if AWAITING_CREDENTIALS:
                parts = text.split()
                if len(parts) == 2:
                    monitor._temp_username, monitor._temp_password = parts[0], parts[1]
                    AWAITING_CREDENTIALS = False
                    send_tg("⏳ Logging in...", target_chat_id=chat_id)
                    asyncio.run_coroutine_threadsafe(monitor.login_and_notify(chat_id), GLOBAL_ASYNC_LOOP)
                else: send_tg("Format: Email Password", target_chat_id=chat_id)
                continue

            if text == "/status": send_tg(get_status_message(stats), target_chat_id=chat_id)
            elif text == "/refresh": asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(chat_id), GLOBAL_ASYNC_LOOP)
            elif text == "/login":
                AWAITING_CREDENTIALS = True
                send_tg("Kirim Email dan Password:", target_chat_id=chat_id)
            elif text == "/startnew":
                BOT_STATUS["monitoring_active"] = True
                send_tg("▶️ Started", target_chat_id=chat_id)
            elif text == "/stop":
                BOT_STATUS["monitoring_active"] = False
                send_tg("⏸️ Stopped", target_chat_id=chat_id)
    except: pass

async def monitor_sms_loop():
    global total_sent
    async with async_playwright() as p:
        try: await monitor.initialize(p)
        except: return
        send_tg("✅ Bot Online. Use /login", target_chat_id=ADMIN_ID)
        while True:
            try:
                await monitor.check_url_login_status() 
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    msgs = await monitor.fetch_sms()
                    new = otp_filter.filter(msgs)
                    for item in new:
                        save_otp_to_json(item)
                        send_tg(format_otp_message(item), with_inline_keyboard=True)
                        total_sent += 1
                        await asyncio.sleep(2) 
            except: pass
            check_cmd(update_global_status())
            await asyncio.sleep(5) 

# ================= Flask (Struktur Asli Anda) =================
app = Flask(__name__)
@app.route('/api/status')
def api_status(): return jsonify(update_global_status())

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    GLOBAL_ASYNC_LOOP = loop 
    Thread(target=run_flask, daemon=True).start()
    try: loop.run_until_complete(monitor_sms_loop())
    except KeyboardInterrupt: pass
