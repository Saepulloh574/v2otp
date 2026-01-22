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
from threading import Thread
from typing import Dict, Any, List
from flask import Flask, jsonify

# Muat variabel lingkungan
load_dotenv()

# ================= Konstanta Telegram =================
TELEGRAM_BOT_LINK = "https://t.me/myzuraisgoodbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except (ValueError, TypeError):
    ADMIN_ID = None

# --- X.MNIT Network Configuration ---
LOGIN_URL = "https://x.mnitnetwork.com/mauth/login" 
DASHBOARD_URL = "https://x.mnitnetwork.com/mdashboard/getnum" 
API_INFO_URL = "https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info"

LAST_ID = 0
OTP_SAVE_FOLDER = os.path.join("..", "get")
OTP_SAVE_FILE = os.path.join(OTP_SAVE_FOLDER, "smc.json")
WAIT_JSON_FILE = os.path.join(OTP_SAVE_FOLDER, "wait.json")

GLOBAL_ASYNC_LOOP = None 
AWAITING_CREDENTIALS = False 

# ================= Utils =================

COUNTRY_EMOJI = {
    "NEPAL": "🇳🇵", "IVORY COAST": "🇨🇮", "GUINEA": "🇬🇳",
    "CENTRAL AFRIKA": "🇨🇫", "CENTRAL AFRICAN REPUBLIC": "🇨🇫", 
    "TOGO": "🇹🇬", "TAJIKISTAN": "🇹🇯", "BENIN": "🇧🇯",
    "SIERRA LEONE": "🇸🇱", "MADAGASCAR": "🇲🇬", "AFGANISTAN": "🇦🇫",
    "LEBANON": "🇱🇧", "QATAR": "🇶🇦", "INDONESIA": "🇮🇩"
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
            [{"text": f"📋 Copy OTP: {otp}", "copy_text": {"text": otp}}, {"text": "🎭 Owner", "url": TELEGRAM_ADMIN_LINK}],
            [{"text": "📞 Get Number", "url": TELEGRAM_BOT_LINK}]
        ]
    }
    return json.dumps(keyboard)

def extract_otp_from_text(text):
    if not text: return None
    patterns = [ 
        r'code[:\s]*([\d\s-]+)', r'verification[:\s]*([\d\s-]+)', 
        r'otp[:\s]*([\d\s-]+)', r'\b(\d{4,8})\b'
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            matched = re.sub(r'[^\d]', '', m.group(1) if m.groups() else m.group(0))
            if matched: return matched
    return None

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    phone = otp_data.get('phone', 'N/A')
    # Masking format: +9617***7299
    digits = re.sub(r'[^\d]', '', phone)
    masked_phone = f"+{digits[:5]}***{digits[-4:]}" if len(digits) > 8 else phone
    
    user_info = get_user_data(phone)
    user_tag = f"@{user_info['username'].replace('@', '')}" if user_info['username'] != "unknown" else "unknown"
    emoji = get_country_emoji(otp_data.get('range', ''))

    return (
        f"💭 <b>New Message Received</b>\n\n"
        f"<b>👤 User:</b> {user_tag}\n"
        f"<b>📱 Number:</b> <code>{masked_phone}</code>\n"
        f"<b>🌍 Country:</b> <b>{otp_data.get('range')} {emoji}</b>\n"
        f"<b>✅ Service:</b> <b>{otp_data.get('service')}</b>\n\n"
        f"🔐 OTP: <code>{otp_data.get('otp')}</code>\n\n"
        f"💸 <i>Greetings From ZuraStore </i> 💸"
    )

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

# ================= OTP Filter & Cache =================

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
        self._cleanup()
        out = []
        for d in lst:
            key = f"{d.get('otp')}_{d.get('phone')}"
            if d.get('otp') and key not in self.cache:
                self.cache[key] = {'t': datetime.now().isoformat()}
                out.append(d)
        self._save()
        return out

otp_filter = OTPFilter()

# ================= SMS Monitor (AJAX Interceptor) =================

class SMSMonitor:
    def __init__(self):
        self.browser = None
        self.page = None
        self.is_logged_in = False 
        self._temp_username = None 
        self._temp_password = None 

    async def initialize(self, p_instance):
        self.browser = await p_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        self.page = self.browser.contexts[0].pages[0] if self.browser.contexts[0].pages else await self.browser.contexts[0].new_page()

    async def login(self):
        if not self.page: return False
        await self.page.goto(LOGIN_URL) 
        await self.page.fill('input[type="email"]', self._temp_username)
        await self.page.fill('input[type="password"]', self._temp_password)
        await self.page.click('button[type="submit"]')
        await self.page.wait_for_url(re.compile(r".*/mdashboard.*"), timeout=20000)
        self.is_logged_in = True
        return True

    async def fetch_sms_ajax(self) -> List[Dict[str, Any]]:
        """Memicu Ajax Refresh via klik Header Tabel & Mencegat JSON."""
        if not self.page or not self.is_logged_in: return []
        
        # Pastikan di Dashboard
        if "/mdashboard" not in self.page.url:
            await self.page.goto(DASHBOARD_URL)
            await self.page.wait_for_selector('thead', timeout=10000)

        messages = []
        try:
            # 1. Pasang Listener untuk API
            async with self.page.expect_response(lambda r: "/getnum/info" in r.url, timeout=12000) as resp_info:
                # 2. Klik Header "Number Info" untuk pemicu Ajax (berdasarkan kode JS web)
                try:
                    await self.page.click('th:has-text("Number Info")', timeout=3000)
                except:
                    # Fallback: jika klik gagal, lakukan reload ringan
                    await self.page.reload(wait_until='domcontentloaded')
                
                response = await resp_info.value
                json_data = await response.json()
                
                # 3. Parsing Data JSON Sesuai Struktur Temuan
                numbers = json_data.get('data', {}).get('numbers', [])
                for item in numbers:
                    if item.get('status') == 'success' and item.get('message'):
                        raw_msg = item.get('message')
                        messages.append({
                            "otp": extract_otp_from_text(raw_msg),
                            "phone": "+" + str(item.get('number')),
                            "service": item.get('full_number') or "Facebook", # full_number = service
                            "range": item.get('country', 'N/A'),
                            "raw_message": raw_msg
                        })
        except Exception as e:
            print(f"📡 Ajax Intercept Timeout: {e}")
            
        return messages

    async def refresh_and_screenshot(self, admin_chat_id):
        path = f"ss_{int(time.time())}.png"
        await self.page.reload(wait_until='networkidle')
        await self.page.screenshot(path=path)
        send_photo_tg(path, f"📸 Dashboard Update\nTime: {datetime.now().strftime('%H:%M:%S')}", admin_chat_id)
        if os.path.exists(path): os.remove(path)

monitor = SMSMonitor()

# ================= Global Logic & Bot Commands =================

BOT_STATUS = {"status": "Starting", "total_sent": 0, "monitoring_active": False}
start_time = time.time()

def send_tg(text, with_inline_keyboard=False, target_chat_id=None, otp_code=None):
    cid = target_chat_id or CHAT
    payload = {'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard and otp_code: payload['reply_markup'] = create_inline_keyboard(otp_code)
    try: requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json=payload)
    except: pass

def send_photo_tg(path, caption, target_chat_id):
    try:
        with open(path, 'rb') as f:
            requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto", 
                          data={'chat_id': target_chat_id, 'caption': caption, 'parse_mode': 'HTML'}, files={'photo': f})
    except: pass

def check_cmd():
    global LAST_ID, AWAITING_CREDENTIALS
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=5).json()
        for u in r.get("result", []):
            LAST_ID = u["update_id"]
            m = u.get("message", {})
            txt = m.get("text", "")
            uid = m.get("from", {}).get("id")
            if uid != ADMIN_ID: continue

            if AWAITING_CREDENTIALS:
                parts = txt.split()
                if len(parts) >= 2:
                    monitor._temp_username, monitor._temp_password = parts[0], parts[1]
                    AWAITING_CREDENTIALS = False
                    send_tg("⏳ Logging in...", target_chat_id=uid)
                    asyncio.run_coroutine_threadsafe(monitor.login(), GLOBAL_ASYNC_LOOP)
                continue

            if txt == "/status":
                uptime = str(timedelta(seconds=int(time.time() - start_time)))
                status_msg = f"🤖 <b>Bot Status</b>\n\n⚡ Monitoring: {'✅ ON' if BOT_STATUS['monitoring_active'] else '⏸️ OFF'}\n🌐 Login: {'✅' if monitor.is_logged_in else '❌'}\n⏱️ Uptime: <code>{uptime}</code>\n📨 Total Sent: <b>{BOT_STATUS['total_sent']}</b>"
                send_tg(status_msg, target_chat_id=uid)
            elif txt == "/login":
                AWAITING_CREDENTIALS = True
                send_tg("🔑 Kirim Email & Password dipisah spasi:", target_chat_id=uid)
            elif txt == "/startnew":
                BOT_STATUS["monitoring_active"] = True
                send_tg("▶️ Monitoring Started (AJAX Mode)", target_chat_id=uid)
            elif txt == "/stop":
                BOT_STATUS["monitoring_active"] = False
                send_tg("⏸️ Monitoring Paused", target_chat_id=uid)
            elif txt == "/refresh":
                asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(uid), GLOBAL_ASYNC_LOOP)
    except: pass

async def monitor_sms_loop():
    async with async_playwright() as p:
        await monitor.initialize(p)
        send_tg("✅ <b>BOT ZURA ACTIVE</b>\nUse <code>/login</code> then <code>/startnew</code>", target_chat_id=ADMIN_ID)
        
        while True:
            try:
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    # Mengambil data via AJAX (Interceptor)
                    all_msgs = await monitor.fetch_sms_ajax()
                    new_msgs = otp_filter.filter(all_msgs)
                    
                    for data in new_msgs:
                        save_otp_to_json(data)
                        send_tg(format_otp_message(data), with_inline_keyboard=True, otp_code=data['otp'])
                        BOT_STATUS["total_sent"] += 1
                        await asyncio.sleep(1)
            except: pass
            
            check_cmd()
            await asyncio.sleep(12) # Jeda antar Ajax Refresh

# ================= FLASK & MAIN =================
app = Flask(__name__)
@app.route('/')
def home(): return "Zura SMS Monitor Running"

if __name__ == "__main__":
    GLOBAL_ASYNC_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(GLOBAL_ASYNC_LOOP)
    Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    GLOBAL_ASYNC_LOOP.run_until_complete(monitor_sms_loop())
