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
    """Fungsi ekstraksi OTP yang fleksibel."""
    if not text: return None
    patterns = [ r'\b(\d{6})\b', r'\b(\d{5})\b', r'\b(\d{4})\b', r'code[:\s]*(\d+)', r'verification[:\s]*(\d+)', r'otp[:\s]*(\d+)', r'pin[:\s]*(\d+)' ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            matched_otp = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            
            if len(matched_otp) == 4:
                try:
                    if 2000 <= int(matched_otp) <= 2099: continue 
                except ValueError:
                    continue 

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

def get_status_message(stats):
    return f"""🤖 <b>Bot Status</b>

⚡ Status: <b>{stats['status']}</b>
🌐 Login Status: <b>{'✅ Logged In' if monitor.is_logged_in else '❌ Awaiting Login'}</b>
⏱️ Uptime: {stats['uptime']}
📨 Total OTPs Sent: <b>{stats['total_otps_sent']}</b>
🔍 Last Check: {stats['last_check']}
💾 Cache Size: {stats['cache_size']} items
📅 Last Cache Reset (GMT): {stats['last_cleanup_gmt_date']}

<i>Bot is running</i>"""

def save_otp_to_json(otp_data: Dict[str, Any]):
    """Menyimpan data OTP ke file JSON di ../get/smc.json."""
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

# ================= OTP Filter Class =================

class OTPFilter:
    
    CLEANUP_KEY = '__LAST_CLEANUP_GMT__' 

    def __init__(self, file='otp_cache.json'): 
        self.file = file
        self.cache = self._load()
        self.last_cleanup_date_gmt = self.cache.pop(self.CLEANUP_KEY, '19700101') 
        self._cleanup() 
        print(f"✅ OTP Cache loaded from '{self.file}'. Size after cleanup: {len(self.cache)} items. Last cleanup GMT: {self.last_cleanup_date_gmt}")
        
    def _load(self) -> Dict[str, Dict[str, Any]]:
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
        
    def _save(self): 
        temp_cache = self.cache.copy()
        temp_cache[self.CLEANUP_KEY] = self.last_cleanup_date_gmt
        json.dump(temp_cache, open(self.file,'w'), indent=2)
    
    def _cleanup(self):
        now_gmt = datetime.now(timezone.utc).strftime('%Y%m%d')
        if now_gmt > self.last_cleanup_date_gmt:
            print(f"🚨 Daily OTP cache cleanup triggered. Last cleanup: {self.last_cleanup_date_gmt}, Current GMT day: {now_gmt}")
            self.cache = {} 
            self.last_cleanup_date_gmt = now_gmt
            self._save()
        else:
            self._save()
        
    def key(self, d: Dict[str, Any]) -> str: 
        return str(d.get('otp'))
    
    def is_dup(self, d: Dict[str, Any]) -> bool:
        self._cleanup() 
        key = self.key(d)
        if not key or key == 'None': return False 
        return key in self.cache
        
    def add(self, d: Dict[str, Any]):
        key = self.key(d)
        if not key or key == 'None': return
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

class SMSMonitor:
    
    def __init__(self, url=DASHBOARD_URL): 
        self.url = url
        self.browser = None
        self.page = None
        self.is_logged_in = False 
        self._temp_username = None 
        self._temp_password = None 

    async def initialize(self, p_instance):
        
        # 1. Koneksi ke Chrome Debug Port
        self.browser = await p_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        
        # 2. Ambil context pertama 
        context = self.browser.contexts[0]
        
        # 3. Buat page baru
        self.page = await context.new_page()
        
        print("✅ Playwright page connected successfully.")

    async def login(self):
        """Melakukan proses login ke X.MNITNetwork menggunakan kredensial di memori."""
        if not self.page:
            raise Exception("Page not initialized for login.")
        
        USERNAME = self._temp_username
        PASSWORD = self._temp_password
        
        if not USERNAME or not PASSWORD:
            raise Exception("Login credentials not found in memory. Please use /login command first.")
        
        # --- PERUBAHAN 1: Navigasi eksplisit dan tunggu selector ---
        print(f"Attempting to navigate to login page: {LOGIN_URL} (Simulating Human Typing URL)")
        
        # Mulai dari halaman kosong untuk simulasi human navigation
        await self.page.goto("about:blank") 
        # Navigasi ke URL login
        await self.page.goto(LOGIN_URL, wait_until='load', timeout=15000) 
        
        # Tunggu hingga kolom email muncul
        EMAIL_SELECTOR = 'input[type="email"]'
        PASSWORD_SELECTOR = 'input[type="password"]'
        SUBMIT_SELECTOR = 'button[type="submit"]'
        
        await self.page.wait_for_selector(EMAIL_SELECTOR, timeout=10000) 
        # ----------------------------------------

        # 1. Isi Username dengan simulasi Human Typing (delay=100ms)
        print("Filling in username with human-like delay...")
        await self.page.click(EMAIL_SELECTOR)
        await self.page.type(EMAIL_SELECTOR, USERNAME, delay=100) 
        
        # 2. Isi Password dengan simulasi Human Typing (delay=100ms)
        print("Filling in password with human-like delay...")
        await self.page.click(PASSWORD_SELECTOR)
        await self.page.type(PASSWORD_SELECTOR, PASSWORD, delay=100)
        
        # 3. Klik Tombol Login
        print("Clicking login button...")
        # Beri jeda sejenak sebelum klik
        await asyncio.sleep(1) 
        await self.page.click(SUBMIT_SELECTOR) 
        
        # 4. Tunggu navigasi ke dashboard
        try:
            # Tingkatkan timeout untuk mengantisipasi TargetClosedError/slow server
            await self.page.wait_for_url(DASHBOARD_URL, timeout=30000) 
            self.is_logged_in = True
            
            # --- Bersihkan kredensial dari memori setelah sukses ---
            self._temp_username = None 
            self._temp_password = None
            # ------------------------------------------------------
            
            print("✅ Login successful, navigated to dashboard.")
            return True
        
        # --- Catch Error dan ambil screenshot ---
        except Exception as e:
            self.is_logged_in = False
            error_msg = f"❌ Login failed or did not navigate to dashboard within 30s. Error: {e}"
            print(error_msg)
            
            screenshot_filename = f"login_fail_{int(time.time())}.png"
            try:
                # Coba ambil screenshot (bisa gagal jika target sudah ditutup)
                await self.page.screenshot(path=screenshot_filename, full_page=True)
                send_photo_tg(screenshot_filename, f"⚠️ Gagal Login ke X.MNITNetwork. Screenshot diambil:", target_chat_id=ADMIN_ID)
                os.remove(screenshot_filename)
            except Exception as se:
                print(f"❌ Gagal mengambil screenshot karena Target Closed/Internal Error: {se.__class__.__name__}")
                send_tg(f"⚠️ Gagal Login ke X.MNITNetwork. Error: `{e.__class__.__name__}`. Gagal mengambil screenshot karena target ditutup.", target_chat_id=ADMIN_ID)
            
            raise Exception(error_msg)

    async def login_and_notify(self, admin_chat_id):
        """Wrapper untuk login dan mengirim notifikasi ke admin."""
        try:
            success = await self.login()
            if success:
                # Mengirim screenshot DASHBOARD setelah login berhasil
                await self.refresh_and_screenshot(admin_chat_id)
                send_tg(f"✅ Login berhasil! Sekarang Anda dapat memulai monitoring dengan perintah: /startnew", target_chat_id=admin_chat_id)
            
        except Exception as e:
            if not self.is_logged_in:
                 send_tg(f"❌ Login GAGAL (Pastikan kredensial benar). Error: `{e.__class__.__name__}`.", target_chat_id=admin_chat_id)
            self.is_logged_in = False

    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page or not self.is_logged_in: 
            print("⚠️ ERROR: Page not initialized or not logged in during fetch_sms.")
            return []
            
        if self.page.url != self.url:
            print(f"Navigating to dashboard URL: {self.url}")
            try:
                await self.page.goto(self.url, wait_until='networkidle', timeout=15000)
            except Exception as e:
                print(f"❌ Error navigating to dashboard: {e}")
                return []


        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        messages = []

        rows = soup.find_all("tr")
        for r in rows:
            otp_badge_span = r.find("span", class_="otp-badge")
            
            if otp_badge_span:
                
                # A. Phone Number
                phone_span = r.find("span", class_="phone-number")
                phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else "N/A")
                
                # B. Raw Message
                copy_icon = otp_badge_span.find("i", class_="copy-icon")
                raw_message_original = copy_icon.get('data-sms', 'N/A') if copy_icon and copy_icon.get('data-sms') else otp_badge_span.get_text(strip=True)
                
                if ':' in raw_message_original and raw_message_original != 'N/A':
                    raw_message_clean = raw_message_original.split(':', 1)[1].strip()
                else:
                    raw_message_clean = raw_message_original
                
                
                # C. OTP 
                otp_raw_text_parts = [t.strip() for t in otp_badge_span.contents if t.name is None and t.strip()]
                otp = otp_raw_text_parts[0] if otp_raw_text_parts and otp_raw_text_parts[0].isdigit() else None 
                
                if not otp:
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
    
    async def soft_refresh(self): 
        """Memuat ulang halaman."""
        if not self.page or not self.is_logged_in: 
            print("❌ Error: Page not initialized or not logged in for soft refresh.")
            return

        try:
            print("🔄 Performing soft page refresh...")
            await self.page.reload(wait_until='networkidle') 
            print("✅ Soft refresh complete.")
        except Exception as e:
            print(f"❌ Error during soft refresh: {e}")

    async def refresh_and_screenshot(self, admin_chat_id): 
        if not self.page or not self.is_logged_in:
            print("❌ Error: Page not initialized/not logged in for refresh/screenshot.")
            send_tg(f"⚠️ **Error Refresh/Screenshot**: Gagal inisialisasi/belum login.", target_chat_id=admin_chat_id)
            return False

        screenshot_filename = f"screenshot_{int(time.time())}.png"
        try:
            if self.page.url != self.url:
                await self.page.goto(self.url, wait_until='networkidle')
                
            print("🔄 Performing page reload...")
            await self.page.reload(wait_until='networkidle') 
            print(f"📸 Taking screenshot: {screenshot_filename}")
            await self.page.screenshot(path=screenshot_filename, full_page=True)
            print("📤 Sending screenshot to Admin Telegram...")
            caption = f"✅ Page Reloaded successfully at {datetime.now().strftime('%H:%M:%S')}"
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
    "monitoring_active": False, 
    "last_cleanup_gmt_date": "N/A"
}

def update_global_status():
    global BOT_STATUS
    global total_sent
    uptime_seconds = time.time() - start
    
    BOT_STATUS["uptime"] = f"{int(uptime_seconds//3600)}h {int((uptime_seconds%3600)//60)}m {int(uptime_seconds%60)}s"
    BOT_STATUS["total_otps_sent"] = total_sent
    BOT_STATUS["last_check"] = datetime.now().strftime("%H:%M:%S")
    BOT_STATUS["cache_size"] = len(otp_filter.cache)
    BOT_STATUS["monitoring_active"] = BOT_STATUS["monitoring_active"] 
    BOT_STATUS["status"] = "Running" if BOT_STATUS["monitoring_active"] and monitor.is_logged_in else ("Paused (Logged In)" if monitor.is_logged_in and not BOT_STATUS["monitoring_active"] else "Paused (Not Logged In)")
    BOT_STATUS["last_cleanup_gmt_date"] = otp_filter.last_cleanup_date_gmt 
    
    # Perbarui status jika monitoring aktif tetapi belum login
    if BOT_STATUS["monitoring_active"] and not monitor.is_logged_in:
         BOT_STATUS["status"] = "Running (Awaiting Login)"
         
    return BOT_STATUS

# ================= FUNGSI UTAMA LOOP DAN COMMAND CHECK =================

def check_cmd(stats):
    global LAST_ID
    global BOT_STATUS
    global AWAITING_CREDENTIALS
    
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
                
                # --- MODE 2: AWAITING CREDENTIALS ---
                if AWAITING_CREDENTIALS:
                    
                    # Split berdasarkan newline atau spasi
                    parts = text.split() 
                    
                    # Cek jika formatnya (email\npassword) atau (email password)
                    if len(parts) == 2:
                        
                        username_input = parts[0]
                        password_input = parts[1]
                        
                        monitor._temp_username = username_input
                        monitor._temp_password = password_input
                        AWAITING_CREDENTIALS = False # Selesai menunggu
                        
                        send_tg("⏳ Kredensial diterima. Executing login to X.MNITNetwork...", with_inline_keyboard=False, target_chat_id=chat_id)
                        
                        if GLOBAL_ASYNC_LOOP:
                            asyncio.run_coroutine_threadsafe(monitor.login_and_notify(admin_chat_id=chat_id), GLOBAL_ASYNC_LOOP)
                        else:
                            send_tg("❌ Loop error: Global loop not set.", target_chat_id=chat_id)
                            
                    else:
                        # Jika Admin mengirim pesan lain saat bot menunggu
                        send_tg("⚠️ Format kredensial salah. Harap kirim <b>Email/Username dan Password</b> di dua baris terpisah atau dalam satu pesan, contoh:\n<code>muhamadreyhan0073@gmail.com\nfd140206</code>", target_chat_id=chat_id)
                        
                    continue # Langsung ke update berikutnya

                # --- MODE 1: COMMAND MODE ---
                
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
                        
                elif text.lower() == "/login": 
                    AWAITING_CREDENTIALS = True
                    send_tg(
                        "🔒 **Mode Kredensial Aktif**\n\n"
                        "Silakan kirim **Email/Username** dan **Password** di dua baris terpisah, atau dalam satu pesan, dengan format berikut:\n\n"
                        "Contoh:\n"
                        "<code>muhamadreyhan0073@gmail.com\n"
                        "fd140206</code>\n\n"
                        "<i>(Bot akan memproses pesan berikutnya sebagai kredensial)</i>",
                        target_chat_id=chat_id
                    )
                        
                elif text == "/startnew":
                    BOT_STATUS["monitoring_active"] = True
                    if monitor.is_logged_in:
                         send_tg("✅ Monitoring started/resumed. Checking for new OTPs...", target_chat_id=chat_id)
                    else:
                         send_tg("⚠️ Monitoring started, but you are not logged in yet. Please use `/login` to enter credentials.", target_chat_id=chat_id)
                
                elif text == "/stop":
                    BOT_STATUS["monitoring_active"] = False
                    send_tg("⏸️ Monitoring paused. Use /startnew to resume.", target_chat_id=chat_id)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error during getUpdates: {e}")
    except Exception as e:
        print(f"❌ Unknown Error in check_cmd: {e}")

async def monitor_sms_loop():
    global total_sent
    global BOT_STATUS
    
    async with async_playwright() as p:
        try:
            await monitor.initialize(p)
        except Exception as e:
            print(f"FATAL ERROR: Failed to initialize SMSMonitor (Playwright/Browser connection). {e}")
            send_tg("🚨 **FATAL ERROR**: Gagal terhubung ke Chrome/Playwright. Pastikan Chrome berjalan dengan `--remote-debugging-port=9222`.")
            BOT_STATUS["status"] = "FATAL ERROR"
            return 
    
        BOT_STATUS["monitoring_active"] = False 
        
        # Kirim pesan awal dan minta login
        initial_msg = (
            "✅ <b>BOT X.MNIT ACTIVE MONITORING IS RUNNING.</b>\n\n"
            "⚠️ **PERHATIAN**: Monitoring saat ini **PAUSED** dan belum login.\n\n"
            "Silakan gunakan perintah admin berikut:\n"
            "1. **Login & Kirim Kredensial**: `/login` (Bot akan meminta Email dan Password secara terpisah)\n" 
            "2. **Mulai Monitoring**: `/startnew` (untuk memulai/melanjutkan cek OTP)"
        )
        send_tg(initial_msg, with_inline_keyboard=False, target_chat_id=ADMIN_ID)


        while True:
            try:
                # Cek: Harus monitoring_active DAN harus is_logged_in
                if BOT_STATUS["monitoring_active"] and monitor.is_logged_in:
                    
                    msgs = await monitor.fetch_sms()
                    
                    new = otp_filter.filter(msgs)

                    if new:
                        print(f"✅ Found {len(new)} new OTP(s). Sending to Telegram one by one with 2-second delay...")
                        
                        for i, otp_data in enumerate(new):
                            save_otp_to_json(otp_data)
                            
                            message_text = format_otp_message(otp_data)
                            print(f"   -> Sending OTP {i+1}/{len(new)}: {otp_data['otp']} for {otp_data['phone']}")
                            
                            send_tg(message_text, with_inline_keyboard=True)
                            total_sent += 1
                            
                            await asyncio.sleep(2) 
                        
                        print("ℹ️ ALL automatic refresh functions are disabled. Use /refresh command.")
                        
                elif BOT_STATUS["monitoring_active"] and not monitor.is_logged_in:
                    print("⚠️ Monitoring active but paused. Awaiting successful login...")
                    
                else: # BOT_STATUS["monitoring_active"] is False
                    print("⏸️ Monitoring paused.")


            except Exception as e:
                error_message = f"Error during fetch/send: {e.__class__.__name__}: {e}"
                print(error_message)

            stats = update_global_status()
            check_cmd(stats)
            
            await asyncio.sleep(5) 

# ================= FLASK WEB SERVER UNTUK API DAN DASHBOARD =================

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
    if GLOBAL_ASYNC_LOOP is None:
        return jsonify({"message": "Error: Asyncio loop not initialized."}), 500
    if not monitor.is_logged_in:
        return jsonify({"message": "Error: Not logged in. Please /login first via Telegram or login manually."}), 400
        
    try:
        asyncio.run_coroutine_threadsafe(monitor.refresh_and_screenshot(admin_chat_id=ADMIN_ID), GLOBAL_ASYNC_LOOP)
        return jsonify({"message": "Halaman X.MNIT Network Refresh & Screenshot sedang dikirim ke Admin Telegram."})
    except RuntimeError as e:
        return jsonify({"message": f"Fatal Error: Asyncio loop issue ({e.__class__.__name__}). Cek log RDP Anda."}), 500
    except Exception as e:
        return jsonify({"message": f"External Error: Gagal menjalankan refresh. Cek log RDP Anda: {e.__class__.__name__}"}), 500

@app.route('/telegram-status', methods=['GET'])
def send_telegram_status_route():
    if ADMIN_ID is None: return jsonify({"message": "Error: Admin ID not configured."}), 400
    
    stats_msg = get_status_message(update_global_status())
    send_tg(stats_msg, target_chat_id=ADMIN_ID)
    
    return jsonify({"message": "Status sent to Telegram Admin."})

@app.route('/clear-cache', methods=['GET'])
def clear_otp_cache_route():
    global otp_filter
    
    now_gmt_str = datetime.now(timezone.utc).strftime('%Y%m%d')
    
    otp_filter.cache = {}
    otp_filter.last_cleanup_date_gmt = now_gmt_str
    otp_filter._save()
    
    update_global_status() 
    return jsonify({"message": f"OTP Cache cleared manually. New size: {BOT_STATUS['cache_size']}."})

@app.route('/test-message', methods=['GET'])
def test_message_route():
    test_data = {
        "otp": "123456",
        "phone": "+12345678999",
        "service": "Facebook",
        "range": "Zura Store",
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "raw_message": "123456 adalah kode konfirmasi Facebook anda: AAABBBCC"
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
    if not BOT or not CHAT or not ADMIN_ID:
        print("FATAL ERROR: Pastikan TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, dan TELEGRAM_ADMIN_ID ada di file .env.")
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
        
        # 2. Mulai loop asinkron monitoring
        try:
            loop.run_until_complete(monitor_sms_loop())
        except KeyboardInterrupt:
            print("Bot shutting down...")
        finally:
            print("Bot core shutdown complete.")
