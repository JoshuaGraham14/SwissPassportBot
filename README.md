# Swiss Passport Appointment Telegram Bot

This bot checks the Swiss e-document reservation calendar for London and sends you a Telegram alert when the site's **Next free appointments** list shows a free appointment inside your configured lookahead window. It only reads the calendar and alerts you; it does not book, cancel, or reschedule anything.

## Setup

```bash
cd /Users/joshuagraham/Downloads/SwissPassportBot
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- `SESSION_URL`: paste the secure session link from your appointment email.
- `CALENDAR_URL`: paste the calendar URL you captured after clicking **Reschedule**.
- `TELEGRAM_BOT_TOKEN`: create a bot with Telegram's BotFather and paste its token.
- `TELEGRAM_CHAT_ID`: send your bot a message, then visit `https://api.telegram.org/bot<token>/getUpdates` to find your chat id.

Install Playwright's managed browser once:

```bash
python -m playwright install chromium
```

Keep `BROWSER_EXECUTABLE_PATH` blank unless you specifically want to point Playwright at another browser.

## If The Swiss Site Blocks The Browser

If a check fails with text like `Web Page Blocked`, `Attack ID`, or `Message ID`, the Swiss site's firewall has refused the automated browser before the appointment page loaded. First try a visible run using the real Chrome app:

```bash
HEADLESS=false BROWSER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" python -m swiss_passport_bot check --dry-run
```

If that works, put these values in `.env`:

```env
HEADLESS=false
BROWSER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

If the visible real-Chrome check is also blocked, the site is refusing automated access from this setup. In that case the bot cannot safely monitor it without the site allowing the session.

## Test It

Send a Telegram test message:

```bash
python -m swiss_passport_bot test-telegram
```

Run one check without sending alerts:

```bash
python -m swiss_passport_bot check --dry-run
```

Run one live check:

```bash
python -m swiss_passport_bot check
```

## Run Every Hour

The simplest foreground runner checks immediately and then every hour:

```bash
python -m swiss_passport_bot run
```

For a background macOS LaunchAgent that runs once per hour:

```bash
./scripts/install_launch_agent.sh
```

Logs are written to `logs/launchd.out.log` and `logs/launchd.err.log`.

The LaunchAgent also runs once at 07:00. On the first run at or after 07:00 each day, the bot prints and Telegrams a daily summary:

- prints yesterday's successful live-search count;
- prints how many appointment slots were found in the configured next `LOOKAHEAD_DAYS` window yesterday;
- clears `.state/seen_slots.json`, so appointments can alert again that day if they are still listed.

The installer also creates a watchdog LaunchAgent. Every 15 minutes it checks `.state/daily_stats.json`; if no live check has succeeded recently, it sends a Telegram warning. By default:

```env
WATCHDOG_STALE_AFTER_SECONDS=7200
WATCHDOG_ALERT_INTERVAL_SECONDS=21600
ALERT_ON_ERRORS=true
```

That means "alert if no successful live check in 2 hours, but do not repeat the watchdog alert more than once every 6 hours." `ALERT_ON_ERRORS=true` also sends Telegram messages when a live check starts but fails.

To remove the LaunchAgent:

```bash
./scripts/uninstall_launch_agent.sh
```

## Run On A Linux VPS With Docker

If the site refuses headless mode and you want your Mac to sleep normally, move the bot to a small Linux VPS and run it in Docker. The container uses a headed Chromium session inside Xvfb, so it does not depend on your laptop.

On the VPS:

```bash
git clone <your-repo-url>
cd SwissPassportBot
cp .env.example .env
```

Edit `.env` for the VPS:

```env
HEADLESS=false
BROWSER_EXECUTABLE_PATH=""
```

Leave the other values the same as your working local configuration. Then start it:

```bash
docker compose up -d --build
```

The container runs the hourly checker and the watchdog as separate background loops. View logs with:

```bash
docker compose logs -f
```

Typical VPS setup cost is about $5 to $15 per month for a small instance. A basic Docker install usually takes 1 to 2 hours if you are comfortable with SSH and Linux, or 2 to 4 hours if you also want to verify the browser session carefully.

## Notes

- The bot stores alerted appointment keys in `.state/seen_slots.json` so it does not keep sending the same slot every hour.
- Daily search stats are stored in `.state/daily_stats.json`.
- If the booking token expires, paste a fresh `SESSION_URL` into `.env`.
- The checker clicks **Next free appointments** and reads the suggestions table. It does not infer availability from the visual calendar grid.
- `LOOKAHEAD_DAYS=31` means "alert me only if the first available appointments are within about a month." Increase it temporarily, for example to `150`, if you want to test against the August appointments.
- If the site changes its markup, run with `--show-browser` to debug:

```bash
python -m swiss_passport_bot check --dry-run --show-browser
```
