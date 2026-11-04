"""Inbox reply checker / stop logic."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from email.utils import getaddresses
from typing import Iterable

import config
import database

STOP_RE = re.compile(
    r"\b(stop|unsubscribe|opt[\s-]?out|remove me|not interested)\b",
    re.I,
)


def _decode_mime(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out: list[str] = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _extract_addresses(raw: str) -> list[str]:
    return [addr.lower() for _, addr in getaddresses([raw]) if addr]


def _message_text(msg: email.message.Message) -> str:
    bits: list[str] = []
    subject = _decode_mime(msg.get("Subject"))
    if subject:
        bits.append(subject)
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                bits.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True) or b""
        if isinstance(payload, bytes):
            bits.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
        else:
            bits.append(str(payload))
    return "\n".join(bits)


def check_replies(known_emails: Iterable[str] | None = None) -> list[str]:
    """
    Poll IMAP for replies from active outreach targets.
    Marks matching history rows as replied/stopped by URL.
    Also treats stop/unsubscribe keywords as an explicit halt.
    """
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print("[tracker] Missing SMTP credentials for IMAP")
        return []

    watch = {e.strip().lower() for e in (known_emails or []) if e}
    if not watch:
        watch = database.active_outreach_emails()

    email_urls = database.email_to_url_map()
    replied: list[str] = []

    imap_host = config.IMAP_HOST or config.SMTP_HOST.replace("smtp.", "imap.", 1)
    if imap_host == config.SMTP_HOST:
        imap_host = "imap.gmail.com"

    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(config.SMTP_USER, config.SMTP_PASSWORD)
        mail.select("INBOX")
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return []

        for num in data[0].split():
            status, msg_data = mail.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            text = _message_text(msg)
            from_addrs = _extract_addresses(_decode_mime(msg.get("From")))
            for addr in from_addrs:
                if addr not in watch:
                    continue
                url = email_urls.get(addr, "")
                if database.is_stopped(email=addr, url=url):
                    continue
                database.mark_replied_by_url(url=url, email=addr)
                replied.append(addr)
                reason = "stop/unsubscribe keyword" if STOP_RE.search(text) else "reply"
                print(f"[tracker] {reason} from {addr} — sequence stopped")
        mail.logout()
    except Exception as exc:
        print(f"[tracker] IMAP check failed: {exc}")

    return replied
