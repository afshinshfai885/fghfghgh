# -*- coding: utf-8 -*-
"""
Afshin Self — ربات سلف تلگرام (Telethon)
بازطراحی کامل: دیتابیس، منوی فارسی با نقطه، کنترل روشن/خاموش ماژول‌ها، لاگ حرفه‌ای.
"""

import asyncio
import logging
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, Iterator, Tuple

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon.errors import (
    PersistentTimestampOutdatedError,
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
)

# ══════════════════════════════════════════════════
#  لاگ‌گیری
# ══════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("afshin_self")


# ══════════════════════════════════════════════════
#  تنظیمات ثابت (غیر قابل تغییر از دیتابیس)
# ══════════════════════════════════════════════════
API_ID   = 22487790
API_HASH = "09c24af20084de9372cc92a760c74961"

SESSION_NAME = "my_account_session"
DB_FILE      = "data/timers.db"

TARGET_BOTS = {"MeowieQBot", "MeowieeQBot", "MeowieeeQBot", "MeowieQIVBot", "MeowieQVBot"}

RESCUE_BUTTON_TEXT = "نجات پیشی خیابونی 🐱"
PISHI_BUTTON_TEXT  = "برداشت میو پوینت ها"
SELL_FISH_BUTTON   = "فروش ماهی"
GIVE_TO_CAT_BUTTON = "بده پیشی بخوره"

# متن‌های ثابت پیام‌ها (دیگر در دیتابیس ذخیره نمی‌شوند)
PISHI_MSG_TEXT = "پیشی"
FISH_MSG_TEXT  = "ماهی"

WAIT_FOR_BOT = 20  # ثانیه، سقف انتظار برای پاسخ بات هدف

MENU_TRIGGER = ".سلف"

# مقادیر پیش‌فرض گروه‌ها (فقط برای اولین اجرا / ساخت دیتابیس)
DEFAULT_RESCUE_GROUPS = [-1003184246310, -1003180169065, -1004296149068]
DEFAULT_MEOW_GROUP    = -1003380347106
DEFAULT_FISH_GROUP    = -1003180169065
DEFAULT_PISHI_GROUP   = -1003180169065
DEFAULT_SMUGGLING_GROUP = -1003979242735
DEFAULT_FACTORY_GROUP   = -1003979242735

# متن‌های کلیدی سیستم قاچاق میویی / کارخونه میویی
SMUGGLE_TRIGGER = "قاچاق میویی"
FACTORY_TRIGGER = "کارخونه میویی"
PRISON_TRIGGER  = "زندان میویی"

SMUGGLE_START_TEXT = "شروع قاچاق پیشی"
SMUGGLE_FEE_TEXT    = "دریافت کارمزد"

FACTORY_PRODUCE_TEXT    = "تولید"
FACTORY_INPROGRESS_TEXT = "در حال تولید"
FACTORY_AIRPLANE_TEXT   = "تولیدی هواپیما"
FACTORY_START_TEXT      = "شروع تولید"
WAREHOUSE_TEXT          = "انبار"
SELL_PRODUCT_TEXT       = "فروش محصول"

# سقف‌ها و تاخیرهای ایمنی قاچاق/کارخونه
SMUGGLE_MAX_STEPS     = 40   # سقف تلاش داخلی هر سیکل — جلوگیری از حلقه بی‌نهایت
SMUGGLE_RETRY_DELAY   = 30   # ثانیه — تاخیر تلاش مجدد در صورت خطا/وضعیت ناشناخته
SMUGGLE_RESTART_DELAY = 5    # ثانیه — تاخیر کوتاه قبل از شروع مجدد بعد از زندان/دریافت کارمزد
FACTORY_RETRY_DELAY   = 60   # ثانیه — تاخیر تلاش مجدد کارخونه در صورت خطا
FACTORY_INITIAL_DELAY = 300  # ۵ دقیقه — فقط در اولین اجرای کاملاً تازه (بدون سابقه در دیتابیس)

# مقادیر پیش‌فرض تنظیمات عددی/متنی
DEFAULT_CONFIG = {
    "meow_sec":  "245",
    "meow_list": "میو,مع,معو,میو میو",
    "pishi_sec": "1480",
    "fish_sec":  "1500",
    "stomach":   "7",
    "smuggling_min":      "5",
    "smuggling_max":      "15",
    "min_sell_price":     "55",
    "smuggling_wait_sec": "1800",
    "factory_wait_sec":   "3600",
}

# مقادیر پیش‌فرض روشن/خاموش ماژول‌ها
DEFAULT_TOGGLES = {
    "self_enabled":    "1",
    "meow_enabled":    "1",
    "pishi_enabled":   "1",
    "fishing_enabled": "1",
    "rescue_enabled":  "1",
    "smuggling_enabled": "1",
    "factory_enabled":   "1",
}

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ══════════════════════════════════════════════════
#  سیستم بیدارباش فوری (Wake Events)
#  وقتی کاربر با دستور فارسی مقداری (فاصله زمانی/گروه) را تغییر می‌دهد،
#  حلقه‌ی مربوطه که ممکن است در وسط asyncio.sleep طولانی گیر کرده باشد
#  باید فوراً بیدار شود و دوباره از دیتابیس بخواند — بدون نیاز به ری‌استارت ربات.
# ══════════════════════════════════════════════════
WAKE_EVENTS: dict = {}


def get_wake_event(name: str) -> asyncio.Event:
    """گرفتن (یا ساخت) Event مربوط به یک حلقه، بر اساس نام."""
    ev = WAKE_EVENTS.get(name)
    if ev is None:
        ev = asyncio.Event()
        WAKE_EVENTS[name] = ev
    return ev


def wake_loop(name: str) -> None:
    """بیدار کردن فوری یک حلقه‌ی مشخص (مثلاً بعد از تغییر تنظیمات آن)."""
    get_wake_event(name).set()


def wake_loops(*names: str) -> None:
    for n in names:
        wake_loop(n)


async def sleep_or_wake(seconds: float, wake_name: str) -> None:
    """
    مثل asyncio.sleep ولی اگر در حین انتظار سیگنال «بیدارباش» برای wake_name
    ست شود، فوراً (بدون صبر تا پایان seconds) برمی‌گردد تا حلقه دوباره
    تنظیمات/گروه جدید را از دیتابیس بخواند.
    """
    if seconds <= 0:
        return
    ev = get_wake_event(wake_name)
    ev.clear()
    try:
        await asyncio.wait_for(ev.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        ev.clear()


# نگاشت: کلید دیتابیسی که با دستور فارسی تغییر می‌کند → نام(های) حلقه‌ای که باید بیدار شود
CONFIG_TO_LOOP = {
    "meow_sec":          ["meow"],
    "meow_list":         ["meow"],
    "pishi_sec":         ["pishi"],
    "fish_sec":          ["fishing"],
    "stomach":           ["fishing", "pishi"],
    "group_meow":        ["meow"],
    "group_pishi":       ["pishi"],
    "group_fish":        ["fishing"],
    "group_rescue":      ["rescue"],
    "smuggling_min":     ["smuggling"],
    "smuggling_max":     ["smuggling"],
    "min_sell_price":    ["factory_price"],
    "smuggling_group":   ["smuggling"],
    "factory_group":     ["factory", "factory_price"],
}

# نگاشت: کلید دستور روشن/خاموش فارسی → نام(های) حلقه‌ای که باید بیدار شود
TOGGLE_TO_LOOP = {
    "میو":       ["meow"],
    "پیشی":      ["pishi"],
    "ماهیگیری":  ["fishing"],
    "خیابونی":   ["rescue"],
    "قاچاق":     ["smuggling"],
    "کارخونه":   ["factory", "factory_price"],
}


# ══════════════════════════════════════════════════
#  لایه دیتابیس
# ══════════════════════════════════════════════════

@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    """کانتکست‌منیجر امن برای اتصال به دیتابیس — همیشه commit/close تضمین می‌شود."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except sqlite3.Error as e:
        log.error(f"[DB] خطای دیتابیس: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def table_count(table: str) -> int:
    try:
        with db_cursor() as c:
            c.execute(f"SELECT COUNT(*) FROM {table}")
            row = c.fetchone()
            return row[0] if row else 0
    except sqlite3.Error:
        return 0


def init_db() -> None:
    """ساخت جداول در صورت نبود، درج مقادیر پیش‌فرض، و چاپ لاگ کامل وضعیت دیتابیس."""
    log.info(f"[DB] مسیر دیتابیس: {DB_FILE}")
    try:
        with db_cursor() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS timers ("
                "key TEXT PRIMARY KEY, last_run REAL NOT NULL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS cat_stats ("
                "id INTEGER PRIMARY KEY CHECK(id=1), stomach INTEGER NOT NULL DEFAULT 0)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS config ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            c.execute("INSERT OR IGNORE INTO cat_stats (id, stomach) VALUES (1, 0)")

            # تنظیمات عددی/متنی پیش‌فرض
            for k, v in DEFAULT_CONFIG.items():
                c.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v)
                )

            # روشن/خاموش ماژول‌ها
            for k, v in DEFAULT_TOGGLES.items():
                c.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v)
                )

            # گروه‌ها
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("group_meow", str(DEFAULT_MEOW_GROUP)),
            )
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("group_pishi", str(DEFAULT_PISHI_GROUP)),
            )
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("group_fish", str(DEFAULT_FISH_GROUP)),
            )
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("group_rescue", ",".join(str(g) for g in DEFAULT_RESCUE_GROUPS)),
            )
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("smuggling_group", str(DEFAULT_SMUGGLING_GROUP)),
            )
            c.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                ("factory_group", str(DEFAULT_FACTORY_GROUP)),
            )

            # پاک‌سازی کلیدهای منسوخ (pishi_msg / fish_msg) طبق درخواست حذف کامل
            c.execute("DELETE FROM config WHERE key IN ('pishi_msg', 'fish_msg')")

        log.info("[DB] Connected")
        log.info(f"[DB] Config Loaded ({table_count('config')} رکورد)")
        log.info(f"[DB] Timers Loaded ({table_count('timers')} رکورد)")
        log.info(f"[DB] Cat Stats Loaded ({table_count('cat_stats')} رکورد)")
    except sqlite3.Error as e:
        log.error(f"[DB] خطای بحرانی در ساخت دیتابیس: {e}")
        raise SystemExit(1)


def cfg(key: str, default: str = "") -> str:
    """خواندن یک مقدار از جدول config. در صورت خطا یا نبود، مقدار پیش‌فرض برمی‌گردد."""
    try:
        with db_cursor() as c:
            c.execute("SELECT value FROM config WHERE key=?", (key,))
            row = c.fetchone()
            return row[0] if row else default
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در خواندن '{key}': {e}")
        return default


def cfg_set(key: str, value: str) -> None:
    try:
        with db_cursor() as c:
            c.execute(
                "INSERT INTO config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        log.info(f"[CFG] {key} => {value}")
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در ذخیره '{key}': {e}")


def cfg_int(key: str, default: int = 0) -> int:
    raw = cfg(key, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        log.error(f"[DB] مقدار خراب برای '{key}'='{raw}' — استفاده از پیش‌فرض {default}")
        return default


def cfg_bool(key: str, default: bool = True) -> bool:
    return cfg(key, "1" if default else "0") == "1"


def cfg_bool_set(key: str, value: bool) -> None:
    cfg_set(key, "1" if value else "0")


def get_group(key: str, default: int) -> int:
    raw = cfg(key, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        log.error(f"[DB] آیدی گروه خراب برای '{key}'='{raw}' — استفاده از پیش‌فرض {default}")
        return default


def get_group_list(key: str, default: list) -> list:
    raw = cfg(key, ",".join(str(g) for g in default))
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            log.error(f"[DB] آیدی نامعتبر در '{key}': '{part}' — نادیده گرفته شد")
    return result or default


def get_last_run(key: str) -> float:
    try:
        with db_cursor() as c:
            c.execute("SELECT last_run FROM timers WHERE key=?", (key,))
            row = c.fetchone()
            return row[0] if row else 0.0
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در خواندن تایمر '{key}': {e}")
        return 0.0


def set_last_run(key: str, ts: float) -> None:
    try:
        with db_cursor() as c:
            c.execute(
                "INSERT INTO timers (key, last_run) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET last_run=excluded.last_run",
                (key, ts),
            )
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در ذخیره تایمر '{key}': {e}")


def get_stomach() -> int:
    try:
        with db_cursor() as c:
            c.execute("SELECT stomach FROM cat_stats WHERE id=1")
            row = c.fetchone()
            return row[0] if row else 0
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در خواندن شکم: {e}")
        return 0


def set_stomach(v: int) -> None:
    try:
        with db_cursor() as c:
            c.execute("UPDATE cat_stats SET stomach=? WHERE id=1", (v,))
    except sqlite3.Error as e:
        log.error(f"[DB] خطا در ذخیره شکم: {e}")


def secs_left(key: str, interval: int) -> float:
    last = get_last_run(key)
    return 0.0 if last == 0.0 else max(0.0, interval - (time.time() - last))


def fmt_time(s: float) -> str:
    s = int(s)
    if s <= 0:
        return "همین الان ✅"
    if s < 60:
        return f"{s} ثانیه"
    if s < 3600:
        return f"{s // 60} دقیقه و {s % 60} ثانیه"
    return f"{s // 3600} ساعت و {(s % 3600) // 60} دقیقه"


def onoff(flag: bool) -> str:
    return "🟢 روشن" if flag else "🔴 خاموش"


# ══════════════════════════════════════════════════
#  کش نام گروه‌ها (برای نمایش در وضعیت به‌جای فقط آیدی خام)
# ══════════════════════════════════════════════════
_GROUP_NAME_CACHE: dict = {}          # {group_id: (name, fetched_at)}
GROUP_NAME_CACHE_TTL = 300            # ثانیه — کش برای ۵ دقیقه معتبر است


async def get_group_name(gid: int) -> str:
    """
    نام (تایتل) گروه/کانال با آیدی gid را برمی‌گرداند.
    نتیجه به مدت GROUP_NAME_CACHE_TTL کش می‌شود تا هر بار درخواست‌های
    غیرضروری به تلگرام زده نشود. در صورت خطا، خودِ آیدی به‌عنوان نام برگردانده می‌شود.
    """
    now = time.time()
    cached = _GROUP_NAME_CACHE.get(gid)
    if cached and (now - cached[1] < GROUP_NAME_CACHE_TTL):
        return cached[0]
    try:
        entity = await client.get_entity(gid)
        name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(gid)
    except Exception as e:
        log.warning(f"[SYSTEM] گرفتن نام گروه {gid} ناموفق: {e}")
        name = str(gid)
    _GROUP_NAME_CACHE[gid] = (name, now)
    return name


async def fmt_group(gid: int) -> str:
    """قالب نمایشی «نام (آیدی)» برای یک گروه."""
    name = await get_group_name(gid)
    return f"{name} ({gid})"


async def fmt_group_list(gids: list) -> str:
    """قالب نمایشی چندخطی «نام (آیدی)» برای لیستی از گروه‌ها."""
    if not gids:
        return "— هیچ گروهی تنظیم نشده —"
    lines = []
    for gid in gids:
        name = await get_group_name(gid)
        lines.append(f"  • {name} ({gid})")
    return "\n".join(lines)


# ══════════════════════════════════════════════════
#  توابع کمکی ارسال / انتظار پاسخ
# ══════════════════════════════════════════════════

BLOCKED = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError)


async def safe_send(gid: int, text: str, retries: int = 3) -> Optional[Message]:
    for attempt in range(retries):
        try:
            msg = await client.send_message(gid, text)
            return msg
        except BLOCKED as e:
            log.warning(f"[SYSTEM] بلاک از گروه {gid}: {type(e).__name__}")
            return None
        except FloodWaitError as e:
            log.warning(f"[SYSTEM] FloodWait {e.seconds}s")
            await asyncio.sleep(e.seconds + 5)
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(10 * (attempt + 1))
        except Exception as e:
            log.error(f"[SYSTEM] خطا در ارسال پیام: {e}")
            await asyncio.sleep(5)
    return None


def is_bot(msg: Message, sender) -> bool:
    """
    True اگر فرستنده یکی از بات‌های آینه (TARGET_BOTS) باشد — چون این بازی چند بات
    مشابه در گروه‌های مختلف دارد و هرکدام که در آن گروه فعال باشد باید شناسایی شود.
    """
    uname = getattr(sender, "username", None)
    return bool(uname) and uname in TARGET_BOTS


def parse_stomach(text: str) -> Optional[int]:
    m = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════
#  پارسرهای سیستم قاچاق میویی / کارخونه میویی
# ══════════════════════════════════════════════════

DURATION_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")


def _normalize(text: Optional[str]) -> str:
    """حذف نیم‌فاصله برای ساده‌ترشدن تطبیق عبارات فارسی."""
    return (text or "").replace("\u200c", " ")


def parse_street_cats(text: str) -> Optional[int]:
    """🐈 شما XXX پیشی خیابونی دارید"""
    m = re.search(r"شما\s+(\d+)\s+پیشی\s+خیابونی\s+دارید", _normalize(text))
    return int(m.group(1)) if m else None


def parse_smuggle_count(text: str) -> Optional[Tuple[int, int]]:
    """✨ تعداد پیشی های قاچاقی : X / 15  →  (X, 15)"""
    m = re.search(r"تعداد\s*پیشی\s*های\s*قاچاقی\s*:\s*(\d+)\s*/\s*(\d+)", _normalize(text))
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_duration(text: str) -> Optional[int]:
    """استخراج زمان HH:MM:SS از متن (زمان مورد نیاز قاچاق/کارخونه) و تبدیل آن به ثانیه."""
    m = DURATION_RE.search(_normalize(text))
    if not m:
        return None
    h, mn, s = (int(x) for x in m.groups())
    return h * 3600 + mn * 60 + s


def parse_market_price(text: str) -> Optional[int]:
    """🛍 قیمت بازار: XX"""
    m = re.search(r"قیمت\s*بازار\D{0,10}(\d+)", _normalize(text))
    return int(m.group(1)) if m else None


def is_arrested(text: str) -> bool:
    """🚨 شما به جرم قاچاق ..."""
    return "به جرم قاچاق" in _normalize(text)


def is_smuggle_success(text: str) -> bool:
    """🐈 قاچاق پیشی ها با موفقیت انجام شد 🎉 (بدون دستگیری)"""
    t = _normalize(text)
    return "با موفقیت انجام شد" in t and "قاچاق" in t


def is_fine_paid(text: str) -> bool:
    """🧑‍⚖️ شما با موفقیت جریمه خود را پرداخت کردید"""
    t = _normalize(text)
    return "جریمه" in t and "پرداخت" in t and "موفقیت" in t


async def wait_for_reply(
    gid: int, my_msg_id: int, has_buttons: set, timeout: int = WAIT_FOR_BOT
) -> Optional[Message]:
    """
    منتظر پیام جداگانه‌ای از TARGET_BOT می‌ماند که reply_to آن برابر my_msg_id باشد
    (به‌جای گشتن دکمه روی پیام ارسالی خودمان).
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
            log.error(f"[SYSTEM] خطا در wait_for_reply: {e}")
            await asyncio.sleep(2)
    return None


async def wait_for_bot_message(gid: int, my_msg_id: int, timeout: int = WAIT_FOR_BOT) -> Optional[Message]:
    """
    نسخه‌ی عمومی‌تر wait_for_reply — بدون فیلتر بر اساس متن دکمه.
    برای قاچاق/کارخونه لازم است چون خیلی از دکمه‌ها متن ندارند.
    منتظر هر پیامی از TARGET_BOT می‌ماند که reply آن my_msg_id باشد.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1)
        try:
            async for msg in client.iter_messages(gid, limit=10):
                if not msg.sender_id:
                    continue
                if not msg.reply_to or msg.reply_to.reply_to_msg_id != my_msg_id:
                    continue
                sender = await msg.get_sender()
                if not is_bot(msg, sender):
                    continue
                return msg
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"[SYSTEM] خطا در wait_for_bot_message: {e}")
            await asyncio.sleep(2)
    return None


async def refresh_message(chat_id: int, msg_id: int, tries: int = 6, delay: float = 0.7) -> Optional[Message]:
    """
    خواندن نسخه‌ی به‌روزشده‌ی پیام از سرور بعد از کلیک روی دکمه
    (چون click() خودِ پیام ادیت‌شده را برنمی‌گرداند).
    """
    for _ in range(tries):
        await asyncio.sleep(delay)
        try:
            fresh = await client.get_messages(chat_id, ids=msg_id)
            if fresh:
                return fresh
        except PersistentTimestampOutdatedError:
            await asyncio.sleep(2)
        except Exception as e:
            log.warning(f"[SYSTEM] خطا در refresh_message: {e}")
    return None


def get_button(msg: Message, row: Optional[int] = None, col: Optional[int] = None,
                text: Optional[str] = None):
    """پیدا کردن آبجکت دکمه از msg.buttons — بر اساس (row, col) یا بر اساس متن. هرگز crash نمی‌کند."""
    if not msg.buttons:
        return None
    if row is not None and col is not None:
        try:
            return msg.buttons[row][col]
        except (IndexError, TypeError):
            return None
    if text is not None:
        try:
            for r in msg.buttons:
                for b in r:
                    if (getattr(b, "text", "") or "").strip() == text:
                        return b
        except Exception:
            return None
    return None


async def raw_click(msg: Message, button) -> bool:
    """
    ارسال مستقیم Callback Query (Direct Callback Query Submission / Injecting Callback Data):
    داده مخفی (data) خودِ دکمه مستقیماً استخراج و به تلگرام ارسال می‌شود — دقیقاً همان
    درخواستی که خود تلگرام هنگام لمس دکمه می‌فرستد. چون این روش فقط به peer گروه نیاز
    دارد (نه resolve دقیق کدام بات)، در گروه‌هایی که چند بات مختلف دارند و msg.click
    معمولی خطا می‌دهد/کار نمی‌کند، پایدار باقی می‌ماند.
    """
    if button is None:
        return False
    try:
        data = button.data
    except AttributeError:
        data = None
    if not data:
        return False
    try:
        chat = await msg.get_input_chat()
        await client(GetBotCallbackAnswerRequest(peer=chat, msg_id=msg.id, data=data))
        return True
    except Exception as e:
        log.warning(f"[BUTTON] کلیک مستقیم (callback data) ناموفق: {e}")
        return False


async def click_button(msg: Message, row: int, col: int, fallback_text: Optional[str] = None) -> bool:
    """
    کلیک ایمن روی دکمه اینلاین با روش Callback Data مستقیم:
    ۱) همیشه اول تلاش با ایندکس (row, col)
    ۲) اگر ناموفق بود و fallback_text داده شده بود، تلاش با متن دکمه
    ۳) اگر هر دو ناموفق بودند، فقط لاگ می‌شود — هیچ خطایی اجرای ربات را متوقف نمی‌کند
    """
    btn = get_button(msg, row=row, col=col)
    if await raw_click(msg, btn):
        return True

    if fallback_text:
        btn = get_button(msg, text=fallback_text)
        if await raw_click(msg, btn):
            return True
        log.warning(f"[BUTTON] کلیک ایندکس ({row},{col}) و متن '{fallback_text}' هر دو ناموفق.")
        return False

    log.warning(f"[BUTTON] کلیک ایندکس ({row},{col}) ناموفق (fallback متنی موجود نیست).")
    return False


async def click_by_text(msg: Message, text: str) -> bool:
    """کلیک ایمن فقط با متن دکمه — با همان روش Callback Data مستقیم."""
    btn = get_button(msg, text=text)
    if await raw_click(msg, btn):
        return True
    log.warning(f"[BUTTON] کلیک متنی '{text}' ناموفق.")
    return False


def _first_button_text(msg: Message) -> str:
    """متن دکمه (0,0) در صورت وجود، وگرنه رشته خالی — هرگز crash نمی‌کند."""
    try:
        if msg.buttons and msg.buttons[0]:
            return (msg.buttons[0][0].text or "").strip()
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════
#  منوی سلف
# ══════════════════════════════════════════════════

def build_menu() -> str:
    return (
        "✨ دستیار هوشمند پیشی افشین سلف ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 وضعیت و مانیتورینگ\n\n"
        "▫️ .وضعیت\n"
        "نمایش وضعیت کامل ربات\n\n"
        "▫️ .تایمر\n"
        "نمایش تایمرهای فعال\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚙️ تنظیمات پیشرفته\n\n"
        "▫️ .میو [ثانیه]\n"
        "فاصله زمانی ارسال میو\n\n"
        "▫️ .پیشی [ثانیه]\n"
        "فاصله زمانی دریافت میوپوینت\n\n"
        "▫️ .ماهی [ثانیه]\n"
        "فاصله زمانی ماهیگیری\n\n"
        "▫️ .شکم [عدد]\n"
        "حداقل میزان شکم برای تصمیم‌گیری خودکار\n\n"
        "▫️ .میولیست [متن]\n"
        "لیست میوها با کاما جدا شود\n\n"
        "▫️ .گروه_میو [آیدی]\n"
        "گروه ارسال میو\n\n"
        "▫️ .گروه_پیشی [آیدی]\n"
        "گروه دریافت میوپوینت\n\n"
        "▫️ .گروه_ماهی [آیدی]\n"
        "گروه ماهیگیری\n\n"
        "▫️ .گروه_خیابونی [آیدی‌ها]\n"
        "چند گروه با کاما جدا شوند\n\n"
        "▫️ .حداقل_قاچاق [عدد]\n"
        "حداقل تعداد پیشی در هر سیکل قاچاق\n\n"
        "▫️ .حداکثر_قاچاق [عدد]\n"
        "حداکثر تعداد پیشی در هر سیکل قاچاق\n\n"
        "▫️ .حداقل_قیمت_فروش [عدد]\n"
        "حداقل قیمت بازار برای فروش خودکار محصول کارخونه\n\n"
        "▫️ .گروه_قاچاق [آیدی]\n"
        "گروه اختصاصی قاچاق میویی\n\n"
        "▫️ .گروه_کارخونه [آیدی]\n"
        "گروه اختصاصی کارخونه میویی\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔌 کنترل ماژول‌ها\n\n"
        "▫️ .سلف روشن   ▫️ .سلف خاموش\n"
        "▫️ .میو روشن   ▫️ .میو خاموش\n"
        "▫️ .پیشی روشن   ▫️ .پیشی خاموش\n"
        "▫️ .ماهیگیری روشن   ▫️ .ماهیگیری خاموش\n"
        "▫️ .خیابونی روشن   ▫️ .خیابونی خاموش\n"
        "▫️ .قاچاق روشن   ▫️ .قاچاق خاموش\n"
        "▫️ .کارخونه روشن   ▫️ .کارخونه خاموش\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 نمونه استفاده\n\n"
        ".میو 340\n"
        ".پیشی 1500\n"
        ".شکم 7\n"
        ".گروه_میو -1001234567890\n"
        ".حداقل_قاچاق 5\n"
        ".حداکثر_قاچاق 15\n"
        ".حداقل_قیمت_فروش 55\n"
        ".گروه_قاچاق -1001234567890\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 سیستم هوشمند ماهیگیری\n\n"
        "اگر مقدار شکم کمتر از حد تعیین‌شده باشد، ماهی به گربه داده می‌شود؛ "
        "در غیر این صورت به‌صورت خودکار فروخته خواهد شد."
    )


async def build_status() -> str:
    mi = cfg_int("meow_sec")
    pi = cfg_int("pishi_sec")
    fi = cfg_int("fish_sec")
    threshold = cfg_int("stomach")
    stomach = get_stomach()

    g_meow   = get_group("group_meow", DEFAULT_MEOW_GROUP)
    g_pishi  = get_group("group_pishi", DEFAULT_PISHI_GROUP)
    g_fish   = get_group("group_fish", DEFAULT_FISH_GROUP)
    g_rescue = get_group_list("group_rescue", DEFAULT_RESCUE_GROUPS)
    g_smuggle = get_group("smuggling_group", DEFAULT_SMUGGLING_GROUP)
    g_factory = get_group("factory_group", DEFAULT_FACTORY_GROUP)

    # نام گروه‌ها را موازی از تلگرام می‌گیریم تا سریع‌تر باشد
    name_meow, name_pishi, name_fish, name_smuggle, name_factory = await asyncio.gather(
        fmt_group(g_meow),
        fmt_group(g_pishi),
        fmt_group(g_fish),
        fmt_group(g_smuggle),
        fmt_group(g_factory),
    )
    rescue_list_str = await fmt_group_list(g_rescue)

    smuggling_wait = cfg_int("smuggling_wait_sec", 1800)
    factory_wait   = cfg_int("factory_wait_sec", 3600)

    return (
        "🤖 وضعیت کامل ربات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"سلف: {onoff(cfg_bool('self_enabled'))}\n"
        f"میو: {onoff(cfg_bool('meow_enabled'))}\n"
        f"پیشی: {onoff(cfg_bool('pishi_enabled'))}\n"
        f"ماهیگیری: {onoff(cfg_bool('fishing_enabled'))}\n"
        f"خیابونی: {onoff(cfg_bool('rescue_enabled'))}\n"
        f"قاچاق: {onoff(cfg_bool('smuggling_enabled'))}\n"
        f"کارخونه: {onoff(cfg_bool('factory_enabled'))}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🍖 شکم فعلی: {stomach}\n"
        f"🎯 آستانه شکم: {threshold}\n\n"
        f"🐱 گروه میو: {name_meow}\n"
        f"🐾 گروه پیشی: {name_pishi}\n"
        f"🎣 گروه ماهیگیری: {name_fish}\n"
        f"🏘 گروه‌های خیابونی ({len(g_rescue)} گروه):\n{rescue_list_str}\n"
        f"📦 گروه قاچاق: {name_smuggle}\n"
        f"🏭 گروه کارخونه: {name_factory}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 حداقل قاچاق: {cfg_int('smuggling_min')}\n"
        f"🔢 حداکثر قاچاق: {cfg_int('smuggling_max')}\n"
        f"💰 حداقل قیمت فروش: {cfg_int('min_sell_price')}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱ میو (هر {mi} ثانیه)\n └─ مانده: {fmt_time(secs_left('meow', mi))}\n\n"
        f"⏱ پیشی (هر {pi} ثانیه)\n └─ مانده: {fmt_time(secs_left('pishi', pi))}\n\n"
        f"⏱ ماهیگیری (هر {fi} ثانیه)\n └─ مانده: {fmt_time(secs_left('fishing', fi))}\n\n"
        f"⏱ قاچاق\n └─ مانده: {fmt_time(secs_left('smuggling', smuggling_wait))}\n\n"
        f"⏱ تولید کارخونه\n └─ مانده: {fmt_time(secs_left('factory', factory_wait))}"
    )


def build_timers() -> str:
    mi = cfg_int("meow_sec")
    pi = cfg_int("pishi_sec")
    fi = cfg_int("fish_sec")
    si = cfg_int("smuggling_wait_sec", 1800)
    ki = cfg_int("factory_wait_sec", 3600)
    return (
        "⏳ تایمرهای فعال سیستم ⏳\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🐱 ارسال میو بعدی:\n └─ {fmt_time(secs_left('meow', mi))}\n\n"
        f"🐾 ارسال پیشی بعدی:\n └─ {fmt_time(secs_left('pishi', pi))}\n\n"
        f"🎣 ارسال ماهی بعدی:\n └─ {fmt_time(secs_left('fishing', fi))}\n\n"
        f"📦 سیکل بعدی قاچاق:\n └─ {fmt_time(secs_left('smuggling', si))}\n\n"
        f"🏭 سیکل بعدی کارخونه:\n └─ {fmt_time(secs_left('factory', ki))}"
    )


# ══════════════════════════════════════════════════
#  پارس دستورات فارسی (پنل کنترل درون-تلگرامی)
# ══════════════════════════════════════════════════

# دستورهای مقداردهی عددی/متنی: کلید فارسی → (کلید دیتابیس، نوع، برچسب نمایشی)
SETTER_COMMANDS = {
    "میو":            ("meow_sec", "int", "فاصله ارسال میو"),
    "پیشی":           ("pishi_sec", "int", "فاصله دریافت میوپوینت"),
    "ماهی":           ("fish_sec", "int", "فاصله ماهیگیری"),
    "شکم":            ("stomach", "int", "آستانه شکم"),
    "میولیست":        ("meow_list", "str", "لیست میوها"),
    "گروه_میو":       ("group_meow", "group", "گروه میو"),
    "گروه_پیشی":      ("group_pishi", "group", "گروه پیشی"),
    "گروه_ماهی":      ("group_fish", "group", "گروه ماهیگیری"),
    "گروه_خیابونی":   ("group_rescue", "group_list", "گروه‌های خیابونی"),
    "حداقل_قاچاق":     ("smuggling_min", "int", "حداقل تعداد قاچاق"),
    "حداکثر_قاچاق":    ("smuggling_max", "int", "حداکثر تعداد قاچاق"),
    "حداقل_قیمت_فروش": ("min_sell_price", "int", "حداقل قیمت فروش"),
    "گروه_قاچاق":      ("smuggling_group", "group", "گروه قاچاق"),
    "گروه_کارخونه":    ("factory_group", "group", "گروه کارخونه"),
}

# دستورهای روشن/خاموش: کلید فارسی → کلید دیتابیس
TOGGLE_COMMANDS = {
    "سلف":       "self_enabled",
    "میو":       "meow_enabled",
    "پیشی":      "pishi_enabled",
    "ماهیگیری":  "fishing_enabled",
    "خیابونی":   "rescue_enabled",
    "قاچاق":     "smuggling_enabled",
    "کارخونه":   "factory_enabled",
}


async def handle_command(event) -> None:
    raw = (event.message.text or "").strip()

    if raw == MENU_TRIGGER:
        try:
            await event.edit(build_menu())
        except Exception as e:
            log.error(f"[SYSTEM] خطا در نمایش منو: {e}")
        return

    if not raw.startswith("."):
        return

    parts = raw[1:].split(" ", 1)
    cmd = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "وضعیت":
            await event.edit(await build_status()); return
        if cmd == "تایمر":
            await event.edit(build_timers()); return

        # روشن / خاموش کردن ماژول‌ها: مثل ".میو روشن" یا ".میو خاموش"
        if rest in ("روشن", "خاموش") and cmd in TOGGLE_COMMANDS:
            db_key = TOGGLE_COMMANDS[cmd]
            new_val = rest == "روشن"
            cfg_bool_set(db_key, new_val)
            # بیدار کردن فوری حلقه‌ی مربوطه تا بدون ری‌استارت اعمال شود
            loop_names = TOGGLE_TO_LOOP.get(cmd, [])
            wake_loops(*loop_names)
            await event.edit(f"✅ {cmd} {onoff(new_val)} شد.")
            return

        # مقداردهی تنظیمات
        if cmd in SETTER_COMMANDS:
            db_key, kind, label = SETTER_COMMANDS[cmd]
            if not rest:
                await event.edit(f"❌ باید یک مقدار وارد کنید.\nمثال: .{cmd} مقدار")
                return

            if kind == "int":
                if not rest.isdigit():
                    await event.edit(f"❌ «{cmd}» فقط عدد می‌پذیرد.")
                    return
                cfg_set(db_key, rest)

            elif kind == "str":
                cfg_set(db_key, rest)

            elif kind == "group":
                cleaned = rest.strip()
                try:
                    int(cleaned)
                except ValueError:
                    await event.edit(f"❌ «{cmd}» باید یک آیدی گروه معتبر (عدد) باشد.")
                    return
                cfg_set(db_key, cleaned)

            elif kind == "group_list":
                ids = [p.strip() for p in rest.split(",") if p.strip()]
                bad = [p for p in ids if not _is_int(p)]
                if bad or not ids:
                    await event.edit("❌ فرمت آیدی‌ها نامعتبر است. با کاما جدا کنید.")
                    return
                cfg_set(db_key, ",".join(ids))

            # بیدار کردن فوری همه‌ی حلقه‌های وابسته به این تنظیم — بدون نیاز به ری‌استارت
            wake_loops(*CONFIG_TO_LOOP.get(db_key, []))

            await event.edit(f"✅ {label} به «{rest}» تغییر یافت و ذخیره شد.")
            return

        await event.edit(f"❓ دستور نامعتبر است.\nبرای راهنما {MENU_TRIGGER} را ارسال کنید.")
    except Exception as e:
        log.error(f"[SYSTEM] خطا در پردازش دستور '{raw}': {e}")


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


# ══════════════════════════════════════════════════
#  حلقه‌های اصلی
# ══════════════════════════════════════════════════

async def meow_loop() -> None:
    interval = cfg_int("meow_sec", 245)
    wait = secs_left("meow", interval)
    if wait > 0:
        log.info(f"[MEOW] {fmt_time(wait)} تا اجرای بعدی مانده")
        await sleep_or_wake(wait, "meow")

    while True:
        if not cfg_bool("meow_enabled"):
            await sleep_or_wake(5, "meow")
            continue

        interval = cfg_int("meow_sec", 245)

        # اگر هنوز به موعد ارسال نرسیده (مثلاً فاصله زمانی تازه تغییر کرده)، صبر می‌کنیم
        # ولی این صبر با wake_loop("meow") قابل قطع فوری است.
        wait = secs_left("meow", interval)
        if wait > 0:
            await sleep_or_wake(wait, "meow")
            continue

        choices = [x.strip() for x in cfg("meow_list", DEFAULT_CONFIG["meow_list"]).split(",") if x.strip()]
        if not choices:
            log.error("[MEOW] لیست میو خالی است — رد شد")
            await sleep_or_wake(interval, "meow")
            continue

        text = random.choice(choices)
        target = get_group("group_meow", DEFAULT_MEOW_GROUP)

        sent = await safe_send(target, text)
        if sent:
            set_last_run("meow", time.time())
            log.info(f"[MEOW] Sent Successfully → '{text}' → {target}")
        else:
            log.warning(f"[MEOW] ارسال ناموفق به گروه {target}")

        interval = cfg_int("meow_sec", 245)
        await sleep_or_wake(interval, "meow")


async def pishi_loop() -> None:
    interval = cfg_int("pishi_sec", 1480)
    wait = secs_left("pishi", interval)
    if wait > 0:
        log.info(f"[PISHI] {fmt_time(wait)} تا اجرای بعدی مانده")
        await sleep_or_wake(wait, "pishi")

    while True:
        if not cfg_bool("pishi_enabled"):
            await sleep_or_wake(5, "pishi")
            continue

        interval = cfg_int("pishi_sec", 1480)
        wait = secs_left("pishi", interval)
        if wait > 0:
            await sleep_or_wake(wait, "pishi")
            continue

        target = get_group("group_pishi", DEFAULT_PISHI_GROUP)

        try:
            sent = await safe_send(target, PISHI_MSG_TEXT)
            if not sent:
                log.warning(f"[PISHI] ارسال ناموفق به گروه {target}")
                await sleep_or_wake(interval, "pishi")
                continue

            set_last_run("pishi", time.time())
            log.info(f"[PISHI] پیام ارسال شد → {target} | منتظر پاسخ بات...")

            msg = await wait_for_reply(target, sent.id, {PISHI_BUTTON_TEXT})
            if msg:
                sv = parse_stomach(msg.text or "")
                if sv is not None:
                    set_stomach(sv)
                    log.info(f"[PISHI] شکم به‌روزرسانی شد: {sv}")
                await click_by_text(msg, PISHI_BUTTON_TEXT)
                log.info("[PISHI] Button Clicked")
            else:
                log.warning("[PISHI] دکمه پاسخ پیدا نشد.")
        except Exception as e:
            log.error(f"[PISHI] خطا: {e}")

        interval = cfg_int("pishi_sec", 1480)
        await sleep_or_wake(interval, "pishi")


async def fishing_loop() -> None:
    interval = cfg_int("fish_sec", 1500)
    wait = secs_left("fishing", interval)
    if wait > 0:
        log.info(f"[FISH] {fmt_time(wait)} تا اجرای بعدی مانده")
        await sleep_or_wake(wait, "fishing")

    while True:
        if not cfg_bool("fishing_enabled"):
            await sleep_or_wake(5, "fishing")
            continue

        interval = cfg_int("fish_sec", 1500)
        wait = secs_left("fishing", interval)
        if wait > 0:
            await sleep_or_wake(wait, "fishing")
            continue

        threshold = cfg_int("stomach", 7)
        target = get_group("group_fish", DEFAULT_FISH_GROUP)

        try:
            sent = await safe_send(target, FISH_MSG_TEXT)
            if not sent:
                log.warning(f"[FISH] ارسال ناموفق به گروه {target}")
                await sleep_or_wake(interval, "fishing")
                continue

            set_last_run("fishing", time.time())
            log.info(f"[FISH] پیام ارسال شد → {target} (id={sent.id}) | منتظر پاسخ بات...")

            msg = await wait_for_reply(target, sent.id, {SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON})
            if msg:
                stomach = get_stomach()
                target_btn = GIVE_TO_CAT_BUTTON if stomach < threshold else SELL_FISH_BUTTON
                log.info(f"[FISH] شکم={stomach} آستانه={threshold} → '{target_btn}'")
                await click_by_text(msg, target_btn)
                if target_btn == SELL_FISH_BUTTON:
                    log.info("[FISH] Fish Sold")
                else:
                    log.info("[FISH] Fish Given To Cat")
            else:
                log.warning("[FISH] پیام پاسخ پیدا نشد.")
        except Exception as e:
            log.error(f"[FISH] خطا: {e}")

        interval = cfg_int("fish_sec", 1500)
        await sleep_or_wake(interval, "fishing")


# ══════════════════════════════════════════════════
#  سیستم قاچاق میویی (loop دائمی)
# ══════════════════════════════════════════════════

async def smuggling_cycle() -> str:
    """
    یک سیکل کامل قاچاق میویی.
    خروجی:
      "started" → سیکل با موفقیت شروع شد؛ باید به مدت زمان استخراج‌شده صبر کرد
      "restart" → زندان/دریافت کارمزد resolve شد؛ باید بلافاصله دوباره شروع شود
      "retry"   → خطا یا وضعیت ناشناخته؛ تلاش مجدد بعد از تاخیر کوتاه
    """
    group = get_group("smuggling_group", DEFAULT_SMUGGLING_GROUP)

    sent = await safe_send(group, SMUGGLE_TRIGGER)
    if not sent:
        log.warning(f"[SMUGGLE] ارسال «{SMUGGLE_TRIGGER}» به گروه {group} ناموفق بود.")
        return "retry"

    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[SMUGGLE] پاسخی از بات دریافت نشد.")
        return "retry"

    smug_min = cfg_int("smuggling_min", 5)
    smug_max = cfg_int("smuggling_max", 15)
    target_count = random.randint(smug_min, max(smug_min, smug_max))
    last_wait: Optional[int] = None

    for _ in range(SMUGGLE_MAX_STEPS):
        text = msg.text or ""

        # ۱) دستگیری
        if is_arrested(text):
            log.info("[SMUGGLE] دستگیر شدیم — ورود به فرآیند زندان/جریمه.")
            await handle_prison(group)
            return "restart"

        # ۲) موفقیت بدون دستگیری → دریافت کارمزد
        if is_smuggle_success(text):
            await click_button(msg, 0, 0, fallback_text=SMUGGLE_FEE_TEXT)
            log.info("[SMUGGLE] کارمزد دریافت شد ✓")
            return "restart"

        # ۳) صفحه اول — نمایش پیشی‌های خیابونی + دکمه شروع
        cats = parse_street_cats(text)
        if cats is not None and msg.buttons:
            log.info(f"[SMUGGLE] پیشی‌های خیابونی: {cats} — کلیک شروع قاچاق")
            await click_button(msg, 0, 0, fallback_text=SMUGGLE_START_TEXT)
            fresh = await refresh_message(group, msg.id)
            if fresh:
                msg = fresh
            continue

        # ۴) صفحه انتخاب تعداد (X / سقف)
        counts = parse_smuggle_count(text)
        if counts is not None:
            current, cap = counts
            eff_target = min(target_count, cap)

            dur = parse_duration(text)
            if dur is not None:
                last_wait = dur

            if current < eff_target:
                await click_button(msg, 0, 2, fallback_text=None)  # دکمه افزایش — بدون متن
                fresh = await refresh_message(group, msg.id)
                if fresh:
                    msg = fresh
                continue

            if current > eff_target:
                await click_button(msg, 0, 0, fallback_text=None)  # دکمه کاهش — بدون متن
                fresh = await refresh_message(group, msg.id)
                if fresh:
                    msg = fresh
                continue

            # تعداد درست تنظیم شده → تایید نهایی و شروع واقعی قاچاق
            await click_button(msg, 1, 0, fallback_text=None)
            fresh = await refresh_message(group, msg.id)
            if fresh:
                msg = fresh
                d2 = parse_duration(msg.text or "")
                if d2 is not None:
                    last_wait = d2

            if last_wait is None:
                last_wait = cfg_int("smuggling_wait_sec", 1800)

            cfg_set("smuggling_wait_sec", str(last_wait))
            set_last_run("smuggling", time.time())
            log.info(f"[SMUGGLE] قاچاق شروع شد | تعداد={eff_target} | زمان={fmt_time(last_wait)}")
            return "started"

        # وضعیت ناشناخته — بدون crash، فقط لاگ و خروج از این تلاش
        log.warning(f"[SMUGGLE] وضعیت پیام ناشناخته — رد شد: {text[:80]!r}")
        break

    log.warning("[SMUGGLE] سیکل بدون نتیجه قطعی پایان یافت.")
    return "retry"


async def handle_prison(group: int) -> None:
    """مدیریت کامل حالت زندان میویی: ارسال، تایید ورود، پرداخت جریمه."""
    try:
        sent = await safe_send(group, PRISON_TRIGGER)
        if not sent:
            log.warning(f"[SMUGGLE] ارسال «{PRISON_TRIGGER}» ناموفق بود.")
            return

        msg = await wait_for_bot_message(group, sent.id)
        if not msg:
            log.warning("[SMUGGLE] پاسخی برای زندان میویی دریافت نشد.")
            return

        # کلیک اول: ورود به صفحه‌ی تایید جریمه
        await click_button(msg, 0, 0, fallback_text=None)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

        # کلیک دوم: تایید نهایی پرداخت جریمه
        await click_button(msg, 0, 0, fallback_text=None)
        fresh = await refresh_message(group, msg.id)

        if fresh and is_fine_paid(fresh.text or ""):
            log.info("[SMUGGLE] جریمه با موفقیت پرداخت شد ✓")
        else:
            log.info("[SMUGGLE] فرآیند پرداخت جریمه انجام شد (وضعیت نهایی نامشخص).")
    except Exception as e:
        log.error(f"[SMUGGLE] خطا در مدیریت زندان: {e}")


async def smuggling_loop() -> None:
    wait = secs_left("smuggling", cfg_int("smuggling_wait_sec", 1800))
    if wait > 0:
        log.info(f"[SMUGGLE] {fmt_time(wait)} تا اجرای بعدی مانده")
        await sleep_or_wake(wait, "smuggling")

    while True:
        if not cfg_bool("smuggling_enabled"):
            await sleep_or_wake(5, "smuggling")
            continue

        wait = secs_left("smuggling", cfg_int("smuggling_wait_sec", 1800))
        if wait > 0:
            await sleep_or_wake(wait, "smuggling")
            continue

        try:
            status = await smuggling_cycle()
        except Exception as e:
            log.error(f"[SMUGGLE] خطای غیرمنتظره: {e}")
            status = "retry"

        if status == "started":
            wait = secs_left("smuggling", cfg_int("smuggling_wait_sec", 1800))
            await sleep_or_wake(wait if wait > 0 else SMUGGLE_RETRY_DELAY, "smuggling")
        elif status == "restart":
            await sleep_or_wake(SMUGGLE_RESTART_DELAY, "smuggling")
        else:
            await sleep_or_wake(SMUGGLE_RETRY_DELAY, "smuggling")


# ══════════════════════════════════════════════════
#  سیستم کارخونه میویی (loop زمان‌بندی‌شده)
# ══════════════════════════════════════════════════

async def factory_cycle() -> str:
    """
    یک سیکل تولید کارخونه میویی (فقط تولید — بررسی انبار/فروش کاملاً جدا و ساعتی است، در factory_price_watch_loop).
    خروجی: "started" | "in_progress" | "retry"
    """
    group = get_group("factory_group", DEFAULT_FACTORY_GROUP)

    sent = await safe_send(group, FACTORY_TRIGGER)
    if not sent:
        log.warning(f"[FACTORY] ارسال «{FACTORY_TRIGGER}» به گروه {group} ناموفق بود.")
        return "retry"

    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[FACTORY] پاسخی از بات دریافت نشد.")
        return "retry"

    btn0 = _first_button_text(msg)

    try:
        if FACTORY_INPROGRESS_TEXT in btn0:
            # در حال تولید — فقط زمان باقی‌مانده را می‌خوانیم و ذخیره می‌کنیم.
            # نکته مهم: بعد از این، دیگر هیچ کلیک دیگری روی این پیام زده نمی‌شود
            # تا تولید در حال انجام به‌اشتباه لغو نشود.
            await click_button(msg, 0, 0, fallback_text=FACTORY_INPROGRESS_TEXT)
            fresh = await refresh_message(group, msg.id)
            remaining = parse_duration((fresh.text if fresh else msg.text) or "")
            wait_sec = remaining if remaining is not None else cfg_int("factory_wait_sec", 3600)

            cfg_set("factory_wait_sec", str(wait_sec))
            set_last_run("factory", time.time())
            log.info(f"[FACTORY] تولید در حال انجام است | باقی‌مانده={fmt_time(wait_sec)} | بدون کلیک اضافه")
            return "in_progress"

        # شروع یک تولید جدید (تولیدی هواپیما)
        await click_button(msg, 0, 0, fallback_text=FACTORY_PRODUCE_TEXT)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

        await click_button(msg, 4, 0, fallback_text=FACTORY_AIRPLANE_TEXT)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

        await click_button(msg, 0, 2, fallback_text=None)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

        await click_button(msg, 0, 3, fallback_text=None)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

        dur = parse_duration(msg.text or "")
        wait_sec = dur if dur is not None else cfg_int("factory_wait_sec", 3600)

        await click_button(msg, 0, 0, fallback_text=FACTORY_START_TEXT)

        cfg_set("factory_wait_sec", str(wait_sec))
        set_last_run("factory", time.time())
        log.info(f"[FACTORY] تولید هواپیما شروع شد | زمان={fmt_time(wait_sec)}")
        return "started"
    except Exception as e:
        log.error(f"[FACTORY] خطا در بخش تولید: {e}")
        return "retry"


async def factory_warehouse_check(group: int) -> None:
    """ورود به انبار، بررسی قیمت بازار، و فروش خودکار محصول در صورت رسیدن به آستانه."""
    sent = await safe_send(group, FACTORY_TRIGGER)
    if not sent:
        return
    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        return

    await click_by_text(msg, WAREHOUSE_TEXT)
    fresh = await refresh_message(group, msg.id)
    if fresh:
        msg = fresh

    await click_button(msg, 1, 0, fallback_text=None)
    fresh = await refresh_message(group, msg.id)
    if fresh:
        msg = fresh

    await click_button(msg, 0, 0, fallback_text=None)
    fresh = await refresh_message(group, msg.id)
    if fresh:
        msg = fresh

    price = parse_market_price(msg.text or "")
    threshold = cfg_int("min_sell_price", 55)

    if price is None:
        log.info("[FACTORY] قیمت بازار قابل تشخیص نبود — از فروش صرف‌نظر شد.")
        return

    if price >= threshold:
        log.info(f"[FACTORY] قیمت بازار={price} ≥ آستانه={threshold} → فروش محصول")
        await click_button(msg, 0, 0, fallback_text=SELL_PRODUCT_TEXT)
        fresh = await refresh_message(group, msg.id)
        if fresh and fresh.buttons:
            await click_button(fresh, 0, 0, fallback_text=None)
            log.info("[FACTORY] فروش تایید شد ✓")
        else:
            log.info("[FACTORY] فروش انجام شد ✓")
    else:
        log.info(f"[FACTORY] قیمت بازار={price} < آستانه={threshold} → فروشی انجام نشد")


def seconds_until_next_31() -> float:
    """
    ثانیه‌های باقی‌مانده تا دقیقه ۳۱ ساعت جاری (یا ساعت بعد اگر رد شده باشیم) —
    چون قیمت بازار هر ساعت، سرِ دقیقه ۳۱ به‌روزرسانی می‌شود.
    """
    now_ts = time.time()
    now = time.localtime(now_ts)
    this_hour_31 = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, 31, 0, 0, 0, -1))
    if this_hour_31 > now_ts:
        return this_hour_31 - now_ts
    return (this_hour_31 + 3600) - now_ts


async def factory_price_watch_loop() -> None:
    """
    حلقه‌ای کاملاً مستقل از چرخه تولید: دقیقاً سرِ دقیقه ۳۱ هر ساعت (۱:۳۱، ۲:۳۱، ۳:۳۱، ...)
    قیمت بازار انبار را چک می‌کند. اگر به آستانه نرسیده باشد، هیچ کلیکی (حتی برای فروش) زده نمی‌شود.
    """
    while True:
        wait = seconds_until_next_31()
        log.info(f"[FACTORY-PRICE] {fmt_time(wait)} تا بررسی بعدی قیمت بازار (ساعت:۳۱)")
        await sleep_or_wake(wait, "factory_price")

        # اگر sleep_or_wake به‌خاطر یک بیدارباش (مثلاً تغییر گروه کارخونه) زودتر
        # از موعد ۳۱ دقیقه برگشته باشد، هنوز وقتش نرسیده — دوباره صبر می‌کنیم.
        if seconds_until_next_31() > 5:
            continue

        if not cfg_bool("factory_enabled"):
            continue

        try:
            group = get_group("factory_group", DEFAULT_FACTORY_GROUP)
            await factory_warehouse_check(group)
        except Exception as e:
            log.error(f"[FACTORY-PRICE] خطا: {e}")


async def factory_loop() -> None:
    if get_last_run("factory") == 0.0:
        wait = FACTORY_INITIAL_DELAY
        log.info(f"[FACTORY] اولین اجرای ربات — {fmt_time(wait)} تاخیر اولیه")
    else:
        wait = secs_left("factory", cfg_int("factory_wait_sec", 3600))
        if wait > 0:
            log.info(f"[FACTORY] {fmt_time(wait)} تا اجرای بعدی مانده")

    if wait > 0:
        await sleep_or_wake(wait, "factory")

    while True:
        if not cfg_bool("factory_enabled"):
            await sleep_or_wake(5, "factory")
            continue

        wait = secs_left("factory", cfg_int("factory_wait_sec", 3600))
        if wait > 0:
            await sleep_or_wake(wait, "factory")
            continue

        try:
            status = await factory_cycle()
        except Exception as e:
            log.error(f"[FACTORY] خطای غیرمنتظره: {e}")
            status = "retry"

        if status in ("started", "in_progress"):
            wait = secs_left("factory", cfg_int("factory_wait_sec", 3600))
            await sleep_or_wake(wait if wait > 0 else FACTORY_RETRY_DELAY, "factory")
        else:
            await sleep_or_wake(FACTORY_RETRY_DELAY, "factory")


# ══════════════════════════════════════════════════
#  Rescue Listener
# ══════════════════════════════════════════════════

RESCUE_CLICK_ATTEMPTS = 5  # تعداد کلیک‌های رگباری برای افزایش شانس نجات پیشی خیابونی


async def _fire_click(btn, attempt: int) -> None:
    """یک تلاش برای کلیک روی دکمه؛ خطاها فقط لاگ می‌شوند و مانع تلاش‌های دیگر نمی‌شوند."""
    try:
        await btn.click()
    except Exception as e:
        log.warning(f"[RESCUE] کلیک شماره {attempt} ناموفق: {e}")


async def sniper_click(msg: Message, action_type: str):
    raw_text = msg.text or ""

    # بررسی متن برای اطمینان از حضور پیشی خیابونی و اینکه قبلاً توسط کسی گرفته نشده باشه
    if ("یک پیشی خیابونی توی شهر پیدا شد" in raw_text or "لطفا به پیشی" in raw_text) and "نجات داد" not in raw_text:
        if msg.buttons:
            for r_idx, row in enumerate(msg.buttons):
                for c_idx, btn in enumerate(row):
                    if "نجات پیشی" in btn.text:
                        log.info(f"🎯 [پیشی شکار شد! ({action_type})] ──> ارسال فوری {RESCUE_CLICK_ATTEMPTS} کلیک...")

                        # همه‌ی کلیک‌ها واقعاً و به‌صورت تضمین‌شده (نه فقط schedule) اجرا می‌شوند:
                        # asyncio.gather با return_exceptions=True یعنی حتی اگر یکی fail شود،
                        # بقیه هم اجرا می‌شوند و هیچ‌کدام گم/کنسل نمی‌شوند.
                        await asyncio.gather(
                            *[_fire_click(btn, i + 1) for i in range(RESCUE_CLICK_ATTEMPTS)],
                            return_exceptions=True,
                        )
                        return True
    return False


async def rescue_listener() -> None:
    """
    به‌جای ثبت هندلر با لیست ثابت گروه‌ها (که فقط در startup خوانده می‌شد و با
    تغییر بعدی .گروه_خیابونی دیگر به‌روز نمی‌شد)، هندلر روی همه‌ی چت‌ها (chats=None)
    ثبت می‌شود و در هر پیام، لیست گروه‌های خیابونی *لحظه‌ای* از دیتابیس خوانده
    می‌شود. این‌طوری تغییر گروه‌ها فوراً و بدون ری‌استارت اعمال می‌شود.
    """
    bot_list = list(TARGET_BOTS)

    def _in_rescue_groups(chat_id: int) -> bool:
        current_groups = get_group_list("group_rescue", DEFAULT_RESCUE_GROUPS)
        return chat_id in current_groups

    @client.on(events.NewMessage(from_users=bot_list))
    async def handle_new_msg(event):
        if not cfg_bool("rescue_enabled"):
            return
        if not _in_rescue_groups(event.chat_id):
            return
        await sniper_click(event.message, "پیام جدید")

    @client.on(events.MessageEdited(from_users=bot_list))
    async def handle_edited_msg(event):
        if not cfg_bool("rescue_enabled"):
            return
        if not _in_rescue_groups(event.chat_id):
            return
        await sniper_click(event.message, "پیام ادیت‌شده/فرصت مجدد")

    await client.run_until_disconnected()


# ══════════════════════════════════════════════════
#  Command Listener
# ══════════════════════════════════════════════════

async def command_listener() -> None:
    @client.on(events.NewMessage(outgoing=True))
    async def handler(event):
        text = (event.message.text or "").strip()
        if text == MENU_TRIGGER or text.startswith("."):
            if not cfg_bool("self_enabled") and text != MENU_TRIGGER:
                # حتی اگر سلف خاموش باشد، خود دستور خاموش/روشن باید کار کند
                if text not in (".سلف روشن", ".سلف خاموش"):
                    return
            await handle_command(event)

    while True:
        await asyncio.sleep(3600)


# ══════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════

async def main() -> None:
    init_db()
    await client.start()
    me = await client.get_me()

    log.info(f"[SYSTEM] اکانت متصل شد: {me.first_name} (@{me.username})")
    log.info(f"[SYSTEM] بات‌های هدف (آینه): {', '.join(sorted(TARGET_BOTS))}")
    log.info(f"[SYSTEM] گروه میو: {get_group('group_meow', DEFAULT_MEOW_GROUP)}")
    log.info(f"[SYSTEM] گروه پیشی: {get_group('group_pishi', DEFAULT_PISHI_GROUP)}")
    log.info(f"[SYSTEM] گروه ماهیگیری: {get_group('group_fish', DEFAULT_FISH_GROUP)}")
    log.info(f"[SYSTEM] گروه‌های خیابونی: {get_group_list('group_rescue', DEFAULT_RESCUE_GROUPS)}")
    log.info(f"[SYSTEM] گروه قاچاق: {get_group('smuggling_group', DEFAULT_SMUGGLING_GROUP)}")
    log.info(f"[SYSTEM] گروه کارخونه: {get_group('factory_group', DEFAULT_FACTORY_GROUP)}")
    log.info(f"[SYSTEM] شکم فعلی: {get_stomach()}")
    log.info(f"[SYSTEM] سلف={onoff(cfg_bool('self_enabled'))} میو={onoff(cfg_bool('meow_enabled'))} "
             f"پیشی={onoff(cfg_bool('pishi_enabled'))} ماهیگیری={onoff(cfg_bool('fishing_enabled'))} "
             f"خیابونی={onoff(cfg_bool('rescue_enabled'))} قاچاق={onoff(cfg_bool('smuggling_enabled'))} "
             f"کارخونه={onoff(cfg_bool('factory_enabled'))}")
    log.info(f"[SYSTEM] ربات فعال شد — برای منو در تلگرام {MENU_TRIGGER} را ارسال کنید.\n")

    await asyncio.gather(
        meow_loop(),
        pishi_loop(),
        fishing_loop(),
        rescue_listener(),
        smuggling_loop(),
        factory_loop(),
        factory_price_watch_loop(),
        command_listener(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
