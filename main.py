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

load_dotenv()

# ================= Konstanta & Config =================
TELEGRAM_BOT_LINK = "https://t.me/myzuraisgoodbot"
TELEGRAM_ADMIN_LINK = "https://t.me/Imr1d"
BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))
except:
    ADMIN_ID = None

LOGIN_URL = "https://x.mnitnetwork.com/mauth/login" 
DASHBOARD_URL = "https://x.mnitnetwork.com/mdashboard/getnum" 
OTP_SAVE_FILE = os.path.join("..", "get", "smc.json")
GLOBAL_ASYNC_LOOP = None 
AWAITING_CREDENTIALS = False 

# ================= Utils =================

COUNTRY_EMOJI = {
    "NEPAL": "🇳🇵", "IVORY COAST": "🇨🇮", "GUINEA": "🇬🇳", "CENTRAL AFRIKA": "🇨🇫",
    "TOGO": "🇹🇬", "TAJIKISTAN": "🇹🇯", "BENIN": "🇧🇯", "SIERRA LEONE": "🇸🇱",
    "MADAGASCAR": "🇲🇬", "AFGANISTAN": "🇦🇫", "ZURA STORE": "🇮🇩", "GEORGIA": "🇬🇪", "MYANMAR": "🇲🇲"
}

def clean_phone_number(phone):
    if not phone: return "N/A"
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned and not cleaned.startswith('+') and cleaned != 'N/A': cleaned = '+' + cleaned
    return cleaned

def clean_service_name(text):
    if not text: return "Unknown"
    text = text.lower()
    maps = {'facebook': 'Facebook', 'whatsapp': 'WhatsApp', 'instagram': 'Instagram', 'google': 'Google', 'tiktok': 'TikTok'}
    for k, v in maps.items():
        if k in text: return v
    return "Service"

def format_otp_message(otp_data):
    emoji = COUNTRY_EMOJI.get(otp_data['range'].upper(), "")
    return f"""🔐 <b>New OTP Received</b>

🌍 Country: <b>{otp_data['range']} {emoji}</b>
📱 Number: <code>{otp_data['phone']}</code>
🌐 Service: <b>{otp_data['service']}</b>
🔢 OTP: <code>{otp_data['otp']}</code>

FULL MESSAGES:
<blockquote>{otp_data['raw_message']}</blockquote>"""

# ================= Monitor Class =================

class SMSMonitor:
    def __init__(self):
        self.url = DASHBOARD_URL
        self.browser = None
        self.page = None
        self.is_logged_in = False

    async def initialize(self, p_instance):
        # Konek ke Chrome yang sudah terbuka
        self.browser = await p_instance.chromium.connect_over_cdp("http://127.0.0.1:9222")
        self.page = self.browser.contexts[0].pages[0] if self.browser.contexts[0].pages else await self.browser.contexts[0].new_page()
        # Berikan izin clipboard agar script bisa membaca isi clipboard setelah klik
        await self.browser.contexts[0].grant_permissions(['clipboard-read', 'clipboard-write'])

    async def fetch_sms(self) -> List[Dict[str, Any]]:
        if not self.page: return []
        
        # Pastikan di dashboard
        if "mdashboard" not in self.page.url:
            await self.page.goto(self.url)
            await self.page.wait_for_load_state("networkidle")

        results = []
        # Ambil semua baris sukses
        rows = await self.page.query_selector_all("tr.group")
        
        for row in rows:
            status_el = await row.query_selector("span.border-green-500")
            if not status_el: continue # Lewati jika bukan success

            # 1. Ambil Nomor & OTP yang terlihat
            phone_el = await row.query_selector("span.font-mono.text-lg")
            phone = await phone_el.inner_text() if phone_el else "N/A"
            
            otp_el = await row.query_selector("span.tracking-widest")
            otp = await otp_el.inner_text() if otp_el else "N/A"

            country_el = await row.query_selector("span.text-slate-200")
            country = await country_el.inner_text() if country_el else "Unknown"

            # 2. LOGIKA KLIK CLIPBOARD: 
            # Karena pesan tidak ada di DOM, kita klik tombolnya lalu baca clipboard
            copy_btn = await row.query_selector("button[title*='Copy']")
            full_msg = "Pesan gagal diambil"
            
            if copy_btn:
                try:
                    await copy_btn.click()
                    await asyncio.sleep(0.5) # Tunggu proses copy JS selesai
                    # Ambil teks dari clipboard menggunakan evaluasi browser
                    full_msg = await self.page.evaluate("navigator.clipboard.readText()")
                except Exception as e:
                    full_msg = f"OTP: {otp} (Gagal akses clipboard)"

            results.append({
                "otp": otp,
                "phone": clean_phone_number(phone),
                "service": clean_service_name(full_msg),
                "range": country,
                "raw_message": full_msg
            })
            
        return results

# ================= OTP Filter & Logic =================

class OTPFilter:
    def __init__(self):
        self.cache = {}
    def filter(self, msgs):
        new = []
        for m in msgs:
            key = f"{m['phone']}_{m['otp']}"
            if key not in self.cache:
                self.cache[key] = True
                new.append(m)
        return new

monitor = SMSMonitor()
otp_filter = OTPFilter()

# ================= Main Loop & Telegram =================

async def main_loop():
    async with async_playwright() as p:
        await monitor.initialize(p)
        print("🚀 Monitor Berjalan...")
        
        while True:
            try:
                # Cek Status Login
                monitor.is_logged_in = "mdashboard" in monitor.page.url
                
                if monitor.is_logged_in:
                    data = await monitor.fetch_sms()
                    new_msgs = otp_filter.filter(data)
                    
                    for m in new_msgs:
                        msg_text = format_otp_message(m)
                        # Kirim ke Telegram
                        requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", 
                                     data={'chat_id': CHAT, 'text': msg_text, 'parse_mode': 'HTML'})
                        
                        # Simpan JSON
                        if not os.path.exists(os.path.dirname(OTP_SAVE_FILE)):
                            os.makedirs(os.path.dirname(OTP_SAVE_FILE))
                        with open(OTP_SAVE_FILE, "a") as f:
                            f.write(json.dumps(m) + "\n")
                            
            except Exception as e:
                print(f"Error: {e}")
            
            await asyncio.sleep(10) # Cek tiap 10 detik

if __name__ == "__main__":
    asyncio.run(main_loop())
