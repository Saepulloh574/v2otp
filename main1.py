import asyncio
import json
import os
import requests
import time
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from datetime import datetime, timezone 
import re
from threading import Thread
from typing import Dict, Any, List

# --- Import Flask ---
from flask import Flask, jsonify

# Muat variabel lingkungan
load_dotenv()

# ================= GLOBAL STATE & CONFIG =================
GLOBAL_ASYNC_LOOP = None 
LAST_ID_MONITOR = 0
LAST_ID_GETTER = 0
start_time = time.time()
total_sent = 0
CACHE_FILE = "cache.json"

# Konfigurasi Bot 1 (OTP Monitor - Dari .env)
BOT_MONITOR = os.getenv("TELEGRAM_BOT_TOKEN") 
CHAT_MONITOR = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", 0)) if os.getenv("TELEGRAM_ADMIN_ID") else None
URL_MNIT = "https://v2.mnitnetwork.com/dashboard/getnum" 
TELEGRAM_BOT_LINK = "https://t.me/myzuraisgoodbot" 
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

# Konfigurasi Bot 2 (Number Getter - Variabel Langsung)
BOT_GETTER_TOKEN = "8047851913:AAFGXlRL_e7JcLEMtOqUuuNd_46ZmIoGJN8" 
GROUP_ID_GETTER = -1003492226491 
API_GETTER = f"https://api.telegram.org/bot{BOT_GETTER_TOKEN}"

# Global State Bot 2
verified_users = set()
waiting_range = set()
pending_message = {} 

# Status Global Bot 1
BOT_STATUS = {"status": "Initializing...", "uptime": "--", "total_otps_sent": 0, "last_check": "Never", "cache_size": 0, "monitoring_active": True, "last_cleanup_gmt_date": "N/A"}

# Konstanta
COUNTRY_EMOJI = {
    "NEPAL": "🇳🇵", "IVORY COAST": "🇨🇮", "GUINEA": "🇬🇳", "CENTRAL AFRIKA": "🇨🇫",
    "TOGO": "🇹🇬", "TAJIKISTAN": "🇹🇯", "BENIN": "🇧🇯", "SIERRA LEONE": "🇸🇱",
    "MADAGASCAR": "🇲🇬", "AFGANISTAN": "🇦🇫",
}

# ================= UTILITAS UMUM & STATUS =================

# --- OTP Filter Class (dari script 1) ---
class OTPFilter:
    CLEANUP_KEY = '__LAST_CLEANUP_GMT__'
    def __init__(self, file='otp_cache.json'): 
        self.file = file
        self.cache = self._load()
        self.last_cleanup_date_gmt = self.cache.pop(self.CLEANUP_KEY, '19700101') 
        self._cleanup() 
    # ... (Semua method _load, _save, _cleanup, key, is_dup, add, filter) ...
    def _load(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.file) and os.stat(self.file).st_size > 0:
            try:
                with open(self.file, 'r') as f: return json.load(f)
            except json.JSONDecodeError: return {}
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
    def key(self, d: Dict[str, Any]) -> str: return str(d.get('otp'))
    def is_dup(self, d: Dict[str, Any]) -> bool:
        self._cleanup()
        return self.key(d) in self.cache
    def add(self, d: Dict[str, Any]):
        key = self.key(d)
        if key: self.cache[key] = {'timestamp':datetime.now().isoformat()} 
        self._save()
    def filter(self, lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for d in lst:
            if d.get('otp') and d.get('phone') != 'N/A' and not self.is_dup(d):
                out.append(d)
                self.add(d)
        return out
otp_filter = OTPFilter()

# --- Cache Utils (Bot 2) ---
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []

def save_cache(number_entry):
    cache = load_cache()
    if not any(entry["number"] == number_entry["number"] for entry in cache):
        cache.append(number_entry)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)

def is_in_cache(number):
    return any(entry["number"] == number for entry in load_cache())

# --- Format & Status Utils (dari script 1) ---
def clean_phone_number(phone):
    if not phone: return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+'):
        if len(cleaned) >= 10: cleaned = '+' + cleaned
    return cleaned or phone

def mask_phone_number(phone, visible_start=4, visible_end=4):
    if not phone or phone == "N/A": return phone
    prefix = ""
    if phone.startswith('+'): prefix = '+'; digits = phone[1:]
    else: digits = phone
    if len(digits) <= visible_start + visible_end: return phone
    start_part = digits[:visible_start]
    end_part = digits[-visible_end:]
    mask_length = len(digits) - visible_start - visible_end
    masked_part = '*' * mask_length
    return prefix + start_part + masked_part + end_part

def extract_otp_from_text(text):
    if not text: return None
    patterns = [ r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b', r'code[:\s]*(\d+)', r'verification[:\s]*(\d+)', r'otp[:\s]*(\d+)', r'pin[:\s]*(\d+)' ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            matched_otp = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            if len(matched_otp) == 4:
                try:
                    if 2000 <= int(matched_otp) <= 2099: continue 
                except ValueError: continue 
            return matched_otp
    return None

def clean_service_name(service):
    if not service: return "Unknown"
    s = service.strip().title()
    maps = {'fb':'Facebook','google':'Google','whatsapp':'WhatsApp','telegram':'Telegram','instagram':'Instagram','twitter':'Twitter','linkedin':'LinkedIn','tiktok':'TikTok', 'mnitnetwork':'M-NIT Network'}
    l = s.lower()
    for k,v in maps.items():
        if k in l: return v
    return s

def get_country_emoji(country_name: str) -> str:
    return COUNTRY_EMOJI.get(country_name.strip().upper(), "")

def create_inline_keyboard():
    keyboard = {"inline_keyboard": [[{"text": "➡️ GetNumber", "url": TELEGRAM_BOT_LINK}, {"text": "👤 Admin", "url": TELEGRAM_ADMIN_LINK}]]}
    return json.dumps(keyboard)

def format_otp_message(otp_data: Dict[str, Any]) -> str:
    otp, phone, service, range_text, full_message = otp_data.get('otp', 'N/A'), otp_data.get('phone', 'N/A'), otp_data.get('service', 'Unknown'), otp_data.get('range', 'N/A'), otp_data.get('raw_message', 'N/A')
    masked_phone = mask_phone_number(phone, visible_start=4, visible_end=4)
    emoji = get_country_emoji(range_text)
    full_message_escaped = full_message.replace('<', '&lt;').replace('>', '&gt;') 
    return f"🔐 <b>New OTP Received</b>\n\n🌍 Country: <b>{range_text} {emoji}</b>\n\n📱 Number: <code>{masked_phone}</code>\n🌐 Service: <b>{service}</b>\n🔢 OTP: <code>{otp}</code>\n\nFULL MESSAGES:\n<blockquote>{full_message_escaped}</blockquote>"

def update_global_status():
    global BOT_STATUS, total_sent
    uptime_seconds = time.time() - start_time
    BOT_STATUS["uptime"] = f"{int(uptime_seconds//3600)}h {int((uptime_seconds%3600)//60)}m {int(uptime_seconds%60)}s"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] else "Paused"
    BOT_STATUS["last_cleanup_gmt_date"] = otp_filter.last_cleanup_date_gmt 
    return BOT_STATUS

def get_status_message(stats):
    return f"🤖 <b>Bot Status</b>\n\n⚡ Status: <b>{stats['status']}</b>\n⏱️ Uptime: {stats['uptime']}\n📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>\n🔍 Last Check: {stats['last_check']}\n💾 Cache Size: {stats['cache_size']} items\n📅 Last Cache Reset (GMT): {stats['last_cleanup_gmt_date']}\n\n<i>Bot is running</i>"


# ================= FUNGSI TELEGRAM BOT 1 (Monitor) =================
def send_tg(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT_MONITOR
    if not BOT_MONITOR or not chat_id_to_use: return
    payload = {'chat_id': chat_id_to_use, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard: payload['reply_markup'] = create_inline_keyboard()
    try: requests.post(f"https://api.telegram.org/bot{BOT_MONITOR}/sendMessage", data=payload, timeout=15)
    except requests.exceptions.RequestException as e: print(f"❌ Bot 1 Connection Error: {e}")

def send_photo_tg(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT_MONITOR
    if not BOT_MONITOR or not chat_id_to_use: return False
    url = f"https://api.telegram.org/bot{BOT_MONITOR}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use, 'caption': caption, 'parse_mode': 'HTML'}
            response = requests.post(url, files=files, data=data, timeout=20)
        return response.ok
    except requests.exceptions.RequestException: return False
    finally:
        if os.path.exists(photo_path): os.remove(photo_path)

# ================= FUNGSI TELEGRAM BOT 2 (Getter) =================
def tg_send(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: data["reply_markup"] = reply_markup
    r = requests.post(f"{API_GETTER}/sendMessage", json=data).json()
    if r.get("ok"): return r["result"]["message_id"]
    return None

def tg_edit(chat_id, message_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: data["reply_markup"] = reply_markup
    requests.post(f"{API_GETTER}/editMessageText", json=data)

def tg_get_updates_getter(offset):
    return requests.get(f"{API_GETTER}/getUpdates", params={"offset": offset, "timeout": 30}).json()

def is_user_in_group(user_id):
    r = requests.get(f"{API_GETTER}/getChatMember", params={"chat_id": GROUP_ID_GETTER, "user_id": user_id}).json()
    if not r.get("ok"): return False
    return r["result"]["status"] in ["member", "administrator", "creator"]


# ================= SCRAPING & COMMANDS =================

# --- Scraper Class (Bot 1) ---
class SMSMonitor:
    def __init__(self, url=URL_MNIT):
        self.url = url
        self.page = None # Akan diset di main_async()

    async def fetch_sms(self) -> List[Dict[str, Any]]:
        # Bot 1 TIDAK AKAN soft_refresh, karena Bot 2 yang melakukan reload.
        if not self.page: return []
            
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        messages = []

        rows = soup.find_all("tr")
        for r in rows:
            otp_badge_span = r.find("span", class_="otp-badge")
            if not otp_badge_span: continue
                
            phone_span = r.find("span", class_="phone-number")
            phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else "N/A")
            
            copy_icon = otp_badge_span.find("i", class_="copy-icon")
            raw_message_original = copy_icon.get('data-sms', 'N/A') if copy_icon and copy_icon.get('data-sms') else otp_badge_span.get_text(strip=True)
            raw_message_clean = raw_message_original.split(':', 1)[1].strip() if ':' in raw_message_original and raw_message_original != 'N/A' else raw_message_original
            otp_full_text = otp_badge_span.get_text(strip=True, separator=' ')
            otp = extract_otp_from_text(otp_full_text)
            
            tds = r.find_all("td")
            range_text = "N/A"
            if len(tds) > 1:
                range_badge = tds[1].find("span", class_="badge")
                if range_badge: range_text = range_badge.get_text(strip=True)
            
            service_raw = raw_message_original.split(':', 1)[0] if raw_message_original != 'N/A' and ':' in raw_message_original else 'Unknown'
            service = clean_service_name(service_raw)
            
            if otp and phone != 'N/A':
                messages.append({"otp": otp, "phone": phone, "service": service, "range": range_text, "timestamp": datetime.now().strftime("%H:%M:%S"), "raw_message": raw_message_clean })
        return messages

    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page:
            send_tg(f"⚠️ **Error Refresh/Screenshot**: Gagal inisialisasi koneksi browser.", target_chat_id=admin_chat_id)
            return False

        screenshot_filename = f"screenshot_{int(time.time())}.png"
        try:
            print("🔄 [Bot 1] Performing page refresh...")
            # PENTING: Bot 1 dipaksa reload, sama seperti Bot 2
            await self.page.reload(wait_until='networkidle') 
            await self.page.screenshot(path=screenshot_filename, full_page=True)
            caption = f"✅ Page Refreshed successfully at {datetime.now().strftime('%H:%M:%S')}"
            success = send_photo_tg(screenshot_filename, caption, target_chat_id=admin_chat_id)
            return success
        except Exception as e:
            send_tg(f"⚠️ **Error Refresh/Screenshot**: `{e.__class__.__name__}: {e}`", target_chat_id=admin_chat_id)
            return False
    
monitor = SMSMonitor()

# --- Scraper Utils (Bot 2) ---
async def get_number_and_country(page):
    rows = await page.query_selector_all("tbody tr")
    for row in rows:
        phone_el = await row.query_selector(".phone-number")
        if not phone_el: continue
        number = (await phone_el.inner_text()).strip()
        if is_in_cache(number): continue
        if await row.query_selector(".status-success") or await row.query_selector(".status-failed"): continue # Pengecekan ini dikembalikan
        country_el = await row.query_selector(".badge.bg-primary")
        country = (await country_el.inner_text()).strip().upper() if country_el else "-"
        return number, country
    return None, None

# ================= FUNGSI BOT COMMAND (Bot 1) =================
def check_cmd(stats):
    global LAST_ID_MONITOR
    if ADMIN_ID is None: return

    try:
        upd = requests.get(f"https://api.telegram.org/bot{BOT_MONITOR}/getUpdates?offset={LAST_ID_MONITOR+1}", timeout=15).json()

        for u in upd.get("result",[]):
            LAST_ID_MONITOR = u["update_id"]
            msg = u.get("message",{})
            text = msg.get("text","")
            user_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")

            if user_id == ADMIN_ID:
                if text == "/status":
                    send_tg(get_status_message(stats), target_chat_id=chat_id)
                elif text == "/refresh":
                    send_tg("⏳ Executing page refresh and screenshot...", target_chat_id=chat_id)
                    if GLOBAL_ASYNC_LOOP:
                        # Bot 1 menggunakan page yang sama, dipaksa reload
                        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=chat_id), GLOBAL_ASYNC_LOOP)
                    else:
                        send_tg("❌ Loop error: Global loop not set.", target_chat_id=chat_id)

    except requests.exceptions.RequestException: pass
    except Exception as e: print(f"❌ [Bot 1] Unknown Error in check_cmd: {e}")

# ================= FUNGSI BOT 2: PROCESS INPUT (Playwright) =================
async def process_user_input(page, user_id, prefix):
    # Mengembalikan logika persis seperti script tunggal
    try:
        msg_id = tg_send(user_id, f"⏳ Sedang mengambil Number...\nRange: {prefix}")
        pending_message[user_id] = msg_id

        # isi input & klik Get Number
        await page.wait_for_selector('input[name="numberrange"]', timeout=10000)
        await page.fill('input[name="numberrange"]', prefix)
        await page.click("#getNumberBtn")

        # refresh halaman dan tunggu load
        await page.reload()
        await page.wait_for_load_state("networkidle")

        # scrape nomor & negara terbaru
        number, country = await get_number_and_country(page)
        if not number:
            cache = load_cache()
            if cache:
                last_entry = cache[-1]
                number = last_entry["number"]
                country = last_entry["country"]
            else:
                tg_edit(user_id, pending_message[user_id], "❌ Nomor tidak ditemukan, coba lagi nanti.")
                del pending_message[user_id]
                return

        save_cache({"number": number, "country": country})

        emoji = COUNTRY_EMOJI.get(country, "🗺️")
        msg = (
            "✅ The number is ready\n\n"
            f"📞 Number  : <code>{number}</code>\n"
            f"{emoji} COUNTRY : {country}\n"
            f"🏷️ Range   : <code>{prefix}</code>"
        )
        inline_kb = {"inline_keyboard": [[{"text": "📲 Get Number", "callback_data": "getnum"}], [{"text": "🔐 OTP Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}]]}
        tg_edit(user_id, pending_message[user_id], msg, reply_markup=inline_kb)

    except Exception as e:
        print(f"[ERROR Bot 2] {e}")
        if user_id in pending_message:
            tg_edit(user_id, pending_message[user_id], f"❌ Terjadi kesalahan: {e.__class__.__name__}")
    finally:
        if user_id in pending_message:
            del pending_message[user_id]

# ================= LOOP UTAMA BOT 1 (OTP Monitor) =================
async def monitor_sms_loop(page):
    global total_sent
    monitor.page = page 
    
    while True:
        try:
            if BOT_STATUS["monitoring_active"]:
                # TIDAK ADA soft_refresh di sini. Hanya scraping.
                msgs = await monitor.fetch_sms()
                new = otp_filter.filter(msgs)

                if new:
                    print(f"✅ Found {len(new)} new OTP(s). Sending to Bot 1...")
                    for i, otp_data in enumerate(new):
                        send_tg(format_otp_message(otp_data), with_inline_keyboard=True)
                        total_sent += 1
                        await asyncio.sleep(2) 
                    
                    if ADMIN_ID is not None:
                        # Lakukan reload dan screenshot secara otomatis setelah kirim OTP
                        await monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID)
                        

        except Exception as e:
            print(f"[ERROR Bot 1] Error during fetch/send: {e.__class__.__name__}: {e}")

        stats = update_global_status()
        check_cmd(stats)
        
        # Bot 1 mengecek setiap 5 detik
        await asyncio.sleep(5) 

# ================= LOOP UTAMA BOT 2 (Number Getter) =================
async def telegram_loop(page):
    global LAST_ID_GETTER
    while True:
        try:
            data = tg_get_updates_getter(LAST_ID_GETTER + 1)
            for upd in data.get("result", []):
                LAST_ID_GETTER = upd["update_id"]
    
                if "message" in upd:
                    msg = upd["message"]
                    user_id = msg["chat"]["id"]
                    username = msg["from"].get("username", "-")
                    text = msg.get("text", "")
    
                    if text == "/start":
                        kb = {"inline_keyboard": [[{"text": "📌 Gabung Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}], [{"text": "✅ Verifikasi", "callback_data": "verify"}]]}
                        tg_send(user_id, f"Halo @{username} 👋\nGabung grup untuk verifikasi.", kb)
                        continue
    
                    if user_id in waiting_range and text.strip():
                        waiting_range.remove(user_id)
                        prefix = text.strip()
                        # Panggil proses asinkron
                        asyncio.create_task(process_user_input(page, user_id, prefix))
    
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    user_id = cq["from"]["id"]
                    data_cb = cq["data"]
                    username = cq["from"].get("username", "-")
    
                    if data_cb == "verify":
                        if not is_user_in_group(user_id):
                            tg_send(user_id, "❌ Belum gabung grup, silakan join dulu.")
                        else:
                            verified_users.add(user_id)
                            kb = {"inline_keyboard": [[{"text": "📲 Get Number", "callback_data": "getnum"}], [{"text": "👨‍💼 Admin", "url": "https://t.me/"}]]}
                            tg_send(user_id, f"✅ Verifikasi Berhasil!\n\nUser : @{username}\nGunakan tombol di bawah:", kb)
    
                    if data_cb == "getnum":
                        if user_id not in verified_users:
                            tg_send(user_id, "⚠️ Harap verifikasi dulu.")
                            continue
                        waiting_range.add(user_id)
                        tg_send(user_id, "Kirim range contoh: <code>628272XXXX</code>")
                        
        except Exception as e:
            print(f"[ERROR Bot 2] Loop: {e.__class__.__name__}")
            
        # Bot 2 mengecek setiap 1 detik
        await asyncio.sleep(1)

# ================= FLASK WEB SERVER =================

app = Flask(__name__, template_folder='templates')

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    global GLOBAL_ASYNC_LOOP
    if GLOBAL_ASYNC_LOOP and not asyncio._get_running_loop():
        asyncio.set_event_loop(GLOBAL_ASYNC_LOOP) 
        
    print(f"✅ Flask API & Dashboard running on http://127.0.0.1:{port}")
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

# --- FLASK ROUTES ---
@app.route('/', methods=['GET'])
def index():
    return "Dashboard HTML placeholder" 

@app.route('/api/status', methods=['GET'])
def get_status_json():
    update_global_status() 
    return jsonify(BOT_STATUS)

@app.route('/manual-check', methods=['GET'])
def manual_check():
    if ADMIN_ID is None or GLOBAL_ASYNC_LOOP is None:
        return jsonify({"message": "Error: Admin ID or Asyncio loop not ready."}), 500
    try:
        # Menggunakan page tunggal untuk refresh
        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID), GLOBAL_ASYNC_LOOP)
        return jsonify({"message": "Halaman Refresh & Screenshot sedang dikirim ke Admin Telegram."})
    except Exception as e:
        return jsonify({"message": f"External Error: Gagal menjalankan refresh: {e.__class__.__name__}"}), 500

@app.route('/test-message', methods=['GET'])
def test_message_route():
    test_data = {"otp": "123456", "phone": "+2250150086627", "service": "Facebook", "range": "Ivory Coast", "timestamp": datetime.now().strftime("%H:%M:%S"), "raw_message": "123456 adalah kode konfirmasi Facebook anda."}
    test_msg = format_otp_message(test_data).replace("🔐 <b>New OTP Received</b>", "🧪 <b>TEST MESSAGE FROM DASHBOARD</b>")
    send_tg(test_msg)
    return jsonify({"message": "Test message sent to main channel."})


# ================= FUNGSI UTAMA START =================
async def main_async():
    if not BOT_MONITOR or not CHAT_MONITOR:
        print("FATAL ERROR: TELEGRAM_BOT_TOKEN/CHAT_ID MONITOR tidak ditemukan.")
        return

    async with async_playwright() as p:
        try:
            # 1. KONEKSI SATU KALI KE CHROME RDP
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            print("[OK] Connected to existing Chrome via CDP: 9222")

            # 2. INISIALISASI SATU PAGE (Digunakan oleh kedua bot)
            page = await context.new_page()
            await page.goto(URL_MNIT, wait_until='networkidle')
            monitor.page = page # Set page untuk Bot 1
            print(f"✅ Single Page opened at {URL_MNIT}")
            
            # Kirim pesan aktivasi untuk kedua bot
            send_tg("✅ BOT MONITORING ACTIVE.", with_inline_keyboard=False) # Bot 1
            tg_send(GROUP_ID_GETTER, "✅ BOT NUMBER GETTER ACTIVE.") # Bot 2

            # 3. JALANKAN KEDUA LOOP SECARA PARALEL (Menggunakan Page yang sama)
            await asyncio.gather(
                monitor_sms_loop(page),
                telegram_loop(page)
            )
            
        except Exception as e:
            print(f"FATAL ERROR IN MAIN: {e}")
            send_tg("🚨 **FATAL ERROR**: Gagal inisialisasi Playwright atau koneksi Chrome. Cek log RDP.")
            if ADMIN_ID:
                 send_tg(f"🚨 **FATAL ERROR**: Gagal terhubung ke Chrome/Playwright: {e.__class__.__name__}.", target_chat_id=ADMIN_ID)


if __name__ == "__main__":
    
    print("Starting CONSOLIDATED (1-Page) SMS Monitor & Getter Bot...")
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    GLOBAL_ASYNC_LOOP = loop 
    
    # 1. Mulai Flask di thread terpisah
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # 2. Mulai loop asinkron monitoring dan getter
    try:
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        print("Bot shutting down...")
    finally:
        print("Bot core shutdown complete.")
