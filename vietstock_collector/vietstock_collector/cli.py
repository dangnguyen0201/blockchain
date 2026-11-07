"""Command line interface.

    python -m vietstock_collector fetch FPT VNM
    python -m vietstock_collector collect FPT VNM HPG --db data/stocks.db
    python -m vietstock_collector watch FPT VNM --interval 300
    python -m vietstock_collector export --db data/stocks.db --format csv -o out.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .client import VietstockClient
from .storage import Storage, export_rows

DEFAULT_DB = "data/vietstock.db"


def _read_symbols(args: argparse.Namespace) -> list[str]:
    symbols = [s.upper() for s in args.symbols]
    if getattr(args, "file", None):
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                symbols.extend(s.upper() for s in line.replace(",", " ").split())
    symbols = list(dict.fromkeys(symbols))  # dedupe, keep order
    if not symbols:
        raise SystemExit("Cần ít nhất một mã chứng khoán (ví dụ: FPT VNM) hoặc --file")
    return symbols


def _print_table(rows: list[dict]) -> None:
    header = f"{'Mã':<6} {'Sàn':<6} {'Giá':>10} {'+/-':>9} {'%':>7}  {'Thời gian':<16}  Tên công ty"
    print(header)
    print("-" * len(header))
    for r in rows:
        def num(v, fmt):
            return format(v, fmt) if v is not None else "-"
        print(
            f"{r['symbol']:<6} {r.get('exchange') or '-':<6} {num(r.get('price'), ',.0f'):>10} "
            f"{num(r.get('change'), '+,.0f'):>9} {num(r.get('percent_change'), '+.2f'):>7}  "
            f"{(r.get('trading_time') or '-').replace('T', ' ')[:16]:<16}  {r.get('company_name') or ''}"
        )


def _collect(client: VietstockClient, symbols: list[str], storage: Storage | None) -> list[dict]:
    rows = []
    for symbol, snap, err in client.get_many(symbols):
        if err is not None:
            print(f"[lỗi] {symbol}: {err}", file=sys.stderr)
            continue
        if storage is not None:
            storage.save(snap)
        rows.append(snap.to_dict())
    return rows


def cmd_fetch(args: argparse.Namespace) -> int:
    client = VietstockClient(delay=args.delay)
    rows = _collect(client, _read_symbols(args), None)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
    return 0 if rows else 1


def cmd_collect(args: argparse.Namespace) -> int:
    client = VietstockClient(delay=args.delay)
    symbols = _read_symbols(args)
    with Storage(args.db) as storage:
        rows = _collect(client, symbols, storage)
    _print_table(rows)
    print(f"\nĐã lưu {len(rows)}/{len(symbols)} mã vào {args.db}")
    return 0 if rows else 1


def cmd_watch(args: argparse.Namespace) -> int:
    client = VietstockClient(delay=args.delay)
    symbols = _read_symbols(args)
    rounds = 0
    with Storage(args.db) as storage:
        try:
            while True:
                rounds += 1
                print(f"\n=== Lượt {rounds} — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
                _print_table(_collect(client, symbols, storage))
                if args.count and rounds >= args.count:
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nDừng theo dõi.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with Storage(args.db) as storage:
        rows = storage.query(symbol=args.symbol, latest_only=args.latest)
    fmt = args.format or Path(args.output).suffix.lstrip(".").lower()
    export_rows(rows, args.output, fmt)
    print(f"Đã xuất {len(rows)} dòng ra {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vietstock_collector",
        description="Thu thập thông tin chứng khoán từ finance.vietstock.vn",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_symbols(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("symbols", nargs="*", help="Mã chứng khoán, ví dụ FPT VNM HPG")
        sp.add_argument("-f", "--file", help="File chứa danh sách mã (mỗi dòng hoặc cách nhau bằng dấu phẩy)")
        sp.add_argument("--delay", type=float, default=1.5, help="Giây nghỉ giữa các request (mặc định 1.5)")

    sp = sub.add_parser("fetch", help="Lấy dữ liệu và in ra màn hình")
    add_symbols(sp)
    sp.add_argument("--json", action="store_true", help="In đầy đủ dạng JSON")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("collect", help="Lấy dữ liệu và lưu vào SQLite")
    add_symbols(sp)
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.set_defaults(func=cmd_collect)

    sp = sub.add_parser("watch", help="Thu thập lặp lại theo chu kỳ")
    add_symbols(sp)
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.add_argument("--interval", type=float, default=300, help="Giây giữa các lượt (mặc định 300)")
    sp.add_argument("--count", type=int, default=0, help="Số lượt rồi dừng (0 = chạy mãi)")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("export", help="Xuất dữ liệu đã lưu ra CSV/JSON")
    sp.add_argument("--db", default=DEFAULT_DB)
    sp.add_argument("-o", "--output", required=True, help="File đầu ra (.csv hoặc .json)")
    sp.add_argument("--format", choices=["csv", "json"])
    sp.add_argument("--symbol", help="Chỉ xuất một mã")
    sp.add_argument("--latest", action="store_true", help="Chỉ lấy bản ghi mới nhất của mỗi mã")
    sp.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
