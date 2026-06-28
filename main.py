import asyncio
import random
import re
import sqlite3
import time
from telethon import TelegramClient, events
from telethon.errors import (PersistentTimestampOutdatedError, FloodWaitError,
                              ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

# ===================== تنظیمات =====================
API_ID = 22487790
API_HASH = "09c24af20084de9372cc92a760c74961"

PRIMARY_GROUP  = -1003380347106
FALLBACK_GROUP = -1003979242735

RESCUE_GROUPS = [
    -1003380347106, -1003979242735, -1002305033993,
    -1003329545310, -1002401888484, -1002352251108,
]

SESSION_NAME = "my_account_session"
DB_FILE      = "timers.db"

TARGET_BOT         = "@MeowieQBot"
RESCUE_BUTTON_TEXT = "نجات پیشی خیابونی 🐱"
PISHI_BUTTON_TEXT  = "برداشت میو پوینت ها"
SELL_FISH_BUTTON   = "فروش ماهی"
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"
WAIT_FOR_BOT       = 15
# =====================================================

client     = TelegramClient(SESSION_NAME, API_ID, API_HASH)
active_group = PRIMARY_GROUP

# ── آخرین پیام help در هر چت (chat_id → msg_id) ──
last_help_msg: dict[int, int] = {}


# ══════════════════════════════════════════════════
#  دیتابیس
# ══════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS timers (key TEXT PRIMARY KEY, last_run REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS cat_stats (id INTEGER PRIMARY KEY CHECK(id=1), stomach INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.execute("INSERT OR IGNORE INTO cat_stats (id, stomach) VALUES (1, 0)")
    defaults = {
        "meow_sec":   "245",
        "meow_list":  "میو,مع,معو,میو میو",
        "pishi_sec":  "1480",
        "fish_sec":   "1500",
        "stomach":    "7",
        "pishi_msg":  "پیشی",
        "fish_msg":   "ماهی",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO config (key,value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()

def cfg(key): 
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else ""

def cfg_set(key, value):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO config (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit(); conn.close()

def get_last_run(key):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT last_run FROM timers WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else 0.0

def set_last_run(key, ts):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT INTO timers (key,last_run) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET last_run=excluded.last_run", (key, ts))
    conn.commit(); conn.close()

def get_stomach():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT stomach FROM cat_stats WHERE id=1")
    row = c.fetchone(); conn.close()
    return row[0] if row else 0

def set_stomach(v):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("UPDATE cat_stats SET stomach=? WHERE id=1", (v,))
    conn.commit(); conn.close()

def secs_left(key, interval):
    last = get_last_run(key)
    return 0.0 if last == 0.0 else max(0.0, interval - (time.time() - last))


# ══════════════════════════════════════════════════
#  توابع کمکی
# ══════════════════════════════════════════════════

BLOCKED = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

async def safe_send(gid, text, retries=3):
    global active_group
    for attempt in range(retries):
        try:
            await client.send_message(gid, text)
            return True
        except BLOCKED as e:
            print(f"[!] بلاک از {gid}: {type(e).__name__}")
            if gid == PRIMARY_GROUP and active_group == PRIMARY_GROUP:
                active_group = FALLBACK_GROUP
                print(f"[~] سوییچ به fallback: {FALLBACK_GROUP}")
            return False
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"[!] خطا ارسال: {e}"); await asyncio.sleep(5)
    return False

async def safe_msgs(gid, limit=5):
    for attempt in range(3):
        try:
            out = []
            async for m in client.iter_messages(gid, limit=limit):
                out.append(m)
            return out
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"[!] خطا خواندن: {e}"); await asyncio.sleep(5)
    return []

def is_bot(msg, sender):
    uname = getattr(sender, "username", None)
    return (str(msg.sender_id) == TARGET_BOT.lstrip("@")
            or (uname and f"@{uname}" == TARGET_BOT))

def parse_stomach(text):
    m = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════
#  پنل کنترل — ویرایش/ارسال پیام در هر جایی
# ══════════════════════════════════════════════════

# کلیدهای مجاز و توضیحشون
KEYS = {
    "meow_sec":  "⏱ فاصله میو (ثانیه)",
    "meow_list": "💬 لیست میوها (با کاما)",
    "pishi_sec": "🐾 فاصله پیشی (ثانیه)",
    "fish_sec":  "🎣 فاصله ماهی (ثانیه)",
    "stomach":   "🍖 آستانه شکم",
    "pishi_msg": "📝 متن پیشی",
    "fish_msg":  "📝 متن ماهی",
}

def build_status() -> str:
    w = secs_left
    lines = [
        "🐱 **Afshin Self**\n",
        f"⏱ میو هر `{cfg('meow_sec')}s` | مانده: `{w('meow', int(cfg('meow_sec'))):.0f}s`",
        f"💬 میوها: `{cfg('meow_list')}`",
        f"🐾 پیشی هر `{cfg('pishi_sec')}s` | مانده: `{w('pishi', int(cfg('pishi_sec'))):.0f}s`",
        f"🎣 ماهی هر `{cfg('fish_sec')}s` | مانده: `{w('fishing', int(cfg('fish_sec'))):.0f}s`",
        f"🍖 آستانه شکم: `{cfg('stomach')}` | فعلی: `{get_stomach()}`",
        f"🏠 گروه فعال: `{active_group}`",
    ]
    return "\n".join(lines)

def build_help() -> str:
    return (
        "🐱 **Afshin Self — راهنما**\n\n"
        "**📊 وضعیت:**\n"
        "`/s` — وضعیت کامل\n"
        "`/t` — زمان‌های مانده\n\n"
        "**⚙️ تغییر تنظیمات:**\n"
        "`/meow_sec 240`\n"
        "`/meow_list میو,مع,معو`\n"
        "`/pishi_sec 2400`\n"
        "`/fish_sec 1500`\n"
        "`/stomach 8`\n"
        "`/pishi_msg پیشی`\n"
        "`/fish_msg ماهی`\n\n"
        "**مثال:** `/meow_sec 240` فاصله میو رو ۲۴۰ ثانیه میکنه"
    )

def build_timers() -> str:
    lines = [
        "⏳ **زمان مانده**\n",
        f"🐱 میو: `{secs_left('meow', int(cfg('meow_sec'))):.0f}s`",
        f"🐾 پیشی: `{secs_left('pishi', int(cfg('pishi_sec'))):.0f}s`",
        f"🎣 ماهی: `{secs_left('fishing', int(cfg('fish_sec'))):.0f}s`",
    ]
    return "\n".join(lines)


async def reply_or_edit(event, text: str):
    """
    اگه قبلاً یه پیام help/status در این چت فرستادیم → ادیتش کن
    وگرنه → پیام جدید بفرست و id رو نگه‌دار
    """
    chat_id = event.chat_id
    existing_id = last_help_msg.get(chat_id)
    if existing_id:
        try:
            await client.edit_message(chat_id, existing_id, text)
            return
        except Exception:
            pass  # اگه ادیت نشد، پیام جدید بفرست
    msg = await client.send_message(chat_id, text)
    last_help_msg[chat_id] = msg.id


async def handle_command(event):
    text = (event.message.text or "").strip()
    if not text.startswith("/"):
        return

    cmd_parts = text[1:].split(" ", 1)
    cmd  = cmd_parts[0].lower()
    rest = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

    # ── دستورات نمایشی ──
    if cmd in ("s", "status"):
        await reply_or_edit(event, build_status())
        return
    if cmd in ("t", "timers"):
        await reply_or_edit(event, build_timers())
        return
    if cmd in ("h", "help"):
        await reply_or_edit(event, build_help())
        return

    # ── دستورات set (کوتاه) ──
    if cmd in KEYS:
        if not rest:
            await reply_or_edit(event, f"❌ مقدار بده: `/{cmd} مقدار`")
            return
        # اعتبارسنجی عددی
        if cmd in ("meow_sec", "pishi_sec", "fish_sec", "stomach"):
            if not rest.isdigit():
                await reply_or_edit(event, f"❌ باید عدد باشه.")
                return
        cfg_set(cmd, rest)
        await reply_or_edit(event, f"✅ `{cmd}` = `{rest}`")
        return

    # دستور ناشناس
    await reply_or_edit(event, f"❓ دستور ناشناس. بنویس `/help`")


# ══════════════════════════════════════════════════
#  حلقه‌های اصلی
# ══════════════════════════════════════════════════

async def meow_loop():
    interval = int(cfg("meow_sec"))
    wait = secs_left("meow", interval)
    if wait > 0:
        print(f"[~] میو: {wait:.0f}s مونده"); await asyncio.sleep(wait)

    while True:
        interval = int(cfg("meow_sec"))
        choices  = [x.strip() for x in cfg("meow_list").split(",")]
        text     = random.choice(choices)
        target   = active_group
        ok = await safe_send(target, text)
        if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
            ok = await safe_send(FALLBACK_GROUP, text)
        if ok:
            set_last_run("meow", time.time())
            print(f"[+] میو '{text}' → {active_group}")
        await asyncio.sleep(interval)


async def pishi_loop():
    interval = int(cfg("pishi_sec"))
    wait = secs_left("pishi", interval)
    if wait > 0:
        print(f"[~] پیشی: {wait:.0f}s مونده"); await asyncio.sleep(wait)

    while True:
        interval   = int(cfg("pishi_sec"))
        pishi_text = cfg("pishi_msg")
        try:
            target = active_group
            ok = await safe_send(target, pishi_text)
            if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                ok = await safe_send(FALLBACK_GROUP, pishi_text)
            if ok:
                set_last_run("pishi", time.time())
                print(f"[+] پیشی → {active_group}")

            clicked = False; elapsed = 0
            while elapsed < WAIT_FOR_BOT and not clicked:
                await asyncio.sleep(1); elapsed += 1
                for msg in await safe_msgs(active_group, 5):
                    if not msg.sender_id or not msg.buttons: continue
                    sender = await msg.get_sender()
                    if not is_bot(msg, sender): continue
                    sv = parse_stomach(msg.text or "")
                    if sv is not None: set_stomach(sv)
                    for row in msg.buttons:
                        for btn in row:
                            if btn.text.strip() == PISHI_BUTTON_TEXT:
                                await msg.click(text=PISHI_BUTTON_TEXT)
                                print(f"[+] '{PISHI_BUTTON_TEXT}' زده شد.")
                                clicked = True; break
                        if clicked: break
                    if clicked: break
            if not clicked: print("[!] دکمه پیشی پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا پیشی: {e}")
        await asyncio.sleep(interval)


async def fishing_loop():
    interval = int(cfg("fish_sec"))
    wait = secs_left("fishing", interval)
    if wait > 0:
        print(f"[~] ماهی: {wait:.0f}s مونده"); await asyncio.sleep(wait)

    while True:
        interval    = int(cfg("fish_sec"))
        fish_text   = cfg("fish_msg")
        threshold   = int(cfg("stomach"))
        try:
            target = active_group
            ok = await safe_send(target, fish_text)
            if not ok and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                ok = await safe_send(FALLBACK_GROUP, fish_text)
            if ok:
                set_last_run("fishing", time.time())
                print(f"[+] ماهی → {active_group}")

            handled = False; elapsed = 0
            while elapsed < WAIT_FOR_BOT and not handled:
                await asyncio.sleep(1); elapsed += 1
                for msg in await safe_msgs(active_group, 5):
                    if not msg.sender_id or not msg.buttons: continue
                    sender = await msg.get_sender()
                    if not is_bot(msg, sender): continue
                    btns = {b.text.strip() for row in msg.buttons for b in row}
                    if not ({SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON} & btns): continue
                    stomach   = get_stomach()
                    target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                    print(f"[i] شکم={stomach} threshold={threshold} → '{target_btn}'")
                    for row in msg.buttons:
                        for btn in row:
                            if btn.text.strip() == target_btn:
                                await msg.click(text=target_btn)
                                print(f"[+] کلیک '{target_btn}'")
                                handled = True; break
                        if handled: break
                    if handled: break
            if not handled: print("[!] پیام ماهیگیری پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا ماهیگیری: {e}")
        await asyncio.sleep(interval)


# ══════════════════════════════════════════════════
#  Rescue Listener
# ══════════════════════════════════════════════════

async def rescue_listener():
    @client.on(events.NewMessage(chats=RESCUE_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.buttons: return
        if RESCUE_BUTTON_TEXT not in {b.text.strip() for row in msg.buttons for b in row}: return
        sender = await msg.get_sender()
        if not is_bot(msg, sender): return
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
                if not fresh or not fresh.buttons: print("[+] دکمه نجات رفت ✓"); break
                if RESCUE_BUTTON_TEXT not in {b.text.strip() for row in fresh.buttons for b in row}:
                    print("[+] دکمه نجات رفت ✓"); break
                await fresh.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک مجدد نجات")
                await asyncio.sleep(0.8)
            except Exception as e:
                print(f"[!] خطا نجات: {e}"); break

    await client.run_until_disconnected()


# ══════════════════════════════════════════════════
#  Command Listener — هر جایی (outgoing)
# ══════════════════════════════════════════════════

async def command_listener():
    @client.on(events.NewMessage(outgoing=True))
    async def handler(event):
        text = (event.message.text or "").strip()
        if text.startswith("/"):
            await handle_command(event)
    while True:
        await asyncio.sleep(3600)


# ══════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════

async def main():
    init_db()
    await client.start()
    me = await client.get_me()
    print(f"[+] اکانت: {me.first_name} (@{me.username})")
    print(f"[+] گروه اصلی: {PRIMARY_GROUP} | پشتیبان: {FALLBACK_GROUP}")
    print(f"[+] شکم: {get_stomach()} | ماهی هر {cfg('fish_sec')}s")
    print("[+] شروع شد — هر جا /help بنویس راهنما میاد\n")

    await asyncio.gather(
        meow_loop(),
        pishi_loop(),
        fishing_loop(),
        rescue_listener(),
        command_listener(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
