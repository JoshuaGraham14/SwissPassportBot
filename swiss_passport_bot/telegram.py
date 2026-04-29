from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi


class TelegramError(RuntimeError):
    pass


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(api_url, data=payload, method="POST")
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"Telegram API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"Telegram API request failed: {exc}") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise TelegramError(f"Telegram API returned an error: {body}")
