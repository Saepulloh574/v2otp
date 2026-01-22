import asyncio
from playwright.async_api import async_playwright 
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
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

LAST_ID = 0

# ================= Konfigurasi File Path =================
OTP_SAVE_FOLDER = os.path.join("..", "get")
OTP_SAVE_FILE = os.path.join(OTP_SAVE_FOLDER, "smc.json")
WAIT_JSON_FILE = os.path.join(OTP_SAVE_FOLDER, "wait.json") 

# ================= Global State for Asyncio Loop & Command =================
GLOBAL_ASYNC_LOOP = None 
AWAITING_CREDENTIALS = False 

# ================= Utils =================

COUNTRY_EMOJI = {
    "NEPAL": "🇳🇵", "IVORY COAST": "🇨🇮", "GUINEA": "🇬🇳",
    "CENTRAL AFRIKA": "🇨🇫", "CENTRAL AFRICAN REPUBLIC": "🇨🇫",
    "TOGO": "🇹🇬", "TAJIKISTAN": "🇹🇯", "BENIN": "🇧🇯",
    "SIERRA LEONE": "🇸🇱", "MADAGASCAR": "🇲🇬", "AFGANISTAN": "🇦🇫",
    "ZURA STORE": "🇮🇩", "LEBANON": "🇱🇧", "QATAR": "🇶🇦", "INDONESIA": "🇮🇩"
}

def get_country_emoji(country_name: str) -> str:
    return COUNTRY_EMOJI.get(country_name.strip().upper(), "🌍")

def get_user_data(phone_number: str) -> Dict[str, Any]:
    if not os.path.exists(WAIT_JSON_FILE):
        return {"username": "unknown", "user_id": None}
    try:
        with open(WAIT_JSON_FILE, 'r') as f:
            wait_list = json.load(f)
            clean_target = re.sub(r'[^\d]', '', phone_number)
            for entry in wait_list:
                clean_entry = re.sub(r'[^\d]', '', str(entry.get("number", "")))
                if clean_target == clean_entry:
                    return {"username": entry.get("username", "unknown"), "user_id": entry.get("user_id")}
    except: pass
    return {"username": "unknown", "user_id": None}

def create_inline_keyboard(otp: str):
    keyboard = {
        "inline_keyboard": [
            [{"text": f"{otp}", "copy_text": {"text": otp}}, {"text": "🎭 Owner", "url": TELEGRAM_ADMIN_LINK}],
            [{"text": "📞 Get Number", "url": TELEGRAM_BOT_LINK}]
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
    if not phone or phone == "N/A": return phone
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) < 7: return phone
    prefix = "+" if phone.startswith('+') else ""
    return f"{prefix}{digits[:5]}***{digits[-4:]}"

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    masked_phone = mask_phone_number_zura(phone)
    service = otp_data.get('service', 'Facebook')
    range_text = otp_data.get('range', 'N/A')
    emoji = get_country_emoji(range_text)
    user_info = get_user_data(phone)
    user_tag = f"@{user_info['username'].replace('@', '')}" if user_info['username'] != "unknown" else "unknown"
    
    return (
        f"💭 <b>New Message Received</b>\n\n"
        f"<b>👤 User:</b> {user_tag}\n"
        f"<b>📱 Number:</b> <code>{masked_phone}</code>\n"
        f"<b>🌍 Country:</b> <b>{range_text} {emoji}</b>\n"
        f"<b>✅ Service:</b> <b>{service}</b>\n\n"
        f"🔐 OTP: <code>{otp}</code>\n\n"
        f"💸 <i>Greetings From ZuraStore </i> 💸"
    )

def extract_otp_from_text(text):
    if not text: return None
    patterns = [ 
        r'<#>\s*([\d\s-]+)\s*—', r'code[:\s]*([\d\s-]+)',  
        r'verification[:\s]*([\d\s-]+)', r'otp[:\s]*([\d\s-]+)',   
        r'\b(\d{4,8})\b', 
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            matched = re.sub(r'[^\d]', '', m.group(1) if m.groups() else m.group(0))
            if matched: return matched
    return None

def save_otp_to_json(otp_data: Dict[str, Any]):
    if not os.path.exists(OTP_SAVE_FOLDER): os.makedirs(OTP_SAVE_FOLDER)
    data_to_save = {"Number": otp_data.get('phone'), "OTP": otp_data.get('otp'), "FullMessage": otp_data.get('raw_message')}
    try:
        existing = []
        if os.path.exists(OTP_SAVE_FILE) and os.stat(OTP_SAVE_FILE).st_size > 0:
            with open(OTP_SAVE_FILE, 'r') as f: existing = json.load(f)
        existing.append(data_to_save)
        with open(OTP_SAVE_FILE, 'w') as f: json.dump(existing, f, indent=2)
    except: pass

# ================= OTP Filter Class =================

class OTPFilter:
    CLEANUP_KEY = '__LAST_CLEANUP_GMT__' 
    def __init__(self, file='otp_cache.json'): 
        self.file = file
        self.cache = self._load()
        self.last_cleanup_date_gmt = self.cache.pop(self.CLEANUP_KEY, '19700101') 
        self._cleanup() 
        
    def _load(self):
        if os.path.exists(self.file):
            try: return json.load(open(self.file, 'r'))
            except: return {}
        return {}
        
    def _save(self): 
        temp = self.cache.copy()
        temp[self.CLEANUP_KEY] = self.last_cleanup_date_gmt
        json.dump(temp, open(self.file,'w'), indent=2)
    
    def _cleanup(self):
        now_gmt = datetime.now(timezone.utc).strftime('%Y%m%d')
        if now_gmt > self.last_cleanup_date_gmt:
            self.cache = {}; self.last_cleanup_date_gmt = now_gmt
            self._save()
        
    def filter(self, lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for d in lst:
            key = f"{d.get('otp')}_{d.get('phone')}"
            if d.get('otp') and key not in self.cache:
                self.cache[key] = {'t': datetime.now().isoformat()}
                out.append(d)
        self._save()
        return out

otp_filter = OTPFilter()

# ================= SMS Monitor (Interceptor Version) =================

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
        # MEMBUKA TAB BARU SESUAI PERMINTAAN
        self.page = await self.browser.contexts[0].new_page()
        print("🚀 Playwright: New Tab Opened & Connected.")

    async def check_url_login_status(self) -> bool:
        if not self.page: return False
        try: return "mdashboard" in self.page.url
        except: return False

    async def login(self):
        if not self.page: raise Exception("Page not initialized.")
        await self.page.goto(LOGIN_URL, wait_until='load', timeout=15000) 
        await self.page.type('input[type="email"]', self._temp_username) 
        await self.page.type('input[type="password"]', self._temp_password)
        await self.page.click('button[type="submit"]') 
        try:
            await self.page.wait_for_url(re.compile(r".*/mdashboard.*"), timeout=30000) 
            self.is_logged_in = True
            return True
        except: return False

    async def login_and_notify(self, admin_chat_id):
        try:
            if await self.login():
                await self.refresh_and_screenshot(admin_chat_id)
                send_tg(f"✅ Login berhasil! Gunakan: <code>/startnew</code>", target_chat_id=admin_chat_id)
        except Exception as e:
            send_tg(f"❌ Login GAGAL: <code>{str(e)[:50]}</code>", target_chat_id=admin_chat_id)

    # 🎯 PERBAIKAN UTAMA: MENGGUNAKAN INTERCEPTOR UNTUK FULL MESSAGE
    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page or not self.is_logged_in: return []
        
        messages = []
        try:
            # Mencegat response JSON dari API internal web
            async with self.page.expect_response(lambda r: "/getnum/info" in r.url, timeout=12000) as resp_info:
                # Memicu AJAX update dengan klik header tabel (cara halus)
                try:
                    await self.page.click('th:has-text("Number Info")', timeout=2000)
                except:
                    await self.page.reload(wait_until='domcontentloaded')

                response = await resp_info.value
                json_data = await response.json()
                
                numbers = json_data.get('data', {}).get('numbers', [])
                for item in numbers:
                    if item.get('status') == 'success' and item.get('message'):
                        raw_msg = item.get('message')
                        messages.append({
                            "otp": extract_otp_from_text(raw_msg),
                            "phone": "+" + str(item.get('number')),
                            "service": item.get('full_number') or "Facebook", # full_number = Nama Service
                            "range": item.get('country', 'N/A'),
                            "raw_message": raw_msg
                        })
        except: pass
        return messages
    
    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page: return False
        path = f"ss_{int(time.time())}.png"
        try:
            await self.page.reload(wait_until='networkidle') 
            await self.page.screenshot(path=path)
            send_photo_tg(path, f"✅ Updated: <code>{datetime.now().strftime('%H:%M:%S')}</code>", target_chat_id=admin_chat_id)
            BOT_STATUS["last_refresh_0701"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return True
        except: return False
        finally:
            if os.path.exists(path): os.remove(path)

monitor = SMSMonitor()

# ================= Telegram & Loop Logic =================

total_sent = 0
BOT_STATUS = {"status": "Starting", "uptime": "--", "total_otps_sent": 0, "monitoring_active": False, "last_refresh_0701": "Never"}
start_time_app = time.time()

def send_tg(text, with_inline_keyboard=False, target_chat_id=None, otp_code=None):
    cid = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not cid: return
    payload = {'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard and otp_code:
        payload['reply_markup'] = create_inline_keyboard(otp_code)
    try: requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json=payload, timeout=15)
    except: pass

def send_photo_tg(path, caption, target_chat_id):
    try:
        with open(path, 'rb') as f:
            requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto", 
                          data={'chat_id': target_chat_id, 'caption': caption, 'parse_mode': 'HTML'}, files={'photo': f}, timeout=20)
    except: pass

def check_cmd():
    global LAST_ID, AWAITING_CREDENTIALS
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=10).json()
        for u in r.get("result", []):
            LAST_ID = u["update_id"]
            m = u.get("message", {})
            txt, uid = m.get("text", ""), m.get("from", {}).get("id")
            if uid != ADMIN_ID: continue

            if AWAITING_CREDENTIALS:
                parts = txt.split()
                if len(parts) == 2:
                    monitor._temp_username, monitor._temp_password = parts[0], parts[1]
                    AWAITING_CREDENTIALS = False
                    asyncio.run_coroutine_threadsafe(monitor.login_and_notify(uid), GLOBAL_ASYNC_LOOP)
                continue

            if txt == "/status":
                uptime = str(timedelta(seconds=int(time.time() - start_time_app)))
                msg = f"🤖 <b>Status</b>\nMonitoring: {'✅' if BOT_STATUS['monitoring_active'] else '⏸️'}\nUptime: <code>{uptime}</code>\nSent: <b>{total_sent}</b>"
                send_tg(msg, target_chat_id=uid)
            elif txt == "/login": AWAITING_CREDENTIALS = True; send_tg("🔑 Kirim Email Password (spasi):", target_chat_id=uid)
            elif txt == "/startnew": BOT_STATUS["monitoring_active"] = True; send_tg("▶️ Monitoring ON", target_chat_id=uid)
            elif txt == "/stop": BOT_STATUS["monitoring_active"] = False; send_tg("⏸️ Monitoring OFF", target_chat_id=uid)
            elif txt == "/refresh": asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(uid), GLOBAL_ASYNC_LOOP)
    except: pass

async def monitor_sms_loop():
    global total_sent
    async with async_playwright() as p:
        await monitor.initialize(p)
        send_tg("✅ <b>BOT ZURA ACTIVE</b>", target_chat_id=ADMIN_ID)
        while True:
            try:
                await monitor.check_url_login_status()
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    all_msgs = await monitor.fetch_sms()
                    new = otp_filter.filter(all_msgs)
                    for data in new:
                        save_otp_to_json(data)
                        send_tg(format_otp_message(data), with_inline_keyboard=True, otp_code=data['otp'])
                        total_sent += 1
                        await asyncio.sleep(2)
            except: pass
            check_cmd()
            await asyncio.sleep(10)

# ================= FLASK =================
app = Flask(__name__)
@app.route('/')
def home(): return "Zura SMS Monitor Running"

if __name__ == "__main__":
    GLOBAL_ASYNC_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(GLOBAL_ASYNC_LOOP)
    Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    GLOBAL_ASYNC_LOOP.run_until_complete(monitor_sms_loop())
