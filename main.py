import asyncio
import random
import re
import sqlite3
import time
from telethon import TelegramClient, events
from telethon.errors import PersistentTimestampOutdatedError, FloodWaitError

# ===================== تنظیمات اصلی =====================
API_ID = 22487790
API_HASH = "09c24af20084de9372cc92a760c74961"

GROUP_ID = -1003979242735

SESSION_NAME = "my_account_session"
DB_FILE = "timers.db"

# ---- تنظیمات بخش رندوم میو ----
MEOW_INTERVAL_SECONDS = 275
MEOW_CHOICES = ["میو", "مع", "معو", "میو میو"]

# ---- تنظیمات بخش "پیشی" + کلیک روی دکمه ----
PISHI_INTERVAL_SECONDS = 40 * 60
PISHI_TEXT = "پیشی"
TARGET_BOT = "@MeowieQBot"
BUTTON_TEXT = "برداشت میو پوینت ها"
WAIT_FOR_BUTTON_SECONDS = 15

# ---- تنظیمات بخش "ماهیگیری" ----
FISHING_INTERVAL_SECONDS = 40 * 60
FISHING_TEXT = "ماهی"
FISH_VALUE_THRESHOLD = 700
SELL_FISH_BUTTON = "فروش ماهی"
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"

# ---- دکمه نجات پیشی ----
RESCUE_BUTTON_TEXT = "نجات پیشی خیابونی 🐱"
# ==========================================================

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


# ===================== دیتابیس تایمر =====================

def init_db():
    """ساخت جدول تایمر اگه وجود نداشت"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS timers (
            key TEXT PRIMARY KEY,
            last_run REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_last_run(key: str) -> float:
    """آخرین زمان اجرای یه تایمر رو برمیگردونه (epoch)، اگه نبود 0"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_run FROM timers WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def set_last_run(key: str, ts: float):
    """آخرین زمان اجرا رو ذخیره می‌کنه"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO timers (key, last_run) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET last_run = excluded.last_run
    """, (key, ts))
    conn.commit()
    conn.close()


def seconds_until_next(key: str, interval: float) -> float:
    """
    چقدر باید صبر کنیم تا نوبت بعدی؟
    اگه از آخرین اجرا interval ثانیه گذشته باشه → 0 (یعنی الان بزن)
    وگرنه → چقدر مونده
    """
    last = get_last_run(key)
    if last == 0.0:
        return 0.0  # اولین اجرا، همین الان بزن
    elapsed = time.time() - last
    remaining = interval - elapsed
    return max(0.0, remaining)


# ===================== توابع کمکی =====================

async def safe_send(group_id, text, retries=3):
    for attempt in range(retries):
        try:
            await client.send_message(group_id, text)
            return True
        except FloodWaitError as e:
            print(f"[!] FloodWait: {e.seconds} ثانیه صبر می‌کنم...")
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            wait = 10 * (attempt + 1)
            print(f"[!] PersistentTimestampOutdated: {wait} ثانیه صبر می‌کنم... ({attempt+1}/{retries})")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"[!] خطا در ارسال: {e}")
            await asyncio.sleep(5)
    return False


async def safe_iter_messages(group_id, limit=5):
    for attempt in range(3):
        try:
            messages = []
            async for msg in client.iter_messages(group_id, limit=limit):
                messages.append(msg)
            return messages
        except PersistentTimestampOutdatedError:
            wait = 10 * (attempt + 1)
            print(f"[!] PersistentTimestampOutdated هنگام خواندن پیام: {wait} ثانیه...")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"[!] خطا در خواندن پیام: {e}")
            await asyncio.sleep(5)
    return []


# ===================== حلقه‌های اصلی =====================

async def send_meow_loop():
    """هر 280 ثانیه یه پیام رندوم میو می‌فرسته، با حافظه تایمر"""
    wait = seconds_until_next("meow", MEOW_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] میو: {wait:.0f} ثانیه مونده تا نوبت بعدی...")
        await asyncio.sleep(wait)

    while True:
        text = random.choice(MEOW_CHOICES)
        ok = await safe_send(GROUP_ID, text)
        if ok:
            set_last_run("meow", time.time())
            print(f"[+] میو رندوم '{text}' ارسال شد.")
        await asyncio.sleep(MEOW_INTERVAL_SECONDS)


async def send_pishi_and_click_loop():
    """هر 40 دقیقه پیشی + کلیک دکمه، با حافظه تایمر"""
    wait = seconds_until_next("pishi", PISHI_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] پیشی: {wait:.0f} ثانیه مونده تا نوبت بعدی...")
        await asyncio.sleep(wait)

    while True:
        try:
            ok = await safe_send(GROUP_ID, PISHI_TEXT)
            if ok:
                set_last_run("pishi", time.time())
                print(f"[+] پیام '{PISHI_TEXT}' ارسال شد. منتظر پاسخ بات...")

            clicked = False
            elapsed = 0
            while elapsed < WAIT_FOR_BUTTON_SECONDS and not clicked:
                await asyncio.sleep(1)
                elapsed += 1
                messages = await safe_iter_messages(GROUP_ID, limit=5)
                for msg in messages:
                    if msg.sender_id is None or not msg.buttons:
                        continue
                    sender = await msg.get_sender()
                    sender_username = getattr(sender, "username", None)
                    is_target = (
                        str(msg.sender_id) == str(TARGET_BOT).lstrip("@")
                        or (sender_username and f"@{sender_username}" == TARGET_BOT)
                    )
                    if not is_target:
                        continue
                    for row in msg.buttons:
                        for button in row:
                            if button.text.strip() == BUTTON_TEXT:
                                await msg.click(text=BUTTON_TEXT)
                                print(f"[+] دکمه '{BUTTON_TEXT}' زده شد.")
                                clicked = True
                                break
                        if clicked:
                            break
                    if clicked:
                        break

            if not clicked:
                print("[!] دکمه پیشی توی این دور پیدا نشد.")

        except Exception as e:
            print(f"[!] خطا در حلقه پیشی: {e}")

        await asyncio.sleep(PISHI_INTERVAL_SECONDS)


async def send_fishing_loop():
    """هر 40 دقیقه ماهی + کلیک شرطی، با حافظه تایمر"""
    wait = seconds_until_next("fishing", FISHING_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] ماهی: {wait:.0f} ثانیه مونده تا نوبت بعدی...")
        await asyncio.sleep(wait)

    while True:
        try:
            ok = await safe_send(GROUP_ID, FISHING_TEXT)
            if ok:
                set_last_run("fishing", time.time())
                print(f"[+] پیام '{FISHING_TEXT}' ارسال شد. منتظر پاسخ بات...")

            handled = False
            elapsed = 0
            while elapsed < WAIT_FOR_BUTTON_SECONDS and not handled:
                await asyncio.sleep(1)
                elapsed += 1
                messages = await safe_iter_messages(GROUP_ID, limit=5)
                for msg in messages:
                    if msg.sender_id is None or not msg.buttons:
                        continue
                    sender = await msg.get_sender()
                    sender_username = getattr(sender, "username", None)
                    is_target = (
                        str(msg.sender_id) == str(TARGET_BOT).lstrip("@")
                        or (sender_username and f"@{sender_username}" == TARGET_BOT)
                    )
                    if not is_target:
                        continue
                    text = msg.text or ""
                    button_texts = {b.text.strip() for row in msg.buttons for b in row}
                    if not ({SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON} & button_texts):
                        continue
                    match = re.search(r"ارزش\s*[:：]\s*`?([\d,]+)`?", text)
                    if not match:
                        print(f"[!] ارزش ماهی پیدا نشد. متن: {text}")
                        continue
                    fish_value = int(match.group(1).replace(",", ""))
                    print(f"[i] ارزش ماهی: {fish_value}")
                    target_button = SELL_FISH_BUTTON if fish_value >= FISH_VALUE_THRESHOLD else GIVE_TO_CAT_BUTTON
                    for row in msg.buttons:
                        for button in row:
                            if button.text.strip() == target_button:
                                await msg.click(text=target_button)
                                print(f"[+] کلیک '{target_button}' (ارزش={fish_value})")
                                handled = True
                                break
                        if handled:
                            break
                    if handled:
                        break

            if not handled:
                print("[!] پیام ماهیگیری توی این دور پیدا نشد.")

        except Exception as e:
            print(f"[!] خطا در حلقه ماهیگیری: {e}")

        await asyncio.sleep(FISHING_INTERVAL_SECONDS)


async def rescue_listener():
    """
    لیسنر پیام‌های جدید گروه:
    اگه پیام جدیدی از TARGET_BOT اومد و دکمه 'نجات پیشی خیابونی' داشت،
    اون دکمه رو بزن تا کاملاً بره (حلقه می‌زنه تا دکمه دیگه نباشه)
    """
    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        msg = event.message
        if not msg.buttons:
            return

        # چک کن فرستنده همون بات باشه
        sender = await msg.get_sender()
        sender_username = getattr(sender, "username", None)
        is_target = (
            str(msg.sender_id) == str(TARGET_BOT).lstrip("@")
            or (sender_username and f"@{sender_username}" == TARGET_BOT)
        )
        if not is_target:
            return

        # دنبال دکمه نجات بگرد
        button_texts = {b.text.strip() for row in msg.buttons for b in row}
        if RESCUE_BUTTON_TEXT not in button_texts:
            return

        print(f"[!] دکمه '{RESCUE_BUTTON_TEXT}' پیدا شد! شروع به کلیک...")

        # حلقه بزن تا دکمه کاملاً بره
        while True:
            try:
                # پیام رو رفرش کن تا ببینیم هنوز دکمه داره
                fresh = await client.get_messages(GROUP_ID, ids=msg.id)
                if not fresh or not fresh.buttons:
                    print(f"[+] دکمه '{RESCUE_BUTTON_TEXT}' دیگه نیست، تموم شد.")
                    break

                current_texts = {b.text.strip() for row in fresh.buttons for b in row}
                if RESCUE_BUTTON_TEXT not in current_texts:
                    print(f"[+] دکمه '{RESCUE_BUTTON_TEXT}' دیگه نیست، تموم شد.")
                    break

                await fresh.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک روی '{RESCUE_BUTTON_TEXT}'")
                await asyncio.sleep(1.5)  # کمی صبر بین کلیک‌ها

            except Exception as e:
                print(f"[!] خطا در حلقه نجات: {e}")
                break

    # نگه‌دار لیسنر رو فعال نگه‌دار (این تابع هرگز تموم نمیشه)
    await client.run_until_disconnected()


async def main():
    init_db()
    await client.start()
    me = await client.get_me()
    print(f"[+] وارد شدی به عنوان: {me.first_name} (@{me.username})")
    print("[+] اسکریپت شروع به کار کرد. برای توقف Ctrl+C بزن.\n")

    await asyncio.gather(
        send_meow_loop(),
        send_pishi_and_click_loop(),
        send_fishing_loop(),
        rescue_listener(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())