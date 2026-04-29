from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .calendar_urls import sanitize_url
from .config import Settings
from .scraper import AppointmentSlot, SwissAppointmentScraper
from .state import DailyStatsStore, SeenSlotStore
from .telegram import send_telegram_message


LOGGER = logging.getLogger("swiss_passport_bot")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    settings: Settings | None = None

    try:
        settings = Settings.from_env()
        if args.command == "test-telegram":
            settings.require_telegram_config()
            send_telegram_message(
                settings.telegram_bot_token or "",
                settings.telegram_chat_id or "",
                "Swiss passport appointment bot test message.",
            )
            print("Telegram test message sent.")
            return 0

        if hasattr(args, "show_browser") and args.show_browser:
            settings = _replace(settings, headless=False)

        if args.command == "check":
            return asyncio.run(run_check(settings, dry_run=args.dry_run, force_alert=args.force_alert))

        if args.command == "run":
            return asyncio.run(run_forever(settings, dry_run=args.dry_run))

        if args.command == "watchdog":
            return run_watchdog(settings)

        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        if args.verbose:
            LOGGER.exception("Runtime error")
        maybe_send_error_alert(settings, exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        if args.verbose:
            LOGGER.exception("Fatal error")
        maybe_send_error_alert(settings, exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Swiss passport appointment availability.")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="run one availability check")
    check.add_argument("--dry-run", action="store_true", help="print results without sending Telegram alerts")
    check.add_argument("--force-alert", action="store_true", help="send alerts even for slots already seen")
    check.add_argument("--show-browser", action="store_true", help="show Chrome while checking")

    run = subparsers.add_parser("run", help="check now, then repeat every CHECK_INTERVAL_SECONDS")
    run.add_argument("--dry-run", action="store_true", help="print results without sending Telegram alerts")
    run.add_argument("--show-browser", action="store_true", help="show Chrome while checking")

    watchdog = subparsers.add_parser("watchdog", help="alert if no successful live checks have happened recently")
    watchdog.add_argument("--show-browser", action="store_true", help="show Chrome while checking")
    subparsers.add_parser("test-telegram", help="send a Telegram test message")
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def maybe_send_error_alert(settings: Settings | None, exc: Exception) -> None:
    if not settings or not settings.alert_on_errors:
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    try:
        send_telegram_message(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            "Swiss passport appointment bot error:\n"
            f"{sanitize_url(str(exc))}",
        )
    except Exception:
        LOGGER.exception("Failed to send error alert")


async def run_forever(settings: Settings, dry_run: bool) -> int:
    LOGGER.info("Starting hourly monitor. Interval: %s seconds", settings.check_interval_seconds)
    while True:
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        LOGGER.info("Starting check at %s", started)
        try:
            await run_check(settings, dry_run=dry_run, force_alert=False)
        except Exception as exc:
            LOGGER.exception("Check failed")
            if settings.alert_on_errors and not dry_run:
                try:
                    settings.require_telegram_config()
                    send_telegram_message(
                        settings.telegram_bot_token or "",
                        settings.telegram_chat_id or "",
                        f"Swiss passport appointment bot error:\n{sanitize_url(str(exc))}",
                    )
                except Exception:
                    LOGGER.exception("Failed to send error alert")
        await asyncio.sleep(settings.check_interval_seconds)


async def run_check(settings: Settings, dry_run: bool, force_alert: bool) -> int:
    settings.require_site_config()
    if not dry_run:
        settings.require_telegram_config()

    if not dry_run:
        maybe_reset_seen_slots_for_new_day(settings)

    scraper = SwissAppointmentScraper(settings)
    slots = await scraper.find_slots()
    print(_format_console_summary(slots))
    if not dry_run:
        record_successful_search(settings, len(slots))

    store = SeenSlotStore(settings.state_dir)
    store.load()
    slots_to_alert = store.new_slots(slots, force=force_alert)

    if not slots_to_alert:
        print("No new appointment slots to alert.")
        return 0

    message = format_alert(slots_to_alert, settings.lookahead_days, settings.session_url)
    if dry_run:
        print("\nDry run: Telegram message would be:\n")
        print(message)
        return 0

    send_telegram_message(settings.telegram_bot_token or "", settings.telegram_chat_id or "", message)
    store.mark_alerted(slots_to_alert)
    store.save()
    print(f"Sent Telegram alert for {len(slots_to_alert)} slot(s).")
    return 0


def maybe_reset_seen_slots_for_new_day(settings: Settings) -> None:
    now = datetime.now(ZoneInfo(settings.timezone))
    if now.time() < time(7, 0):
        return

    stats_store = DailyStatsStore(settings.state_dir)
    stats_store.load()
    if stats_store.has_reset_today(now.date()):
        return

    yesterday = now.date() - timedelta(days=1)
    yesterday_stats = stats_store.stats_for(yesterday)

    seen_store = SeenSlotStore(settings.state_dir)
    seen_store.load()
    seen_store.reset()

    message = (
        "Daily 7am reset: "
        f"{yesterday_stats['successful_searches']} successful search(es) yesterday; "
        f"{yesterday_stats['total_appointments_found']} appointment slot(s) found "
        f"in the next {settings.lookahead_days} days yesterday "
        f"(max in one search: {yesterday_stats['max_appointments_found']}). "
        "Cleared seen appointment slots."
    )
    print(message)
    send_telegram_message(
        settings.telegram_bot_token or "",
        settings.telegram_chat_id or "",
        message,
    )

    stats_store.mark_reset_today(now.date())
    stats_store.save()


def record_successful_search(settings: Settings, appointments_found: int) -> None:
    now = datetime.now(ZoneInfo(settings.timezone))
    stats_store = DailyStatsStore(settings.state_dir)
    stats_store.load()
    stats_store.record_successful_search(now.date(), appointments_found, now)
    stats_store.save()


def run_watchdog(settings: Settings) -> int:
    settings.require_telegram_config()
    now = datetime.now(ZoneInfo(settings.timezone))
    stats_store = DailyStatsStore(settings.state_dir)
    stats_store.load()

    last_success = stats_store.last_success_at()
    if last_success is not None:
        last_success = last_success.astimezone(ZoneInfo(settings.timezone))

    stale = (
        last_success is None
        or (now - last_success).total_seconds() > settings.watchdog_stale_after_seconds
    )
    if not stale:
        print(f"Watchdog OK. Last successful check: {last_success.isoformat()}")
        return 0

    last_alert = stats_store.last_watchdog_alert_at()
    if last_alert is not None:
        last_alert = last_alert.astimezone(ZoneInfo(settings.timezone))
        seconds_since_alert = (now - last_alert).total_seconds()
        if seconds_since_alert < settings.watchdog_alert_interval_seconds:
            print("Watchdog is stale, but an alert was already sent recently.")
            return 0

    last_success_text = "never" if last_success is None else last_success.strftime("%Y-%m-%d %H:%M:%S %Z")
    stale_minutes = round(settings.watchdog_stale_after_seconds / 60)
    message = (
        "Swiss passport appointment bot may not be working.\n\n"
        f"No successful live check in the last {stale_minutes} minutes.\n"
        f"Last successful check: {last_success_text}.\n\n"
        "Check the LaunchAgent logs in logs/launchd.err.log and logs/launchd.out.log."
    )
    send_telegram_message(
        settings.telegram_bot_token or "",
        settings.telegram_chat_id or "",
        message,
    )
    stats_store.mark_watchdog_alert_sent(now)
    stats_store.save()
    print("Watchdog alert sent.")
    return 0


def format_alert(slots: list[AppointmentSlot], lookahead_days: int, session_url: str) -> str:
    lines = [
        "Swiss passport appointment available in London",
        "",
        f"Found {len(slots)} possible free appointment slot(s) in the next {lookahead_days} days:",
    ]

    for slot in slots[:12]:
        time_text = f" at {slot.time}" if slot.time != "unknown" else ""
        lines.append(f"- {slot.date}{time_text}")

    if len(slots) > 12:
        lines.append(f"- plus {len(slots) - 12} more")

    lines.extend(["", f"Open appointment session: {session_url}"])
    return "\n".join(lines)


def _format_console_summary(slots: list[AppointmentSlot]) -> str:
    if not slots:
        return "No free appointment slots found in the configured lookahead window."

    lines = [f"Found {len(slots)} possible free appointment slot(s):"]
    for slot in slots:
        time_text = f" {slot.time}" if slot.time != "unknown" else ""
        lines.append(f"- {slot.date}{time_text} {slot.label}")
    return "\n".join(lines)


def _replace(settings: Settings, **changes) -> Settings:
    data = settings.__dict__.copy()
    data.update(changes)
    return Settings(**data)
