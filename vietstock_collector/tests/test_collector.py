from pathlib import Path

import pytest

from vietstock_collector.parser import ParseError, parse_number, parse_stock_page
from vietstock_collector.storage import Storage, export_rows

FIXTURE = (Path(__file__).parent / "fixtures" / "stock_page.html").read_text(encoding="utf-8")


def test_parse_number():
    assert parse_number("50,800") == 50800
    assert parse_number("-2,100") == -2100
    assert parse_number("+0.52%") == 0.52
    assert parse_number("***") is None
    assert parse_number(None) is None


def test_parse_stock_page():
    s = parse_stock_page(FIXTURE, "abc")
    assert s.symbol == "ABC"
    assert s.company_name == "CTCP Mẫu"
    assert s.exchange == "HOSE"
    assert s.price == 50800
    assert s.change == -2100
    assert s.percent_change == -3.97
    assert s.trading_time == "2026-11-06T14:56:00"
    assert s.trading_status == "Kết thúc phiên"
    assert s.sector == ["Công nghệ thông tin", "Phần mềm và dịch vụ", "Phần mềm"]
    assert s.english_name == "Sample Corporation"
    assert s.email == "ir@example.com"
    assert s.website == "https://example.com"
    assert s.first_trading_date == "2006-12-13"
    assert s.ipo_price == 400000
    assert s.listed_shares == 1885727648
    assert s.outstanding_shares == 1885727648
    assert s.listing_advisor is None
    assert s.tax_code == "0101248141"
    assert s.establishment_license == "178/QĐ-TTG"
    assert s.establishment_license_date == "2002-02-28"
    assert s.business_license_date == "2002-05-13"


def test_parse_rejects_other_pages():
    with pytest.raises(ParseError):
        parse_stock_page("<html><body>404</body></html>", "XYZ")


def test_storage_roundtrip(tmp_path):
    snap = parse_stock_page(FIXTURE, "ABC")
    snap.collected_at = "2026-11-07T08:00:00+00:00"
    with Storage(tmp_path / "db.sqlite") as st:
        st.save(snap)
        snap.price = 51000
        snap.collected_at = "2026-11-07T09:00:00+00:00"
        st.save(snap)
        assert len(st.query()) == 2
        latest = st.query(symbol="abc", latest_only=True)
    assert len(latest) == 1
    assert latest[0]["price"] == 51000
    assert latest[0]["sector"][0] == "Công nghệ thông tin"
    assert latest[0]["listed_shares"] == 1885727648

    export_rows(latest, tmp_path / "out.csv", "csv")
    text = (tmp_path / "out.csv").read_text(encoding="utf-8-sig")
    assert "Công nghệ thông tin > Phần mềm và dịch vụ" in text
    export_rows(latest, tmp_path / "out.json", "json")
    assert "CTCP Mẫu" in (tmp_path / "out.json").read_text(encoding="utf-8")
