#!/usr/bin/env python3
"""Telegram bot for expiry cam (runs on the Pi 5 next to server.py).

- Every day at REMIND_TIME: products that expire within REMIND_DAYS days.
  Each product is mentioned in one reminder only (REMIND_ONCE).
- After midnight: expired products are deleted together with their photos.
- /list, /soon, /del_<id>, /lang (ru/en), /stop, /start, /help

Talks to the Telegram Bot API directly with requests (long polling: no open
ports or public IP needed). Settings come from environment variables, see bot.env.example.
Uses the Pi's local time, so check `timedatectl` shows Europe/Berlin.
"""
import html
import logging
import os
import re
import socket
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import requests

from core import dates, db

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("bot")


def _load_env_file(path) -> None:
    """KEY=VALUE lines from bot.env; real environment variables win (systemd)."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.env"))

# --- settings ------------------------------------------------------------------------
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
ALLOWED_IDS = {int(x) for x in re.split(r"[,\s]+", os.environ.get("TELEGRAM_ALLOWED_IDS", ""))
               if x.strip().lstrip("-").isdigit()}
REMIND_H, REMIND_M = (int(x) for x in os.environ.get("REMIND_TIME", "09:00").split(":"))
REMIND_DAYS = int(os.environ.get("REMIND_DAYS", "3"))
REMIND_ONCE = os.environ.get("REMIND_ONCE", "1") != "0"
FORCE_IPV4 = os.environ.get("TELEGRAM_FORCE_IPV4", "0") == "1"   # for broken home IPv6

API = f"https://api.telegram.org/bot{TOKEN}/"
POLL_TIMEOUT = 25          # long polling: Telegram holds the request up to this long
CONNECT_TIMEOUT = 5        # a dead network path must fail fast, not after 35 s
SLOW_CALL_S = 2.0          # log API calls slower than this

if FORCE_IPV4:
    import urllib3.util.connection
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

# One keep-alive connection: no DNS lookup and TLS handshake for every message
_session = requests.Session()
MAX_MESSAGE = 3800         # Telegram limit is 4096 characters
BOT_USERNAME = ""          # filled by getMe, used to ignore /cmd@OtherBot in groups

# --- texts ---------------------------------------------------------------------------
TEXTS = {
    "ru": {
        "help": ("Привет! Я слежу за сроками годности.\n"
                 "В {time} напоминаю о продуктах, у которых срок истекает "
                 "в ближайшие {days_word}{once}.\n"
                 "Просроченное удаляется само.\n\n"
                 "/list — всё, что отсканировано\n"
                 "/soon — что истекает скоро\n"
                 "/lang — язык / language\n"
                 "/stop — не присылать напоминания"),
        "once": " — один раз на каждый продукт",
        "reminder": "⏰ <b>Скоро истекает срок годности</b>",
        "list_title": "📦 <b>Отсканировано: {n}</b>",
        "list_empty": "Пока ничего не отсканировано.",
        "g_expired": "Просрочено",
        "g_soon": "Скоро — до {days}",
        "g_month": "До 30 дней",
        "g_quarter": "До 3 месяцев",
        "g_later": "Позже",
        "btn_delete_menu": "🗑 Удалить…",
        "btn_delete_this": "🗑 Удалить: {name}",
        "btn_back": "⬅ Назад",
        "btn_close": "✖ Отмена",
        "toast_deleted": "Удалено: {name}",
        "soon_title": "⏰ <b>Истекает в ближайшие {days_word}</b>",
        "soon_empty": "В ближайшие {days_word} ничего не истекает.",
        "confirm": "Удалить «{name}» ({date})?",
        "btn_delete": "🗑 Удалить",
        "btn_cancel": "Отмена",
        "deleted": "Удалено: {name} ({date})",
        "cancelled": "Отменено.",
        "not_found": "Этого продукта уже нет в списке.",
        "lang_prompt": "Выбери язык / Choose language:",
        "lang_set": "Язык: русский",
        "stopped": "Напоминания выключены. Включить снова — /start",
        "denied": "Нет доступа. ID этого чата: <code>{id}</code>\nПопроси владельца добавить его.",
        "no_name": "Без названия",
        "today": "сегодня",
        "tomorrow": "завтра",
        "expired": "просрочено",
    },
    "en": {
        "help": ("Hi! I keep track of expiry dates.\n"
                 "At {time} I remind you about products expiring within {days_word}{once}.\n"
                 "Expired products are removed automatically.\n\n"
                 "/list — everything scanned\n"
                 "/soon — expiring soon\n"
                 "/lang — язык / language\n"
                 "/stop — no more reminders"),
        "once": ", once per product",
        "reminder": "⏰ <b>Expiring soon</b>",
        "list_title": "📦 <b>Scanned: {n}</b>",
        "list_empty": "Nothing scanned yet.",
        "g_expired": "Expired",
        "g_soon": "Soon — within {days}",
        "g_month": "Within 30 days",
        "g_quarter": "Within 3 months",
        "g_later": "Later",
        "btn_delete_menu": "🗑 Delete…",
        "btn_delete_this": "🗑 Delete: {name}",
        "btn_back": "⬅ Back",
        "btn_close": "✖ Cancel",
        "toast_deleted": "Deleted: {name}",
        "soon_title": "⏰ <b>Expiring within {days_word}</b>",
        "soon_empty": "Nothing expires within {days_word}.",
        "confirm": "Delete “{name}” ({date})?",
        "btn_delete": "🗑 Delete",
        "btn_cancel": "Cancel",
        "deleted": "Deleted: {name} ({date})",
        "cancelled": "Cancelled.",
        "not_found": "This product is no longer in the list.",
        "lang_prompt": "Выбери язык / Choose language:",
        "lang_set": "Language: English",
        "stopped": "Reminders are off. /start turns them back on.",
        "denied": "No access. ID of this chat: <code>{id}</code>\nAsk the owner to add it.",
        "no_name": "Unknown product",
        "today": "today",
        "tomorrow": "tomorrow",
        "expired": "expired",
    },
}

COMMANDS = {
    "ru": [("list", "Всё, что отсканировано"), ("soon", "Что истекает скоро"),
           ("lang", "Язык / language"), ("stop", "Выключить напоминания"),
           ("help", "Помощь")],
    "en": [("list", "Everything scanned"), ("soon", "Expiring soon"),
           ("lang", "Язык / language"), ("stop", "Turn reminders off"),
           ("help", "Help")],
}


def t(lang: str, key: str, **kw) -> str:
    return TEXTS[lang][key].format(**kw)


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days_word(lang: str, n: int) -> str:
    """'3 дня' / '3 days'"""
    if lang == "ru":
        return f"{n} {ru_plural(n, 'день', 'дня', 'дней')}"
    return f"{n} day" if n == 1 else f"{n} days"


def when(lang: str, days_left: int) -> str:
    if days_left < 0:
        return t(lang, "expired")
    if days_left == 0:
        return t(lang, "today")
    if days_left == 1:
        return t(lang, "tomorrow")
    return ("через " if lang == "ru" else "in ") + days_word(lang, days_left)


def days_until(lang: str, n: int) -> str:
    """'3 дней' / '3 days' (after 'до' / 'within')"""
    if lang == "ru":
        return f"{n} {'дня' if n % 10 == 1 and n % 100 != 11 else 'дней'}"
    return days_word(lang, n)


def plain_name(lang: str, p: dict, brand: bool = True) -> str:
    """'Name (Brand)' or 'Unknown product · 4006…', not escaped (for buttons)."""
    name = p.get("product_name")
    if not name:
        return t(lang, "no_name") + (f" · {p['barcode']}" if p.get("barcode") else "")
    if brand and p.get("product_brand") and p["product_brand"].lower() not in name.lower():
        name = f"{name} ({p['product_brand']})"
    return name


def product_name(lang: str, p: dict, brand: bool = True) -> str:
    """Escaped name for HTML messages."""
    return html.escape(plain_name(lang, p, brand))


def product_date(p: dict) -> str:
    """As printed on the package: '18.01.2027', '12/2026', '27.07.'"""
    return html.escape(dates.display(p["parsed_expiry_date"]) or p["expires_on"])


NBSP = "\u00a0"


def short_date(p: dict) -> str:
    """Compact date for the date column: '18.01.27', '12/26', '27.07.'"""
    text = dates.display(p["parsed_expiry_date"]) or p["expires_on"]
    if len(text) == 10 and text[2] == "." and text[5] == ".":     # 18.01.2027
        text = text[:6] + text[8:]
    elif len(text) == 7 and text[2] == "/":                        # 12/2026
        text = text[:3] + text[5:]
    return text


def date_cell(p: dict) -> str:
    """Date as monospace chip of equal width, so the names form a straight column."""
    return f"<code>{html.escape(short_date(p)).ljust(8, NBSP)}</code>"


def days_left(p: dict, today: date) -> int:
    return (date.fromisoformat(p["expires_on"]) - today).days


# --- Telegram API ----------------------------------------------------------------------
class TelegramError(Exception):
    pass


def _safe(text: str) -> str:
    """Never let the token end up in the log (request URLs contain it)."""
    return str(text).replace(TOKEN, "<token>") if TOKEN else str(text)


def api(method: str, **params):
    params = {k: v for k, v in params.items() if v is not None}
    read_timeout = POLL_TIMEOUT + 10 if method == "getUpdates" else 15
    retried_conn = retried_flood = False
    while True:
        t0 = time.monotonic()
        try:
            r = _session.post(API + method, json=params, timeout=(CONNECT_TIMEOUT, read_timeout))
            data = r.json()
        except requests.ConnectionError as e:
            if not retried_conn:           # e.g. Telegram closed the idle keep-alive socket
                retried_conn = True
                log.info("%s: connection lost, retrying", method)
                continue
            raise TelegramError(_safe(f"{method}: {e}")) from None
        except (requests.RequestException, ValueError) as e:
            raise TelegramError(_safe(f"{method}: {e}")) from None

        elapsed = time.monotonic() - t0
        if method != "getUpdates" and elapsed > SLOW_CALL_S:
            log.warning("slow Telegram call %s: %.1f s", method, elapsed)
        if data.get("ok"):
            return data["result"]
        retry = (data.get("parameters") or {}).get("retry_after")
        if retry and not retried_flood:    # flood limit: wait and try once more
            retried_flood = True
            time.sleep(min(int(retry), 30))
            continue
        raise TelegramError(f"{method}: {data.get('description')}")


def send(chat_id: int, text: str, buttons: Optional[list] = None):
    markup = {"inline_keyboard": buttons} if buttons else None
    return api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
               reply_markup=markup)


def chunks_of(lines: List[str]) -> List[str]:
    """Join lines into messages below Telegram's size limit."""
    chunks, chunk = [], ""
    for line in lines:
        if chunk and len(chunk) + len(line) + 1 > MAX_MESSAGE:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        chunks.append(chunk)
    return chunks


def send_long(chat_id: int, lines: List[str], buttons: Optional[list] = None) -> None:
    """Send lines, split into several messages if needed; buttons go on the last one."""
    chunks = chunks_of(lines)
    for i, chunk in enumerate(chunks):
        send(chat_id, chunk, buttons if i == len(chunks) - 1 else None)


def edit(chat_id: int, message_id: int, text: str, buttons: Optional[list] = None) -> None:
    markup = {"inline_keyboard": buttons} if buttons else None
    try:
        api("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
            parse_mode="HTML", reply_markup=markup)
    except TelegramError as e:
        if "not modified" not in str(e):
            raise


def edit_buttons(chat_id: int, message_id: int, buttons: Optional[list]) -> None:
    markup = {"inline_keyboard": buttons} if buttons else {"inline_keyboard": []}
    try:
        api("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
            reply_markup=markup)
    except TelegramError as e:
        if "not modified" not in str(e):
            raise


# --- access and language -----------------------------------------------------------------
def allowed(chat_id: int) -> bool:
    """Private chat: chat id = the person's user id. Group: the group's id (negative)."""
    return chat_id in ALLOWED_IDS


def chat_lang(chat_id: int, user: dict) -> str:
    chat = db.get_chat(chat_id)
    if chat and chat["lang"] in TEXTS:
        return chat["lang"]
    return "ru" if (user.get("language_code") or "").startswith("ru") else "en"


# --- commands ------------------------------------------------------------------------
def cmd_help(chat_id: int, lang: str) -> None:
    send(chat_id, t(lang, "help", time=f"{REMIND_H:02d}:{REMIND_M:02d}",
                    days_word=days_word(lang, REMIND_DAYS),
                    once=t(lang, "once") if REMIND_ONCE else ""))


# Groups in /list: (max days left or None, emoji, text key)
GROUPS = [
    (-1, "⚫", "g_expired"),
    (REMIND_DAYS, "🔴", "g_soon"),
    (30, "🟠", "g_month"),
    (90, "🟡", "g_quarter"),
    (None, "🟢", "g_later"),
]
DELETE_PAGE = 8          # products per page in the delete menu


def list_lines(lang: str, items: List[dict]) -> List[str]:
    """/list text: products grouped by how soon they expire, date column + full name."""
    today = date.today()
    lines = [t(lang, "list_title", n=len(items))]
    rest = list(items)                          # already sorted by expiry date
    for limit, emoji, key in GROUPS:
        group = [p for p in rest if limit is None or days_left(p, today) <= limit]
        if not group:
            continue
        rest = rest[len(group):]
        lines += ["", f"{emoji} <b>{t(lang, key, days=days_until(lang, REMIND_DAYS))}</b> ({len(group)})"]
        lines += [f"{date_cell(p)} {product_name(lang, p, brand=False)}" for p in group]
    return lines


def list_buttons(lang: str) -> list:
    return [[{"text": t(lang, "btn_delete_menu"), "callback_data": "lm:del:0"}]]


def delete_buttons(lang: str, items: List[dict], page: int) -> list:
    """One button per product (current page), page switcher, cancel."""
    pages = max(1, -(-len(items) // DELETE_PAGE))
    page = max(0, min(page, pages - 1))
    rows = [[{"text": f"{short_date(p)} · {plain_name(lang, p, brand=False)}",
              "callback_data": f"lm:ask:{p['id']}:{page}"}]
            for p in items[page * DELETE_PAGE:(page + 1) * DELETE_PAGE]]
    if pages > 1:
        rows.append([{"text": "◀", "callback_data": f"lm:del:{(page - 1) % pages}"},
                     {"text": f"{page + 1}/{pages}", "callback_data": "lm:noop"},
                     {"text": "▶", "callback_data": f"lm:del:{(page + 1) % pages}"}])
    rows.append([{"text": t(lang, "btn_close"), "callback_data": "lm:back"}])
    return rows


def confirm_buttons(lang: str, p: dict, page: int) -> list:
    return [[{"text": t(lang, "btn_delete_this", name=plain_name(lang, p, brand=False)),
              "callback_data": f"lm:yes:{p['id']}:{page}"}],
            [{"text": t(lang, "btn_back"), "callback_data": f"lm:del:{page}"}]]


def cmd_list(chat_id: int, lang: str) -> None:
    items = db.products_all()
    if not items:
        send(chat_id, t(lang, "list_empty"))
        return
    send_long(chat_id, list_lines(lang, items), buttons=list_buttons(lang))


def refresh_list(chat_id: int, message_id: int, lang: str) -> None:
    """After a deletion: redraw the list in the same message (or send a new one if
    it no longer fits into one message)."""
    items = db.products_all()
    if not items:
        edit(chat_id, message_id, t(lang, "list_empty"))
        return
    chunks = chunks_of(list_lines(lang, items))
    if len(chunks) == 1:
        edit(chat_id, message_id, chunks[0], buttons=list_buttons(lang))
    else:
        edit_buttons(chat_id, message_id, None)
        cmd_list(chat_id, lang)


def cmd_soon(chat_id: int, lang: str) -> None:
    today = date.today()
    items = db.products_due(today.isoformat(),
                            (today + timedelta(days=REMIND_DAYS)).isoformat(), only_new=False)
    dw = days_word(lang, REMIND_DAYS)
    if not items:
        send(chat_id, t(lang, "soon_empty", days_word=dw))
        return
    lines = [t(lang, "soon_title", days_word=dw), ""]
    lines += [reminder_line(lang, p, today) for p in items]
    send_long(chat_id, lines)


def cmd_delete_ask(chat_id: int, lang: str, scan_id: int) -> None:
    p = next((x for x in db.products_all() if x["id"] == scan_id), None)
    if p is None:
        send(chat_id, t(lang, "not_found"))
        return
    send(chat_id, t(lang, "confirm", name=product_name(lang, p), date=product_date(p)),
         buttons=[[{"text": t(lang, "btn_delete"), "callback_data": f"del:{scan_id}"},
                   {"text": t(lang, "btn_cancel"), "callback_data": "cancel"}]])


def cmd_lang(chat_id: int) -> None:
    send(chat_id, t("ru", "lang_prompt"),
         buttons=[[{"text": "Русский", "callback_data": "lang:ru"},
                   {"text": "English", "callback_data": "lang:en"}]])


def reminder_line(lang: str, p: dict, today: date) -> str:
    return (f"{date_cell(p)} {product_name(lang, p, brand=False)}"
            f" — <i>{when(lang, days_left(p, today))}</i>")


# --- update handling ---------------------------------------------------------------------
def handle_message(msg: dict) -> None:
    text = (msg.get("text") or "").strip()
    chat = msg["chat"]
    chat_id = chat["id"]
    user = msg.get("from") or {}
    private = chat.get("type") == "private"

    if not text.startswith("/"):
        if private and allowed(chat_id):
            cmd_help(chat_id, chat_lang(chat_id, user))
        return

    command = text.split()[0][1:]
    command, _, target = command.partition("@")
    if target and BOT_USERNAME and target.lower() != BOT_USERNAME.lower():
        return                                   # command for another bot in a group
    command = command.lower()

    if not allowed(chat_id):
        log.info("access denied: chat %s (user %s)", chat_id, user.get("id"))
        if private or command == "start":
            send(chat_id, t(chat_lang(chat_id, user), "denied", id=chat_id))
        return

    lang = chat_lang(chat_id, user)
    m = re.fullmatch(r"del_?(\d+)", command)
    if command == "start":
        db.save_chat(chat_id, lang=lang, subscribed=True)
        cmd_help(chat_id, lang)
    elif command == "stop":
        db.save_chat(chat_id, lang=lang, subscribed=False)
        send(chat_id, t(lang, "stopped"))
    elif command == "list":
        cmd_list(chat_id, lang)
    elif command == "soon":
        cmd_soon(chat_id, lang)
    elif command == "lang":
        cmd_lang(chat_id)
    elif m:
        cmd_delete_ask(chat_id, lang, int(m.group(1)))
    else:
        cmd_help(chat_id, lang)


def _answer(q: dict, text: Optional[str] = None) -> None:
    """Stop the button's loading spinner. Fails for very old buttons, that is fine."""
    try:
        api("answerCallbackQuery", callback_query_id=q["id"], text=text)
    except TelegramError as e:
        log.info("answerCallbackQuery: %s", e)


def handle_callback(q: dict) -> None:
    data = q.get("data") or ""
    user = q.get("from") or {}
    message = q.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    if chat_id is None:
        return
    if not allowed(chat_id):
        _answer(q, "No access")
        return
    lang = chat_lang(chat_id, user)

    if data.startswith("lm:"):
        toast = None
        try:
            toast = handle_list_button(data, chat_id, message_id, lang, user)
        finally:
            _answer(q, toast)
        return
    _answer(q)

    if data.startswith("del:"):
        p = db.delete_product(int(data[4:]))
        if p:
            log.info("deleted scan %s by user %s", p["id"], user.get("id"))
            edit(chat_id, message_id,
                 t(lang, "deleted", name=product_name(lang, p), date=product_date(p)))
        else:
            edit(chat_id, message_id, t(lang, "not_found"))
    elif data == "cancel":
        edit(chat_id, message_id, t(lang, "cancelled"))
    elif data.startswith("lang:") and data[5:] in TEXTS:
        lang = data[5:]
        db.save_chat(chat_id, lang=lang)
        edit(chat_id, message_id, t(lang, "lang_set"))
        cmd_help(chat_id, lang)


def handle_list_button(data: str, chat_id: int, message_id: int, lang: str,
                       user: dict) -> Optional[str]:
    """Buttons under /list: delete menu -> confirm -> delete. Returns a toast text."""
    parts = data.split(":")
    action = parts[1]
    items = db.products_all()
    if action == "del":                                    # show / page the delete menu
        edit_buttons(chat_id, message_id, delete_buttons(lang, items, int(parts[2])))
    elif action == "back":
        edit_buttons(chat_id, message_id, list_buttons(lang) if items else None)
    elif action == "ask":
        scan_id, page = int(parts[2]), int(parts[3])
        p = next((x for x in items if x["id"] == scan_id), None)
        if p is None:
            refresh_list(chat_id, message_id, lang)
            return t(lang, "not_found")
        edit_buttons(chat_id, message_id, confirm_buttons(lang, p, page))
    elif action == "yes":
        p = db.delete_product(int(parts[2]))
        refresh_list(chat_id, message_id, lang)
        if p is None:
            return t(lang, "not_found")
        log.info("deleted scan %s by user %s", p["id"], user.get("id"))
        return t(lang, "toast_deleted", name=plain_name(lang, p, brand=False))[:190]
    return None


def handle_update(u: dict) -> None:
    if "callback_query" in u:
        handle_callback(u["callback_query"])
    elif "message" in u:
        handle_message(u["message"])


# --- daily jobs ----------------------------------------------------------------------
def send_reminders(today: date) -> bool:
    """Send the daily reminder to all subscribed chats.
    Returns False if nothing could be sent (network down), so it is retried later."""
    items = db.products_due(today.isoformat(),
                            (today + timedelta(days=REMIND_DAYS)).isoformat(),
                            only_new=REMIND_ONCE)
    # A chat removed from TELEGRAM_ALLOWED_IDS gets nothing, even if it was subscribed
    chats = [c for c in db.subscribed_chats() if allowed(c["chat_id"])]
    if not items or not chats:
        log.info("reminder: %d products, %d chats, nothing to send", len(items), len(chats))
        return True

    sent = 0
    for c in chats:
        lang = c["lang"] if c["lang"] in TEXTS else "ru"
        lines = [t(lang, "reminder"), ""] + [reminder_line(lang, p, today) for p in items]
        try:
            send_long(c["chat_id"], lines)
            sent += 1
        except TelegramError as e:
            log.warning("reminder to %s failed: %s", c["chat_id"], e)
    if sent:
        db.mark_notified([p["id"] for p in items])
        log.info("reminder: %d products sent to %d chats", len(items), sent)
    return sent > 0


def daily_jobs(now: datetime) -> None:
    """Called often from the main loop; every job runs once per day."""
    today = now.date().isoformat()
    if db.get_state("last_cleanup") != today:
        n = db.cleanup(today)
        db.set_state("last_cleanup", today)
        log.info("cleanup: %d expired products deleted", n)
    if (now.hour, now.minute) >= (REMIND_H, REMIND_M) and db.get_state("last_reminder") != today:
        if send_reminders(now.date()):
            db.set_state("last_reminder", today)


# --- main ----------------------------------------------------------------------------
def setup() -> None:
    global BOT_USERNAME
    while True:                        # the network may not be up yet after boot
        try:
            BOT_USERNAME = api("getMe")["username"]
            break
        except TelegramError as e:
            log.warning("Telegram not reachable yet: %s", e)
            time.sleep(10)
    for lang, cmds in COMMANDS.items():
        api("setMyCommands", commands=[{"command": c, "description": d} for c, d in cmds],
            language_code=None if lang == "en" else lang)
    log.info("bot @%s started, allowed ids: %s", BOT_USERNAME, sorted(ALLOWED_IDS) or "NONE")
    if not ALLOWED_IDS:
        log.warning("TELEGRAM_ALLOWED_IDS is empty: send /start to the bot to see your ID")


def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_TOKEN is not set (see bot.env.example)")
    db.init_db()
    setup()
    offset = None
    while True:
        try:
            daily_jobs(datetime.now())
        except Exception:
            log.exception("daily jobs failed")
        try:
            updates = api("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                          allowed_updates=["message", "callback_query"])
        except TelegramError as e:
            if "Conflict" in str(e):
                log.error("another copy of the bot is running (python bot.py in another "
                          "terminal?), only one may poll Telegram")
            else:
                log.warning("%s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            t0 = time.monotonic()
            try:
                handle_update(u)
            except Exception:
                log.exception("update %s failed", u.get("update_id"))
            log.info("%s handled in %.2f s", _describe(u), time.monotonic() - t0)


def _describe(u: dict) -> str:
    """Short text for the log: the command or button, never message contents."""
    if "callback_query" in u:
        return "button " + (u["callback_query"].get("data") or "?")
    text = ((u.get("message") or {}).get("text") or "").strip()
    return text.split()[0][:30] if text.startswith("/") else "message"


if __name__ == "__main__":
    main()
