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

# Muat variabel lingkungan dari file .env
load_dotenv()

# ================= Konstanta Telegram untuk Tombol =================
TELEGRAM_BOT_LINK = "https://t.me/zuraxridbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"

# ================= Telegram Configuration (Loaded from .env) =================
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except (ValueError, TypeError):
    print("⚠️ WARNING: TELEGRAM_ADMIN_ID tidak valid. Perintah admin dinonaktifkan.")
    ADMIN_ID = None

LAST_ID = 0

# ================= Global State for Asyncio Loop =================
GLOBAL_ASYNC_LOOP = None # Variabel global untuk menyimpan event loop utama

# ================= Utils =================

def get_local_ip():
    """Mencari IP address lokal perangkat untuk keperluan fallback."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) 
        ip = s.getsockname()[0]
        return ip
    except Exception:
        return "127.0.0.1" 
    finally:
        if s:
            s.close()
            
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
    timestamp = otp_data.get('timestamp', datetime.now().strftime('%H:%M:%S'))
    full_message = otp_data.get('raw_message', 'N/A')
    return f"""🔐 <b>New OTP Received</b>

🏷️ Range: <b>{range_text}</b>

📱 Number: <code>{masked_phone}</code>
🌐 Service: <b>{service}</b>
🔢 OTP: <code>{otp}</code>

FULL MESSAGES:
<blockquote>{full_message}</blockquote>"""

# FUNGSI INI TIDAK LAGI DIGUNAKAN KARENA KITA MENGIRIMKAN SATU PER SATU
def format_multiple_otps(otp_list):
    # Ditinggalkan untuk memastikan kode tidak error, tapi logika pengiriman di loop utama sudah diubah.
    if len(otp_list) == 1: return format_otp_message(otp_list[0])
    header = f"🔐 <b>{len(otp_list)} New OTPs Received</b>\n\n"
    items = []
    for i, otp_data in enumerate(otp_list, 1):
        otp = otp_data['otp']
        phone = otp_data['phone']
        masked_phone = mask_phone_number(phone, visible_start=4, visible_end=4)
        service = otp_data['service']
        range_text = otp_data.get('range', 'N/A')
        items.append(f"<b>{i}.</b> <code>{otp}</code> | {service} | <code>{masked_phone}</code> | {range_text}")
    return header + "\n".join(items) + "\n\n<i>Tap any OTP to copy it!</i>"

def extract_otp_from_text(text):
    """Fungsi ekstraksi OTP yang fleksibel (dipertahankan untuk keamanan)."""
    if not text: return None
    # Pola untuk mencari 6, 5, atau 4 digit (memastikan 4 digit bukan tahun)
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

# ================= OTP Filter Class =================

class OTPFilter:
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
            except json.JSONDecodeError as e:
                print(f"⚠️ WARNING: Cache file '{self.file}' corrupted. Resetting cache. Error: {e}")
                return {}
            except Exception as e:
                print(f"Error loading cache: {e}")
                return {}
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
        
    # PERBAIKAN FILTER: Menggunakan hanya OTP dan Nomor Telepon untuk kunci unik
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

otp_filter = OTPFilter()

# ================= Telegram Functionality =================

def send_tg(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use:
        print("❌ Telegram config missing (BOT or CHAT ID). Cannot send message.")
        return
    payload = {'chat_id': chat_id_to_use, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard:
        payload['reply_markup'] = create_inline_keyboard()
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            data=payload,
            timeout=15  
        )
        if not response.ok:
            print(f"⚠️ Telegram API Error ({response.status_code}): {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram Connection Error: {e}")
    except Exception as e:
        print(f"❌ Unknown Error in send_tg: {e}")

def send_photo_tg(photo_path, caption="", target_chat_id=None):
    chat_id_to_use = target_chat_id if target_chat_id is not None else CHAT
    if not BOT or not chat_id_to_use:
        print("❌ Telegram config missing (BOT or CHAT ID). Cannot send photo.")
        return False
    url = f"https://api.telegram.org/bot{BOT}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo_file:
            files = {'photo': photo_file}
            data = {'chat_id': chat_id_to_use, 'caption': caption, 'parse_mode': 'HTML'}
            response = requests.post(url, files=files, data=data, timeout=20)
        if not response.ok:
            print(f"⚠️ Telegram Photo API Error ({response.status_code}): {response.text}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram Connection Error while sending photo: {e}")
        return False
    except Exception as e:
        print(f"❌ Unknown Error in send_photo_tg: {e}")
        return False

# ================= Scraper & Monitor Class =================
URL = "https://v2.mnitnetwork.com/dashboard/getnum" 

class SMSMonitor:
    def __init__(self, url=URL):
        self.url = url
        self.browser = None
        self.page = None

    async def initialize(self):
        # PASTIKAN ANDA SUDAH MENJALANKAN CHROME DENGAN ARGUMEN INI DI RDP:
        # chrome.exe --remote-debugging-port=9222
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

    async def fetch_sms(self):
        if not self.page: await self.initialize()
            
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        messages = []

        # Target semua baris tabel
        rows = soup.find_all("tr")

        for r in rows:
            # 1. Cek apakah baris memiliki OTP (hanya baris sukses)
            otp_badge_span = r.find("span", class_="otp-badge")
            
            if otp_badge_span:
                
                # --- Ekstraksi Data ---
                
                # A. Phone Number
                phone_span = r.find("span", class_="phone-number")
                phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else "N/A")
                
                # B. Raw Message (dari data-sms attribute)
                copy_icon = otp_badge_span.find("i", class_="copy-icon")
                raw_message = copy_icon.get('data-sms', 'N/A') if copy_icon else otp_badge_span.get_text(strip=True)
                
                # C. OTP (diekstrak dari raw_message atau teks badge yang bersih)
                otp_raw_text = otp_badge_span.get_text(strip=True, separator=' ')
                otp = extract_otp_from_text(otp_raw_text)
                
                # D. Range/Country
                tds = r.find_all("td")
                range_text = "N/A"
                if len(tds) > 1:
                    range_badge = tds[1].find("span", class_="badge")
                    if range_badge:
                        range_text = range_badge.get_text(strip=True)
                
                # E. Service (dari Raw Message/data-sms)
                service_raw = raw_message.split(':', 1)[0] if raw_message != 'N/A' and ':' in raw_message else 'Unknown'
                service = clean_service_name(service_raw)
                
                # --- Simpan Hasil ---
                if otp and phone != 'N/A':
                    messages.append({
                        "otp": otp,
                        "phone": phone,
                        "service": service,
                        "range": range_text,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "raw_message": raw_message
                    })
        return messages
    
    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page:
            try: await self.initialize()
            except Exception as e:
                print(f"❌ Error during initial connect for refresh: {e}")
                send_tg(f"⚠️ **Error Refresh/Screenshot**: Gagal inisialisasi koneksi browser. `{e.__class__.__name__}: {e}`", target_chat_id=admin_chat_id)
                return False

        screenshot_filename = f"screenshot_{int(time.time())}.png"
        try:
            print("🔄 Performing page refresh...")
            await self.page.reload({'waitUntil': 'networkidle0'}) 
            print(f"📸 Taking screenshot: {screenshot_filename}")
            await self.page.screenshot({'path': screenshot_filename, 'fullPage': True})
            print("📤 Sending screenshot to Admin Telegram...")
            caption = f"✅ Page Refreshed successfully at {datetime.now().strftime('%H:%M:%S')}\n\n<i>Pesan OTP di halaman telah dihapus.</i>"
            success = send_photo_tg(screenshot_filename, caption, target_chat_id=admin_chat_id)
            return success
        except Exception as e:
            print(f"❌ Error during refresh/screenshot: {e}")
            send_tg(f"⚠️ **Error Refresh/Screenshot**: `{e.__class__.__name__}: {e}`", target_chat_id=admin_chat_id)
            return False
        finally:
            if os.path.exists(screenshot_filename):
                os.remove(screenshot_filename)
                print(f"🗑️ Cleaned up {screenshot_filename}")
    
    async def fetch_and_process_once(self, admin_chat_id):
        pass

monitor = SMSMonitor()

# ================= Status Global dan Fungsi Update =================
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

# ================= FUNGSI UTAMA LOOP DAN COMMAND CHECK =================

def check_cmd(stats):
    global LAST_ID
    if ADMIN_ID is None: return

    try:
        upd = requests.get(
            f"https://api.telegram.org/bot{BOT}/getUpdates?offset={LAST_ID+1}",
            timeout=15  
        ).json()

        for u in upd.get("result",[]):
            LAST_ID = u["update_id"]
            msg = u.get("message",{})
            text = msg.get("text","")
            user_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")

            if user_id == ADMIN_ID:
                if text == "/status":
                    requests.post(
                        f"https://api.telegram.org/bot{BOT}/sendMessage",
                        data={'chat_id': chat_id, 'text': get_status_message(stats), 'parse_mode': 'HTML'}
                    )
                elif text == "/refresh":
                    send_tg("⏳ Executing page refresh and screenshot...", with_inline_keyboard=False, target_chat_id=chat_id)
                    if GLOBAL_ASYNC_LOOP:
                        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=chat_id), GLOBAL_ASYNC_LOOP)
                    else:
                        send_tg("❌ Loop error: Global loop not set.", target_chat_id=chat_id)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error during getUpdates: {e}")
    except Exception as e:
        print(f"❌ Unknown Error in check_cmd: {e}")


async def monitor_sms_loop():
    global total_sent
    global BOT_STATUS

    try:
        await monitor.initialize()
    except Exception as e:
        print(f"FATAL ERROR: Failed to initialize SMSMonitor (Pyppeteer/Browser connection). {e}")
        send_tg("🚨 **FATAL ERROR**: Gagal terhubung ke Chrome/Pyppeteer. Pastikan Chrome berjalan dengan `--remote-debugging-port=9222`.")
        BOT_STATUS["status"] = "FATAL ERROR"
        return 

    BOT_STATUS["monitoring_active"] = True

    while True:
        try:
            if BOT_STATUS["monitoring_active"]:
                msgs = await monitor.fetch_sms()
                new = otp_filter.filter(msgs)

                if new:
                    print(f"✅ Found {len(new)} new OTP(s). Sending to Telegram one by one...")
                    
                    # 💥 LOGIKA PENGIRIMAN SATU PER SATU 💥
                    for otp_data in new:
                        message_text = format_otp_message(otp_data)
                        send_tg(message_text, with_inline_keyboard=True)
                        total_sent += 1
                        # Jeda singkat agar Telegram tidak mengira spam jika banyak OTP sekaligus
                        await asyncio.sleep(0.5) 
                    
                    # Refresh hanya dilakukan di sini (setelah semua pesan terkirim)
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
        check_cmd(stats)
        
        await asyncio.sleep(5) 

# ================= FLASK WEB SERVER UNTUK API DAN DASHBOARD =================

app = Flask(__name__, template_folder='templates')

# 1. ROUTE UTAMA (UNTUK DASHBOARD)
@app.route('/', methods=['GET'])
def index():
    """Melayani file dashboard.html."""
    return render_template('dashboard.html')

# 2. ROUTE API (UNTUK DIPANGGIL OLEH JAVASCRIPT DI dashboard.html)
@app.route('/api/status', methods=['GET'])
def get_status_json():
    """Mengembalikan data status bot dalam format JSON."""
    update_global_status() 
    return jsonify(BOT_STATUS)

# ROUTE INI DIUBAH MENJADI FUNGSI REFRESH & SCREENSHOT SAJA
@app.route('/manual-check', methods=['GET'])
def manual_check():
    """Memanggil refresh_and_screenshot di loop asinkron (dipicu dari Dashboard)."""
    if ADMIN_ID is None: return jsonify({"message": "Error: Admin ID not configured for this action."}), 400
    if GLOBAL_ASYNC_LOOP is None:
        return jsonify({"message": "Error: Asyncio loop not initialized."}), 500
        
    try:
        # Panggil refresh_and_screenshot
        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID), GLOBAL_ASYNC_LOOP)
        return jsonify({"message": "Halaman MNIT Network Refresh & Screenshot sedang dikirim ke Admin Telegram."})
    except RuntimeError as e:
        return jsonify({"message": f"Fatal Error: Asyncio loop issue ({e.__class__.__name__}). Cek log RDP Anda."}), 500
    except Exception as e:
        return jsonify({"message": f"External Error: Gagal menjalankan refresh. Cek log RDP Anda: {e.__class__.__name__}"}), 500

@app.route('/telegram-status', methods=['GET'])
def send_telegram_status_route():
    """Memanggil fungsi untuk mengirim status ke Telegram."""
    if ADMIN_ID is None: return jsonify({"message": "Error: Admin ID not configured."}), 400
    
    stats_msg = get_status_message(update_global_status())
    send_tg(stats_msg, target_chat_id=ADMIN_ID)
    
    return jsonify({"message": "Status sent to Telegram Admin."})

@app.route('/clear-cache', methods=['GET'])
def clear_otp_cache_route():
    """Membersihkan cache OTP."""
    global otp_filter
    otp_filter.cache = {}
    otp_filter._save()
    
    update_global_status() 
    return jsonify({"message": f"OTP Cache cleared. New size: {BOT_STATUS['cache_size']}."})

@app.route('/test-message', methods=['GET'])
def test_message_route():
    """Mengirim pesan tes ke Telegram menggunakan format OTP."""
    test_data = {
        "otp": "999999",
        "phone": "+2250150086627",
        "service": "MNIT Test",
        "range": "Ivory Coast",
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "raw_message": "FACEBOOK: FB-999999 adalah kode konfirmasi Facebook anda (Pesan Tes)."
    }
    
    test_msg = format_otp_message(test_data).replace("🔐 <b>New OTP Received</b>", "🧪 <b>TEST MESSAGE FROM DASHBOARD</b>")
    
    send_tg(test_msg)
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
    if GLOBAL_ASYNC_LOOP and not asyncio._get_running_loop():
        asyncio.set_event_loop(GLOBAL_ASYNC_LOOP) 
        print(f"✅ Async loop successfully set for Flask thread: {current_thread().name}")
        
    print(f"✅ Flask API & Dashboard running on http://127.0.0.1:{port}")
    
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    if not BOT or not CHAT:
        print("FATAL ERROR: Pastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID ada di file .env.")
    else:
        print("Starting SMS Monitor Bot and Flask API...")
        
        print("\n=======================================================")
        print("     ⚠️  PENTING: JALANKAN NGROK DI TERMINAL LAIN  ⚠️")
        print("     Setelah bot ini running, buka terminal baru dan:")
        print("     ngrok http 5000")
        print("=======================================================\n")

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
        send_tg("✅ <b>BOT ACTIVE MONITORING IS RUNNING.</b>", with_inline_keyboard=False)
        
        # 3. Mulai loop asinkron monitoring
        try:
            loop.run_until_complete(monitor_sms_loop())
        except KeyboardInterrupt:
            print("Bot shutting down...")
        finally:
            print("Bot core shutdown complete.")
