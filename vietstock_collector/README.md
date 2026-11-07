# vietstock_collector

App dòng lệnh thu thập thông tin cổ phiếu từ trang công khai của
[finance.vietstock.vn](https://finance.vietstock.vn), lưu vào SQLite và xuất ra CSV/JSON.

## Dữ liệu thu thập

Với mỗi mã (ví dụ `FPT`), app đọc trang tổng quan `https://finance.vietstock.vn/FPT-x.htm` và lấy:

| Nhóm | Trường |
|---|---|
| Giá | `price`, `change`, `percent_change`, `trading_time`, `trading_status`, `exchange` |
| Ngành | `sector` (ngành cấp 1 > cấp 2 > cấp 3) |
| Liên hệ | `company_name`, `english_name`, `short_name`, `address`, `phone`, `fax`, `email`, `website` |
| Niêm yết | `first_trading_date`, `ipo_price`, `initial_listed_shares`, `listed_shares`, `outstanding_shares`, `listing_advisor` |
| Đăng ký kinh doanh | `company_status`, `tax_code`, `establishment_license(_date)`, `business_license(_date)` |

Giá là giá cuối phiên/giá gần nhất hiển thị trên trang (đơn vị VND). Các trường Vietstock ẩn với
khách chưa đăng nhập (hiển thị `***`) sẽ để trống.

## Cài đặt

```bash
cd vietstock_collector
pip install -r requirements.txt
```

## Sử dụng

```bash
# Xem nhanh, in bảng ra màn hình
python -m vietstock_collector fetch FPT VNM HPG

# In đầy đủ dạng JSON
python -m vietstock_collector fetch VCB --json

# Thu thập và lưu vào SQLite (mặc định data/vietstock.db)
python -m vietstock_collector collect FPT VNM HPG
python -m vietstock_collector collect -f symbols.example.txt

# Theo dõi định kỳ, mỗi 5 phút một lượt (Ctrl+C để dừng)
python -m vietstock_collector watch -f symbols.example.txt --interval 300

# Xuất dữ liệu đã lưu
python -m vietstock_collector export -o data/latest.csv --latest      # bản mới nhất mỗi mã
python -m vietstock_collector export -o data/fpt.json --symbol FPT    # toàn bộ lịch sử của FPT
```

File danh sách mã: mỗi dòng một hoặc nhiều mã, cách nhau bằng dấu phẩy/khoảng trắng; `#` là chú thích.

Mỗi lần `collect`/`watch` thêm một bản ghi mới (bảng `snapshots`), nên có thể dựng lịch sử giá theo thời gian.

## AI agent

Agent dùng Claude (Anthropic API) để trả lời câu hỏi bằng ngôn ngữ tự nhiên. Nó tự gọi các chức năng
của app như những tool:

| Tool | Việc làm |
|---|---|
| `get_stock_info` | Lấy dữ liệu trực tiếp từ Vietstock cho một hoặc nhiều mã và lưu vào SQLite |
| `list_saved_symbols` | Liệt kê các mã đã lưu, số snapshot, thời gian thu thập |
| `query_history` | Đọc các snapshot đã lưu để xem diễn biến giá |
| `export_data` | Xuất CSV/JSON vào `data/exports/` (chỉ khi được yêu cầu) |

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # lấy tại console.anthropic.com

# Trò chuyện nhiều lượt (/reset để xóa hội thoại, /exit để thoát)
python -m vietstock_collector chat

# Hỏi một câu
python -m vietstock_collector ask "So sánh giá và vốn hóa ước tính của FPT, VNM, HPG"
python -m vietstock_collector ask "Xuất lịch sử FPT ra file fpt.csv"
```

Mặc định dùng model `claude-opus-5-5` với effort `medium`. Có thể đổi bằng `--model` và
`--effort low|medium|high|xhigh|max`; effort thấp hơn thì nhanh và rẻ hơn. Các tool được gọi sẽ in ra
stderr để bạn thấy agent đang làm gì. Mỗi câu hỏi tốn phí gọi API theo bảng giá của Anthropic.

Agent chỉ biết những dữ liệu app thu thập được: chưa có giá lịch sử OHLC hay báo cáo tài chính. Câu trả
lời chỉ mang tính tham khảo, không phải khuyến nghị đầu tư.

## Lưu ý

- App nghỉ 1.5 giây giữa các request (`--delay`) và tự thử lại khi gặp lỗi mạng/5xx. Đừng đặt
  `--interval` quá ngắn; giá trên trang cũng chỉ cập nhật trong giờ giao dịch.
- App chỉ đọc trang HTML công khai, không đăng nhập và không gọi API nội bộ cần token. Hãy tuân thủ
  điều khoản sử dụng của Vietstock khi dùng dữ liệu.
- Nếu Vietstock đổi giao diện, chỉ cần sửa `vietstock_collector/parser.py`.

## Chạy test

```bash
pip install pytest
python -m pytest tests
```
