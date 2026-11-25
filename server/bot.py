#!/usr/bin/env python3
"""Telegram bot for expiry cam (runs on the Pi 5 next to server.py).

- Every day at REMIND_TIME: products that expire within REMIND_DAYS days.
  Each product is mentioned in one reminder only (REMIND_ONCE).
- After midnight: a backup of the database (backups/, one week), expired products are
  deleted together with their photos, photos without a product older than 30 days are
  deleted, and products saved without a name are looked up in Open Food Facts again.
- /list, /soon, /del_<id>, /lang (ru/en), /stop, /start, /help
- "✏️ Edit…" under /list: set the date or the name of a product (typed as a message),
  delete it. Products without a date or a name are in the "❓ Needs info" group.

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

from core import dates, db, products, upkeep
from ocr.parser import parse_expiry_date

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
INPUT_TIMEOUT_S = 300      # a typed date / name is expected this long after the button
NAME_MAX = 60              # longest product name that can be typed

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
        "g_todo": "Нужно дополнить",
        "no_date": "нет даты",
        "todo_reminder": "❓ Нужно дополнить: {n} — /list",
        "btn_edit_menu": "✏️ Изменить…",
        "btn_set_date": "📅 Дата",
        "btn_set_name": "🏷 Название",
        "ask_date": ("📅 Пришли дату для «{name}»{times}, например "
                     "<code>12.03.27</code> или <code>03/2027</code>."),
        "ask_name": "🏷 Пришли название для «{name}»{times} (до {max} символов).",
        "bad_date": "Не понял дату. Пример: <code>12.03.27</code> или <code>03/2027</code>.",
        "past_date": "Дата {date} уже прошла — проверь и пришли ещё раз.",
        "long_name": "Слишком длинно: максимум {max} символов.",
        "date_set": "✅ {name}: {date}",
        "name_set": "✅ Название: {name}",
        "same_undated": "Ещё {n} шт. этого продукта без даты — тоже {date}?",
        "btn_all_same": "Да, тоже",
        "btn_only_this": "Только этой",
        "same_done": "✅ Ещё {n} шт.: {date}",
        "btn_delete_one": "🗑 Удалить 1 (останется {left})",
        "btn_delete_dupe": "🗑 Удалить повтор (останется 1)",
        "btn_delete_dupes": "🗑 Удалить повторы: {n} шт. (останется 1)",
        "btn_back": "⬅ Назад",
        "btn_close": "✖ Отмена",
        "toast_deleted": "Удалено: {name}",
        "toast_deleted_dupe": "Удалён повтор · {name}",
        "toast_deleted_dupes": "Удалено повторов: {n} · {name}",
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
        "g_todo": "Needs info",
        "no_date": "no date",
        "todo_reminder": "❓ Needs info: {n} — /list",
        "btn_edit_menu": "✏️ Edit…",
        "btn_set_date": "📅 Date",
        "btn_set_name": "🏷 Name",
        "ask_date": ("📅 Send the date for “{name}”{times}, e.g. "
                     "<code>12.03.27</code> or <code>03/2027</code>."),
        "ask_name": "🏷 Send the name for “{name}”{times} (up to {max} characters).",
        "bad_date": "Could not read that date. Example: <code>12.03.27</code> or <code>03/2027</code>.",
        "past_date": "{date} is already over — check it and send it again.",
        "long_name": "Too long: {max} characters at most.",
        "date_set": "✅ {name}: {date}",
        "name_set": "✅ Name: {name}",
        "same_undated": "{n} more of this product without a date — {date} too?",
        "btn_all_same": "Yes, too",
        "btn_only_this": "Only this one",
        "same_done": "✅ {n} more: {date}",
        "btn_delete_one": "🗑 Delete 1 ({left} left)",
        "btn_delete_dupe": "🗑 Delete duplicate (1 left)",
        "btn_delete_dupes": "🗑 Delete {n} duplicates (1 left)",
        "btn_back": "⬅ Back",
        "btn_close": "✖ Cancel",
        "toast_deleted": "Deleted: {name}",
        "toast_deleted_dupe": "Deleted duplicate · {name}",
        "toast_deleted_dupes": "Deleted {n} duplicates · {name}",
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
    return html.escape(dates.display(p["parsed_expiry_date"]) or p["expires_on"] or "?")


def incomplete(p: dict) -> bool:
    """No date or no name: shown in the "❓ Needs info" group."""
    return not p.get("expires_on") or not p.get("product_name")


NBSP = "\u00a0"


def short_date(p: dict) -> str:
    """Compact date for the date column: '18.01.27', '12/26', '27.07.', '??.??.??'"""
    if not p.get("expires_on"):
        return "??.??.??"
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


def same_products(items: List[dict]) -> List[dict]:
    """Units of the same product with the same date become one entry with 'ids' and
    'count'. Units without a barcode or without a date stay single (their dates may
    differ). Keeps the order (by expiry date)."""
    entries, by_key = [], {}
    for p in items:
        same = p.get("barcode") and p.get("expires_on")
        key = (p["barcode"], p["expires_on"]) if same else ("single", p["id"])
        if key in by_key:
            by_key[key]["ids"].append(p["id"])
            by_key[key]["count"] += 1
        else:
            entry = dict(p, ids=[p["id"]], count=1)
            by_key[key] = entry
            entries.append(entry)
    return entries


def entry_of(items: List[dict], scan_id: int) -> Optional[dict]:
    """The entry (product + date) that contains this scan id."""
    return next((e for e in same_products(items) if scan_id in e["ids"]), None)


def times(e: dict, html_bold: bool = True) -> str:
    """' ×2' (bold in messages) for several units, nothing for one."""
    if e.get("count", 1) <= 1:
        return ""
    return f" <b>×{e['count']}</b>" if html_bold else f" ×{e['count']}"


def list_lines(lang: str, items: List[dict]) -> List[str]:
    """/list text: products grouped by how soon they expire, date column + full name,
    the same product with the same date once with ×N."""
    today = date.today()
    lines = [t(lang, "list_title", n=len(items))]
    entries = same_products(items)              # already sorted by expiry date
    todo = [e for e in entries if incomplete(e)]
    if todo:
        lines += ["", f"❓ <b>{t(lang, 'g_todo')}</b> ({sum(e['count'] for e in todo)})"]
        lines += [f"{date_cell(e)} {product_name(lang, e, brand=False)}{times(e)}"
                  + (f" — <i>{t(lang, 'no_date')}</i>" if not e.get("expires_on") else "")
                  for e in todo]
    rest = [e for e in entries if not incomplete(e)]
    for limit, emoji, key in GROUPS:
        group = [e for e in rest if limit is None or days_left(e, today) <= limit]
        if not group:
            continue
        rest = rest[len(group):]
        units = sum(e["count"] for e in group)
        lines += ["", f"{emoji} <b>{t(lang, key, days=days_until(lang, REMIND_DAYS))}</b> ({units})"]
        lines += [f"{date_cell(e)} {product_name(lang, e, brand=False)}{times(e)}"
                  for e in group]
    return lines


def list_buttons(lang: str) -> list:
    return [[{"text": t(lang, "btn_edit_menu"), "callback_data": "lm:del:0"}]]


def menu_buttons(lang: str, items: List[dict], page: int) -> list:
    """One button per product and date (current page), page switcher, cancel.
    Products that need info come first (same order as the list) and have a ❓."""
    entries = same_products(items)
    entries = [e for e in entries if incomplete(e)] + [e for e in entries if not incomplete(e)]
    pages = max(1, -(-len(entries) // DELETE_PAGE))
    page = max(0, min(page, pages - 1))
    rows = [[{"text": ("❓ " if incomplete(e) else "")
                      + f"{short_date(e)} · {plain_name(lang, e, brand=False)}{times(e, False)}",
              "callback_data": f"lm:ask:{e['id']}:{page}"}]
            for e in entries[page * DELETE_PAGE:(page + 1) * DELETE_PAGE]]
    if pages > 1:
        rows.append([{"text": "◀", "callback_data": f"lm:del:{(page - 1) % pages}"},
                     {"text": f"{page + 1}/{pages}", "callback_data": "lm:noop"},
                     {"text": "▶", "callback_data": f"lm:del:{(page + 1) % pages}"}])
    rows.append([{"text": t(lang, "btn_close"), "callback_data": "lm:back"}])
    return rows


def card_buttons(lang: str, e: dict, page: int) -> list:
    """Product card: its name and date (not a button), Date / Name, then delete:
    one unit "Delete"; two "Delete duplicate"; three or more "Delete 1" (the last
    scanned) or "Delete duplicates" (all but the first scanned)."""
    title = f"{plain_name(lang, e, brand=False)} · {short_date(e)}{times(e, False)}"
    rows = [[{"text": title, "callback_data": "lm:noop"}],
            [{"text": t(lang, "btn_set_date"), "callback_data": f"lm:date:{e['id']}:{page}"},
             {"text": t(lang, "btn_set_name"), "callback_data": f"lm:name:{e['id']}:{page}"}]]
    back = [{"text": t(lang, "btn_back"), "callback_data": f"lm:del:{page}"}]
    if e["count"] == 1:
        return rows + [[{"text": t(lang, "btn_delete"),
                         "callback_data": f"lm:yes:{e['id']}:{page}"}], back]
    dupes = e["count"] - 1
    if dupes > 1:      # with two units "Delete 1" and "Delete duplicates" would be the same
        rows.append([{"text": t(lang, "btn_delete_one", left=dupes),
                      "callback_data": f"lm:yes:{max(e['ids'])}:{page}"}])
    text = t(lang, "btn_delete_dupes", n=dupes) if dupes > 1 else t(lang, "btn_delete_dupe")
    rows.append([{"text": text, "callback_data": f"lm:dup:{e['id']}:{page}"}])
    return rows + [back]


def cmd_list(chat_id: int, lang: str) -> None:
    items = db.products_all()
    if not items:
        send(chat_id, t(lang, "list_empty"))
        return
    send_long(chat_id, list_lines(lang, items), buttons=list_buttons(lang))


def refresh_list(chat_id: int, message_id: int, lang: str) -> None:
    """After a change: redraw the list in the same message (or send a new one if
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
    lines += [reminder_line(lang, e, today) for e in same_products(items)]
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


# --- typed date / name (after the Date / Name button in the product card) ---------------
# (chat_id, user_id) -> what is expected: kind 'date' or 'name', the units, where the list
# and the question are. Kept in memory: after a bot restart the button is pressed again.
_waiting = {}


# Typed dates: 12.03.27, 12.3.2027, 12 03 27, 2027-03-12, 03/27, 03.2027, 12.03.
_SEP = r"\s*[./\-\s]\s*"
_TYPED_DMY = re.compile(rf"(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{4}}|\d{{2}})")
_TYPED_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_TYPED_MY = re.compile(r"(\d{1,2})\s*/\s*(\d{4}|\d{2})|(\d{1,2})\s*[.\-\s]\s*(\d{4})")
_TYPED_DM_RE = re.compile(rf"(\d{{1,2}}){_SEP}(\d{{1,2}})\.?")


def typed_date(text: str) -> Optional[str]:
    """A date typed by a person, in the parser's format: 'DD-MM-YYYY', '00-MM-YYYY'
    (month and year) or 'DD-MM-0000' (no year). The usual ways to type a date are read
    strictly here (the OCR parser guesses around OCR noise, and it turns a past year into
    "no year"); anything else goes to the OCR parser."""
    text = text.strip()

    def year(y: str) -> int:
        return int(y) + 2000 if len(y) == 2 else int(y)

    def valid(y: int, m: int, d: int) -> bool:
        try:
            date(y, m, d)
            return True
        except ValueError:
            return False

    m = _TYPED_ISO.fullmatch(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{d:02d}-{mo:02d}-{y}" if valid(y, mo, d) else None
    m = _TYPED_DMY.fullmatch(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), year(m.group(3))
        return f"{d:02d}-{mo:02d}-{y}" if valid(y, mo, d) else None
    m = _TYPED_MY.fullmatch(text)          # 03/27, 03/2027, 03.2027
    if m:
        mo, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        return f"00-{int(mo):02d}-{year(y)}" if 1 <= int(mo) <= 12 else None
    m = _TYPED_DM_RE.fullmatch(text)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        return f"{d:02d}-{mo:02d}-0000" if valid(2000, mo, d) else None
    return parse_expiry_date(text)


def start_input(kind: str, chat_id: int, user_id: int, lang: str, e: dict,
                list_msg: int) -> None:
    cancel_input(chat_id, user_id, lang)              # an older question is void now
    name = product_name(lang, e, brand=False)
    if kind == "date":
        text = t(lang, "ask_date", name=name, times=times(e))
    else:
        text = t(lang, "ask_name", name=name, times=times(e), max=NAME_MAX)
    msg = send(chat_id, text, buttons=[[{"text": t(lang, "btn_close"),
                                         "callback_data": "in:cancel"}]])
    _waiting[(chat_id, user_id)] = dict(
        kind=kind, ids=list(e["ids"]), barcode=e.get("barcode"),
        undated=not e.get("expires_on"), list_msg=list_msg,
        prompt_msg=msg.get("message_id"), since=time.monotonic())


def cancel_input(chat_id: int, user_id: int, lang: str) -> None:
    """Forget the question (a command, Cancel or a new question) and say so under it."""
    w = _waiting.pop((chat_id, user_id), None)
    if w and w["prompt_msg"]:
        try:
            edit(chat_id, w["prompt_msg"], t(lang, "cancelled"))
        except TelegramError as e:
            log.info("could not close the question: %s", e)


def waiting_for(chat_id: int, user_id: int) -> Optional[dict]:
    """The open question of this person, None if there is none or it timed out."""
    w = _waiting.get((chat_id, user_id))
    if w and time.monotonic() - w["since"] > INPUT_TIMEOUT_S:
        _waiting.pop((chat_id, user_id), None)
        return None
    return w


def _close_prompt(chat_id: int, w: dict, text: str) -> None:
    """Replace the question with the result and redraw the list it came from."""
    for msg_id, action in ((w["prompt_msg"], "prompt"), (w["list_msg"], "list")):
        if not msg_id:
            continue
        try:
            if action == "prompt":
                edit(chat_id, msg_id, text)
            else:
                refresh_list(chat_id, msg_id, w["lang"])
        except TelegramError as e:
            log.info("could not update the %s: %s", action, e)


def handle_input(chat_id: int, user_id: int, lang: str, text: str, w: dict) -> None:
    """A message while a date or a name is expected."""
    w["lang"] = lang
    if w["kind"] == "date":
        today = date.today()
        parsed = typed_date(text)
        resolved = dates.resolve(parsed, today) if parsed else None
        if resolved is None:
            w["since"] = time.monotonic()             # try again, the time starts anew
            send(chat_id, t(lang, "bad_date"))
            return
        shown = html.escape(dates.display(parsed) or resolved.isoformat())
        if resolved < today:
            w["since"] = time.monotonic()
            send(chat_id, t(lang, "past_date", date=shown))
            return
        _waiting.pop((chat_id, user_id), None)
        if not db.set_date(w["ids"], parsed, resolved.isoformat()):
            _close_prompt(chat_id, w, t(lang, "not_found"))
            return
        log.info("date %s set for scans %s by user %s", resolved, w["ids"], user_id)
        item = next((x for x in db.products_all() if x["id"] == w["ids"][0]), {})
        _close_prompt(chat_id, w, t(lang, "date_set", date=shown,
                                    name=product_name(lang, item, brand=False)))
        others = db.undated_ids(w["barcode"], w["ids"]) if w["undated"] else []
        if others:
            send(chat_id, t(lang, "same_undated", n=len(others), date=shown),
                 buttons=[[{"text": t(lang, "btn_all_same"),
                            "callback_data": f"in:same:{w['ids'][0]}:{w['list_msg'] or 0}"},
                           {"text": t(lang, "btn_only_this"), "callback_data": "in:no"}]])
        return

    name = " ".join(text.split())
    if len(name) > NAME_MAX:
        w["since"] = time.monotonic()
        send(chat_id, t(lang, "long_name", max=NAME_MAX))
        return
    _waiting.pop((chat_id, user_id), None)
    if not db.set_name(w["ids"], w["barcode"], name):
        _close_prompt(chat_id, w, t(lang, "not_found"))
        return
    log.info("name set for scans %s (barcode %s) by user %s", w["ids"], w["barcode"], user_id)
    _close_prompt(chat_id, w, t(lang, "name_set", name=html.escape(name)))


def handle_input_button(data: str, chat_id: int, message_id: int, lang: str,
                        user: dict) -> None:
    """Buttons under the questions: Cancel, and "the same date for the other units"."""
    user_id = user.get("id")
    if data == "in:cancel":
        w = _waiting.get((chat_id, user_id))
        if w and w["prompt_msg"] == message_id:
            _waiting.pop((chat_id, user_id), None)
        edit(chat_id, message_id, t(lang, "cancelled"))
    elif data == "in:no":
        edit_buttons(chat_id, message_id, None)
    elif data.startswith("in:same:"):
        _, _, scan_id, list_msg = data.split(":")
        src = next((x for x in db.products_all() if x["id"] == int(scan_id)), None)
        ids = db.undated_ids(src["barcode"], []) if src and src.get("expires_on") else []
        n = db.set_date(ids, src["parsed_expiry_date"], src["expires_on"]) if ids else 0
        if not n:
            edit(chat_id, message_id, t(lang, "not_found"))
            return
        log.info("date %s set for scans %s by user %s", src["expires_on"], ids, user_id)
        edit(chat_id, message_id, t(lang, "same_done", n=n, date=product_date(src)))
        if int(list_msg):
            try:
                refresh_list(chat_id, int(list_msg), lang)
            except TelegramError as e:
                log.info("could not update the list: %s", e)


def reminder_line(lang: str, e: dict, today: date) -> str:
    return (f"{date_cell(e)} {product_name(lang, e, brand=False)}{times(e)}"
            f" — <i>{when(lang, days_left(e, today))}</i>")


# --- update handling ---------------------------------------------------------------------
def handle_message(msg: dict) -> None:
    text = (msg.get("text") or "").strip()
    chat = msg["chat"]
    chat_id = chat["id"]
    user = msg.get("from") or {}
    private = chat.get("type") == "private"

    if not text.startswith("/"):
        if not allowed(chat_id):
            return
        w = waiting_for(chat_id, user.get("id")) if text else None
        if w:
            handle_input(chat_id, user.get("id"), chat_lang(chat_id, user), text, w)
        elif private:
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
    cancel_input(chat_id, user.get("id"), lang)        # a command ends an open question
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

    if data.startswith("in:"):
        handle_input_button(data, chat_id, message_id, lang, user)
        return

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
    """Buttons under /list: edit menu -> product card -> date / name / delete.
    Returns a toast text."""
    parts = data.split(":")
    action = parts[1]
    items = db.products_all()
    if action == "del":                                    # show / page the edit menu
        edit_buttons(chat_id, message_id, menu_buttons(lang, items, int(parts[2])))
    elif action == "back":
        edit_buttons(chat_id, message_id, list_buttons(lang) if items else None)
    elif action == "ask":
        scan_id, page = int(parts[2]), int(parts[3])
        e = entry_of(items, scan_id)
        if e is None:
            refresh_list(chat_id, message_id, lang)
            return t(lang, "not_found")
        edit_buttons(chat_id, message_id, card_buttons(lang, e, page))
    elif action in ("date", "name"):                       # ask for it, the answer is a message
        e = entry_of(items, int(parts[2]))
        if e is None:
            refresh_list(chat_id, message_id, lang)
            return t(lang, "not_found")
        start_input(action, chat_id, user.get("id"), lang, e, message_id)
    elif action == "yes":                                  # one unit
        p = db.delete_product(int(parts[2]))
        refresh_list(chat_id, message_id, lang)
        if p is None:
            return t(lang, "not_found")
        log.info("deleted scan %s by user %s", p["id"], user.get("id"))
        return t(lang, "toast_deleted", name=plain_name(lang, p, brand=False))[:190]
    elif action == "dup":                                  # all units but the first scanned
        e = entry_of(items, int(parts[2]))
        extra = sorted(e["ids"])[1:] if e else []
        deleted = [d for d in (db.delete_product(i) for i in extra) if d]
        refresh_list(chat_id, message_id, lang)
        if not deleted:
            return t(lang, "not_found")
        log.info("deleted duplicate scans %s by user %s", [d["id"] for d in deleted],
                 user.get("id"))
        key = "toast_deleted_dupes" if len(deleted) > 1 else "toast_deleted_dupe"
        return t(lang, key, name=plain_name(lang, deleted[0], brand=False),
                 n=len(deleted))[:190]
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
    entries = same_products(items)
    todo = sum(1 for p in db.products_all() if incomplete(p))
    for c in chats:
        lang = c["lang"] if c["lang"] in TEXTS else "ru"
        lines = [t(lang, "reminder"), ""] + [reminder_line(lang, e, today) for e in entries]
        if todo:                       # only inside a reminder that is sent anyway
            lines += ["", t(lang, "todo_reminder", n=todo)]
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
        try:                           # first, so yesterday's state is safe whatever follows
            path = upkeep.backup_db(today)
            log.info("backup: %s (%d KB)", path.name, path.stat().st_size // 1024)
        except Exception:
            log.exception("database backup failed")
        n = db.cleanup(today)
        db.set_state("last_cleanup", today)
        log.info("cleanup: %d expired products deleted", n)
        try:
            removed = upkeep.clean_photos()
            if removed:
                log.info("photos: %d without a product, older than %d days, deleted",
                         removed, upkeep.PHOTO_KEEP_DAYS)
        except Exception:
            log.exception("photo cleanup failed")
        try:
            named = products.refresh_unnamed()
            if named:
                log.info("names found later for %d products", named)
        except Exception:
            log.exception("looking up unnamed products failed")
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
