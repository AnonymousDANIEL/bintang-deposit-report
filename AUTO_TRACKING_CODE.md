# Automatic TRACKING_CODE

This build no longer requires a fixed Railway `SITE_TRACKING_CODE`.

Login flow:
1. Refresh the Bintang44 public page/session cookies.
2. If the current site exposes a trackingCode in HTML/JS, use it.
3. Otherwise create the same shape observed in the Bintang44 browser login: a fresh 64-character alphanumeric trackingCode for every login.
4. Login and obtain a fresh accessId/accessToken.
5. If the token/session expires, repeat the whole flow automatically and continue the report.
6. A manually supplied `SITE_TRACKING_CODE` is retained only as a final fallback.

Railway:

    AUTO_TRACKING_CODE=true
    SITE_TRACKING_CODE=

Security note: this automates the normal login fields. It does not bypass CAPTCHA or 2FA. If the account later requires an interactive challenge, that challenge must be satisfied legitimately.


## EXACT HOUR scheduling
This build starts the hourly report at HH:00 (first daemon loop tick) and does not wait an extra 60 seconds.
