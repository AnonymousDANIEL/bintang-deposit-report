from __future__ import annotations

import logging
import re
import secrets
import string
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests

from config import Config

log = logging.getLogger(__name__)
MONEY = Decimal("0.01")
TRACKING_ALPHABET = string.ascii_letters + string.digits
TRACKING_RE = re.compile(
    r'''(?:trackingCode|tracking_code)["'\s:=]+["']([A-Za-z0-9_-]{24,128})["']''',
    re.IGNORECASE,
)
SCRIPT_RE = re.compile(r'''<script[^>]+src=["']([^"']+)["']''', re.IGNORECASE)


class BintangError(RuntimeError):
    pass


@dataclass(frozen=True)
class Totals:
    count: int
    amount: Decimal

    @classmethod
    def from_values(cls, count: Any, amount: Any) -> "Totals":
        return cls(
            count=int(count or 0),
            amount=Decimal(str(amount or 0)).quantize(MONEY, rounding=ROUND_HALF_UP),
        )


class BintangClient:
    """Long-lived Bintang44 API client with automatic session/tracking recovery."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        parts = urlsplit(cfg.site_api_url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": self.origin,
                "Referer": self.origin + "/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
            }
        )
        self.access_id = ""
        self.access_token = ""
        self.last_login_monotonic = 0.0
        self.current_tracking_code = ""

    def _post_raw(self, form: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self.cfg.request_retries + 1):
            try:
                response = self.session.post(
                    self.cfg.site_api_url,
                    data=form,
                    timeout=self.cfg.request_timeout_seconds,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(
                        f"HTTP {response.status_code}", response=response
                    )
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise BintangError(
                        f"API returned non-JSON response (HTTP {response.status_code})"
                    ) from exc
                if not isinstance(payload, dict):
                    raise BintangError("API returned unexpected JSON structure")
                return payload
            except (requests.RequestException, BintangError) as exc:
                last_exc = exc
                if attempt >= self.cfg.request_retries:
                    break
                sleep_s = min(2 ** (attempt - 1), 8)
                log.warning(
                    "API request failed (attempt %s): %s; retrying in %ss",
                    attempt,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        raise BintangError(f"API request failed after retries: {last_exc}")

    @staticmethod
    def _is_success(payload: dict[str, Any]) -> bool:
        return str(payload.get("status", "")).upper() == "SUCCESS"

    @staticmethod
    def _message(payload: dict[str, Any]) -> str:
        data = payload.get("data")
        if isinstance(data, dict) and data.get("message"):
            return str(data.get("message"))
        return str(payload.get("message") or payload.get("error") or payload)

    @classmethod
    def _looks_like_auth_failure(cls, payload: dict[str, Any]) -> bool:
        text = cls._message(payload).lower()
        needles = (
            "token", "session", "login", "unauthor", "forbidden", "access denied",
            "accessid", "access id", "expired", "invalid access", "authentication",
        )
        return any(word in text for word in needles)

    @staticmethod
    def _first_value(data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip() != "":
                return value
        return None

    @staticmethod
    def _fresh_tracking_code() -> str:
        # The web login sends a new 64-character alphanumeric trackingCode each login.
        return "".join(secrets.choice(TRACKING_ALPHABET) for _ in range(64))

    def _refresh_public_session_and_scrape_tracking(self) -> list[str]:
        """Refresh browser-like cookies and opportunistically discover a trackingCode.

        Most Bintang44 builds generate trackingCode in the browser. This scraper is a
        secondary path in case the site starts embedding one in HTML/JS.
        """
        found: list[str] = []
        try:
            r = self.session.get(self.origin + "/", timeout=self.cfg.request_timeout_seconds)
            r.raise_for_status()
            html = r.text or ""
            found.extend(TRACKING_RE.findall(html))
            # Inspect a small number of same-origin JS bundles only.
            for src in SCRIPT_RE.findall(html)[:12]:
                url = urljoin(self.origin + "/", src)
                if urlsplit(url).netloc != urlsplit(self.origin).netloc:
                    continue
                try:
                    js = self.session.get(url, timeout=min(self.cfg.request_timeout_seconds, 15))
                    if js.ok and len(js.text) <= 8_000_000:
                        found.extend(TRACKING_RE.findall(js.text))
                except requests.RequestException:
                    pass
        except requests.RequestException as exc:
            log.warning("Public session refresh skipped: %s", exc)
        # De-duplicate while preserving order.
        out: list[str] = []
        for code in found:
            if code not in out:
                out.append(code)
        return out

    def _tracking_candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if self.cfg.auto_tracking_code:
            # Refresh cookies first; if site exposes a code, prefer it.
            for code in self._refresh_public_session_and_scrape_tracking():
                candidates.append(("discovered", code))
            # Primary path for current Bintang44 frontend: fresh 64-char code per login.
            candidates.append(("generated", self._fresh_tracking_code()))
        if self.cfg.site_tracking_code:
            candidates.append(("railway-fallback", self.cfg.site_tracking_code))
        if not candidates:
            candidates.append(("generated", self._fresh_tracking_code()))

        dedup: list[tuple[str, str]] = []
        seen: set[str] = set()
        for source, code in candidates:
            if code and code not in seen:
                seen.add(code)
                dedup.append((source, code))
        return dedup

    def login(self, *, reason: str = "normal") -> None:
        last_payload: dict[str, Any] | None = None
        candidates = self._tracking_candidates()

        for idx, (source, tracking_code) in enumerate(candidates, start=1):
            form = {
                "username": self.cfg.site_username,
                "password": self.cfg.site_password,
                "passcode2fa": self.cfg.site_passcode_2fa,
                "trackingCode": tracking_code,
                "captchaOutput": self.cfg.site_captcha_output,
                "module": "/users/login",
                "merchantId": self.cfg.site_merchant_id,
                "accessId": "",
                "accessToken": "",
            }
            log.info(
                "LOGIN attempt %s/%s using trackingCode source=%s len=%s",
                idx, len(candidates), source, len(tracking_code),
            )
            payload = self._post_raw(form)
            last_payload = payload
            if self._is_success(payload):
                self.current_tracking_code = tracking_code
                data = payload.get("data") or {}
                if not isinstance(data, dict):
                    raise BintangError("Login succeeded but data is not an object")

                access_id = self._first_value(data, "id", "accessId", "access_id", "adminId")
                token = self._first_value(data, "token", "accessToken", "access_token", "authToken")
                if not access_id:
                    access_id = self._first_value(payload, "accessId", "access_id", "id")
                if not token:
                    token = self._first_value(payload, "accessToken", "access_token", "token")
                if not access_id or not token:
                    raise BintangError(
                        "Login succeeded but response did not contain a usable accessId/token. "
                        "Expected data.id plus data.token/accessToken."
                    )

                self.access_id = str(access_id)
                self.access_token = str(token)
                self.last_login_monotonic = time.monotonic()
                if reason == "takeover":
                    log.warning("SESSION TAKEOVER OK - Bintang44 session reclaimed")
                else:
                    log.info("Bintang44 login OK")
                return

            log.warning(
                "LOGIN rejected with trackingCode source=%s: %s",
                source, self._message(payload),
            )

        raise BintangError(
            "Bintang44 login failed after automatic trackingCode refresh. "
            "Check SITE_USERNAME / SITE_PASSWORD and any CAPTCHA/2FA requirement. "
            f"Last API response: {self._message(last_payload or {})}"
        )

    def force_login(self) -> None:
        self.access_id = ""
        self.access_token = ""
        self.current_tracking_code = ""
        self.login(reason="takeover")

    def _authenticated_post(self, form: dict[str, Any]) -> dict[str, Any]:
        if not self.access_id or not self.access_token:
            self.login()

        body = dict(form)
        body.update({
            "merchantId": self.cfg.site_merchant_id,
            "accessId": self.access_id,
            "accessToken": self.access_token,
        })
        payload = self._post_raw(body)
        if self._is_success(payload):
            return payload
        if not self._looks_like_auth_failure(payload):
            raise BintangError(f"Bintang44 API rejected request: {self._message(payload)}")

        log.warning(
            "SESSION LOST/EXPIRED - API rejected current token: %s. Re-login starts now.",
            self._message(payload),
        )
        last_payload = payload
        for attempt in range(1, self.cfg.auth_relogin_retries + 1):
            try:
                self.force_login()
                body["accessId"] = self.access_id
                body["accessToken"] = self.access_token
                last_payload = self._post_raw(body)
                if self._is_success(last_payload):
                    log.info("SESSION RECOVERED on attempt %s", attempt)
                    return last_payload
                if not self._looks_like_auth_failure(last_payload):
                    raise BintangError(
                        f"Bintang44 API rejected request after re-login: {self._message(last_payload)}"
                    )
                log.warning(
                    "Re-login attempt %s got another auth rejection: %s",
                    attempt, self._message(last_payload),
                )
            except BintangError as exc:
                log.warning("Immediate re-login attempt %s failed: %s", attempt, exc)
            except Exception as exc:
                log.warning("Immediate re-login attempt %s failed: %s", attempt, exc)
            if attempt < self.cfg.auth_relogin_retries:
                time.sleep(min(0.5 * attempt, 2.0))

        raise BintangError(
            "Bintang44 session could not be recovered after re-login attempts. "
            f"Last API response: {self._message(last_payload)}"
        )

    def session_healthcheck(self) -> None:
        today = datetime.now(ZoneInfo(self.cfg.report_timezone)).strftime("%Y-%m-%d")
        form = {
            "sDate": today,
            "eDate": today,
            "period": "Daily",
            "type": "ALL",
            "module": "/reports/transactions",
        }
        self._authenticated_post(form)

    @staticmethod
    def _fmt_dt(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def transaction_totals(self, start: datetime, end: datetime) -> Totals:
        form = {
            "pageIndex": "0", "includeAdmin": "1", "background": "0",
            "transactionId": "", "name": "", "type": "DEPOSIT",
            "sDate": self._fmt_dt(start), "eDate": self._fmt_dt(end),
            "sCash": "", "eCash": "", "status": "COMPLETED", "agent": "",
            "bankId": "", "otherInfo": "", "module": "/transactions/getAllTransactions",
        }
        payload = self._authenticated_post(form)
        data = payload.get("data") or {}
        if not isinstance(data, dict) or "totalCount" not in data or "totalAmount" not in data:
            raise BintangError("Transaction API response missing data.totalCount/data.totalAmount")
        return Totals.from_values(data.get("totalCount"), data.get("totalAmount"))

    def daily_report_totals(self, report_date: datetime) -> Totals:
        date_text = report_date.strftime("%Y-%m-%d")
        form = {
            "sDate": date_text, "eDate": date_text, "period": "Daily", "type": "ALL",
            "module": "/reports/transactions",
        }
        payload = self._authenticated_post(form)
        data = payload.get("data") or {}
        day = data.get(date_text) or {} if isinstance(data, dict) else {}
        dep = day.get("DEPOSIT") or {} if isinstance(day, dict) else {}
        if "count" not in dep or "amount" not in dep:
            raise BintangError(f"Daily report response missing DEPOSIT totals for {date_text}")
        return Totals.from_values(dep.get("count"), dep.get("amount"))
