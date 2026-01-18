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
WAIT_JSON_FILE = os.path.join(OTP_SAVE_FOLDER, "wait.json") # File sumber data user
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
    "ZURA STORE": "🇮🇩",
    "LEBANON": "🇱🇧",
    "QATAR": "🇶🇦"
}

def get_country_emoji(country_name: str) -> str:
    return COUNTRY_EMOJI.get(country_name.strip().upper(), "")

def get_user_data(phone_number: str) -> Dict[str, Any]:
    """Mencari data username dari wait.json berdasarkan kecocokan nomor."""
    if not os.path.exists(WAIT_JSON_FILE):
        return {"username": "unknown", "user_id": None}
    
    try:
        with open(WAIT_JSON_FILE, 'r') as f:
            wait_list = json.load(f)
            # Bersihkan nomor HP target untuk perbandingan
            clean_target = re.sub(r'[^\d]', '', phone_number)
            
            for entry in wait_list:
                clean_entry = re.sub(r'[^\d]', '', str(entry.get("number", "")))
                if clean_target == clean_entry:
                    return {
                        "username": entry.get("username", "unknown"),
                        "user_id": entry.get("user_id")
                    }
    except Exception as e:
        print(f"❌ Error reading wait.json: {e}")
    
    return {"username": "unknown", "user_id": None}

def create_inline_keyboard(otp: str):
    """Menyusun keyboard: OTP & Owner SEJAJAR, Get Number di bawah."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"📋 {otp}", "callback_data": f"copy_{otp}"}, # Teks tombol salin
                {"text": "🎭 Owner", "url": TELEGRAM_ADMIN_LINK}
            ],
            [
                {"text": "📞 Get Number", "url": TELEGRAM_BOT_LINK}
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

def mask_phone_number_zura(phone):
    """Masking khusus format ZuraStore: +9617***7299"""
    if not phone or phone == "N/A": return phone
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) < 7: return phone
    
    prefix = phone[0] if phone.startswith('+') else ""
    start_part = digits[:5]
    end_part = digits[-4:]
    return f"{prefix}{start_part}***{end_part}"

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    """Format pesan sesuai permintaan user ZuraStore."""
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    masked_phone = mask_phone_number_zura(phone)
    service = otp_data.get('service', 'Unknown')
    range_text = otp_data.get('range', 'N/A')
    emoji = get_country_emoji(range_text)
    
    # Ambil data user dari wait.json
    user_info = get_user_data(phone)
    username = user_info['username']
    user_tag = f"@{username.replace('@', '')}" if username != "unknown" else "unknown"
    
    return (
        f"💭 <b>New Message Received</b>\n\n"
        f"<b>👤 User:</b> {user_tag}\n"
        f"<b>📱 Number:</b> <code>{masked_phone}</code>\n"
        f"<b>🌍 Country:</b> <b>{range_text} {emoji}</b>\n"
        f"<b>✅ Service:</b> <b>{service}</b>\n\n"
        f"🔐 OTP: <code>{otp}</code>\n\n"
        f"💸 <i>Greetings From ZuraStore </i> 💸"
    )

# =================================================================
# 🎯 FUNGSI UTAMA PERBAIKAN: EKSTRAKSI OTP DENGAN TANDA HUBUNG/SPASI
# =================================================================

def extract_otp_from_text(text):
    """Fungsi ekstraksi OTP yang fleksibel."""
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
        'facebook': 'Facebook', 'whatsapp': 'WhatsApp', 'instagram': 'Instagram',
        'telegram': 'Telegram', 'google': 'Google', 'twitter': 'Twitter',
        'linkedin': 'LinkedIn', 'tiktok': 'TikTok', 'mnitnetwork': 'M-NIT Network',
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
        print(f"❌ ERROR: Failed to save OTP to JSON file: {e}")

# ================= OTP Filter Class =================

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
        else:
            self._save()
        
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

# ================= Telegram Functionality =================

def send_tg(text, with_inline_keyboard=False, target_chat_id=None, otp_code=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use: return
    payload = {'chat_id': chat_id_to_use, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard and otp_code:
        payload['reply_markup'] = create_inline_keyboard(otp_code)
    try:
        requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", data=payload, timeout=15)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def send_photo_tg(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use: return False
    try:
        with open(photo_path, 'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use, 'caption': caption, 'parse_mode': 'HTML'}
            requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto", files=files, data=data, timeout=20)
        return True
    except Exception as e:
        print(f"❌ Photo Error: {e}")
        return False

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
        self.page = await context.new_page()
        print("✅ Playwright page connected successfully.")

    async def check_url_login_status(self) -> bool:
        if not self.page: return False
        try:
            current_url = self.page.url
            self.is_logged_in = current_url.startswith("https://x.mnitnetwork.com/mdashboard")
            return self.is_logged_in
        except: return False

    async def login(self):
        if not self.page: raise Exception("Page not initialized.")
        USERNAME, PASSWORD = self._temp_username, self._temp_password
        if not USERNAME or not PASSWORD: raise Exception("Credentials not found.")
        
        await self.page.goto(LOGIN_URL, wait_until='load', timeout=15000) 
        await self.page.wait_for_selector('input[type="email"]', timeout=10000) 
        await self.page.type('input[type="email"]', USERNAME, delay=100) 
        await self.page.type('input[type="password"]', PASSWORD, delay=100)
        await self.page.click('button[type="submit"]') 
        
        try:
            await self.page.wait_for_url(re.compile(r"https:\/\/x\.mnitnetwork\.com\/mdashboard.*"), timeout=30000) 
            self.is_logged_in = True
            self._temp_username = self._temp_password = None
            return True
        except Exception as e:
            self.is_logged_in = False
            raise e

    async def login_and_notify(self, admin_chat_id):
        try:
            if await self.login():
                await self.refresh_and_screenshot(admin_chat_id)
                send_tg(f"✅ Login berhasil! Mulai monitoring: <code>/startnew</code>", target_chat_id=admin_chat_id)
        except Exception as e:
            send_tg(f"❌ Login GAGAL: <code>{str(e)[:50]}</code>", target_chat_id=admin_chat_id)

    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page or not self.is_logged_in: return []
        if self.page.url != self.url:
            try: await self.page.goto(self.url, wait_until='domcontentloaded', timeout=15000)
            except: return []
                
        try: await self.page.wait_for_selector('tbody', timeout=10000)
        except: return []

        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        messages = []
        tbody = soup.find("tbody", class_="text-sm divide-y divide-white/5")
        if not tbody: return []
            
        rows = tbody.find_all("tr")
        SERVICE_KEYWORDS = r'(facebook|whatsapp|instagram|telegram|google|twitter|linkedin|tiktok)'

        for r in rows:
            tds = r.find_all("td")
            if len(tds) < 3: continue
            status_span = tds[0].find("span", class_=lambda x: x and "text-[10px]" in x)
            if not status_span or status_span.get_text(strip=True).lower() != 'success': continue
            
            phone_span = tds[0].find("span", class_=lambda x: x and "font-mono" in x)
            phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else "N/A")
            message_div = tds[0].find("div", class_=lambda x: x and "bg-slate-800" in x)
            if not message_div: continue
            
            raw_message_full = message_div.get_text(strip=True, separator=' ')
            otp = extract_otp_from_text(raw_message_full)
            range_span = tds[1].find("span", class_="text-slate-200")
            range_text = range_span.get_text(strip=True) if range_span else "N/A"
            
            service_match = re.search(SERVICE_KEYWORDS, raw_message_full, re.IGNORECASE)
            service = clean_service_name(service_match.group(1)) if service_match else clean_service_name(raw_message_full)

            if otp and phone != 'N/A':
                messages.append({
                    "otp": otp, "phone": phone, "service": service,
                    "range": range_text, "raw_message": raw_message_full
                })
        return messages
    
    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page or not self.is_logged_in: return False
        path = f"ss_{int(time.time())}.png"
        try:
            await self.page.reload(wait_until='networkidle') 
            await self.page.screenshot(path=path, full_page=True)
            send_photo_tg(path, f"✅ Reloaded at <code>{datetime.now().strftime('%H:%M:%S')}</code>", target_chat_id=admin_chat_id)
            return True
        except: return False
        finally:
            if os.path.exists(path): os.remove(path)

monitor = SMSMonitor()

# ================= Status Global =================
start = time.time()
total_sent = 0
BOT_STATUS = {"status": "Initializing...", "uptime": "--", "total_otps_sent": 0, "last_check": "Never", "cache_size": 0, "monitoring_active": False, "last_cleanup_gmt_date": "N/A"}

def update_global_status():
    global total_sent
    uptime_seconds = time.time() - start
    BOT_STATUS["uptime"] = f"{int(uptime_seconds//3600)}h {int((uptime_seconds%3600)//60)}m"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] and monitor.is_logged_in else "Paused"
    BOT_STATUS["last_cleanup_gmt_date"] = otp_filter.last_cleanup_date_gmt 
    return BOT_STATUS

def check_cmd(stats):
    global LAST_ID, AWAITING_CREDENTIALS
    if ADMIN_ID is None: return
    try:
        upd = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=15).json()
        for u in upd.get("result",[]):
            LAST_ID = u["update_id"]
            msg = u.get("message",{})
            text, user_id, chat_id = msg.get("text",""), msg.get("from", {}).get("id"), msg.get("chat", {}).get("id")
            if user_id != ADMIN_ID: continue

            if AWAITING_CREDENTIALS:
                parts = text.split() if '\n' not in text else text.split('\n')
                if len(parts) == 2:
                    monitor._temp_username, monitor._temp_password = parts[0].strip(), parts[1].strip()
                    AWAITING_CREDENTIALS = False
                    send_tg("⏳ Logging in...", target_chat_id=chat_id)
                    asyncio.run_coroutine_threadsafe(monitor.login_and_notify(chat_id), GLOBAL_ASYNC_LOOP)
                else:
                    send_tg("⚠️ Format: Email[spasi]Password", target_chat_id=chat_id)
                continue

            if text == "/status": send_tg(get_status_message(stats), target_chat_id=chat_id)
            elif text == "/refresh": asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(chat_id), GLOBAL_ASYNC_LOOP)
            elif text == "/login":
                if monitor.is_logged_in: send_tg("✅ Already logged in.", target_chat_id=chat_id)
                else: AWAITING_CREDENTIALS = True; send_tg("🔑 Send Email & Password (line separated)", target_chat_id=chat_id)
            elif text == "/startnew": BOT_STATUS["monitoring_active"] = True; send_tg("▶️ Started.", target_chat_id=chat_id)
            elif text == "/stop": BOT_STATUS["monitoring_active"] = False; send_tg("⏸️ Stopped.", target_chat_id=chat_id)
            elif text == "/clear-cache": 
                otp_filter.cache = {}; otp_filter._save()
                send_tg("🗑️ Cache cleared.", target_chat_id=chat_id)
    except: pass

async def monitor_sms_loop():
    global total_sent
    async with async_playwright() as p:
        try: await monitor.initialize(p)
        except Exception as e:
            send_tg(f"🚨 <b>Browser Error</b>: {e}", target_chat_id=ADMIN_ID)
            return 
    
        send_tg("✅ <b>BOT ZURA ACTIVE</b>\nUse <code>/login</code> then <code>/startnew</code>", target_chat_id=ADMIN_ID)
        while True:
            try:
                await monitor.check_url_login_status() 
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    msgs = await monitor.fetch_sms()
                    new = otp_filter.filter(msgs)
                    for otp_data in new:
                        save_otp_to_json(otp_data)
                        message_text = format_otp_message(otp_data)
                        send_tg(message_text, with_inline_keyboard=True, otp_code=otp_data['otp'])
                        total_sent += 1
                        await asyncio.sleep(2) 
            except: pass
            check_cmd(update_global_status())
            await asyncio.sleep(5) 

# ================= FLASK =================
app = Flask(__name__)
@app.route('/')
def index(): return "Zura SMS Monitor API"
@app.route('/api/status')
def get_status_json(): return jsonify(update_global_status())

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    if not BOT or not CHAT or not ADMIN_ID:
        print("FATAL: Check .env file.")
    else:
        GLOBAL_ASYNC_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(GLOBAL_ASYNC_LOOP)
        Thread(target=run_flask, daemon=True).start()
        try:
            GLOBAL_ASYNC_LOOP.run_until_complete(monitor_sms_loop())
        except KeyboardInterrupt:
            print("Shutdown.")
