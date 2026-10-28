from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Any
import uuid


@dataclass(frozen=True)
class NativeDecision:
    actions: tuple[dict[str, Any], ...]
    assistant_message: dict[str, Any]
    provider_tool_call_shape: str
    usage: dict[str, Any] | None = None

    @property
    def action(self) -> dict[str, Any]:
        """The single action of a one-call decision.

        A planning round may return several calls, so the singular accessor
        refuses to guess which one was meant.
        """
        if len(self.actions) != 1:
            raise FunctionCallingProtocolError(
                f"expected exactly one action but got {len(self.actions)}"
            )
        return self.actions[0]


class FunctionCallingProtocolError(ValueError):
    pass


class FunctionCallingAdapter:
    """Translate provider-native tool calls into workflow actions.

    ``allowed_names`` is the hard boundary of the calling agent: a tool that
    is not listed is never rendered into the provider tool list, so the model
    cannot select it because it cannot see it.
    """

    def __init__(
        self,
        *,
        client: Any,
        registry: Any = None,
        temperature: float = 0.2,
        max_tokens: int = 600,
        allowed_names: frozenset[str] | None = None,
        tool_specs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._allowed_names = allowed_names
        self._tool_specs = tool_specs

    def _effective_specs(self) -> list[dict[str, Any]]:
        specs = (
            list(self._tool_specs)
            if self._tool_specs is not None
            else list(self._registry.tool_specs())
        )
        if self._allowed_names is None:
            return specs
        return [spec for spec in specs if spec["name"] in self._allowed_names]

    def decide(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        prior_messages: list[dict[str, Any]],
    ) -> NativeDecision:
        return self.decide_turn(
            system_prompt=system_prompt,
            messages=[
                *prior_messages,
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
            ],
        )

    def decide_turn(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> NativeDecision:
        """Run one planning round against an explicit message history.

        A tool loop needs the assistant/tool turns to stay adjacent, so the
        caller owns the history instead of having it rebuilt per call.
        """
        provider_tools = self._provider_tools()
        response = self._client.chat(
            [{"role": "system", "content": system_prompt}, *messages],
            tools=provider_tools,
            tool_choice="required",
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        assistant_message, provider_shape = self._assistant_message(response)
        raw_calls = self._tool_calls(assistant_message)
        actions: list[dict[str, Any]] = []
        canonical_calls: list[dict[str, Any]] = []
        for raw_call in raw_calls:
            call_id = self._call_id(raw_call, provider_shape)
            self._validate_call_type(raw_call, provider_shape)
            function = raw_call.get("function")
            if not isinstance(function, dict):
                raise FunctionCallingProtocolError("tool call function is required")
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                raise FunctionCallingProtocolError("tool call name is required")
            name = name.strip()
            if name not in self._known_names():
                raise FunctionCallingProtocolError(f"unknown tool call: {name}")
            arguments = self._arguments(function.get("arguments"), provider_shape)
            self._validate_schema_value(
                arguments,
                self._schema_for_name(name, provider_tools),
                path=f"{name}.arguments",
            )
            canonical_calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
            actions.append(self._normalize_action(name, arguments, call_id))
        self._assert_single_terminal(actions)
        assistant_message = self._canonical_assistant_message(
            assistant_message,
            calls=canonical_calls,
        )
        return NativeDecision(
            actions=tuple(actions),
            assistant_message=assistant_message,
            provider_tool_call_shape=provider_shape,
            usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
        )

    def _provider_tools(self) -> list[dict[str, Any]]:
        tools = []
        for spec in self._effective_specs():
            tools.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            })
        tools.append({
            "type": "function",
            "function": {
                "name": "final_reply",
                "description": "Return the final user-facing reply without executing a tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "assistant_reply": {"type": "string"},
                        "need_human": {"type": "boolean"},
                        "clarification_needed": {"type": "boolean"},
                        "issue_type": {"type": "string"},
                        "evidence_needed": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["assistant_reply"],
                    "additionalProperties": False,
                },
            },
        })
        return tools

    def _known_names(self) -> set[str]:
        """Only tools whose schema was shown to the model may be called."""
        return {spec["name"] for spec in self._effective_specs()} | {"final_reply"}

    @staticmethod
    def _assert_single_terminal(actions: list[dict[str, Any]]) -> None:
        """A terminal answer cannot be mixed with further tool calls."""
        terminal = [
            action for action in actions
            if action.get("action") in {"final_reply", "human_handoff"}
        ]
        if terminal and len(actions) > 1:
            raise FunctionCallingProtocolError(
                "a terminal action must be the only action in a planning round"
            )

    @staticmethod
    def _schema_for_name(name: str, provider_tools: list[dict[str, Any]]) -> dict[str, Any]:
        for tool in provider_tools:
            function = tool.get("function")
            if isinstance(function, dict) and function.get("name") == name:
                schema = function.get("parameters")
                if isinstance(schema, dict):
                    return schema
                break
        raise FunctionCallingProtocolError(f"tool call schema is unavailable: {name}")

    @classmethod
    def _validate_schema_value(cls, value: Any, schema: dict[str, Any], *, path: str) -> None:
        expected = schema.get("type")
        if expected == "object":
            if not isinstance(value, dict):
                raise FunctionCallingProtocolError(f"{path} must be an object")
            properties = schema.get("properties")
            required = schema.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list):
                raise FunctionCallingProtocolError(f"{path} has an invalid object schema")
            missing = [name for name in required if name not in value]
            if missing:
                raise FunctionCallingProtocolError(f"{path} is missing required fields: {', '.join(missing)}")
            unknown = set(value) - set(properties)
            if schema.get("additionalProperties") is not False:
                raise FunctionCallingProtocolError(f"{path} schema must reject additional properties")
            if unknown:
                raise FunctionCallingProtocolError(
                    f"{path} contains unknown fields: {', '.join(sorted(unknown))}"
                )
            for name, child in value.items():
                child_schema = properties.get(name)
                if not isinstance(child_schema, dict):
                    raise FunctionCallingProtocolError(f"{path}.{name} has no valid schema")
                cls._validate_schema_value(child, child_schema, path=f"{path}.{name}")
            return
        if expected == "array":
            if not isinstance(value, list):
                raise FunctionCallingProtocolError(f"{path} must be an array")
            items = schema.get("items")
            if not isinstance(items, dict):
                raise FunctionCallingProtocolError(f"{path} has an invalid array schema")
            for index, item in enumerate(value):
                cls._validate_schema_value(item, items, path=f"{path}[{index}]")
            return
        if expected == "string":
            valid = isinstance(value, str)
        elif expected == "boolean":
            valid = isinstance(value, bool)
        elif expected == "number":
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and cls._is_finite_number(value)
            )
        elif expected == "integer":
            valid = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and cls._is_finite_number(value)
            )
        elif expected == "null":
            valid = value is None
        else:
            raise FunctionCallingProtocolError(f"{path} has unsupported schema type: {expected}")
        if not valid:
            raise FunctionCallingProtocolError(f"{path} must be {expected}")

    @staticmethod
    def _is_finite_number(value: int | float) -> bool:
        try:
            return math.isfinite(value)
        except (OverflowError, TypeError):
            return False

    @staticmethod
    def _assistant_message(response: Any) -> tuple[dict[str, Any], str]:
        if not isinstance(response, dict):
            raise FunctionCallingProtocolError("model response must be an object")
        has_openai_shape = "choices" in response
        has_ollama_shape = "message" in response
        if has_openai_shape == has_ollama_shape:
            raise FunctionCallingProtocolError("model response has an ambiguous assistant message shape")
        if has_openai_shape:
            try:
                message = response["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise FunctionCallingProtocolError("model response has no assistant message") from exc
            provider_shape = "openai"
        else:
            message = response["message"]
            provider_shape = "ollama"
        if not isinstance(message, dict):
            raise FunctionCallingProtocolError("model assistant message must be an object")
        if provider_shape == "ollama" and message.get("role") != "assistant":
            raise FunctionCallingProtocolError("Ollama tool response must use the assistant role")
        return message, provider_shape

    @staticmethod
    def _tool_calls(assistant_message: dict[str, Any]) -> list[dict[str, Any]]:
        calls = assistant_message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            raise FunctionCallingProtocolError("model response must contain at least one tool call")
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                raise FunctionCallingProtocolError(f"tool call {index} must be an object")
        return list(calls)

    @staticmethod
    def _arguments(raw: Any, provider_shape: str) -> dict[str, Any]:
        if provider_shape == "ollama":
            if not isinstance(raw, dict):
                raise FunctionCallingProtocolError("Ollama tool call arguments must be an object")
            return dict(raw)
        if not isinstance(raw, str):
            raise FunctionCallingProtocolError("tool call arguments must be a JSON string")
        try:
            arguments = json.loads(
                raw,
                parse_constant=FunctionCallingAdapter._reject_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise FunctionCallingProtocolError("tool call arguments must contain valid JSON") from exc
        if not isinstance(arguments, dict):
            raise FunctionCallingProtocolError("tool call arguments must decode to an object")
        return arguments

    @staticmethod
    def _call_id(tool_call: dict[str, Any], provider_shape: str) -> str:
        call_id = tool_call.get("id")
        if provider_shape == "ollama" and call_id is None:
            return f"call_ollama_{uuid.uuid4().hex}"
        if not isinstance(call_id, str) or not call_id.strip():
            raise FunctionCallingProtocolError("tool call id is required")
        return call_id

    @staticmethod
    def _validate_call_type(tool_call: dict[str, Any], provider_shape: str) -> None:
        call_type = tool_call.get("type")
        if provider_shape == "ollama" and call_type is None:
            return
        if call_type != "function":
            raise FunctionCallingProtocolError("tool call type must be function")

    @staticmethod
    def _canonical_assistant_message(
        source: dict[str, Any],
        *,
        calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        content = source.get("content")
        if content is not None and not isinstance(content, str):
            raise FunctionCallingProtocolError("Ollama assistant content must be text or null")
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": deepcopy(call["function"]["arguments"]),
                    },
                }
                for call in calls
            ],
        }

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant is not allowed: {value}")

    @staticmethod
    def _normalize_action(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
        if name == "final_reply":
            if not isinstance(arguments.get("assistant_reply"), str):
                raise FunctionCallingProtocolError("final_reply requires assistant_reply")
            action: dict[str, Any] = {
                "action": "final_reply",
                "assistant_reply": arguments["assistant_reply"],
                "tool_call_id": call_id,
            }
            if "need_human" in arguments:
                action["need_human"] = arguments["need_human"]
            if "clarification_needed" in arguments:
                action["clarification_needed"] = arguments["clarification_needed"]
            if "issue_type" in arguments:
                action["issue_type"] = arguments["issue_type"]
            if "evidence_needed" in arguments:
                action["evidence_needed"] = arguments["evidence_needed"]
            return action
        if name == "handoff_to_human":
            action = {"action": "human_handoff", "tool_call_id": call_id, "need_human": True}
            for key in ("assistant_reply", "evidence_needed"):
                if key in arguments:
                    action[key] = arguments[key]
            return action
        return {
            "action": "tool_call",
            "tool_name": name,
            "tool_arguments": arguments,
            "tool_call_id": call_id,
        }
