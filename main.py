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
SELL_FISH_BUTTON   = "فروش ماهی"  # طبق خواسته شما روی همان فروش ماهی برگشت
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"
WAIT_FOR_BOT       = 25 
# ══════════════════════════════════════════════════

client       = TelegramClient(SESSION_NAME, API_ID, API_HASH)
active_group = PRIMARY_GROUP
my_user_id   = None  # در متد main مقداردهی می‌شود

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
    if s <= 0:   return "همین الان ✅"
    if s < 60:   return f"{s} ثانیه"
    if s < 3600: return f"{s//60} دقیقه و {s%60} ثانیه"
    return f"{s//3600} ساعت و {(s%3600)//60} دقیقه"

# ══════════════════════════════════════════════════
#  توابع کمکی
# ══════════════════════════════════════════════════

BLOCKED = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

async def safe_send(gid, text, retries=3):
    global active_group
    for attempt in range(retries):
        try:
            msg = await client.send_message(gid, text)
            return msg   
        except BLOCKED as e:
            print(f"[!] بلاک از {gid}: {type(e).__name__}")
            if gid == PRIMARY_GROUP and active_group == PRIMARY_GROUP:
                active_group = FALLBACK_GROUP
                print(f"[~] سوییچ به گروه پشتیبان: {FALLBACK_GROUP}")
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
    global my_user_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1)
        try:
            # اسکن تا 40 پیام آخر برای امنیت بالا در گروه‌های فوق شلوغ
            async for msg in client.iter_messages(gid, limit=40):
                if not msg.buttons or not msg.sender_id:
                    continue
                
                # فیلتر اول: پیام حتما باید مال ربات بازی باشد
                sender = await msg.get_sender()
                if not is_bot(msg, sender):
                    continue
                
                # فیلتر دوم (بسیار مهم): پیام یا باید دقیقاً ریپلای پیام شما باشد یا ایدی شما در متن منشن شده باشد
                is_for_me = False
                if msg.reply_to and msg.reply_to.reply_to_msg_id == my_msg_id:
                    is_for_me = True
                elif my_user_id and str(my_user_id) in (msg.text or ""):
                    is_for_me = True
                
                if not is_for_me:
                    continue

                # بررسی وجود دکمه‌های درخواستی در پیام پیدا شده
                btn_texts = {b.text.strip() for row in msg.buttons for b in row}
                found = False
                for target_btn in has_buttons:
                    for b_txt in btn_texts:
                        if target_btn in b_txt:
                            found = True
                            break
                    if found: break
                
                if found:
                    return msg
        except Exception as e:
            print(f"[!] خطا در wait_for_reply: {e}")
            await asyncio.sleep(1)
    return None

# ══════════════════════════════════════════════════
#  پنل کنترل (با قابلیت ادیت خودکار)
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
        "👑 **پـنـل مـدیـریـت ربـات پـیـشـی** 👑\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 **مشاهده وضعیت:**\n"
        "🔸 `/s` ↤ وضعیت کامل ربات\n"
        "🔸 `/t` ↤ زمان مانده تایمرها\n\n"
        "⚙️ **تـنـظـیـمـات (مقدار را بعد از دستور بنویسید):**\n"
        "🔹 `/meow_sec` ↤ فاصله زمانی میو (ثانیه)\n"
        "🔹 `/meow_list` ↤ متن میوها (جدا شده با کاما)\n"
        "🔹 `/pishi_sec` ↤ فاصله زمانی پیشی (ثانیه)\n"
        "🔹 `/fish_sec` ↤ فاصله زمانی ماهی (ثانیه)\n"
        "🔹 `/stomach` ↤ آستانه شکم (برای فروش یا دادن به پیشی)\n"
        "🔹 `/pishi_msg` ↤ متن ارسالی برای پیشی\n"
        "🔹 `/fish_msg` ↤ متن ارسالی برای ماهی\n\n"
        "💡 **مثال استفاده:**\n"
        "`/meow_sec 240`\n"
        "`/stomach 6`\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def build_status() -> str:
    mi = int(cfg("meow_sec"))
    pi = int(cfg("pishi_sec"))
    fi = int(cfg("fish_sec"))
    threshold = int(cfg("stomach"))
    stomach   = get_stomach()
    fish_action = SELL_FISH_BUTTON if stomach >= threshold else GIVE_TO_CAT_BUTTON
    
    return (
        "🤖 **وضـعـیـت فـعـلـی ربـات**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏠 **گروه فعال:** `{active_group}`\n\n"
        "⏱ **تایمرهای سیستم:**\n"
        f"🐱 **میو:** هر `{mi}` ثانیه ↤ ⏳ مانده: `{fmt_time(secs_left('meow', mi))}`\n"
        f"🐾 **پیشی:** هر `{pi}` ثانیه ↤ ⏳ مانده: `{fmt_time(secs_left('pishi', pi))}`\n"
        f"🎣 **ماهی:** هر `{fi}` ثانیه ↤ ⏳ مانده: `{fmt_time(secs_left('fishing', fi))}`\n\n"
        "💬 **لیست میوها:**\n"
        f"└ `{cfg('meow_list')}`\n\n"
        "🍖 **وضعیت شکم پیشی:**\n"
        f"🔸 حد آستانه تنظیم شده: `{threshold}`\n"
        f"🔸 شکم فعلی ذخیره شده: `{stomach}`\n"
        f"🎯 اکشن بعدی ماهی: **{fish_action}**\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def build_timers() -> str:
    mi = int(cfg("meow_sec"))
    pi = int(cfg("pishi_sec"))
    fi = int(cfg("fish_sec"))
    return (
        "⏳ **تـایـمـرهـای زنـده** ⏳\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🐱 **میو بعدی:** `{fmt_time(secs_left('meow', mi))}`\n"
        f"🐾 **پیشی بعدی:** `{fmt_time(secs_left('pishi', pi))}`\n"
        f"🎣 **ماهی بعدی:** `{fmt_time(secs_left('fishing', fi))}`\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

async def handle_command(event):
    raw = (event.message.text or "").strip()
    if not raw.startswith("/"):
        return
    parts = raw[1:].split(" ", 1)
    cmd   = parts[0].lower()
    rest  = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd in ("h", "help"):
            await event.edit(build_help()); return
        if cmd in ("s", "status"):
            await event.edit(build_status()); return
        if cmd in ("t", "timers"):
            await event.edit(build_timers()); return
        if cmd in KEYS:
            if not rest:
                await event.edit(f"❌ **خطا:** باید یک مقدار وارد کنید.\nمثال: `/{cmd} مقدار`"); return
            if cmd in NUMERIC_KEYS and not rest.isdigit():
                await event.edit(f"❌ **خطا:** مقدار `{cmd}` باید حتماً عدد باشد."); return
            
            cfg_set(cmd, rest)
            emoji = KEYS[cmd][0]
            await event.edit(f"✅ {emoji} تنظیمات با موفقیت ذخیره شد:\n`{cmd}` = `{rest}`")
            return
    except Exception as e:
        print(f"[!] خطا در ادیت پیام: {e}")

# ══════════════════════════════════════════════════
#  حلقه‌های اصلی
# ══════════════════════════════════════════════════

async def meow_loop():
    interval = int(cfg("meow_sec"))
    wait = secs_left("meow", interval)
    if wait > 0:
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
            print(f"[+] میو '{text}' ارسال شد.")
        await asyncio.sleep(interval)

async def pishi_loop():
    interval = int(cfg("pishi_sec"))
    wait = secs_left("pishi", interval)
    if wait > 0:
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
            print(f"[+] دستور پیشی ارسال شد | منتظر ربات مخصوص خودم...")

            msg = await wait_for_reply(active_group, sent.id, {PISHI_BUTTON_TEXT})
            if msg:
                sv = parse_stomach(msg.text or "")
                if sv is not None:
                    set_stomach(sv)
                for row in msg.buttons:
                    for b in row:
                        if PISHI_BUTTON_TEXT in b.text:
                            await b.click()
                            print(f"[+] روی '{b.text}' کلیک شد.")
                            break
            else:
                print("[!] دکمه پیشی در زمان مقرر پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا در حلقه پیشی: {e}")
        await asyncio.sleep(interval)

async def fishing_loop():
    interval = int(cfg("fish_sec"))
    wait = secs_left("fishing", interval)
    if wait > 0:
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
            print(f"[+] دستور ماهی ارسال شد | منتظر ربات مخصوص خودم...")

            msg = await wait_for_reply(active_group, sent.id, {SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON})
            if msg:
                stomach    = get_stomach()
                target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                
                clicked = False
                for row in msg.buttons:
                    for b in row:
                        if target_btn in b.text:
                            await b.click()
                            print(f"[+] کلیک روی '{target_btn}' انجام شد.")
                            clicked = True
                            break
                    if clicked: break
            else:
                print("[!] پیام ماهیگیری ربات پیدا نشد.")
        except Exception as e:
            print(f"[!] خطا در حلقه ماهیگیری: {e}")
        await asyncio.sleep(interval)

# ══════════════════════════════════════════════════
#  Rescue Listener (نجات پیشی با سرعت فوق‌العاده بالا)
# ══════════════════════════════════════════════════

async def fast_click(msg, text):
    try:
        for row in msg.buttons:
            for b in row:
                if text in b.text:
                    await b.click()
                    return True
    except:
        pass
    return False

async def rescue_listener():
    @client.on(events.NewMessage(chats=RESCUE_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.buttons: return
        
        btn_texts = {b.text.strip() for row in msg.buttons for b in row}
        if not any(RESCUE_BUTTON_TEXT in txt for txt in btn_texts): return
        
        sender = await msg.get_sender()
        if not is_bot(msg, sender): return

        print(f"[🚀] نجات پیشی ظاهر شد! کلیک سریع...")

        # ارسال سه درخواست کلیک موازی در صدم ثانیه برای تضمین برنده شدن
        await asyncio.gather(
            fast_click(msg, RESCUE_BUTTON_TEXT),
            fast_click(msg, RESCUE_BUTTON_TEXT),
            fast_click(msg, RESCUE_BUTTON_TEXT)
        )

        await asyncio.sleep(0.4)
        for _ in range(3):
            try:
                fresh = await client.get_messages(event.chat_id, ids=msg.id)
                if not fresh or not fresh.buttons: break
                
                cur = {b.text.strip() for row in fresh.buttons for b in row}
                if not any(RESCUE_BUTTON_TEXT in txt for txt in cur): break
                
                await fast_click(fresh, RESCUE_BUTTON_TEXT)
                await asyncio.sleep(0.4)
            except Exception:
                break

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
    global my_user_id
    init_db()
    await client.start()
    me = await client.get_me()
    my_user_id = me.id # ذخیره ایدی برای فیلتر کردن دقیق پیام‌های ربات
    print(f"[+] اکانت متصل شد: {me.first_name} (ID: {my_user_id})")
    print(f"[+] فیلتر اختصاصی فعال شد: ربات فقط به پیام‌های مربوط به شما پاسخ می‌دهد.")
    print(f"[+] آماده به کار - دستور /help را در تلگرام ارسال کنید.\n")

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
