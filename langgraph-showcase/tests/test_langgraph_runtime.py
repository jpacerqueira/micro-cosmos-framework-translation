"""LLM-mode tool loop without a live model. Deterministic mode is covered elsewhere."""

from micro_cosmos.langgraph_runtime import (
    Content,
    FunctionTool,
    GatewayModel,
    InMemorySessionService,
    LlmAgent,
    Part,
    Runner,
)


def test_gateway_model_keeps_litellm_attribute_shape():
    model = GatewayModel(
        "openai/gemma4:latest",
        api_base="http://llm-gateway:4000/v1",
        api_key="sk-micro-cosmos-local",
        extra_body=None,
    )
    assert model.model == "openai/gemma4:latest"
    assert model._additional_args["api_base"] == "http://llm-gateway:4000/v1"
    assert model._additional_args["extra_body"] is None


async def test_runner_calls_tool_then_stores_output_key(monkeypatch):
    calls = {"n": 0}

    class _Msg:
        def model_dump(self):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "submit_note",
                                "arguments": '{"text": "ok"}',
                            },
                        }
                    ],
                }
            return {"role": "assistant", "content": '{"saved": true}', "tool_calls": None}

    class _Choice:
        def __init__(self):
            self.message = _Msg()

    class _Resp:
        def __init__(self):
            self.choices = [_Choice()]

    async def fake_completion(**kwargs):
        assert kwargs["model"] == "openai/gemma4:latest"
        assert kwargs["api_base"] == "http://llm-gateway:4000/v1"
        return _Resp()

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_completion)

    seen = {}

    def submit_note(text: str, tool_context=None):
        seen["text"] = text
        seen["source"] = tool_context.state.get("source_path")
        return {"accepted": True}

    agent = LlmAgent(
        name="observer_agent",
        model=GatewayModel(
            "openai/gemma4:latest",
            api_base="http://llm-gateway:4000/v1",
            api_key="sk",
        ),
        instruction="Source is {source_path?}.",
        tools=[FunctionTool(submit_note)],
        output_key="ir_graph",
    )
    service = InMemorySessionService()
    await service.create_session(
        app_name="source",
        user_id="source-user",
        session_id="source-session",
        state={"source_path": "/tmp/estate"},
    )
    runner = Runner(app_name="source", agent=agent, session_service=service)
    events = [
        ev
        async for ev in runner.run_async(
            user_id="source-user",
            session_id="source-session",
            new_message=Content(role="user", parts=[Part.from_text(text="begin")]),
        )
    ]
    kinds = []
    for ev in events:
        for part in ev.content.parts:
            if part.function_call:
                kinds.append(part.function_call.name)
            if part.text:
                kinds.append("text")
    assert "submit_note" in kinds
    assert seen == {"text": "ok", "source": "/tmp/estate"}
    session = await service.get_session(
        app_name="source", user_id="source-user", session_id="source-session"
    )
    assert session.state["ir_graph"] == '{"saved": true}'
    assert events[-1].is_final_response()
