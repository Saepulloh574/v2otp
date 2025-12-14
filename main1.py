import asyncio
import time
import requests
from collections import deque
from playwright.async_api import async_playwright

# =======================
# CONFIG
# =======================
BOT_TOKEN = "8047851913:AAFGXlRL_e7JcLEMtOqUuuNd_46ZmIoGJN8"
GROUP_ID = 2250170554077  # ganti dengan ID grup lu
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

GET_NUMBER_DELAY = 5  # detik per user

# =======================
# GLOBAL STATE
# =======================
verified_users = set()
waiting_range = set()

user_last_range = {}      # user_id -> range
user_queues = {}          # user_id -> deque
user_last_time = {}       # user_id -> last get time

sent_numbers = set()      # anti dobel global

# =======================
# TELEGRAM UTILS
# =======================
def tg_send(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup

    requests.post(f"{API}/sendMessage", data=data)


def tg_get_updates(offset):
    return requests.get(
        f"{API}/getUpdates",
        params={"offset": offset, "timeout": 30}
    ).json()


def is_user_in_group(user_id):
    r = requests.get(
        f"{API}/getChatMember",
        params={"chat_id": GROUP_ID, "user_id": user_id}
    ).json()
    if not r.get("ok"):
        return False
    return r["result"]["status"] in ["member", "administrator", "creator"]


# =======================
# QUEUE UTILS
# =======================
def can_process(user_id):
    last = user_last_time.get(user_id, 0)
    return time.time() - last >= GET_NUMBER_DELAY


# =======================
# PARSE NUMBER + COUNTRY
# =======================
async def get_number_and_country(page):
    rows = await page.query_selector_all("tbody tr")

    for row in rows:
        phone_el = await row.query_selector(".phone-number")
        if not phone_el:
            continue

        number = (await phone_el.inner_text()).strip()

        # skip nomor lama
        if number in sent_numbers:
            continue

        # skip otp datang / expired
        if await row.query_selector(".status-success"):
            continue
        if await row.query_selector(".status-failed"):
            continue

        country_el = await row.query_selector(".badge.bg-primary")
        country = (await country_el.inner_text()).strip() if country_el else "-"

        return number, country

    return None, None


# =======================
# PROCESS QUEUE PER USER
# =======================
async def process_user_queue(page, user_id):
    if user_id not in user_queues:
        return
    if not user_queues[user_id]:
        return
    if not can_process(user_id):
        return

    req = user_queues[user_id].popleft()
    prefix = req["prefix"]

    # === ISI PREFIX ===
    await page.fill("#prefixInput", prefix)

    # === CLICK GET NUMBER ===
    await page.click("#getNumber")

    # tunggu tabel update
    await page.wait_for_timeout(2000)

    number, country = await get_number_and_country(page)

    if not number:
        tg_send(user_id, "❌ Nomor tidak ditemukan, silakan coba lagi")
        return

    sent_numbers.add(number)
    user_last_time[user_id] = time.time()

    msg = (
        "The number is ready, please use it.\n\n"
        f"Number  : <code>{number}</code>\n"
        f"Country : {country}\n"
        f"Range   : <code>{prefix}</code>"
    )

    tg_send(
        user_id,
        msg,
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "🔁 Change", "callback_data": "change"},
                    {"text": "🔐 OTP Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}
                ]
            ]
        }
    )


# =======================
# TELEGRAM LOOP
# =======================
async def telegram_loop(page):
    offset = 0

    while True:
        data = tg_get_updates(offset)

        for upd in data.get("result", []):
            offset = upd["update_id"] + 1

            # ===== MESSAGE =====
            if "message" in upd:
                msg = upd["message"]
                user_id = msg["chat"]["id"]
                username = msg["from"].get("username", "-")
                text = msg.get("text", "")

                # /start
                if text == "/start":
                    kb = {
                        "inline_keyboard": [
                            [{"text": "📌 Gabung Grup", "url": "https://t.me/+E5grTSLZvbpiMTI1"}],
                            [{"text": "✅ Verifikasi", "callback_data": "verify"}]
                        ]
                    }
                    tg_send(
                        user_id,
                        f"Halo @{username} selamat datang di ZuraStore,\n"
                        "gabung grup untuk verifikasi",
                        kb
                    )
                    continue

                # user kirim RANGE
                if user_id in waiting_range:
                    prefix = text.strip()
                    waiting_range.remove(user_id)

                    user_last_range[user_id] = prefix
                    user_queues.setdefault(user_id, deque()).append({
                        "prefix": prefix,
                        "time": time.time()
                    })

                    tg_send(
                        user_id,
                        "Sedang mengambil Number mohon tunggu...\n\n"
                        f"Range : {prefix}\n"
                        f"UserID: {user_id}"
                    )

            # ===== CALLBACK =====
            if "callback_query" in upd:
                cq = upd["callback_query"]
                user_id = cq["from"]["id"]
                data_cb = cq["data"]
                username = cq["from"].get("username", "-")

                # verify
                if data_cb == "verify":
                    if not is_user_in_group(user_id):
                        tg_send(
                            user_id,
                            "Anda belum bergabung ke grup.\n"
                            "Silakan gabung lalu kirim /start lagi"
                        )
                    else:
                        verified_users.add(user_id)
                        kb = {
                            "inline_keyboard": [
                                [{"text": "📲 Get Num", "callback_data": "getnum"}],
                                [{"text": "👨‍💼 Admin", "url": "https://t.me/"}]
                            ]
                        }
                        tg_send(
                            user_id,
                            "> verifikasi\n\n"
                            "Selamat Anda Berhasil verifikasi\n\n"
                            f"User : @{username}\n"
                            f"Id   : {user_id}\n\n"
                            "Silahkan gunakan tombol di bawah!!",
                            kb
                        )

                # getnum
                if data_cb == "getnum":
                    if user_id not in verified_users:
                        tg_send(user_id, "Silakan verifikasi dulu")
                        continue

                    waiting_range.add(user_id)
                    tg_send(
                        user_id,
                        "Silahkan kirim range\n"
                        "Contoh: 628272XXXX"
                    )

                # change
                if data_cb == "change":
                    prefix = user_last_range.get(user_id)
                    if not prefix:
                        tg_send(user_id, "Range tidak ditemukan, Get Num ulang")
                        continue

                    user_queues.setdefault(user_id, deque()).append({
                        "prefix": prefix,
                        "time": time.time()
                    })

                    tg_send(user_id, "🔄 Mengganti nomor, mohon tunggu...")

        await asyncio.sleep(1)


# =======================
# WORKER LOOP
# =======================
async def worker_loop(page):
    while True:
        for user_id in list(user_queues.keys()):
            await process_user_queue(page, user_id)
        await asyncio.sleep(1)


# =======================
# MAIN
# =======================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(
            "http://localhost:9222"
        )

        context = browser.contexts[0]
        page = context.pages[0]

        print("[OK] Connected to existing Chrome")

        await asyncio.gather(
            telegram_loop(page),
            worker_loop(page)
        )


if __name__ == "__main__":
    asyncio.run(main())
