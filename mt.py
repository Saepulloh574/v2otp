import os
import json
import requests
import time
import asyncio
from pyppeteer import connect
# from dotenv import load_dotenv # Tidak digunakan karena token di hardcode

# ================= Configuration =================
# 💥 TOKEN DIMASUKKAN LANGSUNG
BOT_TOKEN = "8047851913:AAFGXlRL_e7JcLEMtOqUuuNd_46ZmIoGJN8" 
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Ganti dengan ID Admin Anda (ambil dari env jika ada, atau default 0)
try:
    ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", 0))
except (ValueError, TypeError):
    ADMIN_ID = 0 

LAST_UPDATE_ID = 0

# --- Pyppeteer Global State ---
PYPPEETER_URL = "https://v2.mnitnetwork.com/dashboard/getnum" 
BROWSER_PAGE = None
# ------------------------------

# --- Pilihan Negara & Prefix (Static Menu) ---
NUMBER_PREFIXES = {
    "GUINEA": "2246543XXX",
    "IVORY COAST": "225017054XXX",
    "BENIN": "229019372XXX",
    "SIERRA LEONE": "2327382XXX"
}
# --------------------------------------------------------

# ================= Utils & Telegram Functions =================

def api_call(method, payload):
    """Fungsi generik untuk memanggil Telegram API."""
    try:
        r = requests.post(API_BASE + method, data=payload, timeout=10)
        # Tambahkan logging untuk error jika token bermasalah
        if not r.ok:
            print(f"⚠️ Telegram API Response Error: Status {r.status_code}, Body: {r.text[:100]}...")
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Telegram API Error: {e.__class__.__name__}: {e}")
        return None

def sendMessage(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "HTML"
    }
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    api_call("sendMessage", payload)

def editMessage(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id, 
        "message_id": message_id, 
        "text": text, 
        "parse_mode": "HTML"
    }
    if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
    api_call("editMessageText", payload)

def answerCallbackQuery(callback_id, text):
    payload = {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": False
    }
    api_call("answerCallbackQuery", payload)


# ================= Pyppeteer / Browser Logic =================

async def initialize_browser():
    """Menginisialisasi koneksi ke Chrome Debugging Port."""
    global BROWSER_PAGE
    if BROWSER_PAGE: return BROWSER_PAGE
    
    try:
        # Menghubungkan ke port debugging yang sudah berjalan (asumsi Chrome sudah dibuka)
        browser = await connect(browserURL="http://127.0.0.1:9222")
        pages = await browser.pages()
        page = None
        
        # Cari halaman yang sudah terbuka di URL yang benar
        for p in pages:
            if PYPPEETER_URL in p.url:
                page = p
                break
        if not page:
            # Jika tidak ada, buat halaman baru dan navigasi
            page = await browser.newPage()
            await page.goto(PYPPEETER_URL, {'waitUntil': 'networkidle0'})
        
        BROWSER_PAGE = page
        print("✅ Browser page connected successfully.")
        return BROWSER_PAGE
    except Exception as e:
        print(f"❌ Gagal menghubungkan browser (Pyppeteer): {e.__class__.__name__}: {e}")
        return None


async def get_number_on_page(user_id, number_prefix):
    """Mengisi input dan klik tombol 'Get Numbers' dengan metode yang aman."""
    page = await initialize_browser()
    if not page:
        sendMessage(user_id, f"❌ Bot monitoring belum siap atau koneksi browser gagal.")
        return

    # --- PERBAIKAN STABILITAS: Handle Reload dan Input ---
    input_selector = 'input[name="numberrange"]'
    button_selector = '#getNumberBtn'
    
    # 1. Refresh dulu (Gunakan timeout lebih pendek, tunggu DOM)
    try:
        print(f"-> Browser Action: Safely reloading page...")
        await page.reload({'waitUntil': 'domcontentloaded', 'timeout': 15000}) 
        await asyncio.sleep(1) 
        
        # Pastikan tombol dan input ada setelah reload
        await page.waitForSelector(input_selector, {'timeout': 5000})
        await page.waitForSelector(button_selector, {'timeout': 5000})

    except Exception as e:
        print(f"⚠️ Peringatan: Gagal reload/waitForSelector. Mencoba melanjutkan input: {e.__class__.__name__}")
        await asyncio.sleep(2) # Beri jeda ekstra jika ada isu

    try:
        # 2. Input Nomor (Metode aman: clear input via JS lalu type)
        print(f"-> Browser Action: Typing {number_prefix}...")
        
        # Menghapus teks lama (lebih aman daripada key press)
        await page.evaluate(f'document.querySelector("{input_selector}").value = ""')
        await page.type(input_selector, number_prefix, {'delay': 50})
        
        # 3. Klik Tombol
        print(f"-> Browser Action: Clicking Get Numbers...")
        
        # Klik tombol. Kita TIDAK menunggu navigasi karena ini adalah aksi AJAX.
        await page.click(button_selector)
        
        await asyncio.sleep(3) # Tunggu sebentar agar server/AJAX merespon

        print(f"✅ Number {number_prefix} successfully requested on the page.")
        
        # Kirim notifikasi 'PENDING' kembali ke user
        sendMessage(user_id, f"⏳ Nomor `{number_prefix}` sedang diproses. Mohon tunggu notifikasi OTP.")

    except Exception as e:
        error_msg = f"❌ Gagal input/klik tombol di browser: {e.__class__.__name__}: {e}"
        print(error_msg)
        sendMessage(user_id, f"❌ Gagal memproses nomor `{number_prefix}`. Pastikan browser berjalan di port :9222. Coba lagi.")


# ================= User Bot Core Logic =================

def create_country_keyboard():
    """Membuat keyboard inline untuk pemilihan negara dan manual input."""
    buttons = []
    countries = list(NUMBER_PREFIXES.keys())
    
    # Kelompokkan 2 tombol per baris
    for i in range(0, len(countries), 2):
        row = []
        if i < len(countries):
            ct1 = countries[i]
            row.append({"text": ct1, "callback_data": f"select_{ct1}"})
        if i + 1 < len(countries):
            ct2 = countries[i+1]
            row.append({"text": ct2, "callback_data": f"select_{ct2}"})
        if row: buttons.append(row)
        
    # Tombol Manual Input
    buttons.append([{"text": "➡️ MANUAL INPUT (Prefix)", "callback_data": "manual_input"}])
    buttons.append([{"text": "ADMIN: Reload Menu", "callback_data": "start_menu"}])

    return {"inline_keyboard": buttons}


def handle_start(chat_id):
    """Menangani perintah /start."""
    sendMessage(
        chat_id, 
        "👋 Selamat datang. Silakan pilih negara atau gunakan **MANUAL INPUT** untuk mengirim prefix nomor.", 
        reply_markup=create_country_keyboard()
    )


def handle_callback(callback):
    """Menangani semua callback_query (Pemilihan Negara & Menu)."""
    
    data = callback.get("data")
    user_id = callback["from"]["id"]
    chat_id_cb = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]

    # Handle pemilihan negara
    if data.startswith("select_"):
        country_name = data[7:]
        input_number = NUMBER_PREFIXES.get(country_name)
        
        if input_number:
            answerCallbackQuery(callback['id'], f"✅ Memproses: {country_name}")
            
            # 1. Hapus tombol dan konfirmasi aksi
            editMessage(
                chat_id_cb,
                message_id,
                f"🌍 Anda memilih **{country_name}**. Prefix: `{input_number}`\n\n"
                f"⏳ Nomor sedang diproses. Mohon tunggu notifikasi PENDING."
            )

            # 2. Memicu Pyppeteer
            try:
                asyncio.run_coroutine_threadsafe(
                    get_number_on_page(user_id, input_number), 
                    ASYNC_LOOP
                )
                print(f"✅ Callback Triggered Pyppeteer for: {input_number}")
            except Exception as e:
                sendMessage(user_id, f"❌ Error memicu aksi Pyppeteer: {e.__class__.__name__}")
                print(f"❌ Error memicu aksi Pyppeteer: {e}")
                
        else:
            answerCallbackQuery(callback['id'], "❌ Pilihan tidak valid.")
    
    # Handle tombol Manual Input
    elif data == "manual_input":
        answerCallbackQuery(callback['id'], "Silakan kirim prefix nomor Anda.")
        sendMessage(chat_id_cb, "💬 Silakan kirimkan **prefix** nomor telepon Anda (min 6 digit).\nContoh: `2246543XXX`")
    
    # Handle tombol Reload Menu
    elif data == "start_menu":
        answerCallbackQuery(callback['id'], "Memuat ulang menu...")
        handle_start(chat_id_cb)


def handle_text_input(user_id, chat_id, text):
    """Menangani input teks manual."""
    def clean_phone_number(phone):
        cleaned = ''.join(filter(str.isdigit, phone))
        return cleaned
    
    if text.startswith('+') or text.isdigit():
        input_number = clean_phone_number(text)
        
        if len(input_number) < 6:
            sendMessage(chat_id, "⚠️ Format nomor tidak valid. Minimal 6 digit. Contoh: `2246543XXX`",)
            return
        
        print(f"✅ User {user_id} requested number manually: {input_number}")
        
        try:
            asyncio.run_coroutine_threadsafe(
                get_number_on_page(user_id, input_number), 
                ASYNC_LOOP
            )
        except Exception as e:
            sendMessage(user_id, f"❌ Error memicu aksi Pyppeteer: {e.__class__.__name__}")
            print(f"❌ Error memicu aksi Pyppeteer: {e}")
        
    else:
        # Jika user mengirim teks lain yang tidak dikenal, kirimkan kembali menu
        handle_start(chat_id)


# ================= Main Loop =================

async def main_loop():
    global LAST_UPDATE_ID

    if not BOT_TOKEN:
        print("FATAL: BOT_TOKEN not set.")
        return

    print("🚀 User Bot Service (Pyppeteer Trigger) started...")
    
    # Cek koneksi Pyppeteer di awal
    if not await initialize_browser():
        print("⚠️ Peringatan: Koneksi Browser gagal di awal. Mencoba lagi dalam loop.")

    while True:
        try:
            url = API_BASE + f"getUpdates?offset={LAST_UPDATE_ID+1}&timeout=30"
            response = requests.get(url, timeout=35).json()

            if not response.get("ok"):
                # Logging jika koneksi gagal
                print("❌ Failed to get updates. (Token/Network Error)")
                print(f"DEBUG: Token starts with {BOT_TOKEN[:5]}...")
                await asyncio.sleep(5)
                continue

            for update in response.get("result", []):
                LAST_UPDATE_ID = update["update_id"]
                
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    text = message.get("text", "")
                    user_id = message["from"]["id"]
                    
                    if text == "/start":
                        handle_start(chat_id)
                    elif text:
                        handle_text_input(user_id, chat_id, text)
                
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
            
            await asyncio.sleep(1) 

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"❌ Unhandled Error in main loop: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        ASYNC_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        ASYNC_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(ASYNC_LOOP)

    print("Starting User Service...")
    ASYNC_LOOP.run_until_complete(main_loop())
