"""Offline tests for the agent: a scripted fake replaces the Claude API."""

import json
from pathlib import Path
from types import SimpleNamespace

from vietstock_collector.agent import TOOLS, StockAgent, StockTools
from vietstock_collector.parser import parse_stock_page
from vietstock_collector.storage import Storage

FIXTURE = (Path(__file__).parent / "fixtures" / "stock_page.html").read_text(encoding="utf-8")


class FakeVietstock:
    def get_many(self, symbols):
        for s in symbols:
            if s == "ABC":
                snap = parse_stock_page(FIXTURE, s)
                snap.collected_at = "2026-11-07T08:00:00+00:00"
                yield s, snap, None
            else:
                yield s, None, LookupError(f"Không tìm thấy mã {s}")


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


class FakeClaude:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        content, stop = self.responses.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop)


def make_tools(tmp_path):
    return StockTools(tmp_path / "db.sqlite", client=FakeVietstock(), export_dir=tmp_path / "exports")


def test_tool_schemas_are_strict():
    for t in TOOLS:
        assert t["strict"] is True
        assert t["input_schema"]["additionalProperties"] is False
        assert set(t["input_schema"]["required"]) <= set(t["input_schema"]["properties"])


def test_get_stock_info_saves_and_reports_errors(tmp_path):
    tools = make_tools(tmp_path)
    content, is_error = tools.run("get_stock_info", {"symbols": ["abc", "zzz"]})
    assert not is_error
    data = json.loads(content)
    assert [s["symbol"] for s in data["stocks"]] == ["ABC"]
    assert "ZZZ" in data["errors"]
    with Storage(tmp_path / "db.sqlite") as st:
        assert st.summary()[0]["symbol"] == "ABC"


def test_export_stays_in_export_dir(tmp_path):
    tools = make_tools(tmp_path)
    tools.run("get_stock_info", {"symbols": ["ABC"]})
    content, is_error = tools.run("export_data", {"filename": "../../evil", "format": "csv"})
    assert not is_error
    path = Path(json.loads(content)["path"])
    assert path.parent == tmp_path / "exports" and path.name == "evil.csv"
    assert path.exists()


def test_tool_errors_are_reported(tmp_path):
    tools = make_tools(tmp_path)
    assert tools.run("nope", {})[1] is True
    assert tools.run("get_stock_info", {"symbols": []})[1] is True
    assert tools.run("export_data", {"filename": "x.csv", "format": "csv"})[1] is True  # empty DB


def test_agent_loop_runs_tools_and_keeps_history(tmp_path):
    fake = FakeClaude([
        ([text("Để tôi xem."), tool_use("t1", "get_stock_info", {"symbols": ["ABC"]}),
          tool_use("t2", "list_saved_symbols", {})], "tool_use"),
        ([text("ABC đang ở 50,800 VND.")], "end_turn"),
        ([text("Không có thay đổi.")], "end_turn"),
    ])
    calls = []
    agent = StockAgent(make_tools(tmp_path), client=fake, on_tool_call=lambda n, i: calls.append(n))

    assert agent.ask("Giá ABC?") == "ABC đang ở 50,800 VND."
    assert calls == ["get_stock_info", "list_saved_symbols"]

    # Both tool results come back in one user message, matched by id.
    results = fake.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert all(r["is_error"] is False for r in results)

    # Request shape
    req = fake.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert req["thinking"] == {"type": "adaptive"}

    # Follow-up turn sends the whole history, system prompt unchanged (cache-friendly).
    agent.ask("Còn bây giờ?")
    assert len(fake.calls[2]["messages"]) == 5
    assert fake.calls[2]["system"] == fake.calls[0]["system"]


def test_agent_handles_refusal(tmp_path):
    fake = FakeClaude([([], "refusal")])
    agent = StockAgent(make_tools(tmp_path), client=fake)
    assert "không thể" in agent.ask("...")
