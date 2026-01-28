import asyncio
from playwright.async_api import async_playwright 
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import re
import json
import os
import requests
import time
import html  
from dotenv import load_dotenv
import socket
from threading import Thread, current_thread
from typing import Dict, Any, List

# --- Import Flask ---
from flask import Flask, jsonify, render_template
# --------------------

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

# --- Network Configuration ---
LOGIN_URL = "https://x.mnitnetwork.com/mauth/login" 
DASHBOARD_URL = "https://x.mnitnetwork.com/mdashboard/getnum" 

LAST_ID = 0
OTP_SAVE_FOLDER = os.path.join("..", "get")
OTP_SAVE_FILE = os.path.join(OTP_SAVE_FOLDER, "smc.json")
WAIT_JSON_FILE = os.path.join(OTP_SAVE_FOLDER, "wait.json") 

GLOBAL_ASYNC_LOOP = None 
AWAITING_CREDENTIALS = False 

# ================= Utils =================

COUNTRY_EMOJI = {
    "AFGHANISTAN": "🇦🇫", "ALBANIA": "🇦🇱", "ALGERIA": "🇩🇿", "ANDORRA": "🇦🇩", "ANGOLA": "🇦🇴",
  "ANTIGUA AND BARBUDA": "🇦🇬", "ARGENTINA": "🇦🇷", "ARMENIA": "🇦🇲", "AUSTRALIA": "🇦🇺", "AUSTRIA": "🇦🇹",
  "AZERBAIJAN": "🇦🇿", "BAHAMAS": "🇧🇸", "BAHRAIN": "🇧🇭", "BANGLADESH": "🇧🇩", "BARBADOS": "🇧🇧",
  "BELARUS": "🇧🇾", "BELGIUM": "🇧🇪", "BELIZE": "🇧🇿", "BENIN": "🇧🇯", "BHUTAN": "🇧🇹",
  "BOLIVIA": "🇧🇴", "BOSNIA AND HERZEGOVINA": "🇧🇦", "BOTSWANA": "🇧🇼", "BRAZIL": "🇧🇷", "BRUNEI": "🇧🇳",
  "BULGARIA": "🇧🇬", "BURKINA FASO": "🇧🇫", "BURUNDI": "🇧🇮", "CAMBODIA": "🇰🇭", "CAMEROON": "🇨🇲",
  "CANADA": "🇨🇦", "CAPE VERDE": "🇨🇻", "CENTRAL AFRICAN REPUBLIC": "🇨🇫", "CHAD": "🇹🇩", "CHILE": "🇨🇱",
  "CHINA": "🇨🇳", "COLOMBIA": "🇨🇴", "COMOROS": "🇰🇲", "CONGO": "🇨🇬", "COSTA RICA": "🇨🇷",
  "CROATIA": "🇭🇷", "CUBA": "🇨🇺", "CYPRUS": "🇨🇾", "CZECH REPUBLIC": "🇨🇿", "IVORY COAST": "🇨🇮",
  "DENMARK": "🇩🇰", "DJIBOUTI": "🇩🇯", "DOMINICA": "🇩🇲", "DOMINICAN REPUBLIC": "🇩🇴", "ECUADOR": "🇪🇨",
  "EGYPT": "🇪🇬", "EL SALVADOR": "🇸🇻", "EQUATORIAL GUINEA": "🇬🇶", "ERITREA": "🇪🇷", "ESTONIA": "🇪🇪",
  "ESWATINI": "🇸🇿", "ETHIOPIA": "🇪🇹", "FIJI": "🇫🇯", "FINLAND": "🇫🇮", "FRANCE": "🇫🇷",
  "GABON": "🇬🇦", "GAMBIA": "🇬🇲", "GEORGIA": "🇬🇪", "GERMANY": "🇩🇪", "GHANA": "🇬🇭",
  "GREECE": "🇬🇷", "GRENADA": "🇬🇹", "GUATEMALA": "🇬🇹", "GUINEA REPUBLIC": "🇬🇳", "GUINEA-BISSAU": "🇬🇼",
  "GUYANA": "🇬🇾", "HAITI": "🇭🇹", "HONDURAS": "🇭🇳", "HUNGARY": "🇭🇺", "ICELAND": "🇮🇸",
  "INDIA": "🇮🇳", "INDONESIA": "🇮🇩", "IRAN": "🇮🇷", "IRAQ": "🇮🇶", "IRELAND": "🇮🇪",
  "ISRAEL": "🇮🇱", "ITALY": "🇮🇹", "JAMAICA": "🇯🇲", "JAPAN": "🇯🇵", "JORDAN": "🇯🇴",
  "KAZAKHSTAN": "🇰🇿", "KENYA": "🇰🇪", "KIRIBATI": "🇰🇮", "KUWAIT": "🇰🇼", "KYRGYZSTAN": "🇰🇬",
  "LAOS": "🇱🇦", "LATVIA": "🇱🇻", "LEBANON": "🇱🇧", "LESOTHO": "🇱🇸", "LIBERIA": "🇱🇷",
  "LIBYA": "🇱🇾", "LIECHTENSTEIN": "🇱🇮", "LITHUANIA": "🇱🇹", "LUXEMBOURG": "🇱🇺", "MADAGASCAR": "🇲🇬",
  "MALAWI": "🇲🇼", "MALAYSIA": "🇲🇾", "MALDIVES": "🇲🇻", "MALI": "🇲🇱", "MALTA": "🇲🇹",
  "MARSHALL ISLANDS": "🇲🇭", "MAURITANIA": "🇲🇷", "MAURITIUS": "🇲🇺", "MEXICO": "🇲🇽", "MICRONESIA": "🇫🇲",
  "MOLDOVA": "🇲🇩", "MONACO": "🇲🇨", "MONGOLIA": "🇲🇳", "MONTENEGRO": "🇲🇪", "MOROCCO": "🇲🇦",
  "MOZAMBIQUE": "🇲🇿", "MYANMAR": "🇲🇲", "NAMIBIA": "🇳🇦", "NAURU": "🇳🇷", "NEPAL": "🇳🇵",
  "NETHERLANDS": "🇳🇱", "NEW ZEALAND": "🇳🇿", "NICARAGUA": "🇳🇮", "NIGER": "🇳🇪", "NIGERIA": "🇳🇬",
  "NORTH KOREA": "🇰🇵", "NORTH MACEDONIA": "🇲🇰", "NORWAY": "🇳🇴", "OMAN": "🇴🇲", "PAKISTAN": "🇵🇰",
  "PALAU": "🇵🇼", "PALESTINE": "🇵🇸", "PANAMA": "🇵🇦", "PAPUA NEW GUINEA": "🇵🇬", "PARAGUAY": "🇵🇾",
  "PERU": "🇵🇪", "PHILIPPINES": "🇵🇭", "POLAND": "🇵🇱", "PORTUGAL": "🇵🇹", "QATAR": "🇶🇦",
  "ROMANIA": "🇷🇴", "RUSSIA": "🇷🇺", "RWANDA": "🇷🇼", "SAINT KITTS AND NEVIS": "🇰🇳", "SAINT LUCIA": "🇱🇨",
  "SAINT VINCENT AND THE GRENADINES": "🇻🇨", "SAMOA": "🇼🇸", "SAN MARINO": "🇸🇲", "SAO TOME AND PRINCIPE": "🇸🇹",
  "SAUDI ARABIA": "🇸🇦", "SENEGAL": "🇸🇳", "SERBIA": "🇷🇸", "SEYCHELLES": "🇸🇨", "SIERRA LEONE": "🇸🇱",
  "SINGAPORE": "🇸🇬", "SLOVAKIA": "🇸🇰", "SLOVENIA": "🇸🇮", "SOLOMON ISLANDS": "🇸🇧", "SOMALIA": "🇸🇴",
  "SOUTH AFRICA": "🇿🇦", "SOUTH KOREA": "🇰🇷", "SOUTH SUDAN": "🇸🇸", "SPAIN": "🇪🇸", "SRI LANKA": "🇱🇰", 
  "SUDAN": "🇸🇩", "SURINAME": "🇸🇷", "SWEDEN": "🇸🇪", "SWITZERLAND": "🇨🇭", "SYRIA": "🇸🇾",
  "TAJIKISTAN": "🇹🇯", "TANZANIA": "🇹🇿", "THAILAND": "🇹🇭", "TIMOR-LESTE": "🇹🇱", "TOGO": "🇹🇬",
  "TONGA": "🇹🇴", "TRINIDAD AND TOBAGO": "🇹🇹", "TUNISIA": "🇹🇳", "TURKEY": "🇹🇷", "TURKMENISTAN": "🇹🇲",
  "TUVALU": "🇹🇻", "UGANDA": "🇺🇬", "UKRAINE": "🇺🇦", "UNITED ARAB EMIRATES": "🇦🇪", "UNITED KINGDOM": "🇬🇧",
  "UNITED STATES": "🇺🇸", "URUGUAY": "🇺🇾", "UZBEKISTAN": "🇺🇿", "VANUATU": "🇻🇺", "VATICAN CITY": "🇻🇦",
  "VENEZUELA": "🇻🇪", "VIETNAM": "🇻🇳", "YEMEN": "🇾🇪", "ZAMBIA": "🇿🇲", "ZIMBABWE": "🇿🇼", "KOSOVO": "🇽🇰"
}

def get_country_emoji(country_name: str) -> str:
    return COUNTRY_EMOJI.get(country_name.strip().upper(), "🌍")

def get_user_data(phone_number: str) -> Dict[str, Any]:
    if not os.path.exists(WAIT_JSON_FILE): return {"username": "unknown", "user_id": None}
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

def mask_phone_number_zura(phone):
    if not phone or phone == "N/A": return phone
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) < 7: return phone
    prefix = phone[0] if phone.startswith('+') else ""
    return f"{prefix}{digits[:5]}***{digits[-4:]}"

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    otp, phone = otp_data.get('otp', 'N/A'), otp_data.get('phone', 'N/A')
    user_info = get_user_data(phone)
    user_tag = f"@{user_info['username'].replace('@', '')}" if user_info['username'] != "unknown" else "unknown"
    raw_msg = html.escape(otp_data.get('raw_message', 'No message content'))

    return (
        f"💭 <b>New Message Received</b>\n\n"
        f"<b>👤 User:</b> {user_tag}\n"
        f"<b>📱 Number:</b> <code>{mask_phone_number_zura(phone)}</code>\n"
        f"<b>🌍 Country:</b> <b>{otp_data.get('range')} {get_country_emoji(otp_data.get('range', ''))}</b>\n"
        f"<b>✅ Service:</b> <b>{otp_data.get('service')}</b>\n\n"
        f"🔐 OTP: <code>{otp}</code>\n\n"
        f"<b>FULL MESSAGE:</b>\n"
        f"<blockquote>{raw_msg}</blockquote>"
    )

def extract_otp_from_text(text):
    if not text: return None
    # Pattern 1: Mencari format 123-456 atau 123 456 (Biasanya WhatsApp)
    # Pattern 2: Mencari kata kunci "kode" atau "otp" diikuti angka
    # Pattern 3: Mencari angka berurutan 4-8 digit
    patterns = [
        r'(\d{3}[\s-]\d{3})',  # Menangkap format WhatsApp 123-456
        r'(?:code|otp|kode)[:\s]*([\d\s-]+)', 
        r'\b(\d{4,8})\b'
    ]
    
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            # Hilangkan semua karakter non-digit agar menjadi angka polos (913946)
            otp = re.sub(r'[^\d]', '', m.group(1) if m.groups() else m.group(0))
            if otp: return otp
    return None

def save_otp_to_json(otp_data: Dict[str, Any]):
    """
    Menyimpan data OTP ke file JSON dengan format yang diminta:
    service, number, otp, dan full message.
    """
    if not os.path.exists(OTP_SAVE_FOLDER): os.makedirs(OTP_SAVE_FOLDER)
    
    # Format data sesuai request
    data = {
        "service": otp_data.get('service', 'Unknown'),
        "number": otp_data.get('phone', 'N/A'),
        "otp": otp_data.get('otp', 'N/A'),
        "full_message": otp_data.get('raw_message', '')
    }
    
    try:
        existing = []
        if os.path.exists(OTP_SAVE_FILE) and os.stat(OTP_SAVE_FILE).st_size > 0:
            with open(OTP_SAVE_FILE, 'r') as f: existing = json.load(f)
        existing.append(data)
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

# ================= SMS Monitor Class =================

class SMSMonitor:
    def __init__(self, url=DASHBOARD_URL): 
        self.url, self.browser, self.page, self.is_logged_in = url, None, None, False
        self._temp_username, self._temp_password = None, None

    async def initialize(self, p_instance):
        self.browser = await p_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        self.page = await self.browser.contexts[0].new_page() 
        print("✅ [SYSTEM] Playwright Connected.")

    async def check_url_login_status(self) -> bool:
        if not self.page: return False
        try:
            self.is_logged_in = "mdashboard" in self.page.url
            return self.is_logged_in
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

    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page or not self.is_logged_in: return []
        messages = []
        try:
            async with self.page.expect_response(lambda r: "/getnum/info" in r.url, timeout=5000) as resp_info:
                try: await self.page.click('th:has-text("Number Info")', timeout=1000)
                except: await self.page.reload(wait_until='domcontentloaded')

                response = await resp_info.value
                json_data = await response.json()
                
                numbers = json_data.get('data', {}).get('numbers', [])
                for item in numbers:
                    if item.get('status') == 'success' and item.get('message'):
                        raw_msg = item.get('message')
                        messages.append({
                            "otp": extract_otp_from_text(raw_msg),
                            "phone": "+" + str(item.get('number')),
                            "service": item.get('full_number') or "Facebook",
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
            await self.page.screenshot(path=path, full_page=True)
            send_photo_tg(path, f"✅ Live Screen: <code>{datetime.now().strftime('%H:%M:%S')}</code>", target_chat_id=admin_chat_id)
            return True
        except: return False
        finally:
            if os.path.exists(path): os.remove(path)

monitor = SMSMonitor()

# ================= COMBO DETECTION LOGIC =================

async def wait_for_realtime_change(page):
    try:
        await page.wait_for_selector('tbody', timeout=30000)
        return await page.evaluate('''
            () => {
                return new Promise((resolve) => {
                    const target = document.querySelector('tbody');
                    if (!target) { resolve(false); return; }
                    const observer = new MutationObserver(() => {
                        observer.disconnect();
                        resolve(true);
                    });
                    observer.observe(target, { childList: true, subtree: true });
                    setTimeout(() => { observer.disconnect(); resolve(false); }, 15000); // Wait 15s for change
                });
            }
        ''')
    except: return False

# ================= Telegram & Status Logic =================

start, total_sent = time.time(), 0
BOT_STATUS = {"status": "Starting", "uptime": "--", "total_otps_sent": 0, "monitoring_active": False}

def send_tg(text, with_inline_keyboard=False, target_chat_id=None, otp_code=None):
    cid = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not cid: return
    payload = {'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard and otp_code: payload['reply_markup'] = create_inline_keyboard(otp_code)
    try:
        res = requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json=payload, timeout=15)
        if res.status_code == 200:
            print(f"✅ [TERMINAL] Pesan terkirim ke {cid}")
        else:
            print(f"❌ [TERMINAL] Gagal Telegram: {res.text}")
    except Exception as e:
        print(f"⚠️ [TERMINAL] Error Telegram: {e}")

def send_photo_tg(path, caption, target_chat_id):
    try:
        with open(path, 'rb') as f:
            requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto", 
                          data={'chat_id': target_chat_id, 'caption': caption, 'parse_mode': 'HTML'}, files={'photo': f}, timeout=20)
    except: pass

def check_cmd():
    global LAST_ID, AWAITING_CREDENTIALS
    try:
        upd = requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}", timeout=5).json()
        for u in upd.get("result", []):
            LAST_ID = u["update_id"]
            m = u.get("message", {})
            text, user_id = m.get("text", ""), m.get("from", {}).get("id")
            if user_id != ADMIN_ID: continue

            if AWAITING_CREDENTIALS:
                parts = text.split()
                if len(parts) == 2:
                    monitor._temp_username, monitor._temp_password = parts[0], parts[1]
                    AWAITING_CREDENTIALS = False
                    asyncio.run_coroutine_threadsafe(monitor.login_and_notify(user_id), GLOBAL_ASYNC_LOOP)
                continue

            if text == "/status":
                upt = str(timedelta(seconds=int(time.time() - start)))
                msg = f"🤖 <b>Bot Zura Status</b>\n⚡ Live: {'✅' if BOT_STATUS['monitoring_active'] else '⏸️'}\nUptime: <code>{upt}</code>\nTotal Sent: <b>{total_sent}</b>"
                send_tg(msg, target_chat_id=user_id)
            elif text == "/login": AWAITING_CREDENTIALS = True; send_tg("🔑 Email Password (spasi):", target_chat_id=user_id)
            elif text == "/startnew": BOT_STATUS["monitoring_active"] = True; send_tg("▶️ Real-time Mode Started.", target_chat_id=user_id)
            elif text == "/stop": BOT_STATUS["monitoring_active"] = False; send_tg("⏸️ Monitoring Stopped.", target_chat_id=user_id)
            elif text == "/refresh": asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(user_id), GLOBAL_ASYNC_LOOP)
    except: pass

# ================= MAIN LOOP =================

async def monitor_sms_loop():
    global total_sent
    async with async_playwright() as p:
        try:
            await monitor.initialize(p)
            print("🚀 [SYSTEM] Bot Active.")
        except Exception as e:
            print(f"🚨 [FATAL] Error: {e}")
            return

        send_tg("✅ <b>BOT ZURA ACTIVE (REAL-TIME MODE)</b>", target_chat_id=ADMIN_ID)
        
        while True:
            try:
                await monitor.check_url_login_status() 
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    # LOGIKA PENYISIRAN (FORCE CHECK SETIAP PERUBAHAN ATAU POLLING)
                    print(f"🔍 [MONITOR] Memeriksa tabel dan menunggu update... ({datetime.now().strftime('%H:%M:%S')})", end="\r")
                    
                    # Ambil data saat ini
                    msgs = await monitor.fetch_sms()
                    new_otps = otp_filter.filter(msgs) # Saring yang belum ada di otp_cache.json
                    
                    if new_otps:
                        print(f"\n📩 [NEW/PENDING] Menemukan {len(new_otps)} OTP yang belum terkirim!")
                        for otp_data in new_otps:
                            save_otp_to_json(otp_data)
                            send_tg(format_otp_message(otp_data), with_inline_keyboard=True, otp_code=otp_data['otp'])
                            total_sent += 1
                            await asyncio.sleep(1)
                    
                    # Tunggu perubahan real-time
                    await wait_for_realtime_change(monitor.page)
                else:
                    print("💤 [STATUS] Bot Paused.", end="\r")
            except Exception as e:
                print(f"\n⚠️ [ERROR] Loop Error: {e}")

            check_cmd()
            await asyncio.sleep(0.5) 

# ================= FLASK =================
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Running"

if __name__ == "__main__":
    GLOBAL_ASYNC_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(GLOBAL_ASYNC_LOOP)
    Thread(target=lambda: app.run(host='0.0.0.0', port=5000), daemon=True).start()
    GLOBAL_ASYNC_LOOP.run_until_complete(monitor_sms_loop())
