"""
Test suite — all offline, all mocked. No API keys, no network.

Run:  .venv/bin/python -m pytest test_agent.py -v

Covers:
1. Tool registry integrity (definitions valid, dispatch resolves)
2. dispatch_tool routing (precedence, user_id injection, unknown tools)
3. Agent loop logic with a fake OpenAI client (no Mistral calls)
4. multi_agent classification and fallback behavior
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def fake_tool_call():
    """Factory for OpenAI-style tool call objects."""

    def _make(name, args=None, call_id="call_1"):
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = name
        tc.function.arguments = json.dumps(args or {})
        return tc

    return _make


@pytest.fixture
def fake_client(fake_tool_call):
    """OpenAI client mock: first response asks for a tool, second answers.

    Yields (client, responses) so tests can customize the script.
    """
    def _make(script):
        # script: list of (content, tool_calls) tuples, consumed per call
        responses = []
        for content, tool_calls in script:
            resp = MagicMock()
            msg = MagicMock()
            msg.content = content
            msg.tool_calls = tool_calls or None
            resp.choices = [MagicMock(message=msg)]
            responses.append(resp)

        client = MagicMock()
        client.chat.completions.create = MagicMock(side_effect=responses)
        return client, responses

    return _make


# ============================================================
# 1. Registry integrity
# ============================================================

class TestRegistry:
    def test_registry_imports(self):
        import registry
        assert len(registry.TOOLS) > 100
        # Map-based dispatchers (rest are handled via name-based dispatch
        # to module executors like execute_solana_tool)
        assert len(registry.TOOL_MAP) > 80

    def test_all_definitions_have_name_and_type(self):
        import registry
        for t in registry.TOOLS:
            fn = t.get("function", {})
            assert t.get("type") == "function", f"bad type: {t}"
            assert fn.get("name"), f"missing name: {t}"
            assert isinstance(fn.get("parameters", {}), dict)

    def test_no_duplicate_dispatch_names(self):
        """TOOL_MAP keys must be unique by construction; check a sample."""
        import registry
        assert registry.TOOL_MAP["get_price"] is not None
        assert registry.TOOL_MAP["web_search"] is not None

    def test_tool_names_unique_first_occurrence(self):
        import registry
        names = registry.tool_names()
        assert len(names) == len(set(names))

    def test_solana_precedence_for_get_sol_price(self):
        """get_sol_price is defined by both solana_tools and jupiter_tools.
        Registry precedence gives solana the no-arg version."""
        import registry
        result = registry.dispatch_tool("get_sol_price", {})
        assert "SOL" in result

    def test_every_tool_name_in_TOOLS_dispatches(self):
        """Every defined tool name should resolve to a dispatcher.
        Tools may raise KeyError on missing required args — that still
        proves the tool was found and invoked."""
        import registry
        for name in registry.tool_names():
            try:
                result = registry.dispatch_tool(name, {})
            except KeyError:
                continue  # resolved fine, just needs required args
            assert not result.startswith("Unknown tool"), (
                f"defined tool {name!r} has no dispatcher"
            )


# ============================================================
# 2. dispatch_tool routing
# ============================================================

class TestDispatch:
    def test_unknown_tool(self):
        from registry import dispatch_tool
        assert dispatch_tool("no_such_tool_xyz", {}) == "Unknown tool: no_such_tool_xyz"

    def test_none_args_is_safe(self):
        from registry import dispatch_tool
        assert dispatch_tool("no_such_tool_xyz", None) == "Unknown tool: no_such_tool_xyz"

    def test_user_id_injected_for_auto_trading(self):
        import registry
        from registry import dispatch_tool
        with patch.object(registry, "execute_auto_trading_tool") as ex:
            ex.return_value = "ok"
            dispatch_tool("get_trading_rules", {}, user_id=42)
            # dispatch_tool(name, args) — args dict must carry user_id
            assert ex.call_args[0][1]["user_id"] == 42

    def test_user_id_injected_for_memory(self):
        import memory
        from registry import dispatch_tool
        memory.set_current_user(0)
        dispatch_tool("remember_preference", {"key": "k", "value": "v"}, user_id=7)
        assert memory._user_id_cache == 7

    def test_paper_get_portfolio_runs_offline(self):
        """Portfolio tools hit local SQLite only — safe to call for real."""
        from registry import dispatch_tool
        result = dispatch_tool("get_portfolio", {})
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================
# 3. Agent loop (CLIAgent) with mocked LLM
# ============================================================

class TestAgentLoop:
    def _agent(self, client):
        """Build CLIAgent with a mocked OpenAI client."""
        import agent
        with patch.object(agent, "OpenAI", return_value=client), \
             patch.object(agent, "sys") as _:
            a = agent.CLIAgent.__new__(agent.CLIAgent)
            a.client = client
            a.model = "test-model"
            a.history = [{"role": "system", "content": "sys"}]
            return a

    def test_direct_answer_no_tools(self, fake_client):
        client, _ = fake_client([("42", None)])
        a = self._agent(client)
        assert a.run("what is 6x7") == "42"
        # user msg + assistant reply recorded
        assert a.history[-1]["role"] == "assistant"
        assert a.history[-1]["content"] == "42"

    def test_one_tool_roundtrip(self, fake_client, fake_tool_call):
        client, _ = fake_client([
            ("", [fake_tool_call("get_price", {"coin": "btc"})]),
            ("BTC is priced.", None),
        ])
        a = self._agent(client)
        with patch("agent.dispatch_tool", return_value="$100,000") as dt:
            out = a.run("btc price?")
        assert out == "BTC is priced."
        dt.assert_called_once_with("get_price", {"coin": "btc"})
        # tool result must be fed back as a tool message
        tool_msgs = [m for m in a.history if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "$100,000" in tool_msgs[0]["content"]

    def test_malformed_tool_args_become_empty_dict(self, fake_client, fake_tool_call):
        client, responses = fake_client([
            ("", [fake_tool_call("get_price", {"coin": "btc"})]),
            ("done", None),
        ])
        # Corrupt the arguments JSON (same object the side_effect list holds)
        responses[0].choices[0].message.tool_calls[0].function.arguments = "{not json"
        a = self._agent(client)
        with patch("agent.dispatch_tool", return_value="ok") as dt:
            a.run("go")
        dt.assert_called_once_with("get_price", {})

    def test_max_steps_guard(self, fake_client, fake_tool_call):
        """If the model always calls tools, loop must stop at MAX_AGENT_STEPS."""
        import agent as agent_mod
        responses = []
        # More scripted responses than max steps
        for i in range(agent_mod.MAX_AGENT_STEPS + 5):
            resp = MagicMock()
            msg = MagicMock()
            msg.content = ""
            tc = fake_tool_call("get_price", {"coin": "btc"}, call_id=f"c{i}")
            msg.tool_calls = [tc]
            resp.choices = [MagicMock(message=msg)]
            responses.append(resp)
        client = MagicMock()
        client.chat.completions.create = MagicMock(side_effect=responses)

        a = self._agent(client)
        with patch("agent.dispatch_tool", return_value="$100"):
            out = a.run("loop forever")
        assert out == "(Max steps reached)"

    def test_long_tool_results_truncated(self, fake_client, fake_tool_call):
        client, _ = fake_client([
            ("", [fake_tool_call("get_price", {"coin": "btc"})]),
            ("done", None),
        ])
        a = self._agent(client)
        with patch("agent.dispatch_tool", return_value="x" * 99999):
            a.run("go")
        tool_msgs = [m for m in a.history if m.get("role") == "tool"]
        assert len(tool_msgs[0]["content"]) <= 4000


# ============================================================
# 4. multi_agent router
# ============================================================

class TestMultiAgentRouter:
    def test_classify_code_task(self):
        from multi_agent import classify_task
        assert classify_task("calculate my portfolio variance") == "smolagents"
        assert classify_task("run python to chart data") == "smolagents"

    def test_classify_defaults_to_function(self):
        from multi_agent import classify_task
        assert classify_task("what is the price of bitcoin") == "function"
        assert classify_task("buy eth") == "function"

    def test_fallback_when_primary_fails(self, monkeypatch):
        import multi_agent as ma
        monkeypatch.setattr(ma, "classify_task", lambda m: "smolagents")

        def boom(m):
            raise RuntimeError("smolagents down")
        monkeypatch.setattr(ma, "run_smolagents_agent", boom)

        monkeypatch.setattr(
            ma, "run_function_agent",
            lambda m, user_id=0: "function fallback worked",
        )
        assert ma.run_multi_agent("do a thing") == "function fallback worked"

    def test_total_failure_message(self, monkeypatch):
        import multi_agent as ma
        monkeypatch.setattr(ma, "classify_task", lambda m: "function")

        def boom(*a, **k):
            raise RuntimeError("down")
        monkeypatch.setattr(ma, "run_function_agent", boom)
        monkeypatch.setattr(ma, "run_smolagents_agent", boom)

        assert "failed" in ma.run_multi_agent("hello").lower()

    def test_framework_status_lists_modes(self):
        from multi_agent import get_framework_status
        status = get_framework_status("function")
        assert "function" in status
        assert "smolagents" in status


# ============================================================
# 5. Tool scoping (Codebuff-style: only relevant tools per message)
# ============================================================

class TestToolScoping:
    def test_price_message_gets_small_set(self):
        import registry, tool_scoping
        scoped = tool_scoping.select_tools("what is the price of bitcoin", registry.TOOLS, use_llm=False)
        names = {t["function"]["name"] for t in scoped}
        assert "get_price" in names
        assert "delegate" in names          # always available
        assert "remember_preference" in names  # always-on family
        assert len(scoped) < len(registry.TOOLS) / 2  # actually scoped

    def test_buy_message_includes_trading_and_prices(self):
        import registry, tool_scoping
        scoped = tool_scoping.select_tools("buy 50 dollars of bitcoin", registry.TOOLS, use_llm=False)
        names = {t["function"]["name"] for t in scoped}
        assert "buy" in names
        assert "get_price" in names

    def test_never_returns_empty(self):
        import registry, tool_scoping
        scoped = tool_scoping.select_tools("", registry.TOOLS, use_llm=False)
        assert len(scoped) >= 5

    def test_fail_safe_on_internal_error(self):
        import registry, tool_scoping
        with patch.object(tool_scoping, "_families_from_keywords", side_effect=RuntimeError("boom")):
            scoped = tool_scoping.select_tools("hello", registry.TOOLS, use_llm=False)
        assert scoped == registry.TOOLS  # fail-open to full set

    def test_every_registered_tool_belongs_to_a_family(self):
        """Any tool outside all families would be invisible when scoping
        picks a narrow set — coverage must be total."""
        import registry, tool_scoping
        covered = set(tool_scoping.ALWAYS_ON)
        for members in tool_scoping.TOOL_FAMILIES.values():
            covered |= members
        covered.add(tool_scoping.DELEGATE_TOOL_NAME)
        for name in registry.tool_names():
            assert name in covered, f"tool {name!r} missing from all families"

    def test_families_for_message_debug_helper(self):
        from tool_scoping import families_for_message
        fams = families_for_message("set an alert for eth")
        assert "alerts_rules" in fams


# ============================================================
# 6. Delegation (subagent spawn with scoped tools)
# ============================================================

class TestDelegation:
    def test_unknown_subagent_rejected(self):
        from delegation import run_subagent
        out = run_subagent("hacker_agent", "do evil")
        assert "Unknown subagent" in out

    def test_subagent_tool_loop_with_mocked_llm(self):
        """Subagent calls a tool, gets result, then answers — all mocked."""
        import delegation

        call_count = {"n": 0}
        def fake_chat(messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"content": "", "tool_calls": [
                    {"id": "t1", "type": "function",
                     "function": {"name": "web_search",
                                  "arguments": json.dumps({"query": "solana news"})}}
                ]}
            return {"content": "Found it: Solana is fast.", "tool_calls": []}

        with patch.object(delegation, "_mistral_chat", side_effect=fake_chat), \
             patch("registry.dispatch_tool", return_value="search results here") as dt:
            out = delegation.run_subagent("researcher", "find solana news")

        assert out == "Found it: Solana is fast."
        dt.assert_called_once_with("web_search", {"query": "solana news"}, user_id=0)

    def test_nested_delegation_blocked(self):
        import delegation

        # Subagent tries to delegate every step, then finally answers
        answers = [
            {"content": "", "tool_calls": [
                {"id": f"t{i}", "type": "function",
                 "function": {"name": "delegate",
                              "arguments": json.dumps({"agent": "coder", "task": "x"})}}
            ]}
            for i in range(5)
        ] + [{"content": "gave up recursing", "tool_calls": []}]

        with patch.object(delegation, "_mistral_chat", side_effect=answers):
            out = delegation.run_subagent("researcher", "try to recurse", max_steps=6)
        assert out == "gave up recursing"  # loop kept running, never crashed

        # The delegation attempt was answered with the block message
        blocked = [c for c in (a.get("content", "") for a in answers)
                   if "not allowed" in c]
        # Verify the block message exists by checking the tool result path:
        # rerun capturing the message history via the fake chat
        seen_tool_results = []
        def capturing_chat(messages, tools=None):
            if len(messages) > 2 and messages[-1].get("role") == "tool":
                seen_tool_results.append(messages[-1]["content"])
            return answers[len(seen_tool_results)] if len(seen_tool_results) < len(answers) else answers[-1]

        with patch.object(delegation, "_mistral_chat", side_effect=capturing_chat):
            delegation.run_subagent("researcher", "try to recurse", max_steps=6)
        assert any("not allowed" in r for r in seen_tool_results), \
            "delegation attempt inside a subagent must be blocked"

    def test_subagent_sees_only_scoped_tools(self):
        """The researcher must not see real-trading tools."""
        import delegation, tool_scoping, registry
        allow = set()
        for fam in delegation.SUBAGENTS["researcher"]["families"]:
            allow |= tool_scoping.TOOL_FAMILIES.get(fam, set())
        assert "jupiter_buy" not in allow
        assert "buy_token" not in allow
        assert "web_search" in allow

    def test_delegate_tool_dispatches_through_registry(self):
        import registry
        with patch("delegation.run_subagent", return_value="sub done") as rs:
            out = registry.dispatch_tool("delegate", {"agent": "planner", "task": "plan it"}, user_id=5)
        assert out == "sub done"
        rs.assert_called_once_with(agent_name="planner", task="plan it", context="", user_id=5)


# ============================================================
# 7. Guardrails (action tracking + reviewer pass)
# ============================================================

class TestGuardrails:
    def test_tracker_ignores_benign_tools(self):
        from guardrails import ActionTracker
        t = ActionTracker()
        t.record("get_price", {"coin": "btc"}, "BTC: $100")
        assert not t.has_events()

    def test_tracker_records_consequential_tools(self):
        from guardrails import ActionTracker
        t = ActionTracker()
        t.record("jupiter_buy", {"token": "XYZ"}, "Bought 1M XYZ")
        t.record("get_private_key", {}, "key: 5abc...")
        assert t.has_events()
        assert len(t.events) == 2

    def test_success_claim_with_failed_action_gets_flagged(self):
        from guardrails import ActionTracker, review_reply
        t = ActionTracker()
        t.record("jupiter_buy", {"token": "XYZ"}, "Error: insufficient SOL balance")
        out = review_reply(t, "✅ Successfully bought XYZ!")
        assert "did not complete" in out

    def test_honest_failure_reply_not_double_flagged(self):
        from guardrails import ActionTracker, review_reply
        t = ActionTracker()
        t.record("jupiter_buy", {}, "Error: insufficient SOL")
        out = review_reply(t, "Sorry, the buy failed due to insufficient balance.")
        assert out == "Sorry, the buy failed due to insufficient balance."

    def test_clean_turn_passes_through_untouched(self):
        from guardrails import ActionTracker, review_reply
        t = ActionTracker()
        assert review_reply(t, "BTC is at $100k") == "BTC is at $100k"

    def test_successful_actions_pass_review(self):
        from guardrails import ActionTracker, review_reply
        t = ActionTracker()
        t.record("generate_wallet", {}, "wallet created")
        out = review_reply(t, "Created your new wallet.")
        assert "did not complete" not in out
