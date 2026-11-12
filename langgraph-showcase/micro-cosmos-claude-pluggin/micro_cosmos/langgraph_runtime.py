"""LangGraph stand-in for the Google ADK types this pipeline imports.

Deterministic mode never calls the model. LLM mode runs one LangGraph
tool loop per phase: Chat-completions through LiteLLM (OpenAI-compatible
gateway, or Vertex when ``llm_engine=vertex``), then the same Python tools
the ADK agents call. ``build_llm()`` still returns an object with ``.model``
and ``._additional_args`` so the existing engine tests keep their contract.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

log = logging.getLogger("micro_cosmos.langgraph_runtime")

_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\??\}")
_MAX_TOOL_TURNS = 16


class GatewayModel:
    """Same surface ``tests/test_settings_build_llm.py`` asserts on LiteLlm."""

    def __init__(self, model: str, **kwargs: Any) -> None:
        self.model = model
        self._additional_args = kwargs


class ToolContext:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state


class FunctionTool:
    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func
        self.name = func.__name__


class LlmAgent:
    def __init__(
        self,
        *,
        name: str,
        model: GatewayModel,
        description: str = "",
        instruction: str = "",
        tools: list[FunctionTool] | None = None,
        output_key: str = "",
    ) -> None:
        self.name = name
        self.model = model
        self.description = description
        self.instruction = instruction
        self.tools = list(tools or [])
        self.output_key = output_key


class Part:
    def __init__(
        self,
        text: str | None = None,
        function_call: Any = None,
        function_response: Any = None,
    ) -> None:
        self.text = text
        self.function_call = function_call
        self.function_response = function_response

    @staticmethod
    def from_text(*, text: str) -> "Part":
        return Part(text=text)


class Content:
    def __init__(self, *, role: str, parts: list[Part]) -> None:
        self.role = role
        self.parts = parts


class _Named:
    def __init__(self, name: str, payload: dict[str, Any], *, response: bool = False) -> None:
        self.name = name
        if response:
            self.response = payload
            self.args = None
        else:
            self.args = payload
            self.response = None


class AgentEvent:
    def __init__(self, author: str, content: Content, *, final: bool = False) -> None:
        self.author = author
        self.content = content
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class Session:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state


class InMemorySessionService:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, str], Session] = {}

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        state: dict[str, Any] | None = None,
    ) -> Session:
        key = (app_name, user_id, session_id)
        if key in self._sessions:
            raise ValueError(f"Session already exists: {session_id}")
        session = Session(dict(state or {}))
        self._sessions[key] = session
        return session

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> Session | None:
        return self._sessions.get((app_name, user_id, session_id))

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        self._sessions.pop((app_name, user_id, session_id), None)


class _TurnState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    turns: int


def _render_instruction(instruction: str, state: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        value = state.get(match.group(1), "")
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=str)[:8000]
        return "" if value is None else str(value)

    return _PLACEHOLDER.sub(repl, instruction or "")


def _json_type(annotation: Any) -> str:
    origin = getattr(annotation, "__origin__", None)
    if annotation in (int,):
        return "integer"
    if annotation in (float,):
        return "number"
    if annotation in (bool,):
        return "boolean"
    if annotation in (list, tuple) or origin in (list, tuple):
        return "array"
    if annotation in (dict,) or origin is dict:
        return "object"
    return "string"


def _tool_schema(func: Callable[..., Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in inspect.signature(func).parameters.items():
        if name in {"tool_context", "self"}:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        properties[name] = {"type": _json_type(param.annotation), "description": name}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    description = (inspect.getdoc(func) or func.__name__)[:800]
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    raw = message.model_dump() if hasattr(message, "model_dump") else dict(message)
    out: dict[str, Any] = {"role": raw.get("role") or "assistant"}
    if raw.get("content"):
        out["content"] = raw["content"]
    calls = raw.get("tool_calls") or []
    if calls:
        dumped = []
        for call in calls:
            if isinstance(call, dict):
                dumped.append(call)
            elif hasattr(call, "model_dump"):
                dumped.append(call.model_dump())
        out["tool_calls"] = dumped
    return out


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    return list(message.get("tool_calls") or [])


def _call_name_args(call: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    fn = call.get("function") or {}
    name = fn.get("name") or call.get("name") or ""
    raw_args = fn.get("arguments") if "arguments" in fn else call.get("args")
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return name, args, str(call.get("id") or name)


async def _invoke_tool(func: Callable[..., Any], args: dict[str, Any], state: dict[str, Any]) -> Any:
    signature = inspect.signature(func)
    kwargs = dict(args)
    if "tool_context" in signature.parameters:
        kwargs["tool_context"] = ToolContext(state)
    accepted = set(signature.parameters)
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in accepted}
    if inspect.iscoroutinefunction(func):
        return await func(**kwargs)
    return await asyncio.to_thread(func, **kwargs)


def _as_response(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"result": value}


class Runner:
    def __init__(self, *, app_name: str, agent: LlmAgent, session_service: InMemorySessionService) -> None:
        self.app_name = app_name
        self.agent = agent
        self.session_service = session_service

    async def run_async(self, *, user_id: str, session_id: str, new_message: Content):
        session = await self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        prompt = ""
        if new_message and new_message.parts:
            prompt = new_message.parts[0].text or ""
        events: list[AgentEvent] = []
        graph = _compile_turn(self.agent, session, events, prompt)
        await graph.ainvoke({"messages": [], "turns": 0})
        for event in events:
            yield event


def _compile_turn(agent: LlmAgent, session: Session, events: list[AgentEvent], prompt: str):
    tools = {tool.name: tool.func for tool in agent.tools}
    schemas = [_tool_schema(func) for func in tools.values()]
    system = _render_instruction(agent.instruction, session.state)
    if agent.description:
        system = f"{agent.description}\n\n{system}"

    async def agent_node(state: _TurnState) -> dict[str, Any]:
        import litellm

        messages = list(state.get("messages") or [])
        if not messages:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
        extra = agent.model._additional_args
        kwargs: dict[str, Any] = {
            "model": agent.model.model,
            "messages": messages,
            "drop_params": True,
        }
        if schemas:
            kwargs["tools"] = schemas
        for key in ("api_base", "api_key", "timeout", "temperature", "extra_body"):
            if extra.get(key) is not None:
                kwargs[key] = extra[key]
        if extra.get("vertex_project"):
            kwargs["vertex_project"] = extra["vertex_project"]
        if extra.get("vertex_location"):
            kwargs["vertex_location"] = extra["vertex_location"]
        response = await litellm.acompletion(**kwargs)
        message = _message_dict(response.choices[0].message)
        calls = _tool_calls(message)
        parts: list[Part] = []
        if message.get("content"):
            parts.append(Part(text=str(message["content"])))
        for call in calls:
            name, args, _cid = _call_name_args(call)
            parts.append(Part(function_call=_Named(name, args)))
        events.append(AgentEvent(agent.name, Content(role="assistant", parts=parts), final=not calls))
        if not calls and agent.output_key and message.get("content"):
            session.state[agent.output_key] = str(message["content"])
        return {"messages": messages + [message], "turns": int(state.get("turns") or 0) + 1}

    async def tools_node(state: _TurnState) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else {}
        appended: list[dict[str, Any]] = []
        parts: list[Part] = []
        for call in _tool_calls(last):
            name, args, call_id = _call_name_args(call)
            func = tools.get(name)
            if func is None:
                raise ValueError(f"Tool '{name}' not found")
            try:
                result = await _invoke_tool(func, args, session.state)
            except Exception as exc:
                log.warning("tool %s failed: %s", name, exc)
                result = {"error": str(exc)}
            payload = _as_response(result)
            parts.append(Part(function_response=_Named(name, payload, response=True)))
            appended.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(payload, default=str)[:20000],
                }
            )
        events.append(AgentEvent(agent.name, Content(role="tool", parts=parts)))
        return {"messages": messages + appended}

    def route(state: _TurnState) -> str:
        messages = state.get("messages") or []
        if not messages:
            return "agent"
        if int(state.get("turns") or 0) >= _MAX_TOOL_TURNS:
            return END
        if _tool_calls(messages[-1]):
            return "tools"
        return END

    graph = StateGraph(_TurnState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()
