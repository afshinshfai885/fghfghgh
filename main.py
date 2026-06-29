import asyncio
import random
import re
import sqlite3
import time
from telethon import TelegramClient, events
from telethon.errors import (PersistentTimestampOutdatedError, FloodWaitError,
                              ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)

# ══════════════════════════════════════════════════
#  تنظیمات اصلی سلف‌بات
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
SELL_FISH_BUTTON   = "فروش ماهی"        # بر اساس تایید شما روی همین مقدار تنظیم شد
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"
WAIT_FOR_BOT       = 25 
# ══════════════════════════════════════════════════

client        = TelegramClient(SESSION_NAME, API_ID, API_HASH)
active_group  = PRIMARY_GROUP
my_first_name = ""
my_username   = ""

# دیکشنری جهانی برای ردیابی آنی پاسخ‌های ربات در گپ‌های شلوغ
pending_responses = {}

# ══════════════════════════════════════════════════
#  بخش مدیریت دیتابیس (SQLite)
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
#  توابع پردازشی و کمکی هماهنگ با پیام‌های جدید
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
    """ استخراج فوق العاده دقیق سطح شکم از هر دو ساختار متنی جدید و قدیم ربات """
    # فیلتر اول: ساختار جدید پرانتزی مانند (6 / 10)
    m1 = re.search(r"شکم\s*:\s*.*?\(\s*(\d+)\s*/\s*\d+\s*\)", text)
    if m1:
        return int(m1.group(1))
    # فیلتر دوم: ساختار قدیمی با کدها و علامت بک‌تیک
    m2 = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    if m2:
        return int(m2.group(1))
    # فیلتر سوم: جستجوی عمومی در صورت وجود کلمه شکم
    m3 = re.search(r"(\d+)\s*/\s*\d+", text)
    if m3 and "شکم" in text:
        return int(m3.group(1))
    return None

async def wait_for_bot_response(chat_id: int, my_msg_id: int, timeout: int = WAIT_FOR_BOT):
    """ مکانیزم نوین مبتنی بر Future جهت دریافت آنی پیام بدون گم شدن در شلوغی گپ """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    
    key = (chat_id, my_msg_id)
    pending_responses[key] = fut
    
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_responses.pop(key, None)

# ══════════════════════════════════════════════════
#  بخش ساخت رابط کاربری حرفه‌ای پنل مدیریتی (Premium UI)
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
        "👑 **پـنـل مـدیـریـت پـیـشـرفته ربـات پـیـشـی** 👑\n"
        "✨ `UI ورژن جدید و ارتقا یافته سلف‌بات` ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 **مشاهده وضعیت سیستم:**\n"
        "🔹 `/s` ↤ نمایش وضعیت زنده و آمار شکم\n"
        "🔹 `/t` ↤ بررسی ثانیه‌شمار دقیق تایمرها\n\n"
        "⚙️ **تنظیم پارامترها (مقدار را جلوی دستور بنویسید):**\n"
        "🔸 `/meow_sec` ↤ زمان‌بندی ارسال میو خودکار\n"
        "🔸 `/meow_list` ↤ کلمات میو (جدا شده با کامای انگلیسی `,`)\n"
        "🔸 `/pishi_sec` ↤ چرخه زمانی ارسال دستور پیشی\n"
        "🔸 `/fish_sec` ↤ چرخه زمانی ارسال دستور ماهیگیری\n"
        "🔸 `/stomach` ↤ حداقل میزان شکم جهت تصمیم‌گیری تغذیه/فروش\n"
        "🔸 `/pishi_msg` ↤ متن ارسالی برای فراخوانی پروفایل پیشی\n"
        "🔸 `/fish_msg` ↤ متن ارسالی برای شروع ماهیگیری\n\n"
        "💡 **مثال‌های کاربردی:**\n"
        "▫️ `/meow_sec 240`\n"
        "▫️ `/stomach 7`\n"
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
        "🤖 **وضـعـیـت زنده و لـحـظـه‌ای ربـات**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏠 **شناسه گروه فعال:** `{active_group}`\n\n"
        "⏱ **تایمرهای فعال سیستم:**\n"
        f"🐱 **ارسال میو:** هر `{mi}s` ↤ ⏳ مانده: `{fmt_time(secs_left('meow', mi))}`\n"
        f"🐾 **فراخوانی پیشی:** هر `{pi}s` ↤ ⏳ مانده: `{fmt_time(secs_left('pishi', pi))}`\n"
        f"🎣 **دستور ماهی:** هر `{fi}s` ↤ ⏳ مانده: `{fmt_time(secs_left('fishing', fi))}`\n\n"
        "💬 **بانک کلمات میو:**\n"
        f"└ `{cfg('meow_list')}`\n\n"
        "🍖 **آنالیز وضعیت شکم پیشی:**\n"
        f"🔸 آستانه تعیین شده: `{threshold}`\n"
        f"🔸 شکم فعلی دیتابیس: `{stomach}`\n"
        f"🎯 تصمیم بعدی ماهیگیری: **{fish_action}**\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def build_timers() -> str:
    mi = int(cfg("meow_sec"))
    pi = int(cfg("pishi_sec"))
    fi = int(cfg("fish_sec"))
    return (
        "⏳ **ثانیه‌شمار زنده تایمرها** ⏳\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🐱 **ارسال میو بعدی:** `{fmt_time(secs_left('meow', mi))}`\n"
        f"🐾 **ارسال پیشی بعدی:** `{fmt_time(secs_left('pishi', pi))}`\n"
        f"🎣 **ارسال ماهی بعدی:** `{fmt_time(secs_left('fishing', fi))}`\n"
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
                await event.edit(f"⚠️ **مقدار وارد نشده است!**\nفرمت صحیح: `/{cmd} مقدار جدید`"); return
            if cmd in NUMERIC_KEYS and not rest.isdigit():
                await event.edit(f"❌ **خطای اعتبارسنجی:** مقدار پارامتر `{cmd}` الزاماً باید عدد باشد."); return
            
            cfg_set(cmd, rest)
            emoji = KEYS[cmd][0]
            await event.edit(f"✅ **{emoji} تنظیمات با موفقیت ذخیره شد:**\n`{cmd}` = `{rest}`")
            return
    except Exception as e:
        print(f"[!] خطا در ادیت خودکار دستور: {e}")

# ══════════════════════════════════════════════════
#  حلقه‌های اصلی خودکار اتوماسیون بازی
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
            print(f"[+] دستور پیشی ارسال شد | منتظر دریافت پاسخ اختصاصی...")

            msg = await wait_for_bot_response(active_group, sent.id, timeout=WAIT_FOR_BOT)
            if msg:
                sv = parse_stomach(msg.text or "")
                if sv is not None:
                    set_stomach(sv)
                    print(f"[i] سطح شکم با موفقیت به روزرسانی شد: {sv}")
                
                for row in msg.buttons:
                    for b in row:
                        if PISHI_BUTTON_TEXT in b.text:
                            await b.click()
                            print(f"[+] روی دکمه '{PISHI_BUTTON_TEXT}' کلیک شد.")
                            break
            else:
                print("[!] پیام ربات برای برداشت پوینت‌ها یافت نشد یا منقضی شد.")
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
            print(f"[+] دستور ماهی ارسال شد | منتظر پاسخ اختصاصی...")

            msg = await wait_for_bot_response(active_group, sent.id, timeout=WAIT_FOR_BOT)
            if msg:
                stomach    = get_stomach()
                target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                print(f"[i] وضعیت تصمیم‌گیری ماهیگیری: شکم={stomach} آستانه={threshold} -> دکمه هدف: {target_btn}")
                
                # خواندن خودکار هوشمند ارزش غذایی برای آپدیت در لحظه شکم دیتابیس
                nutritional_value = 0
                if target_btn == GIVE_TO_CAT_BUTTON:
                    m_nut = re.search(r"ارزش غذایی\s*:\s*(\d+)", msg.text or "")
                    if m_nut:
                        nutritional_value = int(m_nut.group(1))

                clicked = False
                for row in msg.buttons:
                    for b in row:
                        if target_btn in b.text:
                            await b.click()
                            print(f"[+] کلیک روی دکمه '{target_btn}' با موفقیت انجام شد.")
                            if target_btn == GIVE_TO_CAT_BUTTON and nutritional_value > 0:
                                set_stomach(stomach + nutritional_value)
                                print(f"[i] شکم به صورت محلی افزایش یافت: {stomach + nutritional_value}")
                            clicked = True
                            break
                    if clicked: break
            else:
                print("[!] پیام ماهیگیری ربات در زمان معین دریافت نشد.")
        except Exception as e:
            print(f"[!] خطا در حلقه ماهیگیری: {e}")
        await asyncio.sleep(interval)

# ══════════════════════════════════════════════════
#  شنود هوشمند و مرکزی پیام‌های ورودی گپ (Rescue & Router)
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

async def central_message_listener():
    """ هندلر مرکزی برای شکار سریع دکمه نجات و هدایت پاسخ‌ها بدون تاخیر زمان‌بندی """
    @client.on(events.NewMessage(chats=RESCUE_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.sender_id: return
        
        # تایید اصالت فرستنده (حتما ربات اصلی بازی باشد)
        sender = await msg.get_sender()
        if not is_bot(msg, sender): return

        # ۱. بخش واکنش فوق سریع به دکمه نجات پیشی خیابونی (بخش موازی صدم ثانیه‌ای)
        if msg.buttons:
            btn_texts = {b.text.strip() for row in msg.buttons for b in row}
            if any(RESCUE_BUTTON_TEXT in txt for txt in btn_texts):
                print(f"[🚀] نجات پیشی ظاهر شد! ارسال کلیک‌های موازی با حداکثر سرعت...")
                await asyncio.gather(
                    fast_click(msg, RESCUE_BUTTON_TEXT),
                    fast_click(msg, RESCUE_BUTTON_TEXT),
                    fast_click(msg, RESCUE_BUTTON_TEXT)
                )
                
                # بررسی ثانویه جهت اطمینان کامل از برداشته شدن دکمه نجات
                await asyncio.sleep(0.4)
                for _ in range(3):
                    try:
                        fresh = await client.get_messages(event.chat_id, ids=msg.id)
                        if not fresh or not fresh.buttons: break
                        cur = {b.text.strip() for row in fresh.buttons for b in row}
                        if not any(RESCUE_BUTTON_TEXT in txt for txt in cur): break
                        await fast_click(fresh, RESCUE_BUTTON_TEXT)
                        await asyncio.sleep(0.4)
                    except:
                        break
                return

        # ۲. ردیاب هوشمند حلقه پیشی و ماهیگیری بر اساس Reply ID یا منشن نام شما
        if msg.reply_to:
            rep_id = msg.reply_to.reply_to_msg_id
            key = (event.chat_id, rep_id)
            if key in pending_responses:
                fut = pending_responses[key]
                if not fut.done():
                    fut.set_result(msg)
                    return

        # فیلتر ثانویه بک‌آپ بر اساس نام و وجود دکمه‌های کنترلی بازی
        if msg.buttons:
            btn_texts = {b.text.strip() for row in msg.buttons for b in row}
            has_game_buttons = any(b in btn_texts for b in [PISHI_BUTTON_TEXT, SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON])
            if has_game_buttons:
                text_content = msg.text or ""
                if (my_first_name and my_first_name in text_content) or (my_username and my_username in text_content):
                    for k, fut in list(pending_responses.items()):
                        if k[0] == event.chat_id and not fut.done():
                            fut.set_result(msg)
                            return

    await client.run_until_disconnected()

# ══════════════════════════════════════════════════
#  شنود دستورات ارسالی خود کاربر (Command Listener)
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
#  تابع اصلی راه اندازی (Main)
# ══════════════════════════════════════════════════

async def main():
    global my_first_name, my_username
    init_db()
    await client.start()
    
    # دریافت مشخصات شما برای احراز هویت پیام‌ها در گپ شلوغ
    me = await client.get_me()
    my_first_name = me.first_name or ""
    my_username   = me.username or ""
    
    print(f"[+] سلف بات با موفقیت به اکانت متصل شد: {my_first_name}")
    print(f"[+] سیستم مانیتورینگ رویداد پیشرفته و زنده با موفقیت فعال گردید.")
    print(f"[+] آماده دریافت دستورات! دستور /help را ارسال نمایید.\n")

    await asyncio.gather(
        meow_loop(),
        pishi_loop(),
        fishing_loop(),
        central_message_listener(),
        command_listener(),
    )

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
