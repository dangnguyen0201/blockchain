"""AI agent (Claude) that answers questions about Vietnamese stocks using the collector as tools.

The agent can fetch live data from Vietstock, read the snapshots stored in SQLite and export files.
It runs a manual tool-use loop so the whole conversation (including tool calls) is kept between
turns, which lets the user ask follow-up questions.

Requires `pip install anthropic` and credentials in the environment (ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

from .client import VietstockClient
from .storage import Storage, export_rows

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
MAX_TOOL_ROUNDS = 15
EXPORT_DIR = Path("data/exports")

SYSTEM_PROMPT = """Bạn là trợ lý dữ liệu chứng khoán Việt Nam, làm việc với app vietstock_collector.

Nguồn dữ liệu là trang tổng quan cổ phiếu công khai của finance.vietstock.vn. Mỗi mã có: giá gần nhất \
(VND), thay đổi +/- và %, thời điểm và trạng thái phiên, sàn, ngành 3 cấp, thông tin liên hệ, thông tin \
niêm yết (ngày giao dịch đầu tiên, giá chào sàn, khối lượng niêm yết/lưu hành) và đăng ký kinh doanh. \
App không có giá lịch sử theo ngày (OHLC), khối lượng giao dịch hay báo cáo tài chính; nếu người dùng \
hỏi những thứ đó, nói rõ là app chưa có thay vì đoán.

Cách làm việc:
- Khi người dùng hỏi giá hoặc thông tin hiện tại, gọi get_stock_info để lấy dữ liệu mới; đừng trả lời \
giá từ trí nhớ.
- Khi hỏi về diễn biến đã thu thập trước đó, dùng list_saved_symbols và query_history.
- Có thể gọi nhiều tool song song khi các bước độc lập.
- Chỉ xuất file khi người dùng yêu cầu.
- Vốn hóa ước tính = giá × khối lượng lưu hành; nếu tính, ghi rõ là ước tính.
- Trả lời bằng ngôn ngữ người dùng dùng (mặc định tiếng Việt), ngắn gọn, số có dấu phẩy phân cách \
hàng nghìn, nêu thời điểm của dữ liệu.
- Đây là thông tin tham khảo, không phải khuyến nghị đầu tư; không đưa ra lời khuyên mua/bán chắc chắn."""


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "get_stock_info",
        "Lấy dữ liệu trực tiếp từ Vietstock cho một hoặc nhiều mã cổ phiếu (giá, ngành, hồ sơ, niêm yết). "
        "Mỗi mã mất khoảng 1-2 giây. Mặc định lưu kết quả vào cơ sở dữ liệu để xem lại sau.",
        {
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Mã cổ phiếu, ví dụ [\"FPT\", \"VNM\"]. Tối đa 20 mã mỗi lần.",
            },
            "save": {"type": "boolean", "description": "Lưu snapshot vào SQLite (mặc định true)."},
        },
        ["symbols"],
    ),
    _tool(
        "list_saved_symbols",
        "Liệt kê các mã đã có trong cơ sở dữ liệu, kèm số snapshot và khoảng thời gian thu thập.",
        {},
        [],
    ),
    _tool(
        "query_history",
        "Đọc các snapshot đã lưu của một mã (hoặc tất cả mã) theo thứ tự thời gian thu thập.",
        {
            "symbol": {"type": "string", "description": "Mã cổ phiếu; bỏ trống để lấy mọi mã."},
            "latest_only": {"type": "boolean", "description": "Chỉ lấy bản mới nhất của mỗi mã."},
            "limit": {"type": "integer", "description": "Số dòng gần nhất tối đa trả về (mặc định 50)."},
        },
        [],
    ),
    _tool(
        "export_data",
        "Xuất snapshot đã lưu ra file CSV hoặc JSON trong thư mục data/exports. Chỉ dùng khi người dùng yêu cầu.",
        {
            "filename": {"type": "string", "description": "Tên file, ví dụ fpt.csv (không chứa thư mục)."},
            "format": {"type": "string", "enum": ["csv", "json"]},
            "symbol": {"type": "string", "description": "Chỉ xuất một mã; bỏ trống để xuất mọi mã."},
            "latest_only": {"type": "boolean"},
        },
        ["filename", "format"],
    ),
]

# Fields that are useful for answering; contact/licence details are kept but trimmed of nothing.
_HISTORY_FIELDS = ("symbol", "price", "change", "percent_change", "trading_time", "trading_status", "collected_at")


class ToolError(Exception):
    """An error the model should see as an is_error tool result."""


class StockTools:
    """Executes the agent's tools against the collector and the SQLite database."""

    def __init__(self, db_path: str | Path, client: Optional[VietstockClient] = None,
                 export_dir: str | Path = EXPORT_DIR) -> None:
        self.db_path = Path(db_path)
        self._client = client
        self.export_dir = Path(export_dir)

    @property
    def client(self) -> VietstockClient:
        if self._client is None:
            self._client = VietstockClient()
        return self._client

    def get_stock_info(self, symbols: list[str], save: bool = True) -> dict:
        symbols = [s.strip().upper() for s in symbols if s.strip()]
        if not symbols:
            raise ToolError("Cần ít nhất một mã cổ phiếu.")
        if len(symbols) > 20:
            raise ToolError("Tối đa 20 mã mỗi lần gọi.")
        results, errors = [], {}
        storage = Storage(self.db_path) if save else None
        try:
            for symbol, snap, err in self.client.get_many(symbols):
                if err is not None:
                    errors[symbol] = str(err)
                    continue
                if storage is not None:
                    storage.save(snap)
                results.append(snap.to_dict())
        finally:
            if storage is not None:
                storage.close()
        return {"stocks": results, "errors": errors, "saved": bool(save and results)}

    def list_saved_symbols(self) -> dict:
        with Storage(self.db_path) as st:
            return {"symbols": st.summary()}

    def query_history(self, symbol: Optional[str] = None, latest_only: bool = False, limit: int = 50) -> dict:
        limit = max(1, min(int(limit), 500))
        with Storage(self.db_path) as st:
            rows = st.query(symbol=symbol or None, latest_only=latest_only)
        total = len(rows)
        rows = rows[-limit:]
        if not latest_only:
            # History is about price movement; keep the payload small.
            rows = [{k: r[k] for k in _HISTORY_FIELDS} for r in rows]
        return {"rows": rows, "returned": len(rows), "total": total}

    def export_data(self, filename: str, format: str, symbol: Optional[str] = None,
                    latest_only: bool = False) -> dict:
        name = Path(filename).name  # no directories: always write inside export_dir
        if not name or name in (".", ".."):
            raise ToolError("Tên file không hợp lệ.")
        if not name.lower().endswith(f".{format}"):
            name = f"{name}.{format}"
        with Storage(self.db_path) as st:
            rows = st.query(symbol=symbol or None, latest_only=latest_only)
        if not rows:
            raise ToolError("Không có dữ liệu để xuất. Hãy thu thập trước bằng get_stock_info.")
        out = self.export_dir / name
        export_rows(rows, out, format)
        return {"path": str(out), "rows": len(rows)}

    def run(self, name: str, tool_input: dict[str, Any]) -> tuple[str, bool]:
        """Return (content, is_error) for a tool_use block."""
        handlers: dict[str, Callable[..., dict]] = {
            "get_stock_info": self.get_stock_info,
            "list_saved_symbols": self.list_saved_symbols,
            "query_history": self.query_history,
            "export_data": self.export_data,
        }
        handler = handlers.get(name)
        if handler is None:
            return f"Tool không tồn tại: {name}", True
        try:
            result = handler(**tool_input)
        except ToolError as exc:
            return str(exc), True
        except TypeError as exc:  # unexpected/missing arguments
            return f"Tham số không hợp lệ: {exc}", True
        except Exception as exc:  # network, database, ... - let the model explain it
            return f"{type(exc).__name__}: {exc}", True
        return json.dumps(result, ensure_ascii=False, default=str), False


class StockAgent:
    """Multi-turn chat agent. Call `ask()` once per user message."""

    def __init__(self, tools: StockTools, client: Any = None, model: str = MODEL,
                 effort: str = "medium",
                 on_tool_call: Optional[Callable[[str, dict], None]] = None) -> None:
        if client is None:
            import anthropic  # imported lazily so the scraper works without the SDK

            client = anthropic.Anthropic()
        self.client = client
        self.tools = tools
        self.model = model
        self.effort = effort
        self.on_tool_call = on_tool_call
        self.messages: list[dict] = []
        # The date is fixed for the session so the system prompt stays byte-identical (prompt caching).
        self.system = f"{SYSTEM_PROMPT}\n\nHôm nay là {date.today().isoformat()}."

    def _create(self):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system,
            tools=TOOLS,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            # On a safety decline the API re-runs the request on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def ask(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._create()
            # Keep the full content (thinking, tool_use, fallback blocks) so the history stays valid.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "Xin lỗi, yêu cầu này không thể được xử lý."
            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "max_tokens" and tool_uses:
                # A tool call cut off by max_tokens may have incomplete input; don't run it.
                self.messages.pop()
                return "Câu trả lời quá dài và bị cắt. Hãy hỏi cụ thể hơn."
            if not tool_uses:
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += "\n\n[Câu trả lời bị cắt do quá dài]"
                return text

            results = []
            for block in tool_uses:
                if self.on_tool_call:
                    self.on_tool_call(block.name, block.input)
                content, is_error = self.tools.run(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
            # All results of one turn go back in a single user message.
            self.messages.append({"role": "user", "content": results})

        return "Agent đã dừng sau quá nhiều bước gọi tool. Hãy thử chia nhỏ câu hỏi."

    def reset(self) -> None:
        self.messages.clear()
