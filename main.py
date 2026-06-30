import asyncio
import random
import re
import sqlite3
import time
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import PersistentTimestampOutdatedError, FloodWaitError

# ===================== تنظیمات اصلی =====================
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

# ---- گروه اصلی و گروه پشتیبان ----
PRIMARY_GROUP = -1003380347106
FALLBACK_GROUP = -1003979242735

# آخرین گروهی که ارسال/عملیات روی آن واقعاً انجام شده (همیشه باید چک شود)
active_group = PRIMARY_GROUP

# ---- گروه‌های مانیتورینگ برای سیستم نجات پیشی خیابونی ----
MONITOR_GROUPS = [
    -1003380347106,
    -1003979242735,
    -1002305033993,
    -1003329545310,
    -1002401888484,
    -1002352251108,
]

# نگه‌داشته شده برای سازگاری با کد قدیمی (دیگر مستقیم استفاده نمی‌شود)
GROUP_ID = PRIMARY_GROUP
EXTRA_GROUPS = []

SESSION_NAME = "my_account_session"
DB_FILE = "timers.db"

# ---- تنظیمات بخش رندوم میو ----
MEOW_INTERVAL_SECONDS = 240
MEOW_CHOICES = ["میو", "مع", "معو", "میو میو","Meo"]

# ---- تنظیمات بخش "پیشی" + کلیک روی دکمه ----
PISHI_INTERVAL_SECONDS = 40 * 60
PISHI_TEXT = "پیشی"
TARGET_BOT = "@MeowieQBot"
BUTTON_TEXT = "برداشت میو پوینت ها"
WAIT_FOR_BUTTON_SECONDS = 15

# ---- تنظیمات بخش "ماهیگیری" ----
FISHING_INTERVAL_SECONDS = 25 * 60
FISHING_TEXT = "ماهی"
SELL_FISH_BUTTON = "فروش ماهی"
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"
STOMACH_THRESHOLD = 7  # زیر 8 → بده پیشی بخوره | 8 به بالا → فروش ماهی

# ---- دکمه نجات پیشی ----
RESCUE_BUTTON_TEXT = "نجات پیشی خیابونی 🐱"

# ---- تنظیمات Heartbeat ----
HEARTBEAT_INTERVAL_SECONDS = 60 * 60  # هر 60 دقیقه
# ==========================================================

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


# ===================== دیتابیس =====================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS timers (
            key TEXT PRIMARY KEY,
            last_run REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS cat_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            stomach INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("INSERT OR IGNORE INTO cat_stats (id, stomach) VALUES (1, 0)")
    conn.commit()
    conn.close()


def get_last_run(key: str) -> float:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_run FROM timers WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def set_last_run(key: str, ts: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO timers (key, last_run) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET last_run = excluded.last_run
    """, (key, ts))
    conn.commit()
    conn.close()


def get_stomach() -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT stomach FROM cat_stats WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def set_stomach(value: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE cat_stats SET stomach = ? WHERE id = 1", (value,))
    conn.commit()
    conn.close()
    print(f"[i] شکم ذخیره شد: {value}")


def seconds_until_next(key: str, interval: float) -> float:
    last = get_last_run(key)
    if last == 0.0:
        return 0.0
    elapsed = time.time() - last
    remaining = interval - elapsed
    return max(0.0, remaining)


# ===================== توابع کمکی =====================

async def safe_send_to_group(group_id, text, retries=3):
    """
    تلاش برای ارسال پیام فقط به یک گروه مشخص (بدون فالبک).
    در صورت موفقیت True برمی‌گرداند، در غیر این صورت False.
    """
    for attempt in range(retries):
        try:
            await client.send_message(group_id, text)
            return True
        except FloodWaitError as e:
            print(f"[!] FloodWait در گروه {group_id}: {e.seconds} ثانیه صبر می‌کنم...")
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            wait = 10 * (attempt + 1)
            print(f"[!] PersistentTimestampOutdated در گروه {group_id}: {wait} ثانیه... ({attempt+1}/{retries})")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"[!] خطا در ارسال به گروه {group_id}: {e}")
            await asyncio.sleep(5)
    return False


async def safe_send(_unused_group_id, text, retries=3):
    """
    ارسال پیام با سیستم گروه اصلی + پشتیبان.
    ابتدا PRIMARY_GROUP امتحان می‌شود. اگر شکست خورد، فوراً FALLBACK_GROUP امتحان می‌شود.
    پارامتر اول برای سازگاری با امضای قبلی نگه داشته شده ولی استفاده نمی‌شود؛
    گروه واقعی همیشه از روی PRIMARY/FALLBACK تعیین می‌شود.

    خروجی: (success: bool, group_used: int یا None)
    """
    global active_group

    print(f"[~] تلاش برای ارسال در گروه اصلی (PRIMARY): {PRIMARY_GROUP}")
    ok = await safe_send_to_group(PRIMARY_GROUP, text, retries=retries)
    if ok:
        if active_group != PRIMARY_GROUP:
            print(f"[i] سوییچ: بازگشت به گروه اصلی (PRIMARY) → {PRIMARY_GROUP}")
        active_group = PRIMARY_GROUP
        return True, PRIMARY_GROUP

    print(f"[!] ارسال در گروه اصلی (PRIMARY) ناموفق بود. سوییچ به گروه پشتیبان (FALLBACK): {FALLBACK_GROUP}")
    ok = await safe_send_to_group(FALLBACK_GROUP, text, retries=retries)
    if ok:
        if active_group != FALLBACK_GROUP:
            print(f"[i] سوییچ: ادامه عملیات روی گروه پشتیبان (FALLBACK) → {FALLBACK_GROUP}")
        active_group = FALLBACK_GROUP
        return True, FALLBACK_GROUP

    print(f"[!] ارسال هم در PRIMARY و هم در FALLBACK ناموفق بود.")
    return False, None


async def safe_iter_messages(group_id, limit=5):
    for attempt in range(3):
        try:
            messages = []
            async for msg in client.iter_messages(group_id, limit=limit):
                messages.append(msg)
            return messages
        except PersistentTimestampOutdatedError:
            wait = 10 * (attempt + 1)
            print(f"[!] PersistentTimestampOutdated هنگام خواندن: {wait} ثانیه...")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"[!] خطا در خواندن پیام: {e}")
            await asyncio.sleep(5)
    return []


def parse_stomach(text: str):
    """
    از متن پیام پیشی، عدد شکم رو استخراج میکنه.
    مثال: 🍖 شکم : 😻 عاشقتمیووو (`10` / `10`)
    عدد اول رو برمیگردونه (مقدار فعلی)
    """
    match = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    if match:
        return int(match.group(1))
    return None


def is_target_bot(msg, sender) -> bool:
    sender_username = getattr(sender, "username", None)
    return (
        str(msg.sender_id) == str(TARGET_BOT).lstrip("@")
        or (sender_username and f"@{sender_username}" == TARGET_BOT)
    )


# ===================== حلقه‌های اصلی =====================

async def send_meow_loop():
    wait = seconds_until_next("meow", MEOW_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] میو: {wait:.0f} ثانیه مونده...")
        await asyncio.sleep(wait)

    while True:
        text = random.choice(MEOW_CHOICES)
        ok, used_group = await safe_send(None, text)
        if ok:
            set_last_run("meow", time.time())
            print(f"[+] میو رندوم '{text}' ارسال شد. (گروه: {used_group})")
        await asyncio.sleep(MEOW_INTERVAL_SECONDS)


async def send_pishi_and_click_loop():
    wait = seconds_until_next("pishi", PISHI_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] پیشی: {wait:.0f} ثانیه مونده...")
        await asyncio.sleep(wait)

    while True:
        try:
            ok, used_group = await safe_send(None, PISHI_TEXT)
            if ok:
                set_last_run("pishi", time.time())
                print(f"[+] پیام '{PISHI_TEXT}' ارسال شد در گروه {used_group}. منتظر پاسخ بات...")
            else:
                used_group = None

            clicked = False
            if used_group is not None:
                elapsed = 0
                while elapsed < WAIT_FOR_BUTTON_SECONDS and not clicked:
                    await asyncio.sleep(1)
                    elapsed += 1
                    # همیشه روی گروهی ادامه می‌دهیم که پیام واقعاً در آن ارسال شده
                    messages = await safe_iter_messages(used_group, limit=5)
                    for msg in messages:
                        if msg.sender_id is None or not msg.buttons:
                            continue
                        sender = await msg.get_sender()
                        if not is_target_bot(msg, sender):
                            continue

                        # --- پارس و ذخیره شکم ---
                        msg_text = msg.text or ""
                        stomach_val = parse_stomach(msg_text)
                        if stomach_val is not None:
                            set_stomach(stomach_val)

                        # --- کلیک دکمه برداشت ---
                        for row in msg.buttons:
                            for button in row:
                                if button.text.strip() == BUTTON_TEXT:
                                    await msg.click(text=BUTTON_TEXT)
                                    print(f"[+] دکمه '{BUTTON_TEXT}' زده شد. (گروه: {used_group})")
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
    wait = seconds_until_next("fishing", FISHING_INTERVAL_SECONDS)
    if wait > 0:
        print(f"[~] ماهی: {wait:.0f} ثانیه مونده...")
        await asyncio.sleep(wait)

    while True:
        try:
            ok, used_group = await safe_send(None, FISHING_TEXT)
            if ok:
                set_last_run("fishing", time.time())
                print(f"[+] پیام '{FISHING_TEXT}' ارسال شد در گروه {used_group}. منتظر پاسخ بات...")
            else:
                used_group = None

            handled = False
            if used_group is not None:
                elapsed = 0
                while elapsed < WAIT_FOR_BUTTON_SECONDS and not handled:
                    await asyncio.sleep(1)
                    elapsed += 1
                    # همیشه روی گروهی ادامه می‌دهیم که پیام واقعاً در آن ارسال شده
                    messages = await safe_iter_messages(used_group, limit=5)
                    for msg in messages:
                        if msg.sender_id is None or not msg.buttons:
                            continue
                        sender = await msg.get_sender()
                        if not is_target_bot(msg, sender):
                            continue

                        button_texts = {b.text.strip() for row in msg.buttons for b in row}
                        if not ({SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON} & button_texts):
                            continue

                        # --- تصمیم بر اساس شکم ---
                        stomach = get_stomach()
                        print(f"[i] شکم فعلی: {stomach}")

                        if stomach < STOMACH_THRESHOLD:
                            target_button = GIVE_TO_CAT_BUTTON
                            print(f"[i] شکم {stomach} < {STOMACH_THRESHOLD} → '{GIVE_TO_CAT_BUTTON}'")
                        else:
                            target_button = SELL_FISH_BUTTON
                            print(f"[i] شکم {stomach} >= {STOMACH_THRESHOLD} → '{SELL_FISH_BUTTON}'")

                        for row in msg.buttons:
                            for button in row:
                                if button.text.strip() == target_button:
                                    await msg.click(text=target_button)
                                    print(f"[+] کلیک '{target_button}' (شکم={stomach}, گروه={used_group})")
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


# ===================== Rescue Listener (Event-Based، سریع و تهاجمی) =====================

async def rescue_listener():
    """
    به صورت کاملاً Event-Based (بدون Polling) روی MONITOR_GROUPS گوش می‌دهد.
    به محض دریافت پیام جدید از TARGET_BOT که حاوی دکمه دقیق RESCUE_BUTTON_TEXT باشد،
    بلافاصله و بدون هیچ Sleep یا Delay روی Button Object کلیک می‌کند.

    پس از اولین کلیک، عملیات متوقف نمی‌شود: همان پیام دوباره از تلگرام خوانده می‌شود
    و تا زمانی که دکمه نجات کاملاً حذف نشده یا پیام پاک نشده یا خطای غیرقابل بازیابی
    رخ ندهد، کلیک‌های پی‌درپی ادامه پیدا می‌کند.
    """

    @client.on(events.NewMessage(chats=MONITOR_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.buttons:
            return

        sender = await msg.get_sender()
        if not is_target_bot(msg, sender):
            return

        # --- پیدا کردن مستقیم Button Object برای کلیک فوری ---
        rescue_button = None
        for row in msg.buttons:
            for button in row:
                if button.text.strip() == RESCUE_BUTTON_TEXT:
                    rescue_button = button
                    break
            if rescue_button:
                break

        if rescue_button is None:
            return

        chat_id = event.chat_id

        # --- کلیک اول: بدون هیچ تأخیری، مستقیم روی Button Object ---
        try:
            await rescue_button.click()
            print(f"[!!!] کلیک فوری روی '{RESCUE_BUTTON_TEXT}' (گروه: {chat_id}, پیام: {msg.id})")
        except Exception as e:
            print(f"[!] خطا در کلیک اول نجات پیشی (گروه: {chat_id}): {e}")
            # حتی اگر کلیک اول خطا داد، وارد حلقه تهاجمی می‌شویم تا با fetch تازه دوباره تلاش شود

        # --- حلقه کلیک تهاجمی و مداوم تا حذف کامل دکمه ---
        while True:
            try:
                fresh = await client.get_messages(chat_id, ids=msg.id)
                if not fresh or not fresh.buttons:
                    print(f"[+] دکمه '{RESCUE_BUTTON_TEXT}' دیگه نیست. پیشی نجات پیدا کرد/فرصت تمام شد. (گروه: {chat_id})")
                    break

                current_texts = {b.text.strip() for row in fresh.buttons for b in row}
                if RESCUE_BUTTON_TEXT not in current_texts:
                    print(f"[+] دکمه '{RESCUE_BUTTON_TEXT}' دیگه نیست. (گروه: {chat_id})")
                    break

                await fresh.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک مجدد روی '{RESCUE_BUTTON_TEXT}' (گروه: {chat_id})")

            except Exception as e:
                print(f"[!] خطای غیرقابل بازیابی در حلقه نجات (گروه: {chat_id}): {e}")
                break


# ===================== Heartbeat (گزارش سلامت) =====================

async def heartbeat_loop():
    """
    هر HEARTBEAT_INTERVAL_SECONDS (پیش‌فرض 60 دقیقه) یک‌بار وضعیت ربات را
    به Saved Messages گزارش می‌دهد. خطای این بخش هرگز کل برنامه را متوقف نمی‌کند.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            now_str = datetime.now().strftime("%H:%M:%S")
            text = (
                "✅ ربات فعال است\n"
                f"⏰ زمان: {now_str}\n"
                "📊 وضعیت: سالم"
            )
            await client.send_message("me", text)
            print(f"[+] Heartbeat ارسال شد به Saved Messages ({now_str})")
        except Exception as e:
            print(f"[!] خطا در ارسال Heartbeat (برنامه متوقف نمی‌شود): {e}")


# ===================== Main =====================

async def main():
    init_db()
    await client.start()
    me = await client.get_me()
    print(f"[+] وارد شدی به عنوان: {me.first_name} (@{me.username})")
    print(f"[+] شکم فعلی تو DB: {get_stomach()}")
    print(f"[+] گروه اصلی (PRIMARY): {PRIMARY_GROUP}")
    print(f"[+] گروه پشتیبان (FALLBACK): {FALLBACK_GROUP}")
    print(f"[+] گروه‌های مانیتورینگ نجات پیشی: {MONITOR_GROUPS}")
    print("[+] اسکریپت شروع شد. Ctrl+C برای توقف.\n")

    await asyncio.gather(
        send_meow_loop(),
        send_pishi_and_click_loop(),
        send_fishing_loop(),
        rescue_listener(),
        heartbeat_loop(),
        client.run_until_disconnected(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
