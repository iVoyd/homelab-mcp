"""The demo loop, driven by a scripted fake Claude client (no network)."""

import asyncio
from types import SimpleNamespace as NS

from homelab_mcp import demo
from homelab_mcp.server import build_server


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, args):
    return NS(type="tool_use", id=id_, name=name, input=args)


def usage(i, o, cr=0, cw=0):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr,
              cache_creation_input_tokens=cw)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        # Copy the message list: the loop keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def scripted():
    return [
        NS(stop_reason="tool_use", usage=usage(1500, 60, cw=1400),
           content=[NS(type="thinking", thinking=""), text("Checking the CronJobs and Jobs."),
                    tool_use("t1", "k3s_cronjobs", {"namespace": "default"}),
                    tool_use("t2", "k3s_jobs", {"namespace": "default", "limit": 5})]),
        NS(stop_reason="tool_use", usage=usage(300, 40, cr=1400),
           content=[tool_use("t3", "job_logs",
                             {"namespace": "default", "job": "job-radar-nightly-29370435"}),
                    tool_use("t4", "run_job", {"cronjob": "default/job-radar-nightly",
                                               "confirm": True})]),
        NS(stop_reason="end_turn", usage=usage(900, 120, cr=1700),
           content=[text("Yes. job-radar-nightly-29370435 succeeded in 282s and found "
                         "3 new matches.")]),
    ]


def in_process_tools(service):
    server = build_server(service)
    listed = asyncio.run(server.list_tools())
    tools = [demo.mcp_tool_to_anthropic(t) for t in listed if t.name not in demo.EXCLUDED_TOOLS]

    async def call_tool(name, args):
        return demo.result_text(await server.call_tool(name, args))

    return tools, call_tool


def run(service, responses):
    tools, call_tool = in_process_tools(service)
    client = FakeClient(responses)
    t = asyncio.run(demo.run_conversation(client, tools, call_tool, demo.DEFAULT_QUESTION))
    return t, client


def test_loop_calls_real_tools_and_records_answer(service, runner):
    t, client = run(service, scripted())
    assert t.answer.startswith("Yes. job-radar-nightly-29370435 succeeded")
    assert [s.name for s in t.steps if s.kind == "tool"] == [
        "k3s_cronjobs", "k3s_jobs", "job_logs", "run_job",
    ]
    logs = next(s for s in t.steps if s.name == "job_logs")
    assert "sk-ant-" not in logs.result and "[REDACTED" in logs.result


def test_run_job_is_not_offered_and_is_refused(service, runner):
    t, client = run(service, scripted())
    offered = {tool["name"] for tool in client.requests[0]["tools"]}
    assert "run_job" not in offered and "k3s_jobs" in offered
    refused = next(s for s in t.steps if s.name == "run_job")
    assert refused.is_error and "not available" in refused.result
    assert not any("create" in argv for argv, _ in runner.calls)


def test_request_shape(service):
    t, client = run(service, scripted())
    first, second = client.requests[0], client.requests[1]
    assert first["model"] == "claude-haiku-5-5"
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["system"] == demo.SYSTEM_PROMPT
    # Second request: question, full assistant content (incl. thinking), one user
    # message carrying both tool results.
    msgs = second["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][0].type == "thinking"
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" for r in results)


def test_usage_and_cost(service):
    t, _ = run(service, scripted())
    u = t.usage
    assert (u.requests, u.input_tokens, u.output_tokens) == (3, 2700, 220)
    assert (u.cache_creation_input_tokens, u.cache_read_input_tokens) == (1400, 3100)
    expected = (2700 * 0.10 + 1400 * 0.125 + 3100 * 0.01 + 220 * 0.50) / 1e6
    assert abs(u.cost_usd("claude-haiku-5-5") - expected) < 1e-12
    assert u.cost_usd("unknown-model") is None


def test_tool_error_is_flagged(service):
    responses = [
        NS(stop_reason="tool_use", usage=usage(10, 5),
           content=[tool_use("t1", "k3s_jobs", {"namespace": "kube-system"})]),
        NS(stop_reason="end_turn", usage=usage(10, 5), content=[text("Not allowed.")]),
    ]
    t, client = run(service, responses)
    assert t.steps[0].is_error
    assert client.requests[1]["messages"][2]["content"][0]["is_error"] is True


def test_refusal_and_max_turns(service):
    t, _ = run(service, [NS(stop_reason="refusal", usage=usage(10, 0), content=[])])
    assert "declined" in t.answer

    loop = [NS(stop_reason="tool_use", usage=usage(1, 1),
               content=[tool_use(f"t{i}", "systemd_timers", {})]) for i in range(12)]
    t, _ = run(service, loop)
    assert "max_turns" in t.answer


def test_markdown_render(service):
    t, _ = run(service, scripted())
    md = demo.render_markdown(t)
    assert "> Did last night's job succeed" in md
    assert "### 3. `job_logs`" in md
    assert "### 4. `run_job` (error)" in md
    assert "| 3 | 2700 | 1400 | 3100 | 220 |" in md
    assert "sk-ant-api03" not in md


def test_main_requires_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert demo.main([]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_record_over_real_stdio_server(tmp_path, sample_db, monkeypatch):
    import anthropic

    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[sqlite.databases]\napp = "{sample_db}"\n'
                   f'[audit]\npath = "{tmp_path}/audit.jsonl"\n')
    responses = [
        NS(stop_reason="tool_use", usage=usage(100, 10),
           content=[tool_use("t1", "sqlite_query",
                             {"db_alias": "app", "sql": "SELECT status, note FROM runs"})]),
        NS(stop_reason="end_turn", usage=usage(50, 20), content=[text("Two runs.")]),
    ]
    fake = FakeClient(responses)
    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake)
    out = tmp_path / "demo.md"
    t = asyncio.run(demo.record(str(cfg), "How many runs?", demo.DEFAULT_MODEL, out))
    assert t.answer == "Two runs."
    assert '"row_count": 2' in t.steps[0].result
    assert "admin@example.com" not in out.read_text()
    offered = [tool["name"] for tool in fake.requests[0]["tools"]]
    assert offered == sorted(offered) and "run_job" not in offered
    assert (tmp_path / "audit.jsonl").read_text().count('"tool": "sqlite_query"') == 1
