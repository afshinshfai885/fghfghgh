import asyncio
import random
import re
import sqlite3
import time
from telethon import TelegramClient, events
from telethon.errors import PersistentTimestampOutdatedError, FloodWaitError, ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError

# ===================== تنظیمات =====================
API_ID = 22487790
API_HASH = "09c24af20084de9372cc92a760c74961"

PRIMARY_GROUP  = -1003380347106
FALLBACK_GROUP = -1003979242735

RESCUE_GROUPS = [
    -1003380347106,
    -1003979242735,
    -1002305033993,
    -1003329545310,
    -1002401888484,
    -1002352251108,
]

SESSION_NAME = "my_account_session"
DB_FILE      = "timers.db"

TARGET_BOT         = "@MeowieQBot"
RESCUE_BUTTON_TEXT = "نجات پیشی خیابونی 🐱"
PISHI_BUTTON_TEXT  = "برداشت میو پوینت ها"
SELL_FISH_BUTTON   = "فروش ماهی"
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"

WAIT_FOR_BUTTON_SECONDS = 15
# =====================================================

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
active_group = PRIMARY_GROUP
my_id = None  # آیدی خود اکانت، بعد از start پر میشه


# ===================== دیتابیس =====================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS timers (
        key TEXT PRIMARY KEY, last_run REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS cat_stats (
        id INTEGER PRIMARY KEY CHECK (id=1), stomach INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    c.execute("INSERT OR IGNORE INTO cat_stats (id, stomach) VALUES (1, 0)")
    # مقادیر پیش‌فرض config
    defaults = {
        "meow_interval":   "275",
        "meow_choices":    "میو,مع,معو,میو میو",
        "pishi_interval":  "2400",
        "fishing_interval":"2400",
        "stomach_threshold":"8",
        "pishi_text":      "پیشی",
        "fishing_text":    "ماهی",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def cfg_get(key: str) -> str:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def cfg_set(key: str, value: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO config (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


def get_last_run(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_run FROM timers WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def set_last_run(key, ts):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO timers (key,last_run) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET last_run=excluded.last_run", (key, ts))
    conn.commit()
    conn.close()


def get_stomach():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT stomach FROM cat_stats WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def set_stomach(value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE cat_stats SET stomach=? WHERE id=1", (value,))
    conn.commit()
    conn.close()


def seconds_until_next(key, interval):
    last = get_last_run(key)
    if last == 0.0:
        return 0.0
    return max(0.0, interval - (time.time() - last))


# ===================== توابع کمکی =====================

SEND_BLOCKED = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)


async def safe_send(group_id, text, retries=3):
    global active_group
    for attempt in range(retries):
        try:
            await client.send_message(group_id, text)
            return True
        except SEND_BLOCKED as e:
            print(f"[!] بلاک از {group_id}: {type(e).__name__}")
            if group_id == PRIMARY_GROUP and active_group == PRIMARY_GROUP:
                print(f"[~] سوییچ به fallback: {FALLBACK_GROUP}")
                active_group = FALLBACK_GROUP
            return False
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"[!] خطا ارسال: {e}")
            await asyncio.sleep(5)
    return False


async def safe_iter_messages(group_id, limit=5):
    for attempt in range(3):
        try:
            msgs = []
            async for m in client.iter_messages(group_id, limit=limit):
                msgs.append(m)
            return msgs
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"[!] خطا خواندن: {e}")
            await asyncio.sleep(5)
    return []


def is_target_bot(msg, sender):
    uname = getattr(sender, "username", None)
    return (str(msg.sender_id) == TARGET_BOT.lstrip("@")
            or (uname and f"@{uname}" == TARGET_BOT))


def parse_stomach(text):
    m = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    return int(m.group(1)) if m else None


# ===================== پنل کنترل (Saved Messages) =====================

HELP_TEXT = """🐱 **Afshin Self — پنل کنترل**

━━━━━━━━━━━━━━━━
⏱ **تایمرها**
`/set meow_interval 275` — فاصله میو (ثانیه)
`/set pishi_interval 2400` — فاصله پیشی (ثانیه)
`/set fishing_interval 2400` — فاصله ماهی (ثانیه)

━━━━━━━━━━━━━━━━
🐟 **ماهیگیری**
`/set stomach_threshold 8` — آستانه شکم (زیرش → بده پیشی)

━━━━━━━━━━━━━━━━
💬 **متن پیام‌ها**
`/set meow_choices میو,مع,معو,میو میو` — لیست میوها (با کاما)
`/set pishi_text پیشی` — متن پیشی
`/set fishing_text ماهی` — متن ماهی

━━━━━━━━━━━━━━━━
📊 **وضعیت و اطلاعات**
`/status` — نمایش همه تنظیمات فعلی
`/stomach` — شکم فعلی پیشی
`/timers` — زمان مانده تا ارسال بعدی
`/help` — این راهنما
"""


async def send_to_me(text):
    """پیام به Saved Messages خودم"""
    await client.send_message("me", text)


async def handle_command(text: str):
    """پردازش دستورات از Saved Messages"""
    text = text.strip()

    if text == "/help":
        await send_to_me(HELP_TEXT)

    elif text == "/status":
        lines = [
            "📊 **تنظیمات فعلی Afshin Self**\n",
            f"⏱ میو هر `{cfg_get('meow_interval')}` ثانیه",
            f"💬 میوها: `{cfg_get('meow_choices')}`",
            f"🐱 پیشی هر `{cfg_get('pishi_interval')}` ثانیه  (متن: `{cfg_get('pishi_text')}`)",
            f"🎣 ماهی هر `{cfg_get('fishing_interval')}` ثانیه  (متن: `{cfg_get('fishing_text')}`)",
            f"🍖 آستانه شکم: `{cfg_get('stomach_threshold')}`",
            f"🏠 گروه فعال: `{active_group}`",
            f"🏠 گروه اصلی: `{PRIMARY_GROUP}`",
            f"🔄 گروه پشتیبان: `{FALLBACK_GROUP}`",
        ]
        await send_to_me("\n".join(lines))

    elif text == "/stomach":
        await send_to_me(f"🍖 شکم فعلی پیشی: `{get_stomach()}`")

    elif text == "/timers":
        mi = int(cfg_get("meow_interval"))
        pi = int(cfg_get("pishi_interval"))
        fi = int(cfg_get("fishing_interval"))
        lines = [
            "⏳ **زمان مانده تا ارسال بعدی**\n",
            f"🐱 میو: `{seconds_until_next('meow', mi):.0f}` ثانیه",
            f"🐾 پیشی: `{seconds_until_next('pishi', pi):.0f}` ثانیه",
            f"🎣 ماهی: `{seconds_until_next('fishing', fi):.0f}` ثانیه",
        ]
        await send_to_me("\n".join(lines))

    elif text.startswith("/set "):
        parts = text[5:].split(" ", 1)
        if len(parts) != 2:
            await send_to_me("❌ فرمت: `/set کلید مقدار`")
            return
        key, value = parts[0].strip(), parts[1].strip()
        valid_keys = [
            "meow_interval", "meow_choices", "pishi_interval",
            "fishing_interval", "stomach_threshold", "pishi_text", "fishing_text"
        ]
        if key not in valid_keys:
            await send_to_me(f"❌ کلید `{key}` معتبر نیست.\n\nکلیدهای مجاز:\n" + "\n".join(f"`{k}`" for k in valid_keys))
            return
        # اعتبارسنجی عددی
        if key in ("meow_interval", "pishi_interval", "fishing_interval", "stomach_threshold"):
            if not value.isdigit():
                await send_to_me(f"❌ مقدار `{key}` باید عدد باشه.")
                return
        cfg_set(key, value)
        await send_to_me(f"✅ `{key}` = `{value}` ذخیره شد.")

    else:
        # دستور ناشناس — بی‌صدا رد کن
        pass


# ===================== حلقه‌های اصلی =====================

async def send_meow_loop():
    interval = int(cfg_get("meow_interval"))
    wait = seconds_until_next("meow", interval)
    if wait > 0:
        print(f"[~] میو: {wait:.0f}s مونده...")
        await asyncio.sleep(wait)

    while True:
        interval = int(cfg_get("meow_interval"))
        choices = cfg_get("meow_choices").split(",")
        text = random.choice(choices).strip()
        target = active_group
        ok = await safe_send(target, text)
        if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
            ok = await safe_send(FALLBACK_GROUP, text)
        if ok:
            set_last_run("meow", time.time())
            print(f"[+] میو '{text}' → {active_group}")
        await asyncio.sleep(interval)


async def send_pishi_and_click_loop():
    interval = int(cfg_get("pishi_interval"))
    wait = seconds_until_next("pishi", interval)
    if wait > 0:
        print(f"[~] پیشی: {wait:.0f}s مونده...")
        await asyncio.sleep(wait)

    while True:
        interval = int(cfg_get("pishi_interval"))
        pishi_text = cfg_get("pishi_text")
        try:
            target = active_group
            ok = await safe_send(target, pishi_text)
            if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                ok = await safe_send(FALLBACK_GROUP, pishi_text)
            if ok:
                set_last_run("pishi", time.time())
                print(f"[+] پیشی → {active_group}")

            clicked = False
            elapsed = 0
            while elapsed < WAIT_FOR_BUTTON_SECONDS and not clicked:
                await asyncio.sleep(1)
                elapsed += 1
                msgs = await safe_iter_messages(active_group, limit=5)
                for msg in msgs:
                    if not msg.sender_id or not msg.buttons:
                        continue
                    sender = await msg.get_sender()
                    if not is_target_bot(msg, sender):
                        continue
                    sv = parse_stomach(msg.text or "")
                    if sv is not None:
                        set_stomach(sv)
                    for row in msg.buttons:
                        for btn in row:
                            if btn.text.strip() == PISHI_BUTTON_TEXT:
                                await msg.click(text=PISHI_BUTTON_TEXT)
                                print(f"[+] '{PISHI_BUTTON_TEXT}' زده شد.")
                                clicked = True
                                break
                        if clicked:
                            break
                    if clicked:
                        break
            if not clicked:
                print("[!] دکمه پیشی پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا پیشی: {e}")
        await asyncio.sleep(interval)


async def send_fishing_loop():
    interval = int(cfg_get("fishing_interval"))
    wait = seconds_until_next("fishing", interval)
    if wait > 0:
        print(f"[~] ماهی: {wait:.0f}s مونده...")
        await asyncio.sleep(wait)

    while True:
        interval = int(cfg_get("fishing_interval"))
        fishing_text = cfg_get("fishing_text")
        threshold = int(cfg_get("stomach_threshold"))
        try:
            target = active_group
            ok = await safe_send(target, fishing_text)
            if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                ok = await safe_send(FALLBACK_GROUP, fishing_text)
            if ok:
                set_last_run("fishing", time.time())
                print(f"[+] ماهی → {active_group}")

            handled = False
            elapsed = 0
            while elapsed < WAIT_FOR_BUTTON_SECONDS and not handled:
                await asyncio.sleep(1)
                elapsed += 1
                msgs = await safe_iter_messages(active_group, limit=5)
                for msg in msgs:
                    if not msg.sender_id or not msg.buttons:
                        continue
                    sender = await msg.get_sender()
                    if not is_target_bot(msg, sender):
                        continue
                    btn_texts = {b.text.strip() for row in msg.buttons for b in row}
                    if not ({SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON} & btn_texts):
                        continue
                    stomach = get_stomach()
                    target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                    print(f"[i] شکم={stomach} → '{target_btn}'")
                    for row in msg.buttons:
                        for btn in row:
                            if btn.text.strip() == target_btn:
                                await msg.click(text=target_btn)
                                print(f"[+] کلیک '{target_btn}'")
                                handled = True
                                break
                        if handled:
                            break
                    if handled:
                        break
            if not handled:
                print("[!] پیام ماهیگیری پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا ماهیگیری: {e}")
        await asyncio.sleep(interval)


# ===================== Rescue Listener =====================

async def rescue_listener():
    @client.on(events.NewMessage(chats=RESCUE_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.buttons:
            return
        btn_texts = {b.text.strip() for row in msg.buttons for b in row}
        if RESCUE_BUTTON_TEXT not in btn_texts:
            return
        sender = await msg.get_sender()
        if not is_target_bot(msg, sender):
            return
        chat_id = event.chat_id
        print(f"[!!!] نجات پیشی! گروه {chat_id}")
        try:
            await msg.click(text=RESCUE_BUTTON_TEXT)
            print(f"[+] کلیک اول نجات")
        except Exception as e:
            print(f"[!] کلیک اول خطا: {e}")
        await asyncio.sleep(0.8)
        while True:
            try:
                fresh = await client.get_messages(chat_id, ids=msg.id)
                if not fresh or not fresh.buttons:
                    print("[+] دکمه نجات رفت ✓")
                    break
                if RESCUE_BUTTON_TEXT not in {b.text.strip() for row in fresh.buttons for b in row}:
                    print("[+] دکمه نجات رفت ✓")
                    break
                await fresh.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک مجدد نجات")
                await asyncio.sleep(0.8)
            except Exception as e:
                print(f"[!] خطا نجات: {e}")
                break

    await client.run_until_disconnected()


# ===================== Command Listener (Saved Messages) =====================

async def command_listener():
    """
    پیام‌های خودت به Saved Messages رو گوش میده.
    اگه با / شروع شد → دستور
    """
    @client.on(events.NewMessage(outgoing=True, chats="me"))
    async def handler(event):
        text = event.message.text or ""
        if text.startswith("/"):
            await handle_command(text)

    # نگه‌دار تا disconnect نشه (rescue_listener این کارو میکنه، اینجا فقط handler تعریف میشه)
    while True:
        await asyncio.sleep(3600)


# ===================== Main =====================

async def main():
    global my_id
    init_db()
    await client.start()
    me = await client.get_me()
    my_id = me.id
    print(f"[+] اکانت: {me.first_name} (@{me.username})")
    print(f"[+] گروه اصلی: {PRIMARY_GROUP} | پشتیبان: {FALLBACK_GROUP}")
    print(f"[+] شکم: {get_stomach()}")
    print("[+] شروع شد. برای راهنما توی Saved Messages بنویس: /help\n")

    # ارسال راهنما به Saved Messages در شروع
    await send_to_me("🐱 **Afshin Self راه‌اندازی شد!**\nبرای راهنما بنویس: /help")

    await asyncio.gather(
        send_meow_loop(),
        send_pishi_and_click_loop(),
        send_fishing_loop(),
        rescue_listener(),
        command_listener(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
