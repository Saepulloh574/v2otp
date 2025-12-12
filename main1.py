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

# In-Memory Cache untuk OTP dan User Request
otp_filter = None # Akan diinisialisasi nanti
USER_REQUEST_CACHE = {} # { Nomor Pending: User ID Telegram }
USER_ALLOWED_IDS = set() # { User ID Telegram }

# Global State
GLOBAL_ASYNC_LOOP = None
start = time.time()
total_sent = 0
# ... (BOT_STATUS tetap)


# ================= Utils & Telegram Functions (Dipersingkat) =================

# ... (Semua fungsi utils: get_local_ip, create_inline_keyboard, clean_phone_number, 
# mask_phone_number, format_otp_message, extract_otp_from_text, 
# clean_service_name, get_status_message, update_global_status, OTPFilter, dll.)
# ***************** GANTIKAN DENGAN KODE LAMA ANDA *****************


# --- Fungsi Telegram Generik ---
def send_tg_generic(token, chat_id, text, with_inline_keyboard=False):
    if not token or not chat_id:
        print("❌ Telegram config missing. Cannot send message.")
        return
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if with_inline_keyboard:
        # Gunakan keyboard yang sama atau buat keyboard khusus jika perlu
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

# Fungsi Kirim untuk Bot Monitor (sama seperti send_tg lama)
def send_tg_monitor(text, with_inline_keyboard=False, target_chat_id=None):
    chat_id = target_chat_id if target_chat_id is not None else CHAT_MONITOR_ID
    send_tg_generic(BOT_MONITOR_TOKEN, chat_id, text, with_inline_keyboard)

# Fungsi Kirim untuk Bot User
def send_tg_user(text, chat_id, with_inline_keyboard=False):
    send_tg_generic(BOT_USER_TOKEN, chat_id, text, with_inline_keyboard)


# ================= User Bot Class (NEW) =================

class UserBot:
    def __init__(self, token):
        self.token = token
        self.last_id = 0
    
    async def run(self):
        print("🚀 User Bot (Pelayanan) started...")
        while True:
            await self._check_updates()
            await asyncio.sleep(1) # Cek update setiap 1 detik

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

            if not chat_id: continue # Abaikan jika tidak ada chat_id

            if text == "/start":
                USER_ALLOWED_IDS.add(user_id)
                send_tg_user(
                    f"Halo, ID Anda ({user_id}) telah disimpan. Silakan kirimkan format nomor telepon yang ingin Anda dapatkan.", 
                    chat_id
                )
                send_tg_monitor(f"👤 **New User Registered**: ID `{user_id}`", with_inline_keyboard=False)
            
            elif user_id in USER_ALLOWED_IDS and text.startswith('+') or text.isdigit():
                # Format yang diminta: 2246543XXX atau +2246543XXX
                if monitor.page is None:
                    send_tg_user("❌ Sistem sedang inisialisasi. Coba lagi sebentar.", chat_id)
                    continue

                # Normalisasi dan validasi input nomor (minimal 6 digit)
                input_number = clean_phone_number(text)
                if len(input_number) < 6:
                    send_tg_user("⚠️ Format nomor tidak valid. Contoh: `+2246543XXX`", chat_id)
                    continue
                
                # Masukkan request ke cache
                USER_REQUEST_CACHE[input_number] = user_id 
                
                # Eksekusi Get Number di Browser
                asyncio.run_coroutine_threadsafe(
                    monitor.get_number_on_page(input_number), 
                    GLOBAL_ASYNC_LOOP
                )

                print(f"✅ User {user_id} requested number: {input_number}")
                send_tg_user(f"⏳ Nomor `{input_number}` sedang diproses. Mohon tunggu notifikasi.", chat_id)
            
            else:
                if user_id not in USER_ALLOWED_IDS:
                    send_tg_user("Mohon ketik /start terlebih dahulu.", chat_id)


# ================= Scraper & Monitor Class (MODIFIED) =================

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

        print(f"-> Browser Action: Refreshing page...")
        await self.page.reload({'waitUntil': 'networkidle0'})
        
        try:
            # 1. Input Nomor
            print(f"-> Browser Action: Typing {number_prefix}...")
            await self.page.type('input[name="numberrange"]', number_prefix, {'delay': 50})
            
            # 2. Klik Tombol
            print(f"-> Browser Action: Clicking Get Numbers...")
            await self.page.click('#getNumberBtn')
            
            # Tunggu sebentar agar status "pending" muncul
            await asyncio.sleep(3) 

            print(f"✅ Number {number_prefix} successfully requested on the page.")

        except Exception as e:
            error_msg = f"❌ Gagal input/klik tombol di browser: {e.__class__.__name__}: {e}"
            print(error_msg)
            # Hapus dari cache jika gagal
            if number_prefix in USER_REQUEST_CACHE:
                user_id = USER_REQUEST_CACHE.pop(number_prefix)
                send_tg_user(f"❌ Gagal memproses nomor `{number_prefix}`. Coba lagi.", user_id)

    async def fetch_sms(self):
        # LOGIKA FETCH SMS SAMA SEPERTI KODE FINAL TERAKHIR
        # ... (Mengambil pesan sukses)
        
        # *** Logika Baru: Memproses Status Pending ***
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Cari baris dengan status 'pending'
        pending_rows = soup.find_all("span", class_="status-pending")
        
        for p_span in pending_rows:
            row = p_span.find_parent("tr")
            if not row: continue
            
            phone_span = row.find("span", class_="phone-number")
            phone = clean_phone_number(phone_span.get_text(strip=True) if phone_span else None)
            
            if phone:
                # Cek apakah nomor ini diminta oleh user
                for prefix, user_id in USER_REQUEST_CACHE.items():
                    # Jika nomor pending cocok dengan prefix yang diminta user
                    if phone.startswith(prefix) or phone.startswith(prefix.replace('+', '')):
                        
                        # Kirim notifikasi ke user!
                        message = f"✅ Nomor **{phone}** telah berhasil *di-request*."
                        message += "\n\nMenunggu OTP..."
                        send_tg_user(message, user_id)
                        
                        print(f"-> NOTIFY: User {user_id} notified about pending number: {phone}")
                        
                        # Hapus dari cache USER_REQUEST_CACHE 
                        # Nomor pending ini sekarang akan dipantau sebagai nomor biasa (jika statusnya berubah jadi success)
                        del USER_REQUEST_CACHE[prefix]
                        break # Pindah ke baris pending berikutnya
        
        # ... (LOGIKA LAMA UNTUK MENGAMBIL PESAN SUKSES)
        
        # *** GANTI DENGAN LOGIKA FETCH SMS DAN FILTER DUP LAMA ANDA ***
        # ...
        
        return [] # Kembalikan pesan sukses untuk diproses lebih lanjut
    
    # ... (refresh_and_screenshot tetap sama)

monitor = SMSMonitor()


# ================= FUNGSI UTAMA START =================

# ... (Kode Flask, run_flask, dan if __name__ == "__main__" dimodifikasi di bawah)


# ================= FUNGSI UTAMA START (MODIFIED) =================

def run_flask():
    # ... (sama seperti sebelumnya)
    pass # Menggunakan kode lama

if __name__ == "__main__":
    if not BOT_MONITOR_TOKEN or not CHAT_MONITOR_ID or not BOT_USER_TOKEN:
        print("FATAL ERROR: Pastikan semua token dan chat ID (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN_USER) ada di file .env.")
    else:
        print("Starting Multi-Bot SMS Monitor and User Service...")
        
        # Inisialisasi Filter
        otp_filter = OTPFilter()

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        GLOBAL_ASYNC_LOOP = loop 
        
        # 1. Mulai Flask di thread terpisah
        # ... (Kode flask_thread tetap sama)
        
        # 2. Kirim Pesan Aktivasi Telegram 
        send_tg_monitor("✅ <b>[Monitor Bot] ACTIVE. Monitoring is RUNNING.</b>", with_inline_keyboard=False)
        send_tg_user("✅ <b>[User Bot] ACTIVE. Ready to accept number requests.</b>", chat_id=ADMIN_ID) # Kirim ke admin ID sebagai notif

        # 3. Inisialisasi dan Mulai Bot
        user_bot_instance = UserBot(BOT_USER_TOKEN)
        
        # Menjalankan dua loop bot secara konkuren (bersamaan)
        try:
            loop.run_until_complete(
                asyncio.gather(
                    monitor_sms_loop(), # Bot Monitor (lama)
                    user_bot_instance.run() # Bot Pelayanan User (baru)
                )
            )
        except KeyboardInterrupt:
            print("Bot shutting down...")
        finally:
            print("Bot core shutdown complete.")
