"""HTTP client for the public stock pages of finance.vietstock.vn."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

import requests

from . import __version__
from .parser import ParseError, StockSnapshot, parse_stock_page

BASE_URL = "https://finance.vietstock.vn"
USER_AGENT = f"vietstock-collector/{__version__}"


class StockNotFound(LookupError):
    pass


class VietstockClient:
    """Fetches one page per symbol, politely (delay between requests, retries)."""

    def __init__(
        self,
        delay: float = 1.5,
        timeout: float = 30.0,
        retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        if session is None:
            # requests' default "python-requests/x" UA is refused by the site; identify the app instead.
            self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0

    @staticmethod
    def stock_url(symbol: str) -> str:
        # Vietstock ignores the slug after the code, so "<CODE>-x.htm" resolves any symbol.
        return f"{BASE_URL}/{symbol.strip().upper()}-x.htm"

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def fetch_html(self, symbol: str) -> str:
        url = self.stock_url(symbol)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code == 404:
                    raise StockNotFound(f"Không tìm thấy mã {symbol.upper()} trên Vietstock")
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    resp.encoding = resp.encoding or "utf-8"
                    return resp.text
                last_exc = requests.HTTPError(f"HTTP {resp.status_code} for {url}")
            time.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc

    def get_stock(self, symbol: str) -> StockSnapshot:
        html = self.fetch_html(symbol)
        snap = parse_stock_page(html, symbol)
        snap.source_url = self.stock_url(symbol)
        snap.collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return snap

    def get_many(self, symbols: Iterable[str]) -> Iterator[tuple[str, Optional[StockSnapshot], Optional[Exception]]]:
        """Yield (symbol, snapshot, error) for each symbol; one failure does not stop the rest."""
        for symbol in symbols:
            try:
                yield symbol.upper(), self.get_stock(symbol), None
            except (StockNotFound, ParseError, requests.RequestException) as exc:
                yield symbol.upper(), None, exc
