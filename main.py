# -*- coding: utf-8 -*-
"""
Afshin Self — ربات سلف تلگرام (Telethon)
بازطراحی کامل ماژول کارخونه، وضعیت، تنظیمات و بروزرسانی لحظه‌ای گروه‌ها.
"""

import asyncio
import logging
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, Iterator, Tuple, List
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
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

PISHI_MSG_TEXT = "پیشی"
FISH_MSG_TEXT  = "ماهی"

# ── سیستم یخچال میویی ──
FRIDGE_TRIGGER      = "یخچال میویی"
FRIDGE_STORE_BUTTON = "بندازش تو یخچال"

# حدس منطقی برای متن دکمه‌ی تایید شروع پخت — کلیک اصلی روی این مرحله «موقعیتی»
# (ردیف ۰ ستون ۰) است، این متن فقط به‌عنوان fallback استفاده می‌شود؛ اگر متن
# واقعی دکمه در ربات هدف چیز دیگری بود، فقط همین یک رشته را عوض کن.
FRIDGE_COOK_CONFIRM_TEXT = "بپوخش"

# لیست ایموجی موجودات دریایی قابل‌شناسایی — برای افزودن یک نوع ماهی/موجود جدید
# در آینده فقط کافیه ایموجی‌اش رو به همین آرایه اضافه کنی، هیچ منطقی جای دیگه
# نیاز به تغییر نداره (مطابق اصل «افزودن یک ردیف داده، نه بازنویسی موتور»).
FRIDGE_CREATURE_EMOJIS = ["🐙", "🦑", "🐬", "🦭", "🦐", "🐟", "🦞", "🐡", "🐳", "🐋", "🦈"]

FRIDGE_DEFAULT_POLL = 30  # ثانیه — فاصله بررسی وضعیت یخچال وقتی کاری در جریان نیست

GROUP_NOT_SET_TEXT = "هیچ گروهی ست نشده است⛔"

WAIT_FOR_BOT = 20  # ثانیه، سقف انتظار برای پاسخ بات هدف

MENU_TRIGGER = ".سلف"

# مقادیر زیر دیگر به‌صورت خودکار در دیتابیس درج نمی‌شوند (طبق درخواست: در اولین
# اجرا هیچ آیدی عددی برای هیچ گروهی — از جمله یخچال — ست نشود). این ثابت‌ها فقط
# به‌عنوان مرجع/مستندات نگه داشته شده‌اند و دیگر در init_db() استفاده نمی‌شوند؛
# get_group()/get_group_list() اکنون در نبود مقدار، None یا [] برمی‌گردانند و
# UI مربوطه دقیقاً عبارت GROUP_NOT_SET_TEXT را نشان می‌دهد.
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
SMUGGLE_MAX_STEPS     = 40
SMUGGLE_RETRY_DELAY   = 30
SMUGGLE_RESTART_DELAY = 5
FACTORY_RETRY_DELAY   = 60
FACTORY_INITIAL_DELAY = 300

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
    # ── یخچال میویی ──
    "refrigerator_food_value_min": "5",     # حداقل ارزش غذایی برای ذخیره در یخچال
    "refrigerator_fish_value_max": "5000",  # سقف ارزش ماهیِ پخته‌شده برای تغذیه (بالاتر → فروش)
    "fridge_capacity_max": "0",             # 0 یعنی هنوز از بازی سینک نشده
    "fridge_poll_sec":     "30",
}

# مقادیر پیش‌فرض روشن/خاموش ماژول‌ها.
# طبق درخواست: در اولین راه‌اندازی (دیتابیس خالی) فقط «سلف» روشن است و تمام
# ماژول‌های دیگر — از جمله یخچال — کاملاً خاموش می‌مانند. این مقادیر فقط زمانی
# اعمال می‌شوند که دیتابیس تازه ساخته شود (INSERT OR IGNORE)؛ روی دیتابیس‌های
# موجود که این کلیدها را از قبل دارند هیچ تاثیری ندارد.
DEFAULT_TOGGLES = {
    "self_enabled":         "1",
    "meow_enabled":         "0",
    "pishi_enabled":        "0",
    "fishing_enabled":      "0",
    "rescue_enabled":       "0",
    "smuggling_enabled":    "0",
    "factory_enabled":      "0",
    "refrigerator_enabled": "0",
    "fridge_synced_once":   "0",
}

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# رویداد داخلی برای اطلاع‌رسانی به rescue_listener که لیست گروه‌های خیابونی تغییر کرده
rescue_groups_changed = asyncio.Event()

# کش نام گروه‌ها — جلوگیری از فراخوانی مکرر get_entity برای هر رندر وضعیت
_entity_name_cache: dict = {}
_entity_cache_ttl = 300  # ثانیه


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
            # مورد ۲ سند یخچال: جدول اختصاصی موجودی یخچال — هر ردیف یعنی یک نوع
            # ماهی/موجود دریایی درون یخچال است (کلید = ایموجی → جلوگیری از تکرار).
            # status: 'raw' (تازه ذخیره‌شده، پخت شروع نشده) | 'cooking' | 'cooked'
            # miss_count/last_attempt_at: برای جلوگیری از تلاش بی‌وقفه روی ماهی‌ای
            # که در یخچال واقعی پیدا نمی‌شود (مثلاً به‌خاطر ناهماهنگی دیتابیس محلی).
            c.execute(
                "CREATE TABLE IF NOT EXISTS meow_refrigerator ("
                "emoji TEXT PRIMARY KEY, "
                "status TEXT NOT NULL DEFAULT 'raw', "
                "added_at REAL NOT NULL, "
                "cook_started_at REAL, "
                "cook_ready_at REAL, "
                "miss_count INTEGER NOT NULL DEFAULT 0, "
                "last_attempt_at REAL)"
            )
            # ALTER TABLE ایمن برای دیتابیس‌هایی که از نسخه‌ی قبلی (بدون این دو
            # ستون) آپدیت می‌شوند — روی دیتابیس تازه بی‌اثر است (ستون از قبل هست).
            for col_def in ("miss_count INTEGER NOT NULL DEFAULT 0", "last_attempt_at REAL"):
                try:
                    c.execute(f"ALTER TABLE meow_refrigerator ADD COLUMN {col_def}")
                except sqlite3.OperationalError:
                    pass  # ستون از قبل وجود دارد
            c.execute("INSERT OR IGNORE INTO cat_stats (id, stomach) VALUES (1, 0)")

            for k, v in DEFAULT_CONFIG.items():
                c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))

            for k, v in DEFAULT_TOGGLES.items():
                c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))

            # مورد ۱ سند یخچال: در اولین اجرا هیچ آیدی عددی برای هیچ گروهی (میو،
            # پیشی، ماهیگیری، خیابونی، قاچاق، کارخونه، یخچال) درج نمی‌شود. گروه‌ها
            # تا وقتی کاربر با دستورهای .گروه_... مقداردهی نکند «ست‌نشده» می‌مانند
            # و get_group()/get_group_list() برای آن‌ها None/[] برمی‌گردانند.

            c.execute("DELETE FROM config WHERE key IN ('pishi_msg', 'fish_msg')")

        log.info("[DB] Connected")
        log.info(f"[DB] Config Loaded ({table_count('config')} رکورد)")
        log.info(f"[DB] Timers Loaded ({table_count('timers')} رکورد)")
        log.info(f"[DB] Cat Stats Loaded ({table_count('cat_stats')} رکورد)")
        log.info(f"[DB] Fridge Loaded ({table_count('meow_refrigerator')} رکورد)")
    except sqlite3.Error as e:
        log.error(f"[DB] خطای بحرانی در ساخت دیتابیس: {e}")
        raise SystemExit(1)


def cfg(key: str, default: str = "") -> str:
    """
    خواندن مستقیم از دیتابیس در هر بار فراخوانی — به‌عمد بدون کش.
    این تضمین می‌کند که تغییر یک تنظیم از طریق پنل، در همان لحظه توسط تمام
    حلقه‌ها (که هر بار دوباره cfg() را صدا می‌زنند) دیده شود؛ نیازی به ریستارت نیست.
    """
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
        log.info(f"[CFG] تنظیم بروزرسانی شد: {key} => {value}")
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


def get_group(key: str, default: Optional[int] = None) -> Optional[int]:
    """
    خواندن آیدی یک گروه از دیتابیس.
    برخلاف نسخه قبلی، اگر مقدار ست نشده باشد به یک آیدی هاردکدشده fallback
    نمی‌شود — None برمی‌گردد. این باعث می‌شود:
      • نمایش وضعیت بتواند دقیقاً GROUP_NOT_SET_TEXT را نشان دهد،
      • حلقه‌ها بتوانند قبل از ارسال، ست‌نبودن گروه را تشخیص داده و رد شوند
        (به‌جای ارسال ناخواسته به یک گروه پیش‌فرض قدیمی).
    """
    raw = cfg(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        log.error(f"[DB] آیدی گروه خراب برای '{key}'='{raw}' — به‌عنوان ست‌نشده در نظر گرفته شد")
        return default


def get_group_list(key: str, default: Optional[list] = None) -> list:
    """نسخه‌ی 'None-safe': اگر گروهی ست نشده باشد [] برمی‌گردد، نه یک لیست پیش‌فرض هاردکدشده."""
    if default is None:
        default = []
    raw = cfg(key, "").strip()
    if not raw:
        return list(default)
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            log.error(f"[DB] آیدی نامعتبر در '{key}': '{part}' — نادیده گرفته شد")
    return result if result else list(default)


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


def reset_timer(key: str) -> None:
    """صفر کردن کامل یک تایمر — استفاده در دستورهایی مثل .تایم_کارخونه که باید فوراً اعمال شوند."""
    set_last_run(key, time.time())
    log.info(f"[TIMER] تایمر '{key}' ریست شد.")


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


# ══════════════════════════════════════════════════
#  لایه دیتابیس یخچال میویی (جدول meow_refrigerator)
# ══════════════════════════════════════════════════

def fridge_has(emoji: str) -> bool:
    """آیا این نوع ماهی/موجود از قبل در یخچال (محلی) موجود است؟ — مورد ۴ شرط ۳."""
    try:
        with db_cursor() as c:
            c.execute("SELECT 1 FROM meow_refrigerator WHERE emoji=?", (emoji,))
            return c.fetchone() is not None
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در بررسی موجودی '{emoji}': {e}")
        return False


def fridge_add(emoji: str) -> None:
    """ثبت یک ماهی تازه‌ذخیره‌شده با وضعیت 'raw'."""
    try:
        with db_cursor() as c:
            c.execute(
                "INSERT OR IGNORE INTO meow_refrigerator (emoji, status, added_at) "
                "VALUES (?, 'raw', ?)",
                (emoji, time.time()),
            )
        log.info(f"[FRIDGE-DB] ماهی '{emoji}' به یخچال اضافه شد (وضعیت: raw).")
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در افزودن '{emoji}': {e}")


def fridge_remove(emoji: str) -> None:
    """حذف یک اسلات یخچال — بعد از فروش/تغذیه‌ی نهایی ماهیِ پخته‌شده."""
    try:
        with db_cursor() as c:
            c.execute("DELETE FROM meow_refrigerator WHERE emoji=?", (emoji,))
        log.info(f"[FRIDGE-DB] ماهی '{emoji}' از یخچال حذف شد (اسلات آزاد شد).")
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در حذف '{emoji}': {e}")


def fridge_reset_all() -> None:
    """
    پاک‌سازی کامل جدول محلی یخچال — طبق درخواست کاربر، هر بار ماژول یخچال از
    خاموش به روشن تغییر می‌کند، دیتابیس محلی کاملاً خالی می‌شود و پرچم
    fridge_synced_once هم پاک می‌شود تا دقیقاً یک سینک تازه (fridge_sync_if_empty)
    در دور بعدی fridge_loop انجام شود — نه کمتر، نه بیشتر.
    """
    try:
        with db_cursor() as c:
            c.execute("DELETE FROM meow_refrigerator")
        cfg_set("fridge_capacity_max", "0")
        cfg_bool_set("fridge_synced_once", False)
        log.info("[FRIDGE-DB] دیتابیس محلی یخچال کاملاً پاک شد — یک سینک تازه در دور بعدی انجام می‌شود.")
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در پاک‌سازی کامل: {e}")


def fridge_set_status(
    emoji: str,
    status: str,
    cook_started_at: Optional[float] = None,
    cook_ready_at: Optional[float] = None,
) -> None:
    """تغییر وضعیت یک ردیف یخچال؛ در صورت وجود، زمان‌های شروع/پایان پخت هم ثبت می‌شوند."""
    try:
        with db_cursor() as c:
            if cook_started_at is not None or cook_ready_at is not None:
                c.execute(
                    "UPDATE meow_refrigerator SET status=?, cook_started_at=?, cook_ready_at=? "
                    "WHERE emoji=?",
                    (status, cook_started_at, cook_ready_at, emoji),
                )
            else:
                c.execute("UPDATE meow_refrigerator SET status=? WHERE emoji=?", (status, emoji))
        log.info(f"[FRIDGE-DB] وضعیت '{emoji}' → '{status}'")
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در تغییر وضعیت '{emoji}': {e}")


def fridge_list_raw() -> List[str]:
    """ماهی‌هایی که تازه ذخیره شده‌اند ولی هنوز فرآیند پخت برایشان شروع نشده."""
    try:
        with db_cursor() as c:
            c.execute("SELECT emoji FROM meow_refrigerator WHERE status='raw'")
            return [r[0] for r in c.fetchall()]
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در خواندن لیست خام‌ها: {e}")
        return []


def fridge_due_now() -> List[str]:
    """
    ماهی‌هایی که آماده‌ی جمع‌آوری‌اند: یا از قبل به‌عنوان 'cooked' علامت خورده‌اند
    (مثلاً از طریق سینک اولیه با یخچالی که از قبل چیز پخته‌شده داشته)، یا در حال
    پخت بوده و زمانشان به پایان رسیده.
    """
    try:
        with db_cursor() as c:
            c.execute(
                "SELECT emoji FROM meow_refrigerator WHERE status='cooked' "
                "OR (status='cooking' AND cook_ready_at IS NOT NULL AND cook_ready_at<=?)",
                (time.time(),),
            )
            return [r[0] for r in c.fetchall()]
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در خواندن لیست آماده‌ی جمع‌آوری: {e}")
        return []


def fridge_next_ready_at() -> Optional[float]:
    """نزدیک‌ترین زمانی که یک ماهیِ در-حال-پخت آماده می‌شود — برای محاسبه‌ی خواب پویا در fridge_loop."""
    try:
        with db_cursor() as c:
            c.execute(
                "SELECT MIN(cook_ready_at) FROM meow_refrigerator "
                "WHERE status='cooking' AND cook_ready_at IS NOT NULL"
            )
            row = c.fetchone()
            return row[0] if row and row[0] is not None else None
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در خواندن نزدیک‌ترین زمان آماده‌شدن: {e}")
        return None


FRIDGE_MISS_BACKOFF_SEC = 60   # حداقل فاصله بین دو تلاش متوالی برای همون ماهی بعد از یک شکست
FRIDGE_MISS_GIVE_UP = 10       # بعد از این تعداد شکست پیاپی، دیگر تلاش خودکار نمی‌شود (نیاز به بررسی دستی)


def fridge_should_attempt(emoji: str) -> bool:
    """
    آیا الان زمان مناسبی برای تلاش دوباره روی این ماهی هست؟ اگر اخیراً (کمتر از
    FRIDGE_MISS_BACKOFF_SEC پیش) یک تلاش شکست‌خورده داشته، صبر می‌کنیم تا از
    درخواست‌های پشت‌سرهم و بی‌فایده به تلگرام جلوگیری شود.
    """
    try:
        with db_cursor() as c:
            c.execute(
                "SELECT miss_count, last_attempt_at FROM meow_refrigerator WHERE emoji=?",
                (emoji,),
            )
            row = c.fetchone()
            if not row:
                return True
            miss_count, last_attempt_at = row
            if miss_count >= FRIDGE_MISS_GIVE_UP:
                return False
            if last_attempt_at and (time.time() - last_attempt_at) < FRIDGE_MISS_BACKOFF_SEC:
                return False
            return True
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در بررسی زمان تلاش مجدد '{emoji}': {e}")
        return True


def fridge_record_attempt(emoji: str, success: bool) -> None:
    """ثبت نتیجه‌ی یک تلاش (موفق/ناموفق) روی این ماهی — برای مدیریت backoff."""
    try:
        with db_cursor() as c:
            if success:
                c.execute(
                    "UPDATE meow_refrigerator SET miss_count=0, last_attempt_at=? WHERE emoji=?",
                    (time.time(), emoji),
                )
            else:
                c.execute(
                    "UPDATE meow_refrigerator SET miss_count=miss_count+1, last_attempt_at=? WHERE emoji=?",
                    (time.time(), emoji),
                )
    except sqlite3.Error as e:
        log.error(f"[FRIDGE-DB] خطا در ثبت نتیجه‌ی تلاش '{emoji}': {e}")


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


def fmt_timer_line(key: str, interval: int, enabled: bool) -> str:
    """
    نمایش صحیح خط تایمر با در نظر گرفتن وضعیت روشن/خاموش ماژول (مورد ۵):
    اگر ماژول خاموش باشد، به‌جای «همین الان ✅» باید «🔴 خاموش» نمایش داده شود —
    چون ماژول خاموش هرگز اجرا نخواهد شد و «همین الان» گمراه‌کننده است.
    """
    if not enabled:
        return "🔴 خاموش"
    return fmt_time(secs_left(key, interval))


def onoff(flag: bool) -> str:
    return "🟢 روشن" if flag else "🔴 خاموش"


def fmt_fridge_timer_line() -> str:
    """
    برخلاف میو/پیشی/ماهیگیری/قاچاق/کارخونه، یخچال یک فاصله‌ی زمانی ثابت ندارد
    (بسته به سطح ماهی متغیر است)؛ به‌جای شمارش معکوس ساختگی، وضعیت واقعی نمایش
    داده می‌شود: خاموش / در حال پخت (با زمان واقعی باقی‌مانده) / آماده‌ی شروع
    پخت / منتظر ماهی جدید.
    """
    if not cfg_bool("refrigerator_enabled", False):
        return "🔴 خاموش"
    next_ready = fridge_next_ready_at()
    if next_ready is not None:
        remaining = max(0.0, next_ready - time.time())
        return f"🍳 در حال پخت — مانده: {fmt_time(remaining)}"
    if fridge_due_now():
        return "📦 ماهی پخته‌شده منتظر جمع‌آوری است"
    if fridge_list_raw():
        return "📥 آماده‌ی شروع پخت"
    return "⏳ منتظر ماهی جدید"


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
    uname = getattr(sender, "username", None)
    return bool(uname) and uname in TARGET_BOTS


def parse_stomach(text: str) -> Optional[int]:
    m = re.search(r"شکم\s*:.*?`(\d+)`\s*/\s*`\d+`", text)
    return int(m.group(1)) if m else None


# ══════════════════════════════════════════════════
#  پارسرهای سیستم قاچاق میویی / کارخونه میویی
# ══════════════════════════════════════════════════

DURATION_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")

# الگوی اختصاصی «زمان باقی مانده» — مورد ۴: چون ممکن است در یک پیام چند عدد
# با فرمت HH:MM:SS وجود داشته باشد (مثلاً یک زمان کلی و یک زمان باقی‌مانده)،
# پارسر باید طوری بازنویسی شود که فقط زمانِ بعد از عبارت «زمان باقی مانده» را
# بردارد، نه اولین HH:MM:SS پیدا شده در کل متن.
REMAINING_TIME_RE = re.compile(
    r"زمان\s*باقی\s*مانده\D{0,10}(\d{1,2}):(\d{2}):(\d{2})"
)

# ظرفیت انبار — مثال: «ظرفیت انبار : 0 / 25,000 محصول»
WAREHOUSE_CAPACITY_RE = re.compile(
    r"ظرفیت\s*انبار\s*:?\s*([\d,]+)\s*/\s*([\d,]+)"
)


def _normalize(text: Optional[str]) -> str:
    """
    حذف نیم‌فاصله، نشانه‌های نامرئی جهت‌دهی متن (RLM/LRM/ALM)، و بک‌تیک‌های
    مارک‌داون (`) که ربات‌های هدف اغلب دور اعداد می‌گذارند (مثلاً «ظرفیت یخچال :
    `0` / `3`»). حذف این کاراکترها کاملاً بی‌خطر است — هیچ‌کدام تاثیری روی
    محتوای عددی/متنی قابل‌مشاهده ندارند و فقط برای ساده‌ترشدن تطبیق ریجکس‌ها
    حذف می‌شوند.
    """
    t = text or ""
    t = t.replace("\u200c", " ")
    for ch in ("\u200e", "\u200f", "\u061c", "`"):
        t = t.replace(ch, "")
    return t


def parse_street_cats(text: str) -> Optional[int]:
    m = re.search(r"شما\s+(\d+)\s+پیشی\s+خیابونی\s+دارید", _normalize(text))
    return int(m.group(1)) if m else None


def parse_smuggle_count(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"تعداد\s*پیشی\s*های\s*قاچاقی\s*:\s*(\d+)\s*/\s*(\d+)", _normalize(text))
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_duration(text: str) -> Optional[int]:
    """
    استخراج عمومی زمان HH:MM:SS از متن (برای مواردی که عبارت «زمان باقی مانده» وجود ندارد،
    مثل صفحه انتخاب تعداد قاچاق). برای پارس اختصاصی کارخونه از parse_remaining_time استفاده شود.
    """
    m = DURATION_RE.search(_normalize(text))
    if not m:
        return None
    h, mn, s = (int(x) for x in m.groups())
    return h * 3600 + mn * 60 + s


def parse_remaining_time(text: str) -> Optional[int]:
    """
    پارسر بازنویسی‌شده مخصوص «زمان باقی مانده» (مورد ۴).
    مستقیماً روی عبارت «زمان باقی مانده» انکور می‌شود تا در صورت وجود چند
    HH:MM:SS در یک پیام، همیشه زمان درست استخراج شود — نه اولین موردی که
    به‌صورت اتفاقی در متن ظاهر می‌شود.
    اگر عبارت «زمان باقی مانده» پیدا نشد، fallback به اولین HH:MM:SS متن.
    """
    t = _normalize(text)
    m = REMAINING_TIME_RE.search(t)
    if m:
        h, mn, s = (int(x) for x in m.groups())
        return h * 3600 + mn * 60 + s
    # fallback ایمن — اگر برچسب دقیق پیدا نشد ولی زمانی در متن هست
    return parse_duration(t)


def parse_warehouse_stock(text: str) -> Optional[Tuple[int, int]]:
    """
    استخراج ظرفیت انبار از متنی مانند «ظرفیت انبار : 0 / 25,000 محصول» → (0, 25000).
    اعداد شامل کاما (جداکننده هزارگان) هستند و باید قبل از تبدیل حذف شوند.
    """
    m = WAREHOUSE_CAPACITY_RE.search(_normalize(text))
    if not m:
        return None
    current = int(m.group(1).replace(",", ""))
    capacity = int(m.group(2).replace(",", ""))
    return current, capacity


def parse_market_price(text: str) -> Optional[int]:
    m = re.search(r"قیمت\s*بازار\D{0,10}(\d+)", _normalize(text))
    return int(m.group(1)) if m else None


def is_arrested(text: str) -> bool:
    return "به جرم قاچاق" in _normalize(text)


def is_smuggle_success(text: str) -> bool:
    t = _normalize(text)
    return "با موفقیت انجام شد" in t and "قاچاق" in t


def is_fine_paid(text: str) -> bool:
    t = _normalize(text)
    return "جریمه" in t and "پرداخت" in t and "موفقیت" in t


def is_factory_in_progress(text: str) -> bool:
    """
    تشخیص حالت «در حال تولید» کارخونه (مورد ۱).
    بر اساس متن نمونه:
        🐱 کارخونه میویی 🏭
        ✨ درحال تولید ...
        ┘─ ⏳ زمان باقی مانده : HH:MM:SS
    تشخیص روی عبارت «درحال تولید» (با یا بدون نیم‌فاصله) انجام می‌شود تا هم به
    متن دکمه (FACTORY_INPROGRESS_TEXT) و هم به بدنه پیام مقاوم باشد.
    """
    t = _normalize(text)
    return "حال تولید" in t


# ══════════════════════════════════════════════════
#  پارسرهای سیستم یخچال میویی
# ══════════════════════════════════════════════════

# ظرفیت یخچال — مثال: «🐟 ظرفیت یخچال : 2 / 2»
FRIDGE_CAPACITY_RE = re.compile(r"ظرفیت\s*یخچال\s*:?\s*([\d,]+)\s*/\s*([\d,]+)")

# «زمان مورد نیاز پخیدن : 1:58» — معمولاً MM:SS، اما HH:MM:SS هم پشتیبانی می‌شود
COOK_DURATION_RE = re.compile(
    r"زمان\s*مورد\s*نیاز\s*پخیدن\D{0,10}(\d{1,2}):(\d{2})(?::(\d{2}))?"
)

# «ارزش» به‌تنهایی (نه «ارزش غذایی») — لوک‌اِهد منفی مانع تطبیق با ارزش غذایی می‌شود
FISH_VALUE_RE = re.compile(r"ارزش(?!\s*غذایی)\s*:?\s*([\d,]+)")

# «ارزش غذایی : 5»
FOOD_VALUE_RE = re.compile(r"ارزش\s*غذایی\D{0,10}([\d,]+)")

# الگوی هدر هر ردیف یخچال — مثال: «🐙 | حماسی 🔡 | (پخته شده 🐟)» یا «🦑 | حماسی 🔡 | (خام)»
_FRIDGE_HEADER_RE = re.compile(
    "(" + "|".join(re.escape(e) for e in FRIDGE_CREATURE_EMOJIS) + r")"
    r"\s*\|[^\n|]*\|\s*\(([^)]*)\)"
)


def parse_fridge_capacity(text: str) -> Optional[Tuple[int, int]]:
    """استخراج (ظرفیت‌فعلی، ظرفیت‌حداکثر) از پیام یخچال میویی."""
    m = FRIDGE_CAPACITY_RE.search(_normalize(text))
    if not m:
        return None
    return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))


def parse_fish_emoji(text: str) -> Optional[str]:
    """
    تشخیص ایموجی نوع ماهی/موجود دریایی از هر جای متن — بر اساس اسکن روی
    FRIDGE_CREATURE_EMOJIS، نه یک اندیس یا فرمت ثابت. افزودن نوع جدید فقط با
    افزودن ایموجی به آن آرایه ممکن می‌شود، بدون تغییر این تابع.
    """
    t = text or ""
    for emo in FRIDGE_CREATURE_EMOJIS:
        if emo in t:
            return emo
    return None


def parse_fish_value(text: str) -> Optional[int]:
    """ارزش پولی ماهی («💰 ارزش : 1,144 🪙») — با «ارزش غذایی» اشتباه گرفته نمی‌شود."""
    m = FISH_VALUE_RE.search(_normalize(text))
    return int(m.group(1).replace(",", "")) if m else None


def parse_food_value(text: str) -> Optional[int]:
    """ارزش غذایی ماهی («🍖 ارزش غذایی : 5»)."""
    m = FOOD_VALUE_RE.search(_normalize(text))
    return int(m.group(1).replace(",", "")) if m else None


def parse_cook_duration(text: str) -> Optional[int]:
    """زمان موردنیاز برای پخته‌شدن ماهی، به ثانیه."""
    m = COOK_DURATION_RE.search(_normalize(text))
    if not m:
        return None
    parts = [g for g in m.groups() if g is not None]
    if len(parts) == 3:
        h, mn, s = (int(x) for x in parts)
        return h * 3600 + mn * 60 + s
    if len(parts) == 2:
        mn, s = (int(x) for x in parts)
        return mn * 60 + s
    return None


def is_cooked_label(text: str) -> bool:
    """آیا برچسب وضعیت ماهی «پخته شده» است؟"""
    return "پخته" in _normalize(text)


def is_fridge_empty(text: str) -> bool:
    """آیا پیام یخچال میویی صراحتاً «یخچال خالی است» را نشان می‌دهد؟"""
    return "یخچال خالی است" in _normalize(text)


def parse_fridge_entries(text: str) -> List[dict]:
    """
    استخراج کامل لیست ماهی‌های داخل یخچال، به همان ترتیبی که در متن ظاهر
    می‌شوند (مورد ۵/۶) — هر آیتم: emoji، cooked (bool)، weight، value، food_value.

    این پارسر بر اساس *موقعیت هر ایموجی در متن* عمل می‌کند، نه اندیس ثابت؛
    بنابراین کاملاً با ترتیب دکمه‌های آنانیم (که به همین ترتیب متن ظاهر می‌شوند)
    قابل تطبیق است. افزودن یک نوع ماهی جدید فقط با افزودن ایموجی‌اش به
    FRIDGE_CREATURE_EMOJIS ممکن می‌شود، بدون تغییر این تابع.
    """
    t = _normalize(text)
    headers = list(_FRIDGE_HEADER_RE.finditer(t))
    entries: List[dict] = []
    for i, hm in enumerate(headers):
        start = hm.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(t)
        block = t[start:end]

        weight_m = re.search(r"وزن\s*:\s*([\d.]+)", block)
        value_m = FISH_VALUE_RE.search(block)
        food_m = FOOD_VALUE_RE.search(block)

        entries.append({
            "emoji": hm.group(1),
            "cooked": is_cooked_label(hm.group(2) or ""),
            "weight": float(weight_m.group(1)) if weight_m else None,
            "value": int(value_m.group(1).replace(",", "")) if value_m else None,
            "food_value": int(food_m.group(1).replace(",", "")) if food_m else None,
        })
    return entries


# ══════════════════════════════════════════════════
#  کش نام گروه‌ها (مورد ۷/۸) — get_entity با مدیریت خطا
# ══════════════════════════════════════════════════

async def resolve_group_name(gid: int) -> str:
    """
    دریافت نام یک گروه با get_entity، با کش کوتاه‌مدت برای جلوگیری از
    فراخوانی مکرر (هر بار .وضعیت اجرا شود، نباید هر بار مستقیماً به سرور زده شود).
    در صورت هر نوع خطا (گروه حذف‌شده، بن، عدم دسترسی، آیدی اشتباه) رشته
    «❌ نامشخص» برگردانده می‌شود — هرگز crash نمی‌کند (مورد ۶/۷).
    """
    now = time.time()
    cached = _entity_name_cache.get(gid)
    if cached and (now - cached[1]) < _entity_cache_ttl:
        return cached[0]

    try:
        entity = await client.get_entity(gid)
        name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(gid)
        _entity_name_cache[gid] = (name, now)
        return name
    except ChannelPrivateError:
        log.warning(f"[GROUP] دسترسی به گروه {gid} وجود ندارد (ChannelPrivateError).")
        result = "❌ دسترسی وجود ندارد"
    except (ValueError, TypeError) as e:
        log.warning(f"[GROUP] گروه {gid} پیدا نشد یا آیدی نامعتبر است: {e}")
        result = "❌ گروه در دسترس نیست"
    except Exception as e:
        log.warning(f"[GROUP] خطای نامشخص هنگام دریافت اطلاعات گروه {gid}: {e}")
        result = "❌ نامشخص"

    _entity_name_cache[gid] = (result, now)
    return result


async def format_group_block(label: str, gid: Optional[int]) -> str:
    """
    قالب نمایش یک گروه به‌صورت:
        🐱 گروه میو:
        └─ NameOrError
        └─ -1003380347106
    (مورد ۷)

    اگر گروه اصلاً ست نشده باشد (gid=None)، بدون هیچ تماس شبکه‌ای اضافه‌ای،
    دقیقاً GROUP_NOT_SET_TEXT نمایش داده می‌شود.
    """
    if gid is None:
        return f"{label}:\n└─ {GROUP_NOT_SET_TEXT}"
    name = await resolve_group_name(gid)
    return f"{label}:\n└─ {name}\n└─ {gid}"


async def format_rescue_groups_block(gids: List[int]) -> str:
    """
    قالب نمایش کامل تمام گروه‌های خیابونی (مورد ۸) — همه گروه‌ها بدون خلاصه‌سازی:
        🏘 گروه‌های خیابونی:

        └─ GroupName1
        └─ -1001111111111

        └─ GroupName2
        └─ -1002222222222
    """
    if not gids:
        return f"🏘 گروه‌های خیابونی:\n└─ {GROUP_NOT_SET_TEXT}"

    lines = ["🏘 گروه‌های خیابونی:"]
    for gid in gids:
        name = await resolve_group_name(gid)
        lines.append(f"\n└─ {name}\n└─ {gid}")
    return "\n".join(lines)


async def wait_for_reply(
    gid: int, my_msg_id: int, has_buttons: set, timeout: int = WAIT_FOR_BOT
) -> Optional[Message]:
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
    btn = get_button(msg, text=text)
    if await raw_click(msg, btn):
        return True
    log.warning(f"[BUTTON] کلیک متنی '{text}' ناموفق.")
    return False


def _first_button_text(msg: Message) -> str:
    try:
        if msg.buttons and msg.buttons[0]:
            return (msg.buttons[0][0].text or "").strip()
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════
#  موقعیت دکمه‌های آنانیم یخچال (بدون هیچ متنی)
# ══════════════════════════════════════════════════
#
# طبق تایید صریح کاربر: این دکمه‌ها اصلاً متن ندارند و فقط بر اساس «موقعیت»
# شناسایی می‌شوند — نه با اسکن‌کردن پیام برای دکمه‌های خالی. قانون دقیق:
#   • اگر دکمه‌ی متنی «ارتقا سطح یخچال» در پیام نباشد:
#       ماهی اول → ردیف ۰ ستون ۰ | ماهی دوم → ردیف ۰ ستون ۱ | ...
#   • اگر آن دکمه باشد (ردیف ۰ را اشغال کرده):
#       ماهی اول → ردیف ۱ ستون ۰ | ماهی دوم → ردیف ۱ ستون ۱ | ...
# یعنی ستون همیشه = ایندکس ماهی در لیست متن (0-based)، و فقط ردیف بر اساس
# وجود/عدم‌وجود دکمه‌ی ارتقا بین ۰ و ۱ جابه‌جا می‌شود.

FRIDGE_UPGRADE_BUTTON_TEXT = "ارتقا سطح یخچال"


def fridge_fish_button_position(msg: Message, fish_index: int) -> Tuple[int, int]:
    """موقعیت (ردیف, ستون) دکمه‌ی آنانیمِ متناظر با fish_index-امین ماهیِ لیست متن."""
    has_upgrade = get_button(msg, text=FRIDGE_UPGRADE_BUTTON_TEXT) is not None
    row = 1 if has_upgrade else 0
    return row, fish_index


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
        "▫️ .تایم_کارخونه [ثانیه]\n"
        "تنظیم دستی و فوری تایمر کارخونه (بدون نیاز به ریستارت)\n\n"
        "▫️ .حداقل_ارزش_غذایی [عدد]\n"
        "حداقل ارزش غذایی ماهی برای ذخیره در یخچال (پیش‌فرض 5)\n\n"
        "▫️ .حداکثر_ارزش_ماهی [عدد]\n"
        "سقف ارزش ماهیِ پخته‌شده برای تغذیه؛ بالاتر از این مقدار فروخته می‌شود (پیش‌فرض 5000)\n\n"
        "▫️ .گروه_یخچال [آیدی]\n"
        "گروه اختصاصی یخچال میویی\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔌 کنترل ماژول‌ها\n\n"
        "▫️ .سلف روشن   ▫️ .سلف خاموش\n"
        "▫️ .میو روشن   ▫️ .میو خاموش\n"
        "▫️ .پیشی روشن   ▫️ .پیشی خاموش\n"
        "▫️ .ماهیگیری روشن   ▫️ .ماهیگیری خاموش\n"
        "▫️ .خیابونی روشن   ▫️ .خیابونی خاموش\n"
        "▫️ .قاچاق روشن   ▫️ .قاچاق خاموش\n"
        "▫️ .کارخونه روشن   ▫️ .کارخونه خاموش\n"
        "▫️ .یخچال روشن   ▫️ .یخچال خاموش\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 نمونه استفاده\n\n"
        ".میو 340\n"
        ".پیشی 1500\n"
        ".شکم 7\n"
        ".گروه_میو -1001234567890\n"
        ".حداقل_قاچاق 5\n"
        ".حداکثر_قاچاق 15\n"
        ".حداقل_قیمت_فروش 55\n"
        ".گروه_قاچاق -1001234567890\n"
        ".تایم_کارخونه 6000\n"
        ".یخچال روشن\n"
        ".گروه_یخچال -1001234567890\n"
        ".حداقل_ارزش_غذایی 5\n"
        ".حداکثر_ارزش_ماهی 5000\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 سیستم هوشمند ماهیگیری\n\n"
        "اگر مقدار شکم کمتر از حد تعیین‌شده باشد، ماهی به گربه داده می‌شود؛ "
        "در غیر این صورت به‌صورت خودکار فروخته خواهد شد.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 سیستم هوشمند یخچال میویی\n\n"
        "وقتی «یخچال» روشن باشد و گزینه‌ی «بندازش تو یخچال» در ماهیگیری ظاهر شود، "
        "ربات فقط زمانی ماهی را داخل یخچال می‌گذارد که: ارزش غذایی‌اش حداقل به‌اندازه "
        "«.حداقل_ارزش_غذایی» باشد، از قبل هم‌نوعش در یخچال نباشد، و ظرفیت یخچال پر نباشد. "
        "سپس ربات به‌طور خودکار پخت را شروع کرده و پس از اتمام، اگر شکم گربه کم و ارزش "
        "ماهیِ پخته‌شده زیر «.حداکثر_ارزش_ماهی» باشد آن را به گربه می‌دهد، در غیر این صورت "
        "می‌فروشد. اگر «یخچال» خاموش باشد، ماهیگیری دقیقاً طبق روال سابق (فروش/تغذیه فوری) ادامه می‌یابد."
    )


async def build_status() -> str:
    mi = cfg_int("meow_sec")
    pi = cfg_int("pishi_sec")
    fi = cfg_int("fish_sec")
    threshold = cfg_int("stomach")
    stomach = get_stomach()

    g_meow    = get_group("group_meow")
    g_pishi   = get_group("group_pishi")
    g_fish    = get_group("group_fish")
    g_rescue  = get_group_list("group_rescue")
    g_smuggle = get_group("smuggling_group")
    g_factory = get_group("factory_group")
    g_fridge  = get_group("refrigerator_group")

    smuggling_wait = cfg_int("smuggling_wait_sec", 1800)
    factory_wait   = cfg_int("factory_wait_sec", 3600)

    self_on         = cfg_bool("self_enabled")
    meow_on         = cfg_bool("meow_enabled", False)
    pishi_on        = cfg_bool("pishi_enabled", False)
    fishing_on      = cfg_bool("fishing_enabled", False)
    rescue_on       = cfg_bool("rescue_enabled", False)
    smuggling_on    = cfg_bool("smuggling_enabled", False)
    factory_on      = cfg_bool("factory_enabled", False)
    refrigerator_on = cfg_bool("refrigerator_enabled", False)

    # مورد ۷: نام گروه‌ها کنار آیدی — همه با get_entity، خطاها هندل می‌شوند
    # (و اگر گروهی ست نشده باشد، بدون تماس شبکه‌ای، GROUP_NOT_SET_TEXT نمایش داده می‌شود)
    meow_block    = await format_group_block("🐱 گروه میو", g_meow)
    pishi_block   = await format_group_block("🐾 گروه پیشی", g_pishi)
    fish_block    = await format_group_block("🎣 گروه ماهیگیری", g_fish)
    smuggle_block = await format_group_block("📦 گروه قاچاق", g_smuggle)
    factory_block = await format_group_block("🏭 گروه کارخونه", g_factory)
    fridge_block  = await format_group_block("🧊 گروه یخچال", g_fridge)

    # مورد ۸: نمایش کامل گروه‌های خیابونی (بدون خلاصه‌سازی به تعداد)
    rescue_block = await format_rescue_groups_block(g_rescue)

    fridge_food_min  = cfg_int("refrigerator_food_value_min", 5)
    fridge_value_max = cfg_int("refrigerator_fish_value_max", 5000)
    fridge_cap_max   = cfg_int("fridge_capacity_max", 0)
    fridge_cap_cur   = table_count("meow_refrigerator")
    fridge_cap_disp  = f"{fridge_cap_cur} / {fridge_cap_max}" if fridge_cap_max > 0 else f"{fridge_cap_cur} / نامشخص (هنوز سینک نشده)"

    return (
        "🤖 وضعیت کامل ربات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"سلف: {onoff(self_on)}\n"
        f"میو: {onoff(meow_on)}\n"
        f"پیشی: {onoff(pishi_on)}\n"
        f"ماهیگیری: {onoff(fishing_on)}\n"
        f"خیابونی: {onoff(rescue_on)}\n"
        f"قاچاق: {onoff(smuggling_on)}\n"
        f"کارخونه: {onoff(factory_on)}\n"
        f"یخچال: {onoff(refrigerator_on)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🍖 شکم فعلی: {stomach}\n"
        f"🎯 آستانه شکم: {threshold}\n\n"
        f"{meow_block}\n\n"
        f"{pishi_block}\n\n"
        f"{fish_block}\n\n"
        f"{rescue_block}\n\n"
        f"{smuggle_block}\n\n"
        f"{factory_block}\n\n"
        f"{fridge_block}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 حداقل قاچاق: {cfg_int('smuggling_min')}\n"
        f"🔢 حداکثر قاچاق: {cfg_int('smuggling_max')}\n"
        f"💰 حداقل قیمت فروش (کارخونه): {cfg_int('min_sell_price')}\n\n"
        f"🧊 ظرفیت یخچال: {fridge_cap_disp}\n"
        f"🍖 حداقل ارزش غذایی ذخیره در یخچال: {fridge_food_min}\n"
        f"💰 حداکثر ارزش ماهی برای تغذیه: {fridge_value_max}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱ میو (هر {mi} ثانیه)\n └─ مانده: {fmt_timer_line('meow', mi, meow_on)}\n\n"
        f"⏱ پیشی (هر {pi} ثانیه)\n └─ مانده: {fmt_timer_line('pishi', pi, pishi_on)}\n\n"
        f"⏱ ماهیگیری (هر {fi} ثانیه)\n └─ مانده: {fmt_timer_line('fishing', fi, fishing_on)}\n\n"
        f"⏱ قاچاق\n └─ مانده: {fmt_timer_line('smuggling', smuggling_wait, smuggling_on)}\n\n"
        f"⏱ تولید کارخونه\n └─ مانده: {fmt_timer_line('factory', factory_wait, factory_on)}\n\n"
        f"⏱ یخچال\n └─ مانده: {fmt_fridge_timer_line()}"
    )


def build_timers() -> str:
    """
    مورد ۵: در تایمرهای ماژول‌های خاموش، به‌جای «همین الان ✅» عبارت «🔴 خاموش» نمایش داده شود.
    """
    mi = cfg_int("meow_sec")
    pi = cfg_int("pishi_sec")
    fi = cfg_int("fish_sec")
    si = cfg_int("smuggling_wait_sec", 1800)
    ki = cfg_int("factory_wait_sec", 3600)

    meow_on      = cfg_bool("meow_enabled", False)
    pishi_on     = cfg_bool("pishi_enabled", False)
    fishing_on   = cfg_bool("fishing_enabled", False)
    smuggling_on = cfg_bool("smuggling_enabled", False)
    factory_on   = cfg_bool("factory_enabled", False)

    return (
        "⏳ تایمرهای فعال سیستم ⏳\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🐱 ارسال میو بعدی:\n └─ {fmt_timer_line('meow', mi, meow_on)}\n\n"
        f"🐾 ارسال پیشی بعدی:\n └─ {fmt_timer_line('pishi', pi, pishi_on)}\n\n"
        f"🎣 ارسال ماهی بعدی:\n └─ {fmt_timer_line('fishing', fi, fishing_on)}\n\n"
        f"📦 سیکل بعدی قاچاق:\n └─ {fmt_timer_line('smuggling', si, smuggling_on)}\n\n"
        f"🏭 سیکل بعدی کارخونه:\n └─ {fmt_timer_line('factory', ki, factory_on)}\n\n"
        f"🧊 یخچال:\n └─ {fmt_fridge_timer_line()}"
    )


# ══════════════════════════════════════════════════
#  پارس دستورات فارسی (پنل کنترل درون-تلگرامی)
# ══════════════════════════════════════════════════

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
    # مورد ۲: دستور جدید تنظیم دستی تایمر کارخونه
    "تایم_کارخونه":   ("factory_wait_sec", "int", "تایمر دستی کارخونه"),
    # ── یخچال میویی ──
    "حداقل_ارزش_غذایی": ("refrigerator_food_value_min", "int", "حداقل ارزش غذایی برای ذخیره در یخچال"),
    "حداکثر_ارزش_ماهی": ("refrigerator_fish_value_max", "int", "حداکثر ارزش ماهی برای تغذیه"),
    "گروه_یخچال":        ("refrigerator_group", "group", "گروه یخچال میویی"),
}

TOGGLE_COMMANDS = {
    "سلف":       "self_enabled",
    "میو":       "meow_enabled",
    "پیشی":      "pishi_enabled",
    "ماهیگیری":  "fishing_enabled",
    "خیابونی":   "rescue_enabled",
    "قاچاق":     "smuggling_enabled",
    "کارخونه":   "factory_enabled",
    "یخچال":     "refrigerator_enabled",
}

# کلیدهایی که با تغییرشان باید یک اقدام لحظه‌ای اضافه (غیر از صرفِ cfg_set) انجام شود
GROUP_KEY_TO_RESCUE_RELOAD = "group_rescue"


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

    # فیلتر پیام تک‌نقطه‌ای: اگر بعد از حذف نقطه چیزی جز فاصله باقی نماند
    # (یعنی پیام دقیقاً «.» یا «. » و مشابه بود)، کاملاً و بی‌سروصدا نادیده گرفته
    # می‌شود — نه پاسخی، نه پیام «دستور نامعتبر است».
    if not cmd:
        return

    try:
        if cmd == "وضعیت":
            await event.edit(await build_status()); return
        if cmd == "تایمر":
            await event.edit(build_timers()); return

        # روشن / خاموش کردن ماژول‌ها
        if rest in ("روشن", "خاموش") and cmd in TOGGLE_COMMANDS:
            db_key = TOGGLE_COMMANDS[cmd]
            new_val = rest == "روشن"
            cfg_bool_set(db_key, new_val)
            log.info(f"[TOGGLE] ماژول '{cmd}' → {onoff(new_val)}")

            # طبق درخواست کاربر: هر بار یخچال روشن می‌شود، دیتابیس محلی کاملاً
            # ریست می‌شود تا سینک از صفر و کامل با یخچال واقعی انجام شود.
            if db_key == "refrigerator_enabled" and new_val:
                fridge_reset_all()
                log.info("[FRIDGE] به‌خاطر روشن‌شدن مجدد ماژول، لیست یخچال به‌طور کامل ریست شد.")

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

                # مورد ۲: دستور .تایم_کارخونه باید علاوه بر ذخیره مقدار،
                # تایمر فعلی را نیز فوراً ریست کند تا مقدار جدید از همین لحظه اعمال شود
                # (بدون نیاز به منتظرماندن برای پایان سیکل قبلی یا ریستارت ربات).
                if db_key == "factory_wait_sec":
                    reset_timer("factory")
                    log.info(f"[FACTORY] تایمر کارخونه دستی تنظیم شد: {rest} ثانیه — فوراً اعمال شد.")

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
                log.info(f"[GROUP] گروه '{db_key}' تغییر کرد → {cleaned} (بدون نیاز به ریستارت)")

            elif kind == "group_list":
                ids = [p.strip() for p in rest.split(",") if p.strip()]
                bad = [p for p in ids if not _is_int(p)]
                if bad or not ids:
                    await event.edit("❌ فرمت آیدی‌ها نامعتبر است. با کاما جدا کنید.")
                    return
                cfg_set(db_key, ",".join(ids))

                # مورد ۱۰: بروزرسانی لحظه‌ای لیسنر خیابونی — به محض تغییر .گروه_خیابونی
                # باید event handler قبلی حذف و با لیست جدید دوباره ثبت شود.
                if db_key == GROUP_KEY_TO_RESCUE_RELOAD:
                    log.info(f"[GROUP] لیست گروه‌های خیابونی تغییر کرد → {ids}")
                    rescue_groups_changed.set()

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
        await asyncio.sleep(wait)

    while True:
        if not cfg_bool("meow_enabled"):
            await asyncio.sleep(5)
            continue

        # مورد ۱۱: خواندن مجدد interval/لیست/گروه در هر دور — تضمین می‌کند
        # که مقدار جدید بلافاصله بعد از تغییر توسط دستور اعمال شود.
        interval = cfg_int("meow_sec", 245)
        choices = [x.strip() for x in cfg("meow_list", DEFAULT_CONFIG["meow_list"]).split(",") if x.strip()]
        if not choices:
            log.error("[MEOW] لیست میو خالی است — رد شد")
            await asyncio.sleep(interval)
            continue

        text = random.choice(choices)
        target = get_group("group_meow")
        if target is None:
            log.warning("[MEOW] گروه میو تنظیم نشده — رد شد.")
            await asyncio.sleep(interval)
            continue

        sent = await safe_send(target, text)
        if sent:
            set_last_run("meow", time.time())
            log.info(f"[MEOW] Sent Successfully → '{text}' → {target}")
        else:
            log.warning(f"[MEOW] ارسال ناموفق به گروه {target}")

        await asyncio.sleep(interval)


async def pishi_loop() -> None:
    interval = cfg_int("pishi_sec", 1480)
    wait = secs_left("pishi", interval)
    if wait > 0:
        log.info(f"[PISHI] {fmt_time(wait)} تا اجرای بعدی مانده")
        await asyncio.sleep(wait)

    while True:
        if not cfg_bool("pishi_enabled"):
            await asyncio.sleep(5)
            continue

        interval = cfg_int("pishi_sec", 1480)
        target = get_group("group_pishi")
        if target is None:
            log.warning("[PISHI] گروه پیشی تنظیم نشده — رد شد.")
            await asyncio.sleep(interval)
            continue

        try:
            sent = await safe_send(target, PISHI_MSG_TEXT)
            if not sent:
                log.warning(f"[PISHI] ارسال ناموفق به گروه {target}")
                await asyncio.sleep(interval)
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

        await asyncio.sleep(interval)


async def try_store_in_fridge(msg: Message, catch_text: str, fish_group: int) -> bool:
    """
    بررسی ۴ شرط ذخیره در یخچال (سند یخچال، مورد ۴) روی متن پیام صید ماهی:
      ۱) ماژول یخچال روشن باشد — این را خودِ فراخوان (fishing_loop) از قبل چک می‌کند.
      ۲) ارزش غذایی ماهی ≥ آستانه‌ی تنظیم‌شده (.حداقل_ارزش_غذایی).
      ۳) نوع ماهی (ایموجی) از قبل در یخچال (محلی) نباشد.
      ۴) ظرفیت یخچال پر نباشد.
    در صورت برقرار بودن همه، روی «بندازش تو یخچال» کلیک و ماهی در دیتابیس محلی
    ثبت می‌شود (وضعیت 'raw'). سپس — طبق درخواست کاربر — بلافاصله (بدون منتظر
    ماندن برای دور بعدی fridge_loop) فرآیند شروع پخت هم در همین‌جا اجرا می‌شود.
    خروجی: True یعنی ماهی به یخچال منتقل شد؛ False یعنی fishing_loop باید طبق
    روال سابق (فروش/تغذیه فوری) ادامه دهد.
    """
    food_val = parse_food_value(catch_text)
    fish_emo = parse_fish_emoji(catch_text)
    food_threshold = cfg_int("refrigerator_food_value_min", 5)

    cur_count = table_count("meow_refrigerator")
    max_cap = cfg_int("fridge_capacity_max", 0)

    cond_food = food_val is not None and food_val >= food_threshold
    cond_species = fish_emo is not None
    cond_dup = cond_species and not fridge_has(fish_emo)
    cond_room = max_cap > 0 and cur_count < max_cap

    log.info(
        f"[FRIDGE] بررسی شروط ذخیره | ارزش‌غذایی={food_val} (آستانه={food_threshold}) "
        f"| گونه={fish_emo} | غیرتکراری={'بله' if cond_dup else 'خیر'} "
        f"| ظرفیت={cur_count}/{max_cap or '؟'}"
    )

    if not (cond_food and cond_species and cond_dup and cond_room):
        log.info("[FRIDGE] شروط ذخیره در یخچال برقرار نبود — روال عادی فروش/تغذیه ادامه می‌یابد.")
        return False

    clicked = await click_by_text(msg, FRIDGE_STORE_BUTTON)
    if not clicked:
        log.warning("[FRIDGE] کلیک روی «بندازش تو یخچال» ناموفق بود (احتمالاً این دکمه در این صید موجود نبود).")
        return False

    fridge_add(fish_emo)
    log.info(f"[FRIDGE] ماهی '{fish_emo}' با موفقیت به یخچال منتقل شد ✓ — بلافاصله شروع پخت را امتحان می‌کنیم.")

    # طبق درخواست کاربر: به‌جای صبر برای دور بعدی fridge_loop، همین الان تلاش
    # می‌کنیم فرآیند پخت را شروع کنیم. یک مکث کوتاه می‌دهیم تا پیام «بندازش تو
    # یخچال» واقعاً روی سرور بازی اعمال شده باشد.
    await asyncio.sleep(2)
    try:
        started = await fridge_initiate_cook(fish_group, fish_emo)
        fridge_record_attempt(fish_emo, started)
        if started:
            log.info(f"[FRIDGE] پخت ماهی '{fish_emo}' بلافاصله بعد از ذخیره شروع شد ✓")
        else:
            log.info(
                f"[FRIDGE] شروع فوری پخت برای '{fish_emo}' موفق نشد — fridge_loop در دورهای "
                f"بعدی دوباره تلاش می‌کند."
            )
    except Exception as e:
        log.error(f"[FRIDGE] خطا در تلاش برای شروع فوری پخت '{fish_emo}': {e}")

    return True


async def fishing_loop() -> None:
    interval = cfg_int("fish_sec", 1500)
    wait = secs_left("fishing", interval)
    if wait > 0:
        log.info(f"[FISH] {fmt_time(wait)} تا اجرای بعدی مانده")
        await asyncio.sleep(wait)

    while True:
        if not cfg_bool("fishing_enabled"):
            await asyncio.sleep(5)
            continue

        interval = cfg_int("fish_sec", 1500)
        threshold = cfg_int("stomach", 7)
        target = get_group("group_fish")
        if target is None:
            log.warning("[FISH] گروه ماهیگیری تنظیم نشده — رد شد.")
            await asyncio.sleep(interval)
            continue

        try:
            sent = await safe_send(target, FISH_MSG_TEXT)
            if not sent:
                log.warning(f"[FISH] ارسال ناموفق به گروه {target}")
                await asyncio.sleep(interval)
                continue

            set_last_run("fishing", time.time())
            log.info(f"[FISH] پیام ارسال شد → {target} (id={sent.id}) | منتظر پاسخ بات...")

            # مورد ۴ سند یخچال: علاوه بر دکمه‌های سابق، احتمال وجود دکمه‌ی
            # «بندازش تو یخچال» را هم در انتظار پاسخ لحاظ می‌کنیم.
            msg = await wait_for_reply(
                target, sent.id, {SELL_FISH_BUTTON, GIVE_TO_CAT_BUTTON, FRIDGE_STORE_BUTTON}
            )
            if msg:
                catch_text = msg.text or ""
                used_fridge = False

                if cfg_bool("refrigerator_enabled", False):
                    fridge_group = get_group("refrigerator_group")
                    if fridge_group is not None:
                        used_fridge = await try_store_in_fridge(msg, catch_text, fridge_group)
                    else:
                        log.warning("[FRIDGE] گروه یخچال تنظیم نشده — ذخیره در یخچال رد شد.")

                if not used_fridge:
                    # بک‌آپ: روال دقیقاً طبق سابق (یخچال خاموش بود یا این صید واجد شرایط نبود)
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

        await asyncio.sleep(interval)


# ══════════════════════════════════════════════════
#  سیستم قاچاق میویی (loop دائمی)
# ══════════════════════════════════════════════════

async def smuggling_cycle() -> str:
    group = get_group("smuggling_group")
    if group is None:
        log.warning("[SMUGGLE] گروه قاچاق تنظیم نشده — رد شد.")
        return "retry"

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

        if is_arrested(text):
            log.info("[SMUGGLE] دستگیر شدیم — ورود به فرآیند زندان/جریمه.")
            await handle_prison(group)
            return "restart"

        if is_smuggle_success(text):
            await click_button(msg, 0, 0, fallback_text=SMUGGLE_FEE_TEXT)
            log.info("[SMUGGLE] کارمزد دریافت شد ✓")
            return "restart"

        cats = parse_street_cats(text)
        if cats is not None and msg.buttons:
            log.info(f"[SMUGGLE] پیشی‌های خیابونی: {cats} — کلیک شروع قاچاق")
            await click_button(msg, 0, 0, fallback_text=SMUGGLE_START_TEXT)
            fresh = await refresh_message(group, msg.id)
            if fresh:
                msg = fresh
            continue

        counts = parse_smuggle_count(text)
        if counts is not None:
            current, cap = counts
            eff_target = min(target_count, cap)

            dur = parse_duration(text)
            if dur is not None:
                last_wait = dur

            if current < eff_target:
                await click_button(msg, 0, 2, fallback_text=None)
                fresh = await refresh_message(group, msg.id)
                if fresh:
                    msg = fresh
                continue

            if current > eff_target:
                await click_button(msg, 0, 0, fallback_text=None)
                fresh = await refresh_message(group, msg.id)
                if fresh:
                    msg = fresh
                continue

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

        log.warning(f"[SMUGGLE] وضعیت پیام ناشناخته — رد شد: {text[:80]!r}")
        break

    log.warning("[SMUGGLE] سیکل بدون نتیجه قطعی پایان یافت.")
    return "retry"


async def handle_prison(group: int) -> None:
    try:
        sent = await safe_send(group, PRISON_TRIGGER)
        if not sent:
            log.warning(f"[SMUGGLE] ارسال «{PRISON_TRIGGER}» ناموفق بود.")
            return

        msg = await wait_for_bot_message(group, sent.id)
        if not msg:
            log.warning("[SMUGGLE] پاسخی برای زندان میویی دریافت نشد.")
            return

        await click_button(msg, 0, 0, fallback_text=None)
        fresh = await refresh_message(group, msg.id)
        if fresh:
            msg = fresh

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
        await asyncio.sleep(wait)

    while True:
        if not cfg_bool("smuggling_enabled"):
            await asyncio.sleep(5)
            continue

        try:
            status = await smuggling_cycle()
        except Exception as e:
            log.error(f"[SMUGGLE] خطای غیرمنتظره: {e}")
            status = "retry"

        if status == "started":
            wait = secs_left("smuggling", cfg_int("smuggling_wait_sec", 1800))
            await asyncio.sleep(wait if wait > 0 else SMUGGLE_RETRY_DELAY)
        elif status == "restart":
            await asyncio.sleep(SMUGGLE_RESTART_DELAY)
        else:
            await asyncio.sleep(SMUGGLE_RETRY_DELAY)


# ══════════════════════════════════════════════════
#  سیستم کارخونه میویی (loop زمان‌بندی‌شده)
# ══════════════════════════════════════════════════

async def factory_cycle() -> str:
    """
    یک سیکل تولید کارخونه میویی.
    خروجی: "started" | "in_progress" | "retry"

    مورد ۱ (بازطراحی کامل): اگر پیام نشان‌دهنده‌ی «در حال تولید» باشد، این تابع
    باید فقط زمان باقی‌مانده را بخواند و ذخیره کند — بدون هیچ کلیک، بدون هیچ
    refresh یا ورود به منوی دیگر، و بدون هیچ عملیاتی که احتمال لغو تولید در حال
    انجام را داشته باشد. این چک باید *قبل* از هرگونه کلیک روی پیام انجام شود.
    """
    group = get_group("factory_group")
    if group is None:
        log.warning("[FACTORY] گروه کارخونه تنظیم نشده — رد شد.")
        return "retry"

    sent = await safe_send(group, FACTORY_TRIGGER)
    if not sent:
        log.warning(f"[FACTORY] ارسال «{FACTORY_TRIGGER}» به گروه {group} ناموفق بود.")
        return "retry"

    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[FACTORY] پاسخی از بات دریافت نشد.")
        return "retry"

    raw_text = msg.text or ""

    # ── حالت «در حال تولید»: فقط خواندن متن — هیچ کلیکی مجاز نیست ──
    if is_factory_in_progress(raw_text):
        remaining = parse_remaining_time(raw_text)
        wait_sec = remaining if remaining is not None else cfg_int("factory_wait_sec", 3600)

        cfg_set("factory_wait_sec", str(wait_sec))
        set_last_run("factory", time.time())
        log.info(
            f"[FACTORY] تشخیص داده شد که تولید در حال انجام است | "
            f"زمان باقی‌مانده استخراج‌شده={fmt_time(wait_sec)} | "
            f"هیچ کلیک یا refresh اضافه‌ای انجام نشد."
        )
        return "in_progress"

    # ── از این‌جا به بعد، تولید در حال انجام نیست → شروع تولید جدید مجاز است ──
    try:
        log.info("[FACTORY] تولید در حال انجام نیست — شروع فرآیند تولید جدید (تولیدی هواپیما).")

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

        dur = parse_remaining_time(msg.text or "")
        wait_sec = dur if dur is not None else cfg_int("factory_wait_sec", 3600)

        await click_button(msg, 0, 0, fallback_text=FACTORY_START_TEXT)

        cfg_set("factory_wait_sec", str(wait_sec))
        set_last_run("factory", time.time())
        log.info(f"[FACTORY] تولید هواپیما با موفقیت شروع شد | زمان={fmt_time(wait_sec)}")
        return "started"
    except Exception as e:
        log.error(f"[FACTORY] خطا در بخش تولید: {e}")
        return "retry"


async def factory_warehouse_check(group: int) -> None:
    """
    ورود به انبار، بررسی ظرفیت، و در صورت غیرخالی بودن، بررسی قیمت بازار و فروش خودکار.

    مورد ۳: قبل از ورود به مسیر محصول→بازار→فروش، ابتدا ظرفیت انبار خوانده می‌شود.
    اگر مقدار فعلی انبار صفر باشد (مثلاً «ظرفیت انبار : 0 / 25,000 محصول»)، هیچ کلیک
    اضافه‌ای انجام نمی‌شود، وارد بخش محصول/بازار/فروش نمی‌شویم، فقط لاگ ثبت و تابع
    خاتمه می‌یابد.
    """
    sent = await safe_send(group, FACTORY_TRIGGER)
    if not sent:
        log.warning(f"[FACTORY] ارسال «{FACTORY_TRIGGER}» برای بررسی انبار ناموفق بود.")
        return
    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[FACTORY] پاسخی برای بررسی انبار دریافت نشد.")
        return

    # اگر همزمان تولید در حال انجام بود، از ورود به انبار صرف‌نظر می‌کنیم تا
    # هیچ کلیکی که ممکن است تداخل ایجاد کند زده نشود.
    if is_factory_in_progress(msg.text or ""):
        log.info("[FACTORY] هنگام بررسی انبار مشخص شد تولید در حال انجام است — بررسی قیمت لغو شد.")
        return

    await click_by_text(msg, WAREHOUSE_TEXT)
    fresh = await refresh_message(group, msg.id)
    if fresh:
        msg = fresh

    stock = parse_warehouse_stock(msg.text or "")
    if stock is not None:
        current, capacity = stock
        if current <= 0:
            log.info("[FACTORY] انبار خالی است — بررسی قیمت انجام نشد")
            return
        log.info(f"[FACTORY] ظرفیت انبار: {current} / {capacity} — ادامه به بررسی قیمت بازار.")
    else:
        log.warning("[FACTORY] ظرفیت انبار قابل تشخیص نبود — به‌صورت احتیاطی ادامه داده می‌شود.")

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
        log.info(f"[FACTORY] قیمت بازار={price} ≥ آستانه={threshold} → شروع فروش محصول")
        await click_button(msg, 0, 0, fallback_text=SELL_PRODUCT_TEXT)
        fresh = await refresh_message(group, msg.id)
        if fresh and fresh.buttons:
            await click_button(fresh, 0, 0, fallback_text=None)
            log.info("[FACTORY] فروش با موفقیت تایید شد ✓")
        else:
            log.info("[FACTORY] فروش با موفقیت انجام شد ✓")
    else:
        log.info(f"[FACTORY] قیمت بازار={price} < آستانه={threshold} → فروشی انجام نشد")


def seconds_until_next_31() -> float:
    now_ts = time.time()
    now = time.localtime(now_ts)
    this_hour_31 = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, 31, 0, 0, 0, -1))
    if this_hour_31 > now_ts:
        return this_hour_31 - now_ts
    return (this_hour_31 + 3600) - now_ts


async def factory_price_watch_loop() -> None:
    while True:
        wait = seconds_until_next_31()
        log.info(f"[FACTORY-PRICE] {fmt_time(wait)} تا بررسی بعدی قیمت بازار (ساعت:۳۱)")
        await asyncio.sleep(wait)

        if not cfg_bool("factory_enabled"):
            continue

        try:
            group = get_group("factory_group")
            if group is None:
                log.warning("[FACTORY-PRICE] گروه کارخونه تنظیم نشده — رد شد.")
                continue
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
        await asyncio.sleep(wait)

    while True:
        if not cfg_bool("factory_enabled"):
            await asyncio.sleep(5)
            continue

        try:
            status = await factory_cycle()
        except Exception as e:
            log.error(f"[FACTORY] خطای غیرمنتظره: {e}")
            status = "retry"

        if status in ("started", "in_progress"):
            wait = secs_left("factory", cfg_int("factory_wait_sec", 3600))
            await asyncio.sleep(wait if wait > 0 else FACTORY_RETRY_DELAY)
        else:
            await asyncio.sleep(FACTORY_RETRY_DELAY)


# ══════════════════════════════════════════════════
#  سیستم یخچال میویی (loop مستقل)
# ══════════════════════════════════════════════════
#
# این حلقه، مانند smuggling_loop/factory_loop، کاملاً مستقل و پایدار است.
# مسئولیت‌ها عمداً از fishing_loop جدا شده‌اند (اصل «جداسازی ماژولار»):
#   • fishing_loop فقط تصمیم می‌گیرد که آیا ماهیِ تازه‌صید‌شده باید داخل
#     یخچال گذاشته شود یا نه، و در صورت مثبت بودن فقط کلیک اولیه را می‌زند
#     و ماهی را با وضعیت 'raw' در جدول محلی ثبت می‌کند.
#   • تمام مراحل بعدی — شروع پخت، انتظار برای اتمام پخت، جمع‌آوری و تصمیم
#     نهایی فروش/تغذیه — به‌طور کامل توسط همین حلقه مدیریت می‌شود.
# چون تمام وضعیت (raw/cooking/cooked + cook_ready_at) در جدول
# meow_refrigerator ذخیره شده و هر دور دوباره از دیتابیس خوانده می‌شود، این
# حلقه در برابر ری‌استارت ربات کاملاً مقاوم است — نیازی به نگه‌داشتن هیچ
# وضعیتی در حافظه نیست.


def _sync_capacity_from_text(text: str) -> None:
    """در صورت وجود «ظرفیت یخچال : X / Y» در متن، مقدار حداکثر (Y) را در کانفیگ به‌روز می‌کند."""
    cap = parse_fridge_capacity(text)
    if cap is not None:
        _, mx = cap
        if mx > 0:
            cfg_set("fridge_capacity_max", str(mx))


async def fridge_sync_if_empty(group: int) -> None:
    """
    مورد ۳ سند یخچال: اگر جدول محلی یخچال کاملاً خالی باشد و هنوز سینکی روی این
    دوره‌ی «روشن بودن» ماژول انجام نشده باشد، پیام «یخچال میویی» ارسال و از روی
    پاسخ، ظرفیت و لیست موجودی فعلی سینک می‌شود.

    این کار *دقیقاً یک‌بار* در هر دوره‌ی روشن‌بودنِ ماژول انجام می‌شود — چه
    یخچال واقعی چیزی داشته باشد چه خالی باشد، نتیجه فرقی نمی‌کند: بعد از یک
    تلاش، پرچم fridge_synced_once ست می‌شود و دیگر تا زمانی که کاربر دوباره
    «.یخچال خاموش» و «.یخچال روشن» نزند (که fridge_reset_all این پرچم را پاک
    می‌کند)، هیچ سینک خودکار دیگری انجام نمی‌شود.
    """
    if cfg_bool("fridge_synced_once", False):
        return
    if table_count("meow_refrigerator") != 0:
        return

    cfg_bool_set("fridge_synced_once", True)  # قبل از تلاش ست می‌شود تا هرگز دوباره تکرار نشود

    sent = await safe_send(group, FRIDGE_TRIGGER)
    if not sent:
        log.warning(f"[FRIDGE] ارسال «{FRIDGE_TRIGGER}» برای سینک اولیه ناموفق بود — دیگر خودکار تکرار نمی‌شود.")
        return
    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[FRIDGE] پاسخی برای سینک اولیه یخچال دریافت نشد — دیگر خودکار تکرار نمی‌شود.")
        return

    text = msg.text or ""
    _sync_capacity_from_text(text)

    if is_fridge_empty(text):
        log.info("[FRIDGE] سینک انجام شد | یخچال واقعاً خالی است — هیچ ماهی‌ای برای افزودن نبود.")
        return

    entries = parse_fridge_entries(text)
    for e in entries:
        if not e["emoji"]:
            continue
        fridge_add(e["emoji"])
        if e["cooked"]:
            fridge_set_status(e["emoji"], "cooked")
    log.info(f"[FRIDGE] سینک اولیه انجام شد | {len(entries)} ماهی شناسایی شد.")


async def fridge_initiate_cook(group: int, emo: str) -> bool:
    """
    مورد ۵ سند یخچال: ورود به گروه یخچال، پیدا کردن دکمه‌ی مربوط به ماهی 'emo'
    بر اساس ترتیب آن در متن، کلیک روی آن و سپس تایید شروع پخت.

    موقعیت دکمه (طبق تایید صریح کاربر): دکمه‌ها هیچ متنی ندارند و فقط بر اساس
    «موقعیت» مشخص می‌شوند — نه با اسکن‌کردن پیام برای دکمه‌های خالی:
      • اگر دکمه‌ی متنیِ «ارتقا سطح یخچال» نبود → ماهیِ اول = (ردیف۰, ستون۰)
      • اگر آن دکمه بود (ردیف۰ را اشغال کرده) → ماهیِ اول = (ردیف۱, ستون۰)
    در هر دو حالت، ستون = ایندکس ماهی در لیست متن (fridge_fish_button_position).
    """
    sent = await safe_send(group, FRIDGE_TRIGGER)
    if not sent:
        log.warning(f"[FRIDGE] ارسال «{FRIDGE_TRIGGER}» برای شروع پخت ناموفق بود.")
        return False

    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        log.warning("[FRIDGE] پاسخی برای شروع پخت دریافت نشد.")
        return False

    listing_text = msg.text or ""
    _sync_capacity_from_text(listing_text)

    if is_fridge_empty(listing_text):
        log.warning(
            f"[FRIDGE] یخچال واقعی خالی است ولی دیتابیس محلی ماهی '{emo}' را دارد — "
            f"رکورد محلی ناهماهنگ حذف شد (خودترمیمی)."
        )
        fridge_remove(emo)
        return False

    entries = parse_fridge_entries(listing_text)
    idx = next((i for i, e in enumerate(entries) if e["emoji"] == emo), None)
    if idx is None:
        log.warning(f"[FRIDGE] ماهی '{emo}' در لیست یخچال پیدا نشد — منتظر سینک بعدی می‌مانیم.")
        return False

    row, col = fridge_fish_button_position(msg, idx)
    btn = get_button(msg, row=row, col=col)
    if btn is None:
        log.warning(f"[FRIDGE] دکمه‌ی متناظر با ماهی '{emo}' در موقعیت (ردیف={row}, ستون={col}) پیدا نشد.")
        return False

    if not await raw_click(msg, btn):
        log.warning(f"[FRIDGE] کلیک روی دکمه‌ی ماهی '{emo}' (ردیف={row}, ستون={col}) ناموفق بود.")
        return False

    fresh = await refresh_message(group, msg.id)
    if not fresh:
        log.warning("[FRIDGE] پیام صفحه‌ی مشخصات ماهی دریافت نشد.")
        return False

    detail_text = fresh.text or ""

    # اگر متن هنوز به‌روزرسانی نشده (پخیدن شروع نشده)، دنبال جدیدترین پیام بات بگرد
    if "پخیدن" not in detail_text and "زمان مورد نیاز" not in detail_text:
        newer = await wait_for_bot_message(group, msg.id, timeout=10)
        if newer:
            fresh = newer
            detail_text = fresh.text or ""

    cook_dur = parse_cook_duration(detail_text)
    if cook_dur is None:
        cook_dur = 120
        log.warning(f"[FRIDGE] زمان پخت برای '{emo}' پارس نشد — از fallback {cook_dur} ثانیه استفاده شد.")

        
    detail_text = fresh.text or ""
    cook_dur = parse_cook_duration(detail_text)
    if cook_dur is None:
        cook_dur = 120  # fallback ایمن — اگر زمان از متن پارس نشد
        log.warning(f"[FRIDGE] زمان پخت برای '{emo}' پارس نشد — از fallback {cook_dur} ثانیه استفاده شد.")

    # تایید شروع پخت: مطابق الگوی موجود در factory_cycle، کلیک «موقعیتی» (۰,۰)
    # اصل ماجراست؛ متن fallback فقط برای مقاومت در برابر جابه‌جایی موقعیت است.
    await click_button(fresh, 2, 0, fallback_text=FRIDGE_COOK_CONFIRM_TEXT)

    confirm_msg = await refresh_message(group, fresh.id)
    if confirm_msg:
        await click_button(confirm_msg, 0, 0, fallback_text=None)

    now = time.time()
    fridge_set_status(emo, "cooking", cook_started_at=now, cook_ready_at=now + cook_dur)
    log.info(f"[FRIDGE] پخت ماهی '{emo}' آغاز شد | زمان لازم={fmt_time(cook_dur)}")
    return True


async def fridge_collect_cooked(group: int, emo: str) -> bool:
    """جمع‌آوری ماهی پخته‌شده + تصمیم فروش یا تغذیه"""
    sent = await safe_send(group, FRIDGE_TRIGGER)
    if not sent:
        log.warning(f"[FRIDGE] ارسال پیام یخچال ناموفق")
        return False

    msg = await wait_for_bot_message(group, sent.id)
    if not msg:
        return False

    listing_text = msg.text or ""
    _sync_capacity_from_text(listing_text)

    if is_fridge_empty(listing_text):
        log.warning(f"[FRIDGE] ماهی '{emo}' دیگر در یخچال نیست — حذف محلی")
        fridge_remove(emo)
        return False

    entries = parse_fridge_entries(listing_text)
    idx = next((i for i, e in enumerate(entries) if e["emoji"] == emo), None)
    if idx is None:
        log.warning(f"[FRIDGE] ماهی '{emo}' در لیست پیدا نشد")
        return False

    # باز کردن صفحه ماهی
    row, col = fridge_fish_button_position(msg, idx)
    if not await raw_click(msg, get_button(msg, row=row, col=col)):
        log.warning(f"[FRIDGE] کلیک روی ماهی '{emo}' ناموفق")
        return False

    fresh = await refresh_message(group, msg.id, tries=8, delay=0.8)
    if not fresh:
        return False

    detail_text = fresh.text or ""
    if not is_cooked_label(detail_text):
        log.info(f"[FRIDGE] ماهی هنوز پخته نشده")
        return False

    fish_value = parse_fish_value(detail_text)
    stomach = get_stomach()
    stomach_threshold = cfg_int("stomach", 7)
    value_threshold = cfg_int("refrigerator_fish_value_max", 5000)

    feed = (stomach < stomach_threshold) and (fish_value is not None and fish_value < value_threshold)
    target_btn_text = GIVE_TO_CAT_BUTTON if feed else SELL_FISH_BUTTON

    log.info(
        f"[FRIDGE] ماهی '{emo}' آماده | ارزش={fish_value} | شکم={stomach} → "
        f"{'تغذیه' if feed else 'فروش'}"
    )

    # === کلیک موقعیتی (قوی‌تر) ===
    success = False
    
    if feed:
        # بده پیشی بخوره → ردیف 1، ستون 0
        success = await click_button(fresh, 1, 0)
    else:
        # فروش ماهی → ردیف 0، ستون 0
        success = await click_button(fresh, 0, 0)

    # fallback متنی در صورت شکست
    if not success:
        success = await click_by_text(fresh, target_btn_text)

    if success:
        log.info(f"[FRIDGE] ✅ اقدام موفق: {target_btn_text}")
        fridge_remove(emo)
        return True
    else:
        log.error(f"[FRIDGE] ❌ هر دو روش کلیک (موقعیتی + متنی) شکست خورد برای '{target_btn_text}'")
        # ماهی را حذف نمی‌کنیم تا دور بعدی دوباره تلاش کند
        return False


async def fridge_loop() -> None:
    """
    حلقه‌ی مدیریت کامل چرخه‌ی یخچال میویی. هر دور *فقط یک* اقدام انجام می‌دهد
    (جمع‌آوری، یا شروع پخت، یا سینک) — هرگز بیش از یکی در یک دور، تا از ارسال
    پی‌درپی چند پیام به گروه یخچال در عرض چند ثانیه جلوگیری شود.

    اگر ماهی‌ای در یخچال واقعی پیدا نشود (ناهماهنگی دیتابیس محلی)، به‌جای تلاش
    بی‌وقفه در هر دور، یک backoff اعمال می‌شود (fridge_should_attempt) تا حداکثر
    هر FRIDGE_MISS_BACKOFF_SEC ثانیه یک‌بار دوباره امتحان شود، و بعد از
    FRIDGE_MISS_GIVE_UP بار شکست پیاپی، دیگر خودکار تلاش نمی‌شود (نیاز به بررسی
    دستی — احتمالاً یعنی آن ماهی دیگر واقعاً در یخچال بازی وجود ندارد).
    """
    while True:
        if not cfg_bool("refrigerator_enabled", False):
            await asyncio.sleep(5)
            continue

        group = get_group("refrigerator_group")
        if group is None:
            log.warning("[FRIDGE] گروه یخچال تنظیم نشده — رد شد.")
            await asyncio.sleep(cfg_int("fridge_poll_sec", FRIDGE_DEFAULT_POLL))
            continue

        try:
            due_now = [e for e in fridge_due_now() if fridge_should_attempt(e)]
            if due_now:
                emo = due_now[0]
                ok = await fridge_collect_cooked(group, emo)
                fridge_record_attempt(emo, ok)
                if not ok:
                    log.warning(
                        f"[FRIDGE] ماهی '{emo}' در یخچال واقعی پیدا نشد — احتمالاً دیتابیس "
                        f"محلی با بازی هماهنگ نیست. تا {FRIDGE_MISS_BACKOFF_SEC} ثانیه دیگر "
                        f"دوباره امتحان می‌شود (حداکثر {FRIDGE_MISS_GIVE_UP} بار)."
                    )
            else:
                raw_pending = [e for e in fridge_list_raw() if fridge_should_attempt(e)]
                if raw_pending:
                    emo = raw_pending[0]
                    ok = await fridge_initiate_cook(group, emo)
                    fridge_record_attempt(emo, ok)
                    if not ok:
                        log.warning(
                            f"[FRIDGE] ماهی '{emo}' برای شروع پخت در یخچال واقعی پیدا نشد — "
                            f"تا {FRIDGE_MISS_BACKOFF_SEC} ثانیه دیگر دوباره امتحان می‌شود "
                            f"(حداکثر {FRIDGE_MISS_GIVE_UP} بار)."
                        )
                elif table_count("meow_refrigerator") == 0:
                    await fridge_sync_if_empty(group)
        except Exception as e:
            log.error(f"[FRIDGE] خطای غیرمنتظره در حلقه یخچال: {e}")

        # فاصله‌ی خواب: طبق fridge_poll_sec، مگر این‌که یک پخت واقعاً زودتر آماده شود
        sleep_for = cfg_int("fridge_poll_sec", FRIDGE_DEFAULT_POLL)
        next_ready = fridge_next_ready_at()
        if next_ready is not None:
            remaining = next_ready - time.time()
            if 0 < remaining < sleep_for:
                sleep_for = remaining + 2

        await asyncio.sleep(max(3, sleep_for))


# ══════════════════════════════════════════════════
#  Rescue Listener — با پشتیبانی از بروزرسانی لحظه‌ای (مورد ۱۰)
# ══════════════════════════════════════════════════

async def sniper_click(msg: Message, action_type: str):
    raw_text = msg.text or ""

    if ("یک پیشی خیابونی توی شهر پیدا شد" in raw_text or "لطفا به پیشی" in raw_text) and "نجات داد" not in raw_text:
        
        log.info(f"🎯 [پیشی شکار شد!] ──> شروع فاز اول ترکیبی (کلیک + ری‌اکشن)...")
        
        try:
            # ۱. ری‌اکشن قلب اول
            await client(SendReactionRequest(peer=msg.chat_id, msg_id=msg.id, reaction=[ReactionEmoji(emoticon='❤️')]))
            await asyncio.sleep(0.9)

            # ۲. کلیک اول
            await msg.click(0, 0)
            await asyncio.sleep(0.5)

            # ۳. حذف ری‌اکشن اول
            await client(SendReactionRequest(peer=msg.chat_id, msg_id=msg.id, reaction=[]))
            await asyncio.sleep(0.5)

            # ۴. کلیک دوم
            await msg.click(0, 0)
            await asyncio.sleep(0.5)

            # ۵. ری‌اکشن قلب دوم
            await client(SendReactionRequest(peer=msg.chat_id, msg_id=msg.id, reaction=[ReactionEmoji(emoticon='❤️')]))
            await asyncio.sleep(0.5)

            # ۶. کلیک سوم
            await msg.click(0, 0)
            await asyncio.sleep(0.5)

            # ۷. حذف ری‌اکشن دوم
            await client(SendReactionRequest(peer=msg.chat_id, msg_id=msg.id, reaction=[]))
            
            log.info("⚡️ فاز اول ترکیبی با موفقیت انجام شد.")

        except Exception as e:
            log.error(f"خطا در شلیک اولیه: {e}")
        # ----------------------------------------
        # مهلت به سرور بازی و آپدیت وضعیت پیام
        await asyncio.sleep(1.0)
        msg = await client.get_messages(msg.chat_id, ids=msg.id)

        # 🛡 فاز دوم (پیگیری امن در صورت غیب نشدن دکمه)
        if msg.buttons:
            log.info("⚠️ دکمه هنوز هست؛ ورود به فاز دوم (۱۵ کلیک امن با تایمر)...")
            max_attempts = 15
            attempt = 0
            
            while msg.buttons and attempt < max_attempts:
                attempt += 1
                try:
                    client.loop.create_task(msg.click(0, 0))
                    await asyncio.sleep(0.5)
                    msg = await client.get_messages(msg.chat_id, ids=msg.id)
                except Exception as e:
                    log.error(f"❌ خطا در فاز دوم: {e}")
                    break

        # نتیجه نهایی
        if not msg.buttons:
            log.info("✅ عالیه! دکمه با موفقیت غیب شد.")
            return True
        else:
            log.warning("🛑 دکمه غیب نشد. ربات رفت خونش.")
            return False

    return False

async def rescue_listener() -> None:
    """
    مورد ۱۰: به‌جای ثبت یک‌بارِ ثابت در استارت برنامه، این حلقه بیرونی هر بار که
    .گروه_خیابونی تغییر کند (از طریق rescue_groups_changed.set() در handle_command)
    هندلرهای قبلی را remove_event_handler می‌کند و با لیست جدید دوباره ثبت می‌کند —
    بدون نیاز به ریستارت یا reconnect.
    """
    current_handlers: list = []

    def _register(groups: list):
        bot_list = list(TARGET_BOTS)

        async def handle_new_msg(event):
            if not cfg_bool("rescue_enabled"):
                return
            await sniper_click(event.message, "پیام جدید")

        async def handle_edited_msg(event):
            if not cfg_bool("rescue_enabled"):
                return
            await sniper_click(event.message, "پیام ادیت‌شده/فرصت مجدد")

        client.add_event_handler(handle_new_msg, events.NewMessage(chats=groups, from_users=bot_list))
        client.add_event_handler(handle_edited_msg, events.MessageEdited(chats=groups, from_users=bot_list))
        return [handle_new_msg, handle_edited_msg]

    def _unregister(handlers: list):
        for h in handlers:
            try:
                client.remove_event_handler(h)
            except Exception as e:
                log.warning(f"[RESCUE] خطا در حذف هندلر قدیمی: {e}")

    rescue_groups = get_group_list("group_rescue")
    current_handlers = _register(rescue_groups)
    if rescue_groups:
        log.info(f"[RESCUE] لیسنر خیابونی ثبت شد برای گروه‌ها: {rescue_groups}")
    else:
        log.warning(f"[RESCUE] هیچ گروه خیابونی‌ای ست نشده — {GROUP_NOT_SET_TEXT} (لیسنر با لیست خالی ثبت شد).")

    while True:
        await rescue_groups_changed.wait()
        rescue_groups_changed.clear()

        new_groups = get_group_list("group_rescue")
        log.info(f"[RESCUE] تغییر گروه‌های خیابونی شناسایی شد — بروزرسانی لیسنر بدون ریستارت.")

        _unregister(current_handlers)
        current_handlers = _register(new_groups)
        log.info(f"[RESCUE] لیسنر خیابونی مجدداً ثبت شد برای گروه‌های جدید: {new_groups}")


# ══════════════════════════════════════════════════
#  Command Listener
# ══════════════════════════════════════════════════

async def command_listener() -> None:
    @client.on(events.NewMessage(outgoing=True))
    async def handler(event):
        text = (event.message.text or "").strip()
        if text == MENU_TRIGGER or text.startswith("."):
            if not cfg_bool("self_enabled") and text != MENU_TRIGGER:
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
    log.info(f"[SYSTEM] گروه میو: {get_group('group_meow') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه پیشی: {get_group('group_pishi') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه ماهیگیری: {get_group('group_fish') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه‌های خیابونی: {get_group_list('group_rescue') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه قاچاق: {get_group('smuggling_group') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه کارخونه: {get_group('factory_group') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] گروه یخچال: {get_group('refrigerator_group') or GROUP_NOT_SET_TEXT}")
    log.info(f"[SYSTEM] شکم فعلی: {get_stomach()}")
    log.info(f"[SYSTEM] سلف={onoff(cfg_bool('self_enabled'))} میو={onoff(cfg_bool('meow_enabled'))} "
             f"پیشی={onoff(cfg_bool('pishi_enabled'))} ماهیگیری={onoff(cfg_bool('fishing_enabled'))} "
             f"خیابونی={onoff(cfg_bool('rescue_enabled'))} قاچاق={onoff(cfg_bool('smuggling_enabled'))} "
             f"کارخونه={onoff(cfg_bool('factory_enabled'))} یخچال={onoff(cfg_bool('refrigerator_enabled'))}")
    log.info(f"[SYSTEM] ربات فعال شد — برای منو در تلگرام {MENU_TRIGGER} را ارسال کنید.\n")

    await asyncio.gather(
        meow_loop(),
        pishi_loop(),
        fishing_loop(),
        rescue_listener(),
        smuggling_loop(),
        factory_loop(),
        factory_price_watch_loop(),
        fridge_loop(),
        command_listener(),
    )


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
