# Bintang44 Deposit Report — Auto TRACKING_CODE Final

This version automatically refreshes/generates a fresh 64-character `trackingCode` on every login and on session recovery. Keep `AUTO_TRACKING_CODE=true` and leave `SITE_TRACKING_CODE` blank in Railway.

# Bintang44 Telegram Deposit Report — Railway Final

This project is the Bintang44 version of the stable hourly Telegram report.

## Report behavior

- Same report date = edit the same Telegram message.
- New report date = send a new Telegram message.
- Always displays all 24 rows in this exact order: `0100` ... `2300`, `0000`.
- A not-yet-closed hour stays: Count `0`, Amount `RM 0.00`, TOTAL `0 / RM 0.00`.
- When an hour closes, that row is recalculated from real `COMPLETED` `DEPOSIT` data and its cumulative TOTAL becomes real.
- Exact-hour schedule: the worker starts the hourly read at `HH:00` (first loop tick, normally within ~2 seconds), with no extra +1 minute delay.
- Message is plain text only; there is no `<pre>` / `<code>`, so Telegram does not show the large Copy button.

## Bintang44 backend confirmed

- API: `https://90018.gawlt.com/api/v1/index.php`
- Merchant ID: `90018`
- Login: `/users/login`
- Transactions: `/transactions/getAllTransactions`
- Daily report: `/reports/transactions`

## Railway

1. Deploy this folder/repository as an always-on service. The included Dockerfile runs `python main.py`.
2. Copy the variable names from `RAILWAY_VARIABLES.txt` into Railway Variables and fill only your own secret values there.
3. Create/mount a Railway Volume at `/data`. Keep `STATE_PATH=/data/bintang44_state.json`. This preserves the Telegram message ID across restart/deploy, so the same day's message can continue to be edited.
4. Do not use cron. Keep the service running continuously.

## Session recovery

- The worker keeps an authenticated session.
- A periodic authenticated probe checks the session.
- If access/session is rejected or expired, the worker re-logins automatically and retries.
- Hourly report failures retry without waiting for the next hour.

## Security

Do not hard-code the real backend password, tracking code, Telegram bot token, access ID, or access token in this ZIP. Put them only in Railway Variables.
