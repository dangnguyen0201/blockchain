"""Parse the public stock overview page of finance.vietstock.vn.

The parser is a pure function over HTML so it can be tested offline.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class StockSnapshot:
    symbol: str
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    price: Optional[float] = None
    change: Optional[float] = None
    percent_change: Optional[float] = None
    trading_time: Optional[str] = None  # ISO 8601, local exchange time (UTC+7)
    trading_status: Optional[str] = None
    sector: list[str] = field(default_factory=list)
    english_name: Optional[str] = None
    short_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    first_trading_date: Optional[str] = None  # ISO date
    ipo_price: Optional[float] = None
    initial_listed_shares: Optional[int] = None
    listed_shares: Optional[int] = None
    outstanding_shares: Optional[int] = None
    listing_advisor: Optional[str] = None
    company_status: Optional[str] = None
    tax_code: Optional[str] = None
    establishment_license: Optional[str] = None
    establishment_license_date: Optional[str] = None
    business_license: Optional[str] = None
    business_license_date: Optional[str] = None
    collected_at: Optional[str] = None
    source_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ParseError(ValueError):
    """Raised when the page does not look like a Vietstock stock page."""


_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_number(text: Optional[str]) -> Optional[float]:
    """'50,800' -> 50800.0, '-3.97%' -> -3.97, '***' / '' -> None."""
    if not text:
        return None
    m = _NUM_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def parse_int(text: Optional[str]) -> Optional[int]:
    value = parse_number(text)
    return int(value) if value is not None else None


def parse_date(text: Optional[str]) -> Optional[str]:
    """'13/12/2006' -> '2006-12-13'."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_datetime(text: Optional[str]) -> Optional[str]:
    """'06/11/2026 14:56' -> '2026-11-06T14:56:00'."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y %H:%M").isoformat()
    except ValueError:
        return None


def _text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    # Fields hidden from anonymous visitors are rendered as "***".
    if not value or set(value) == {"*"}:
        return None
    return value


def _pairs(container: Optional[Tag], item_sel: str, label_sel: str, value_sel: str) -> list[tuple[str, Optional[str]]]:
    """Ordered (label, value) pairs; order matters because labels can repeat."""
    if container is None:
        return []
    out = []
    for item in container.select(item_sel):
        label = _text(item.select_one(label_sel))
        if label:
            out.append((label, _text(item.select_one(value_sel))))
    return out


_CONTACT_FIELDS = {
    "Tên tiếng Anh": "english_name",
    "Tên viết tắt": "short_name",
    "Địa chỉ": "address",
    "Điện thoại": "phone",
    "Fax": "fax",
    "Email": "email",
    "Website": "website",
}


def parse_stock_page(html: str, symbol: str) -> StockSnapshot:
    soup = BeautifulSoup(html, "lxml")
    header = soup.select_one(".company-general__group-info")
    if header is None:
        raise ParseError(f"{symbol}: không tìm thấy thông tin cổ phiếu trên trang")

    snap = StockSnapshot(symbol=symbol.upper())
    snap.company_name = _text(header.select_one(".company-general-name"))
    code = _text(header.select_one(".company-general-stock-code"))
    if code:
        snap.symbol = code.upper()
    snap.exchange = _text(header.select_one(".company-general-stock-exchange"))
    snap.price = parse_number(_text(header.select_one("#company-price-desk")))
    snap.change = parse_number(_text(header.select_one("#company-change-desk")))
    snap.percent_change = parse_number(_text(header.select_one("#company-perchange-desk")))
    snap.trading_time = parse_datetime(_text(header.select_one("#company-general-trading-date-desk")))
    snap.trading_status = _text(header.select_one("#company-general-trading-status-text-desk"))
    sector = header.select_one("#company-general-sector-desk")
    if sector is not None:
        snap.sector = [a.get_text(strip=True) for a in sector.select(".company-general-sector-link a")]

    # --- Contact ---
    for label, value in _pairs(
        soup.select_one("#overview-profile-contact"),
        ".overview-profile__contact-stat",
        ".overview-profile__contact-stat-title",
        ".overview-profile__contact-stat-val",
    ):
        attr = _CONTACT_FIELDS.get(label)
        if attr:
            setattr(snap, attr, value)

    # --- Listing ---
    for label, value in _pairs(
        soup.select_one("#overview-profile-listing"),
        ".overview-profile__listing-box",
        ".overview-profile__listing-label",
        ".overview-profile__listing-value, .overview-profile__listing-value-advisor",
    ):
        if label == "Ngày giao dịch đầu tiên":
            snap.first_trading_date = parse_date(value)
        elif label == "Giá chào sàn":
            snap.ipo_price = parse_number(value)
        elif label == "Khối lượng niêm yết lần đầu":
            snap.initial_listed_shares = parse_int(value)
        elif label == "Khối lượng niêm yết":
            snap.listed_shares = parse_int(value)
        elif label == "Khối lượng lưu hành":
            snap.outstanding_shares = parse_int(value)
        elif label == "Tư vấn niêm yết":
            snap.listing_advisor = value

    # --- Business registration ("Ngày cấp" follows the license it belongs to) ---
    last_license = None
    for label, value in _pairs(
        soup.select_one("#overview-profile-business"),
        ".overview-profile__business-stat",
        ".overview-profile__contact-stat-title",
        ".overview-profile__contact-stat-val",
    ):
        if label == "Trạng thái":
            snap.company_status = value
        elif label == "Mã số thuế":
            snap.tax_code = value
        elif label == "GPTL":
            snap.establishment_license, last_license = value, "establishment_license"
        elif label == "GPKD":
            snap.business_license, last_license = value, "business_license"
        elif label == "Ngày cấp" and last_license:
            setattr(snap, f"{last_license}_date", parse_date(value))

    return snap
