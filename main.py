import asyncio
import random
import re
import sqlite3
import time
from telethon import TelegramClient, events
from telethon.errors import (PersistentTimestampOutdatedError, FloodWaitError,
                              ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

# ══════════════════════════════════════════════════
#  تنظیمات
# ══════════════════════════════════════════════════
API_ID   = 22487790
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
WAIT_FOR_BOT       = 20
# ══════════════════════════════════════════════════

client       = TelegramClient(SESSION_NAME, API_ID, API_HASH)
active_group = PRIMARY_GROUP

last_panel_msg: dict[int, tuple[int, str]] = {}


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
        "meow_sec":  "245",
        "meow_list": "میو,مع,معو,میو میو",
        "pishi_sec": "1480",
        "fish_sec":  "1500",
        "stomach":   "7",
        "pishi_msg": "پیشی",
        "fish_msg":  "ماهی",
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

def fmt_time(s: float) -> str:
    s = int(s)
    if s <= 0:   return "الان ✅"
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"


# ══════════════════════════════════════════════════
#  توابع کمکی
# ══════════════════════════════════════════════════

BLOCKED = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

async def safe_send(gid, text, retries=3):
    global active_group
    for attempt in range(retries):
        try:
            msg = await client.send_message(gid, text)
            return msg   # ← پیام ارسال‌شده رو برمیگردونه
        except BLOCKED as e:
            print(f"[!] بلاک از {gid}: {type(e).__name__}")
            if gid == PRIMARY_GROUP and active_group == PRIMARY_GROUP:
                active_group = FALLBACK_GROUP
                print(f"[~] سوییچ به fallback: {FALLBACK_GROUP}")
            return None
        except FloodWaitError as e:
            print(f"[!] FloodWait {e.seconds}s")
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            print(f"[!] خطا ارسال: {e}"); await asyncio.sleep(5)
    return None

def is_bot(msg, sender) -> bool:
    uname = getattr(sender, "username", None)
    return (str(msg.sender_id) == TARGET_BOT.lstrip("@")
            or (uname and f"@{uname}" == TARGET_BOT))

def parse_stomach(text: str):
    m = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    return int(m.group(1)) if m else None


async def wait_for_reply(gid: int, my_msg_id: int, has_buttons: set, timeout: int = WAIT_FOR_BOT):
    """
    فقط پیامی رو قبول می‌کنه که:
    - از TARGET_BOT باشه
    - reply_to_msg_id اون دقیقاً برابر my_msg_id باشه
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1)
        try:
            async for msg in client.iter_messages(gid, limit=10):
                if not msg.buttons or not msg.sender_id:
                    continue
                if not msg.reply_to or msg.reply_to.reply_to_msg_id != my_msg_id:
                    continue
                sender = await msg.get_sender()
                if not is_bot(msg, sender):
                    continue
                btn_texts = {b.text.strip() for row in msg.buttons for b in row}
                if has_buttons & btn_texts:
                    return msg
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[!] خطا در wait_for_reply: {e}")
            await asyncio.sleep(2)
    return None


# ══════════════════════════════════════════════════
#  پنل کنترل
# ══════════════════════════════════════════════════

KEYS = {
    "meow_sec":  ("⏱", "فاصله میو", "ثانیه"),
    "meow_list": ("💬", "لیست میوها", "با کاما جدا کن"),
    "pishi_sec": ("🐾", "فاصله پیشی", "ثانیه"),
    "fish_sec":  ("🎣", "فاصله ماهی", "ثانیه"),
    "stomach":   ("🍖", "آستانه شکم", "زیرش بده پیشی"),
    "pishi_msg": ("📨", "متن پیشی", "پیامی که ارسال میشه"),
    "fish_msg":  ("📨", "متن ماهی", "پیامی که ارسال میشه"),
}
NUMERIC_KEYS = {"meow_sec", "pishi_sec", "fish_sec", "stomach"}

def build_help() -> str:
    return (
        "╔══════════════════════╗\n"
        "║   🐱  Afshin Self    ║\n"
        "╚══════════════════════╝\n\n"
        "📊  **وضعیت و تایمر**\n"
        "┌─────────────────────\n"
        "│  `/s`  ─  وضعیت کامل\n"
        "│  `/t`  ─  زمان مانده\n"
        "└─────────────────────\n\n"
        "⚙️  **تنظیمات** _(مقدار جدید رو بعد دستور بنویس)_\n"
        "┌─────────────────────\n"
        "│  `/meow_sec`   ─  فاصله میو (ثانیه)\n"
        "│  `/meow_list`  ─  لیست میوها (با کاما)\n"
        "│  `/pishi_sec`  ─  فاصله پیشی (ثانیه)\n"
        "│  `/fish_sec`   ─  فاصله ماهی (ثانیه)\n"
        "│  `/stomach`    ─  آستانه شکم\n"
        "│  `/pishi_msg`  ─  متن پیام پیشی\n"
        "│  `/fish_msg`   ─  متن پیام ماهی\n"
        "└─────────────────────\n\n"
        "💡  **مثال‌ها**\n"
        "┌─────────────────────\n"
        "│  `/meow_sec 240`\n"
        "│  `/stomach 6`\n"
        "│  `/meow_list میو,مع,معو,مرررو`\n"
        "└─────────────────────\n\n"
        "🐟  **منطق ماهی**\n"
        "┌─────────────────────\n"
        "│  شکم < `/stomach` → بده پیشی بخوره\n"
        "│  شکم ≥ `/stomach` → فروش ماهی\n"
        "└─────────────────────"
    )

def build_status() -> str:
    mi = int(cfg("meow_sec"))
    pi = int(cfg("pishi_sec"))
    fi = int(cfg("fish_sec"))
    threshold = int(cfg("stomach"))
    stomach   = get_stomach()
    fish_action = SELL_FISH_BUTTON if stomach >= threshold else GIVE_TO_CAT_BUTTON
    return (
        "╔══════════════════════╗\n"
        "║   🐱  Afshin Self    ║\n"
        "╚══════════════════════╝\n\n"
        f"🏠  گروه فعال: `{active_group}`\n\n"
        "⏱  **تایمرها**\n"
        "┌─────────────────────\n"
        f"│  🐱 میو     هر `{mi}s`  ─  مانده: `{fmt_time(secs_left('meow', mi))}`\n"
        f"│  🐾 پیشی    هر `{pi}s`  ─  مانده: `{fmt_time(secs_left('pishi', pi))}`\n"
        f"│  🎣 ماهی    هر `{fi}s`  ─  مانده: `{fmt_time(secs_left('fishing', fi))}`\n"
        "└─────────────────────\n\n"
        "💬  **میوها**\n"
        f"┌─  `{cfg('meow_list')}`\n\n"
        "🍖  **ماهی / شکم**\n"
        "┌─────────────────────\n"
        f"│  آستانه: `{threshold}`  │  شکم فعلی: `{stomach}`\n"
        f"│  اکشن بعدی: **{fish_action}**\n"
        "└─────────────────────"
    )

def build_timers() -> str:
    mi = int(cfg("meow_sec"))
    pi = int(cfg("pishi_sec"))
    fi = int(cfg("fish_sec"))
    return (
        "╔══════════════════════╗\n"
        "║   ⏳  تایمرها        ║\n"
        "╚══════════════════════╝\n\n"
        f"🐱  میو    ─  `{fmt_time(secs_left('meow', mi))}`\n"
        f"🐾  پیشی   ─  `{fmt_time(secs_left('pishi', pi))}`\n"
        f"🎣  ماهی   ─  `{fmt_time(secs_left('fishing', fi))}`"
    )

async def panel_reply(event, text: str):
    chat_id = event.chat_id
    info    = last_panel_msg.get(chat_id)
    if info:
        prev_id, prev_text = info
        if prev_text != text:
            try:
                await client.edit_message(chat_id, prev_id, text)
                last_panel_msg[chat_id] = (prev_id, text)
                return
            except Exception:
                pass
        else:
            return
    msg = await client.send_message(chat_id, text)
    last_panel_msg[chat_id] = (msg.id, text)

async def handle_command(event):
    raw = (event.message.text or "").strip()
    if not raw.startswith("/"):
        return
    parts = raw[1:].split(" ", 1)
    cmd   = parts[0].lower()
    rest  = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("h", "help"):
        await panel_reply(event, build_help()); return
    if cmd in ("s", "status"):
        await panel_reply(event, build_status()); return
    if cmd in ("t", "timers"):
        await panel_reply(event, build_timers()); return
    if cmd in KEYS:
        if not rest:
            await panel_reply(event, f"❌  مقدار بده:\n`/{cmd} مقدار`"); return
        if cmd in NUMERIC_KEYS and not rest.isdigit():
            await panel_reply(event, f"❌  `{cmd}` باید عدد باشه."); return
        cfg_set(cmd, rest)
        emoji = KEYS[cmd][0]
        await panel_reply(event, f"✅  {emoji} `{cmd}` = `{rest}` ذخیره شد.")
        return
    await panel_reply(event, "❓  دستور ناشناس.\n`/help` بزن.")


# ══════════════════════════════════════════════════
#  حلقه‌های اصلی
# ══════════════════════════════════════════════════

async def meow_loop():
    interval = int(cfg("meow_sec"))
    wait = secs_left("meow", interval)
    if wait > 0:
        print(f"[~] میو: {fmt_time(wait)} مونده")
        await asyncio.sleep(wait)

    while True:
        interval = int(cfg("meow_sec"))
        choices  = [x.strip() for x in cfg("meow_list").split(",") if x.strip()]
        text     = random.choice(choices)
        target   = active_group
        sent = await safe_send(target, text)
        if not sent and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
            sent = await safe_send(FALLBACK_GROUP, text)
        if sent:
            set_last_run("meow", time.time())
            print(f"[+] میو '{text}' → {active_group}")
        await asyncio.sleep(interval)


async def pishi_loop():
    interval = int(cfg("pishi_sec"))
    wait = secs_left("pishi", interval)
    if wait > 0:
        print(f"[~] پیشی: {fmt_time(wait)} مونده")
        await asyncio.sleep(wait)

    while True:
        interval   = int(cfg("pishi_sec"))
        pishi_text = cfg("pishi_msg")
        try:
            target = active_group
            sent = await safe_send(target, pishi_text)
            if not sent and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                sent = await safe_send(FALLBACK_GROUP, pishi_text)
            if not sent:
                await asyncio.sleep(interval); continue

            set_last_run("pishi", time.time())
            print(f"[+] پیشی → {active_group} (id={sent.id}) | منتظر ریپلای بات...")

            msg = await wait_for_reply(active_group, sent.id, {PISHI_BUTTON_TEXT})
            if msg:
                sv = parse_stomach(msg.text or "")
                if sv is not None:
                    set_stomach(sv)
                    print(f"[i] شکم بروزرسانی شد: {sv}")
                await msg.click(text=PISHI_BUTTON_TEXT)
                print(f"[+] '{PISHI_BUTTON_TEXT}' زده شد.")
            else:
                print("[!] دکمه پیشی پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا پیشی: {e}")
        await asyncio.sleep(interval)


async def fishing_loop():
    interval = int(cfg("fish_sec"))
    wait = secs_left("fishing", interval)
    if wait > 0:
        print(f"[~] ماهی: {fmt_time(wait)} مونده")
        await asyncio.sleep(wait)

    while True:
        interval  = int(cfg("fish_sec"))
        fish_text = cfg("fish_msg")
        threshold = int(cfg("stomach"))
        try:
            target = active_group
            sent = await safe_send(target, fish_text)
            if not sent and target == PRIMARY_GROUP and active_group == FALLBACK_GROUP:
                sent = await safe_send(FALLBACK_GROUP, fish_text)
            if not sent:
                await asyncio.sleep(interval); continue

            set_last_run("fishing", time.time())
            print(f"[+] ماهی → {active_group} (id={sent.id}) | منتظر ریپلای بات...")

            msg = await wait_for_reply(active_group, sent.id, {SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON})
            if msg:
                stomach    = get_stomach()
                target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                print(f"[i] شکم={stomach} threshold={threshold} → '{target_btn}'")
                await msg.click(text=target_btn)
                print(f"[+] کلیک '{target_btn}' ✓")
            else:
                print("[!] پیام ماهیگیری پیدا نشد.")
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
        btn_texts = {b.text.strip() for row in msg.buttons for b in row}
        if RESCUE_BUTTON_TEXT not in btn_texts: return
        sender = await msg.get_sender()
        if not is_bot(msg, sender): return

        chat_id = event.chat_id
        print(f"[!!!] نجات پیشی! گروه {chat_id} — کلیک فوری...")

        for attempt in range(3):
            try:
                await msg.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک {attempt+1} نجات ✓")
                break
            except Exception as e:
                print(f"[!] کلیک {attempt+1} خطا: {e}")
                await asyncio.sleep(0.2)

        await asyncio.sleep(0.3)
        while True:
            try:
                fresh = await client.get_messages(chat_id, ids=msg.id)
                if not fresh or not fresh.buttons:
                    print("[+] دکمه نجات رفت ✓"); break
                cur = {b.text.strip() for row in fresh.buttons for b in row}
                if RESCUE_BUTTON_TEXT not in cur:
                    print("[+] دکمه نجات رفت ✓"); break
                await fresh.click(text=RESCUE_BUTTON_TEXT)
                print(f"[+] کلیک مجدد نجات ✓")
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[!] خطا نجات: {e}"); break

    await client.run_until_disconnected()


# ══════════════════════════════════════════════════
#  Command Listener
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
    print("[+] شروع شد — هر جا /help بنویس\n")

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
