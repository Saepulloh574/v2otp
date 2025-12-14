import asyncio
import time
import requests
from collections import deque
from playwright.async_api import async_playwright

# =======================
# CONFIG
# =======================
BOT_TOKEN = "8047851913:AAFGXlRL_e7JcLEMtOqUuuNd_46ZmIoGJN8"
GROUP_ID = -1003492226491  # ⚠️ HARUS NEGATIF
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

GET_NUMBER_DELAY = 5

# =======================
# GLOBAL STATE
# =======================
verified_users = set()
waiting_range = set()

user_last_range = {}
user_queues = {}
user_last_time = {}

sent_numbers = set()

# =======================
# TELEGRAM UTILS
# =======================
def tg_send(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        requests.post(f"{API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print("[TG SEND ERROR]", e)


def tg_get_updates(offset):
    return requests.get(
        f"{API}/getUpdates",
        params={"offset": offset, "timeout": 30},
        timeout=35
    ).json()


def is_user_in_group(user_id):
    r = requests.get(
        f"{API}/getChatMember",
        params={"chat_id": GROUP_ID, "user_id": user_id}
    ).json()
    if not r.get("ok"):
        return False
    return r["result"]["status"] in ("member", "administrator", "creator")

# =======================
# QUEUE UTILS
# =======================
def can_process(user_id):
    return time.time() - user_last_time.get(user_id, 0) >= GET_NUMBER_DELAY

# =======================
# PARSE NUMBER
# =======================
async def get_number_and_country(page):
    rows = await page.query_selector_all("tbody tr")

    for row in rows:
        phone_el = await row.query_selector(".phone-number")
        if not phone_el:
            continue

        number = (await phone_el.inner_text()).strip()
        if number in sent_numbers:
            continue

        if await row.query_selector(".status-success"):
            continue
        if await row.query_selector(".status-failed"):
            continue

        country_el = await row.query_selector(".badge.bg-primary")
        country = (await country_el.inner_text()).strip() if country_el else "-"

        return number, country

    return None, None

# =======================
# PROCESS QUEUE
# =======================
async def process_user_queue(page, user_id):
    if user_id not in user_queues or not user_queues[user_id]:
        return
    if not can_process(user_id):
        return

    req = user_queues[user_id].popleft()
    prefix = req["prefix"]

    await page.fill("#prefixInput", prefix)
    await page.click("#getNumber")
    await page.wait_for_timeout(2000)

    number, country = await get_number_and_country(page)

    if not number:
        tg_send(user_id, "❌ Nomor tidak ditemukan, coba lagi")
        return

    sent_numbers.add(number)
    user_last_time[user_id] = time.time()

    tg_send(
        user_id,
        (
            "The number is ready, please use it.\n\n"
            f"Number  : <code>{number}</code>\n"
            f"Country : {country}\n"
            f"Range   : <code>{prefix}</code>"
        ),
        reply_markup={
            "inline_keyboard": [
                [{"text": "🔁 Change", "callback_data": "change"}],
                [{"text": "🔐 OTP Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}]
            ]
        }
    )

# =======================
# TELEGRAM LOOP
# =======================
async def telegram_loop(page):
    offset = 0
    print("[TG] Listening...")

    while True:
        data = tg_get_updates(offset)

        for upd in data.get("result", []):
            offset = upd["update_id"] + 1

            if "message" in upd:
                msg = upd["message"]
                user_id = msg["chat"]["id"]
                text = msg.get("text", "")
                username = msg["from"].get("username", "-")

                if text == "/start":
                    tg_send(
                        user_id,
                        f"Halo @{username}\nSilakan verifikasi dulu",
                        {
                            "inline_keyboard": [
                                [{"text": "📌 Gabung Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}],
                                [{"text": "✅ Verifikasi", "callback_data": "verify"}]
                            ]
                        }
                    )

                elif user_id in waiting_range:
                    waiting_range.remove(user_id)
                    user_last_range[user_id] = text
                    user_queues.setdefault(user_id, deque()).append({"prefix": text})
                    tg_send(user_id, "⏳ Mengambil nomor...")

            if "callback_query" in upd:
                cq = upd["callback_query"]
                user_id = cq["from"]["id"]
                data_cb = cq["data"]
                username = cq["from"].get("username", "-")

                if data_cb == "verify":
                    if not is_user_in_group(user_id):
                        tg_send(user_id, "❌ Belum join grup")
                    else:
                        verified_users.add(user_id)
                        tg_send(
                            user_id,
                            f"✅ Verifikasi sukses\n@{username}",
                            {
                                "inline_keyboard": [
                                    [{"text": "📲 Get Num", "callback_data": "getnum"}]
                                ]
                            }
                        )

                elif data_cb == "getnum":
                    if user_id not in verified_users:
                        tg_send(user_id, "Verifikasi dulu")
                    else:
                        waiting_range.add(user_id)
                        tg_send(user_id, "Kirim range\nContoh: 62812XXXX")

                elif data_cb == "change":
                    prefix = user_last_range.get(user_id)
                    if prefix:
                        user_queues.setdefault(user_id, deque()).append({"prefix": prefix})
                        tg_send(user_id, "🔄 Mengganti nomor...")

        await asyncio.sleep(1)

# =======================
# WORKER LOOP
# =======================
async def worker_loop(page):
    while True:
        for uid in list(user_queues):
            await process_user_queue(page, uid)
        await asyncio.sleep(1)

# =======================
# MAIN
# =======================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        page = browser.contexts[0].pages[0]

        print("[OK] Chrome connected")

        # 🔔 NOTIF BOT AKTIF KE GRUP
        tg_send(
            GROUP_ID,
            "🤖 Bot number active\nStatus: ONLINE"
        )

        await asyncio.gather(
            telegram_loop(page),
            worker_loop(page)
        )

if __name__ == "__main__":
    asyncio.run(main())
