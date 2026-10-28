"""会话 Agent 的规划器：让模型决定下一步查什么。

规划器只做一件事——把模型的选择翻译成动作。它不执行工具，也不判断可信度。
工具清单由角色白名单决定，模型看不见的工具就选不到。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....application.function_calling import (
    FunctionCallingAdapter,
    NativeDecision,
)
from ....tools import ROLE_TOOL_NAMES, AgentToolRegistry, ToolRole


@dataclass
class ConsultationPlanner:
    """Turn one planning round into a set of actions."""

    llm: Any
    role: str = ToolRole.CONSULTATION
    temperature: float = 0.1
    max_tokens: int = 900

    def __post_init__(self) -> None:
        allowed = ROLE_TOOL_NAMES.get(self.role)
        if allowed is None:
            raise KeyError(f"unknown tool role: {self.role}")
        self._allowed_names = allowed
        specs = []
        for spec in AgentToolRegistry.all_tool_specs():
            schema = spec["input_schema"]
            owned_arguments = spec["name"] in {"review_images", "get_merchant_policy"}
            properties = {} if owned_arguments else dict(schema["properties"])
            properties["reason"] = {"type": "string"}
            specs.append({
                **spec,
                "input_schema": {
                    **schema,
                    "properties": properties,
                    "required": [
                        *([] if owned_arguments else schema["required"]),
                        "reason",
                    ],
                },
            })
        self._adapter = FunctionCallingAdapter(
            client=self.llm,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            allowed_names=self._allowed_names,
            tool_specs=specs,
        )

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        """The tools this planner may expose to the model."""
        return self._allowed_names

    @property
    def model_tools(self) -> list[dict[str, Any]]:
        return self._adapter._provider_tools()

    def plan(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        trace_recorder: Any | None = None,
    ) -> NativeDecision:
        """Run one planning round."""
        recorder = trace_recorder
        if recorder is None:
            return self._adapter.decide_turn(
                system_prompt=system_prompt,
                messages=messages,
            )
        with recorder.step("consultation_plan", allowed_tools=sorted(self._allowed_names)):
            return self._adapter.decide_turn(
                system_prompt=system_prompt,
                messages=messages,
            )
