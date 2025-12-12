import asyncio
from pyppeteer import connect
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import os
import requests
import time
from dotenv import load_dotenv
import socket
from threading import Thread, current_thread

# --- Import Flask ---
from flask import Flask, jsonify, render_template
# --------------------

load_dotenv()

# ================= Configuration & Global State =================
URL = "https://v2.mnitnetwork.com/dashboard/getnum" 

# Bot Monitor (Old)
BOT_MONITOR_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_MONITOR_ID = os.getenv("TELEGRAM_CHAT_ID")
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except (ValueError, TypeError):
    ADMIN_ID = None
LAST_ID_MONITOR = 0

# Bot Pelayanan User (New)
BOT_USER_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_USER")
LAST_ID_USER = 0

# Constants
TELEGRAM_BOT_LINK = "https://t.me/zuraxridbot" # Ganti dengan link bot Anda
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"     # Ganti dengan link admin Anda

# In-Memory Cache untuk OTP dan User Request
otp_filter = None # Akan diinisialisasi nanti

# --- Variabel Persistensi User ---
USER_FILE = 'user.json' 
USER_ALLOWED_IDS = set() # Akan dimuat dari user.json
# ----------------------------------

USER_REQUEST_CACHE = {} # { Nomor Prefix Request: User ID Telegram }

# Global State
GLOBAL_ASYNC_LOOP = None
start = time.time()
total_sent = 0

BOT_STATUS = {
    "status": "Initializing...",
    "uptime": "--",
    "total_otps_sent": 0,
    "last_check": "Never",
    "cache_size": 0,
    "monitoring_active": True
}


# ================= Utils & Telegram Functions =================

def get_local_ip():
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) 
        ip = s.getsockname()[0]
        return ip
    except Exception:
        return "127.0.0.1" 
    finally:
        if s: s.close()
            
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
    if cleaned and not cleaned.startswith('+'):
        if len(cleaned) >= 10: cleaned = '+' + cleaned
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
    start_part = digits[:visible_start]
    end_part = digits[-visible_end:]
    mask_length = len(digits) - visible_start - visible_end
    masked_part = '*' * mask_length
    return prefix + start_part + masked_part + end_part

def format_otp_message(otp_data):
    otp = otp_data.get('otp', 'N/A')
    phone = otp_data.get('phone', 'N/A')
    masked_phone = mask_phone_number(phone, visible_start=4, visible_end=4)
    service = otp_data.get('service', 'Unknown')
    range_text = otp_data.get('range', 'N/A')
    full_message = otp_data.get('raw_message', 'N/A')
    
    # PERBAIKAN ESCAPING HTML: Escape &, <, dan >
    full_message_escaped = full_message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    return f"""🔐 <b>New OTP Received</b>

🏷️ Range: <b>{range_text}</b>

📱 Number: <code>{masked_phone}</code>
🌐 Service: <b>{service}</b>
🔢 OTP: <code>{otp}</code>

FULL MESSAGES:
<blockquote>{full_message_escaped}</blockquote>"""

def extract_otp_from_text(text):
    if not text: return None
    patterns = [ r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b', r'code[:\s]*(\d+)', r'verification[:\s]*(\d+)', r'otp[:\s]*(\d+)', r'pin[:\s]*(\d+)' ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            if (len(m.group(1)) == 4 and '20' not in m.group(1)) or len(m.group(1)) > 4:
                return m.group(1)
    return None

def clean_service_name(service):
    if not service: return "Unknown"
    s = service.strip().title()
    maps = {'fb':'Facebook','google':'Google','whatsapp':'WhatsApp','telegram':'Telegram','instagram':'Instagram','twitter':'Twitter','linkedin':'LinkedIn','tiktok':'TikTok', 'mnitnetwork':'M-NIT Network'}
    l = s.lower()
    for k,v in maps.items():
        if k in l: return v
    return s

def get_status_message(stats):
    return f"""🤖 <b>Bot Status</b>

⚡ Status: <b>{stats['status']}</b>
⏱️ Uptime: {stats['uptime']}
📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>
🔍 Last Check: {stats['last_check']}
💾 Cache Size: {stats['cache_size']} items

<i>Bot is running</i>"""

# --- Fungsi Persistensi User ---
def load_users():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, 'r') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, FileNotFoundError):
            return set()
    return set()

def save_users(user_set):
    try:
        with open(USER_FILE, 'w') as f:
            json.dump(list(user_set), f, indent=2)
    except Exception as e:
        print(f"❌ Error saving {USER_FILE}: {e}")
# ----------------------------------------


class OTPFilter:
    # PERBAIKAN SINTAKSIS: expire=30
    def __init__(self, file='otp_cache.json', expire=30):
        self.file = file
        self.expire = expire
        self.cache = self._load()
    def _load(self):
        if os.path.exists(self.file):
            try:
                if os.stat(self.file).st_size > 0:
                    with open(self.file, 'r') as f: return json.load(f)
                else: return {}
            except json.JSONDecodeError: return {}
            except Exception: return {}
        return {}
    def _save(self): json.dump(self.cache, open(self.file,'w'), indent=2)
    def _cleanup(self):
        now = datetime.now()
        dead = []
        for k,v in self.cache.items():
            try:
                t = datetime.fromisoformat(v['timestamp'])
                if (now-t).total_seconds() > self.expire*60: dead.append(k)
            except: dead.append(k)
        for k in dead: del self.cache[k]
        self._save()
        
    def key(self, d): return f"{d['otp']}_{d['phone']}" 
    
    def is_dup(self, d):
        self._cleanup()
        return self.key(d) in self.cache
        
    def add(self, d):
        self.cache[self.key(d)] = {'timestamp':datetime.now().isoformat()} 
        self._save()
        
    def filter(self, lst):
        out = []
        for d in lst:
            if d.get('otp') and d.get('phone') != 'N/A':
                if not self.is_dup(d):
                    out.append(d)
                    self.add(d)
        return out

# --- Fungsi Telegram Generik ---
def send_tg_generic(token, chat_id, text, with_inline_keyboard=False):
    if not token or not chat_id:
        print("❌ Telegram config missing. Cannot send message.")
        return
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard:
        payload['reply_markup'] = create_inline_keyboard() 
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            timeout=15  
        )
        if not response.ok:
            print(f"⚠️ Telegram API Error ({response.status_code}): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram Connection Error: {e}")

# Fungsi Kirim untuk Bot Monitor
def send_tg_monitor(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id = target_chat_id if target_chat_id is not None else CHAT_MONITOR_ID
    send_tg_generic(BOT_MONITOR_TOKEN, chat_id, text, with_inline_keyboard)

# Fungsi Kirim untuk Bot User
def send_tg_user(text, chat_id, with_inline_keyboard=False):
    send_tg_generic(BOT_USER_TOKEN, chat_id, text, with_inline_keyboard)

def send_photo_tg_monitor(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT_MONITOR_ID
    if not BOT_MONITOR_TOKEN or not chat_id_to_use: return False
    url = f"https://api.telegram.org/bot{BOT_MONITOR_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use, 'caption': caption, 'parse_mode': 'HTML'}
            response = requests.post(url, files=files, data=data, timeout=20)
        return response.ok
    except Exception as e:
        print(f"❌ Unknown Error in send_photo_tg_monitor: {e}")
        return False
    finally:
        if os.path.exists(photo_path): os.remove(photo_path)

def update_global_status():
    global BOT_STATUS
    global total_sent
    uptime_seconds = time.time() - start
    
    BOT_STATUS["uptime"] = f"{int(uptime_seconds//3600)}h {int((uptime_seconds%3600)//60)}m {int(uptime_seconds%60)}s"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] else "Paused"
    
    return BOT_STATUS


# ================= User Bot Class =================

class UserBot:
    def __init__(self, token):
        self.token = token
        self.last_id = 0
    
    async def run(self):
        print("🚀 User Bot (Pelayanan) started...")
        while True:
            await self._check_updates()
            await asyncio.sleep(1) 

    async def _check_updates(self):
        global USER_ALLOWED_IDS
        url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self.last_id+1}&timeout=10"
        
        try:
            response = requests.get(url, timeout=15)
            upd = response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ User Bot Error during getUpdates: {e}")
            return
        
        for u in upd.get("result", []):
            self.last_id = u["update_id"]
            msg = u.get("message", {})
            text = msg.get("text", "")
            user_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")

            if not chat_id: continue 

            if text == "/start":
                if user_id not in USER_ALLOWED_IDS:
                    USER_ALLOWED_IDS.add(user_id)
                    save_users(USER_ALLOWED_IDS) # SIMPAN ID USER BARU
                    
                    # FEEDBACK USER BARU
                    welcome_message = (
                        f"✅ Selamat datang! ID Anda (`{user_id}`) telah terdaftar dan tersimpan.\n\n"
                        f"Untuk memulai, kirimkan **prefix nomor telepon** yang ingin Anda dapatkan "
                        f"(minimal 6 digit).\n\n"
                        f"Contoh:\n"
                        f"• `+2246543XXX`\n"
                        f"• `85712345XX`"
                    )
                    send_tg_user(welcome_message, chat_id)
                    send_tg_monitor(f"👤 **New User Registered**: ID `{user_id}`", with_inline_keyboard=False)
                else:
                    # FEEDBACK USER LAMA
                    welcome_message_back = (
                        f"👋 Halo kembali! ID Anda (`{user_id}`) sudah terdaftar.\n\n"
                        f"Silakan kirimkan **prefix nomor telepon** yang ingin Anda dapatkan.\n"
                        f"Contoh: `+2246543XXX`"
                    )
                    send_tg_user(welcome_message_back, chat_id)
            
            elif user_id in USER_ALLOWED_IDS and (text.startswith('+') or text.isdigit()):
                input_number = clean_phone_number(text)
                if len(input_number.replace('+', '')) < 6:
                    send_tg_user("⚠️ Format nomor tidak valid. Minimal 6 digit. Contoh: `+2246543XXX`", chat_id)
                    continue
                
                # Masukkan request ke cache, menggunakan prefix sebagai key
                USER_REQUEST_CACHE[input_number] = user_id 
                
                # Eksekusi Get Number di Browser secara asinkron
                if GLOBAL_ASYNC_LOOP:
                     asyncio.run_coroutine_threadsafe(
                        monitor.get_number_on_page(input_number), 
                        GLOBAL_ASYNC_LOOP
                    )
                else:
                    send_tg_user("❌ Bot monitoring belum siap. Coba lagi sebentar.", chat_id)
                    continue

                print(f"✅ User {user_id} requested number: {input_number}")
                send_tg_user(f"⏳ Nomor `{input_number}` sedang diproses. Mohon tunggu notifikasi.", chat_id)
            
            else:
                if user_id not in USER_ALLOWED_IDS:
                    send_tg_user("Mohon ketik /start terlebih dahulu.", chat_id)


# ================= Scraper & Monitor Class =================

class SMSMonitor:
    def __init__(self, url=URL):
        self.url = url
        self.browser = None
        self.page = None

    async def initialize(self):
        self.browser = await connect(browserURL="http://127.0.0.1:9222")
        pages = await self.browser.pages()
        page = None
        for p in pages:
            if self.url in p.url:
                page = p
                break
        if not page:
            page = await self.browser.newPage()
            await page.goto(self.url, {'waitUntil': 'networkidle0'})
        self.page = page
        print("✅ Browser page connected successfully.")
    
    async def get_number_on_page(self, number_prefix):
        """Mengisi input dan klik tombol 'Get Numbers'."""
        if not self.page: await self.initialize()

        # 1. Refresh dulu
        try:
            print(f"-> Browser Action: Refreshing page...")
            await self.page.reload({'waitUntil': 'networkidle0'})
            await asyncio.sleep(1) 
        except Exception as e:
            print(f"❌ Gagal Refresh sebelum input: {e}")

        try:
            # 2. Input Nomor (Selector: input[name="numberrange"])
            print(f"-> Browser Action: Typing {number_prefix}...")
            # Menghapus teks lama sebelum mengetik
            await self.page.evaluate('document.querySelector("input[name=\\"numberrange\\"]").value = ""')
            await self.page.type('input[name="numberrange"]', number_prefix, {'delay': 50})
            
            # 3. Klik Tombol (Selector: #getNumberBtn)
            print(f"-> Browser Action: Clicking Get Numbers...")
            await self.page.click('#getNumberBtn')
            
            # Tunggu sebentar agar status "pending" muncul
            await asyncio.sleep(3) 

            print(f"✅ Number {number_prefix} successfully requested on the page.")

        except Exception as e:
            error_msg = f"❌ Gagal input/klik tombol di browser: {e.__class__.__name__}: {e}"
            print(error_msg)
            # Notifikasi kegagalan ke user
            if number_prefix in USER_REQUEST_CACHE:
                user_id = USER_REQUEST_CACHE.pop(number_prefix)
                send_tg_user(f"❌ Gagal memproses nomor `{number_prefix}`. Coba lagi.", user_id)


    async def fetch_sms(self):
        if not self.page: await self.initialize()
            
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        messages = []

        # === Logika Baru: Memproses Status Pending (Untuk Notifikasi User) ===
        pending_rows = soup.find_all("span", class_="status-pending")
        
        for p_span in pending_rows:
            row = p_span.find_parent("tr")
            if not row: continue
            
            phone_span = row.find("span", class_="phone-number")
            phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else None)
            
            if phone:
                # Cek apakah nomor ini diminta oleh user
                for prefix, user_id in list(USER_REQUEST_CACHE.items()): 
                    if phone.startswith(prefix) or phone.startswith(prefix.replace('+', '')):
                        
                        # Kirim notifikasi ke user!
                        message = f"✅ Nomor **{phone}** telah berhasil *di-request* dan berstatus **PENDING**."
                        message += "\n\nMenunggu OTP..."
                        send_tg_user(message, user_id)
                        
                        print(f"-> NOTIFY PENDING: User {user_id} notified about pending number: {phone}")
                        
                        # Hapus dari cache USER_REQUEST_CACHE 
                        del USER_REQUEST_CACHE[prefix]
                        break 
        
        # === Logika Lama: Mengambil Pesan Sukses (OTP) ===

        rows = soup.find_all("tr")

        for r in rows:
            otp_badge_span = r.find("span", class_="otp-badge")
            
            if otp_badge_span:
                
                # A. Phone Number
                phone_span = r.find("span", class_="phone-number")
                phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else "N/A")
                
                # B. Raw Message (Original & Cleaned)
                copy_icon = otp_badge_span.find("i", class_="copy-icon")
                raw_message_original = copy_icon.get('data-sms', 'N/A') if copy_icon else otp_badge_span.get_text(strip=True)
                
                # LOGIKA PENGAMBILAN PESAN PENUH MENTAH 
                if ':' in raw_message_original and raw_message_original != 'N/A':
                    raw_message_clean = raw_message_original.split(':', 1)[1].strip()
                else:
                    raw_message_clean = raw_message_original
                
                # C. OTP
                otp_raw_text_parts = [t.strip() for t in otp_badge_span.contents if t.name is None and t.strip()]
                otp = otp_raw_text_parts[0] if otp_raw_text_parts else None 
                
                if not (otp and otp.isdigit()):
                    otp_full_text = otp_badge_span.get_text(strip=True, separator=' ')
                    otp = extract_otp_from_text(otp_full_text)
                    
                # D. Range/Country
                tds = r.find_all("td")
                range_text = "N/A"
                if len(tds) > 1:
                    range_badge = tds[1].find("span", class_="badge")
                    if range_badge:
                        range_text = range_badge.get_text(strip=True)
                
                # E. Service 
                service_raw = raw_message_original.split(':', 1)[0] if raw_message_original != 'N/A' and ':' in raw_message_original else 'Unknown'
                service = clean_service_name(service_raw)
                
                # --- Simpan Hasil ---
                if otp and phone != 'N/A':
                    messages.append({
                        "otp": otp,
                        "phone": phone,
                        "service": service,
                        "range": range_text,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "raw_message": raw_message_clean 
                    })
        return messages
    
    async def refresh_and_screenshot(self, admin_chat_id): 
        screenshot_filename = f"screenshot_{int(time.time())}.png"
        try:
            if not self.page: await self.initialize()
            print("🔄 Performing page refresh...")
            await self.page.reload({'waitUntil': 'networkidle0'}) 
            print(f"📸 Taking screenshot: {screenshot_filename}")
            await self.page.screenshot({'path': screenshot_filename, 'fullPage': True})
            print("📤 Sending screenshot to Admin Telegram...")
            caption = f"✅ Page Refreshed successfully at {datetime.now().strftime('%H:%M:%S')}\n\n<i>Pesan OTP di halaman telah dihapus.</i>"
            success = send_photo_tg_monitor(screenshot_filename, caption, target_chat_id=admin_chat_id)
            return success
        except Exception as e:
            print(f"❌ Error during refresh/screenshot: {e}")
            send_tg_monitor(f"⚠️ **Error Refresh/Screenshot**: `{e.__class__.__name__}: {e}`", target_chat_id=admin_chat_id)
            return False
        finally:
            if os.path.exists(screenshot_filename):
                os.remove(screenshot_filename)
                print(f"🗑️ Cleaned up {screenshot_filename}")

monitor = SMSMonitor()

# ================= FUNGSI UTAMA LOOP DAN COMMAND CHECK =================

def check_cmd(stats):
    global LAST_ID_MONITOR
    if ADMIN_ID is None: return

    try:
        upd = requests.get(
            f"https://api.telegram.org/bot{BOT_MONITOR_TOKEN}/getUpdates?offset={LAST_ID_MONITOR+1}",
            timeout=15  
        ).json()

        for u in upd.get("result",[]):
            LAST_ID_MONITOR = u["update_id"]
            msg = u.get("message",{})
            text = msg.get("text","")
            user_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")

            if user_id == ADMIN_ID:
                if text == "/status":
                    requests.post(
                        f"https://api.telegram.org/bot{BOT_MONITOR_TOKEN}/sendMessage",
                        data={'chat_id': chat_id, 'text': get_status_message(stats), 'parse_mode': 'HTML'}
                    )
                elif text == "/refresh":
                    send_tg_monitor("⏳ Executing page refresh and screenshot...", with_inline_keyboard=False, target_chat_id=chat_id)
                    if GLOBAL_ASYNC_LOOP:
                        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=chat_id), GLOBAL_ASYNC_LOOP)
                    else:
                        send_tg_monitor("❌ Loop error: Global loop not set.", target_chat_id=chat_id)
                elif text == "/clearcache":
                    otp_filter.cache = {}
                    otp_filter._save()
                    send_tg_monitor(f"✅ OTP Cache cleared. New size: {len(otp_filter.cache)}.", target_chat_id=chat_id)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error during getUpdates (Monitor Bot): {e}")
    except Exception as e:
        print(f"❌ Unknown Error in check_cmd: {e}")


async def monitor_sms_loop():
    global total_sent
    global BOT_STATUS

    try:
        await monitor.initialize()
    except Exception as e:
        print(f"FATAL ERROR: Failed to initialize SMSMonitor. {e}")
        send_tg_monitor("🚨 **FATAL ERROR**: Gagal terhubung ke Chrome/Pyppeteer. Pastikan Chrome berjalan dengan `--remote-debugging-port=9222`.")
        BOT_STATUS["status"] = "FATAL ERROR"
        return 

    BOT_STATUS["monitoring_active"] = True

    while True:
        try:
            if BOT_STATUS["monitoring_active"]:
                msgs = await monitor.fetch_sms() 
                new = otp_filter.filter(msgs)

                if new:
                    print(f"✅ Found {len(new)} new OTP(s). Sending to Telegram one by one with 2-second delay...")
                    
                    for i, otp_data in enumerate(new):
                        # Kirim ke Channel Monitor
                        send_tg_monitor(format_otp_message(otp_data), with_inline_keyboard=True)
                        total_sent += 1
                        
                        await asyncio.sleep(2) 
                    
                    if ADMIN_ID is not None:
                        print("⚙️ Executing automatic refresh and screenshot to admin...")
                        await monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID)
                    else:
                        print("⚠️ WARNING: ADMIN_ID not set. Skipping automatic refresh/screenshot.")
            else:
                print("⏸️ Monitoring paused.")

        except Exception as e:
            error_message = f"Error during fetch/send: {e.__class__.__name__}: {e}"
            print(error_message)

        stats = update_global_status()
        # Jalankan check_cmd di thread karena menggunakan requests sinkronus
        Thread(target=check_cmd, args=(stats,)).start() 
        
        await asyncio.sleep(5) 

# ================= FLASK WEB SERVER =================

app = Flask(__name__, template_folder='templates')

@app.route('/', methods=['GET'])
def index():
    return render_template('dashboard.html')

@app.route('/api/status', methods=['GET'])
def get_status_json():
    update_global_status() 
    return jsonify(BOT_STATUS)

@app.route('/manual-check', methods=['GET'])
def manual_check():
    if ADMIN_ID is None: return jsonify({"message": "Error: Admin ID not configured for this action."}), 400
    if GLOBAL_ASYNC_LOOP is None: return jsonify({"message": "Error: Asyncio loop not initialized."}), 500
        
    try:
        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID), GLOBAL_ASYNC_LOOP)
        return jsonify({"message": "Halaman MNIT Network Refresh & Screenshot sedang dikirim ke Admin Telegram."})
    except Exception as e:
        return jsonify({"message": f"External Error: Gagal menjalankan refresh: {e.__class__.__name__}"}), 500

@app.route('/telegram-status', methods=['GET'])
def send_telegram_status_route():
    if ADMIN_ID is None: return jsonify({"message": "Error: Admin ID not configured."}), 400
    stats_msg = get_status_message(update_global_status())
    send_tg_monitor(stats_msg, target_chat_id=ADMIN_ID)
    return jsonify({"message": "Status sent to Telegram Admin."})

@app.route('/clear-cache', methods=['GET'])
def clear_otp_cache_route():
    global otp_filter
    otp_filter.cache = {}
    otp_filter._save()
    update_global_status() 
    return jsonify({"message": f"OTP Cache cleared. New size: {BOT_STATUS['cache_size']}."})

@app.route('/test-message', methods=['GET'])
def test_message_route():
    test_data = {
        "otp": "999999",
        "phone": "+2250150086627",
        "service": "MNIT Test",
        "range": "Ivory Coast",
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "raw_message": "FB:&lt;#&gt;999999 adalah kode konfirmasi. Pesan Penuh."
    }
    test_msg = format_otp_message(test_data).replace("🔐 <b>New OTP Received</b>", "🧪 <b>TEST MESSAGE FROM DASHBOARD</b>")
    send_tg_monitor(test_msg)
    return jsonify({"message": "Test message sent to main channel."})

@app.route('/start-monitor', methods=['GET'])
def start_monitor_route():
    BOT_STATUS["monitoring_active"] = True
    return jsonify({"message": "Monitor status set to Running."})

@app.route('/stop-monitor', methods=['GET'])
def stop_monitor_route():
    BOT_STATUS["monitoring_active"] = False
    return jsonify({"message": "Monitor status set to Paused."})


# ================= FUNGSI UTAMA START =================

def run_flask():
    """Fungsi untuk menjalankan Flask di thread terpisah."""
    port = int(os.environ.get('PORT', 5000))
    
    global GLOBAL_ASYNC_LOOP
    # Pastikan loop diatur untuk thread Flask 
    if GLOBAL_ASYNC_LOOP and not asyncio._get_running_loop():
        asyncio.set_event_loop(GLOBAL_ASYNC_LOOP) 
        print(f"✅ Async loop successfully set for Flask thread: {current_thread().name}")
        
    print(f"✅ Flask API & Dashboard running on http://127.0.0.1:{port}")
    
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    if not all([BOT_MONITOR_TOKEN, CHAT_MONITOR_ID, BOT_USER_TOKEN]):
        print("FATAL ERROR: Pastikan TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, dan TELEGRAM_BOT_TOKEN_USER ada di file .env.")
    else:
        print("Starting Multi-Bot SMS Monitor and User Service...")
        
        otp_filter = OTPFilter() # Inisialisasi Filter
        
        # Muat user yang sudah terdaftar dari file
        USER_ALLOWED_IDS = load_users()
        print(f"✅ Loaded {len(USER_ALLOWED_IDS)} authorized users from {USER_FILE}.")

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
        
        # 2. Kirim Pesan Aktivasi Telegram 
        send_tg_monitor("✅ <b>[Monitor Bot] ACTIVE. Monitoring is RUNNING.</b>", with_inline_keyboard=False)
        if ADMIN_ID:
            send_tg_user("✅ <b>[User Bot] ACTIVE. Ready to accept number requests.</b>", chat_id=ADMIN_ID)

        # 3. Inisialisasi dan Mulai Bot
        user_bot_instance = UserBot(BOT_USER_TOKEN)
        
        # Menjalankan dua loop bot secara konkuren (bersamaan)
        try:
            loop.run_until_complete(
                asyncio.gather(
                    monitor_sms_loop(), # Bot Monitor
                    user_bot_instance.run() # Bot Pelayanan User
                )
            )
        except KeyboardInterrupt:
            print("Bot shutting down...")
        finally:
            print("Bot core shutdown complete.")
