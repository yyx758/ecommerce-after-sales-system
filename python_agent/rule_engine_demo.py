from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ScopeLevel(IntEnum):
    PLATFORM = 0
    CATEGORY = 100
    MERCHANT = 200
    PRODUCT = 400
    SKU = 500


@dataclass(frozen=True)
class Rule:
    code: str
    name: str
    scope_level: ScopeLevel
    scene_code: str
    priority: int
    merge_mode: str = "MERGE"
    merchant_id: int | None = None
    product_category: str | None = None
    product_id: int | None = None
    sku_id: int | None = None
    condition: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    settlement: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleRequest:
    merchant_id: int
    product_category: str
    product_id: int | None
    sku_id: int | None
    scene_code: str
    order_amount: float
    received_days: int | None = None
    reported_hours: int | None = None
    opened: bool | None = None
    tags_intact: bool | None = None


class PolicyResolverDemo:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    def resolve(self, request: RuleRequest) -> dict[str, Any]:
        matched = [rule for rule in self.rules if self._matches(rule, request)]
        matched.sort(
            key=lambda rule: (
                int(rule.scope_level),
                rule.priority,
            ),
            reverse=True,
        )

        snapshot = {
            "scene_code": request.scene_code,
            "matched_rules": [],
            "condition": {},
            "action": {},
            "evidence": {},
            "audit": {},
            "settlement": {},
        }

        for rule in reversed(matched):
            snapshot["matched_rules"].append(
                {
                    "code": rule.code,
                    "name": rule.name,
                    "scope_level": rule.scope_level.name,
                    "priority": rule.priority,
                    "merge_mode": rule.merge_mode,
                }
            )
            self._apply_rule(snapshot, rule)

        snapshot["eligibility"] = self._evaluate(snapshot, request)
        return snapshot

    @staticmethod
    def _matches(rule: Rule, request: RuleRequest) -> bool:
        if rule.scene_code != request.scene_code:
            return False
        if rule.merchant_id is not None and rule.merchant_id != request.merchant_id:
            return False
        if rule.product_category is not None and rule.product_category != request.product_category:
            return False
        if rule.product_id is not None and rule.product_id != request.product_id:
            return False
        if rule.sku_id is not None and rule.sku_id != request.sku_id:
            return False
        return True

    @staticmethod
    def _apply_rule(snapshot: dict[str, Any], rule: Rule) -> None:
        for section in ("condition", "action", "evidence", "audit", "settlement"):
            incoming = getattr(rule, section)
            if not incoming:
                continue
            if rule.merge_mode == "REPLACE":
                snapshot[section] = dict(incoming)
            else:
                snapshot[section].update(incoming)

    @staticmethod
    def _evaluate(snapshot: dict[str, Any], request: RuleRequest) -> dict[str, Any]:
        condition = snapshot["condition"]
        action = snapshot["action"]

        reasons: list[str] = []
        allowed = True

        receive_within_days = condition.get("receive_within_days")
        if receive_within_days is not None and request.received_days is not None:
            if request.received_days > receive_within_days:
                allowed = False
                reasons.append(f"超出签收后 {receive_within_days} 天时限")

        report_within_hours = condition.get("report_within_hours")
        if report_within_hours is not None and request.reported_hours is not None:
            if request.reported_hours > report_within_hours:
                allowed = False
                reasons.append(f"超出报备 {report_within_hours} 小时时限")

        allow_opened = condition.get("allow_opened")
        if allow_opened is False and request.opened is True:
            allowed = False
            reasons.append("商品已拆封，不满足当前规则")

        need_tags_intact = condition.get("need_tags_intact")
        if need_tags_intact is True and request.tags_intact is False:
            allowed = False
            reasons.append("吊牌不完整，不满足当前规则")

        supported_actions = [key for key, value in action.items() if key.startswith("support_") and value]
        if not supported_actions:
            allowed = False
            reasons.append("当前规则下不支持该售后场景")

        return {
            "allowed": allowed,
            "reasons": reasons or ["命中规则，允许继续处理"],
            "supported_actions": supported_actions,
        }


def sample_rules() -> list[Rule]:
    return [
        Rule(
            code="RULE_PLATFORM_CLOTHING_7DAY",
            name="平台服饰七天无理由",
            scope_level=ScopeLevel.CATEGORY,
            scene_code="NO_REASON",
            product_category="CLOTHING",
            priority=100,
            condition={
                "receive_within_days": 7,
                "allow_opened": True,
                "need_tags_intact": True,
            },
            action={
                "support_return_refund": True,
            },
            evidence={
                "need_problem_desc": True,
            },
            settlement={
                "freight_payer": "BUYER",
            },
        ),
        Rule(
            code="RULE_MERCHANT_CLOTHING_FREE_RETURN",
            name="服饰商家包邮退",
            scope_level=ScopeLevel.MERCHANT,
            scene_code="NO_REASON",
            merchant_id=1002,
            product_category="CLOTHING",
            priority=180,
            action={
                "support_return_refund": True,
            },
            settlement={
                "freight_payer": "SELLER",
            },
        ),
        Rule(
            code="RULE_PRODUCT_UNDERWEAR_BLOCK",
            name="贴身衣物不支持无理由",
            scope_level=ScopeLevel.PRODUCT,
            scene_code="NO_REASON",
            merchant_id=1002,
            product_category="CLOTHING",
            product_id=20021,
            priority=280,
            merge_mode="REPLACE",
            action={},
            condition={
                "receive_within_days": 7,
                "allow_opened": False,
            },
        ),
        Rule(
            code="RULE_PLATFORM_FRESH_DAMAGE",
            name="平台生鲜坏果规则",
            scope_level=ScopeLevel.CATEGORY,
            scene_code="FRESH_SPOILAGE",
            product_category="FRESH",
            priority=120,
            condition={
                "report_within_hours": 24,
                "allow_opened": True,
            },
            action={
                "support_refund_only": True,
                "support_partial_refund": True,
            },
            evidence={
                "need_problem_desc": True,
                "need_damage_photo": True,
                "need_outer_package_photo": True,
                "need_logistics_label_photo": True,
            },
            audit={
                "audit_mode": "MANUAL",
                "dispatch_to": "FRESH_TEAM",
            },
            settlement={
                "freight_payer": "SELLER",
            },
        ),
        Rule(
            code="RULE_PLATFORM_DIGITAL_FUNCTION",
            name="平台数码功能故障",
            scope_level=ScopeLevel.CATEGORY,
            scene_code="FUNCTION_FAULT",
            product_category="DIGITAL",
            priority=150,
            condition={
                "receive_within_days": 15,
                "allow_opened": True,
            },
            action={
                "support_refund_only": True,
                "support_return_refund": True,
                "support_exchange": True,
                "support_repair": True,
            },
            evidence={
                "need_problem_desc": True,
            },
            settlement={
                "freight_payer": "SELLER",
            },
        ),
        Rule(
            code="RULE_MERCHANT_DIGITAL_STRICT",
            name="数码商家要求故障视频和序列号",
            scope_level=ScopeLevel.MERCHANT,
            scene_code="FUNCTION_FAULT",
            merchant_id=1001,
            product_category="DIGITAL",
            priority=220,
            evidence={
                "need_fault_video": True,
                "need_serial_number": True,
            },
            audit={
                "audit_mode": "MANUAL",
                "dispatch_to": "QUALITY_TEAM",
                "risk_level": "HIGH",
            },
        ),
    ]


def sample_requests() -> list[tuple[str, RuleRequest]]:
    return [
        (
            "服饰普通商家，7天内无理由退货",
            RuleRequest(
                merchant_id=1002,
                product_category="CLOTHING",
                product_id=20011,
                sku_id=None,
                scene_code="NO_REASON",
                order_amount=129.0,
                received_days=5,
                opened=True,
                tags_intact=True,
            ),
        ),
        (
            "贴身衣物，命中商品级封禁规则",
            RuleRequest(
                merchant_id=1002,
                product_category="CLOTHING",
                product_id=20021,
                sku_id=None,
                scene_code="NO_REASON",
                order_amount=59.0,
                received_days=3,
                opened=True,
                tags_intact=True,
            ),
        ),
        (
            "生鲜坏果，20小时内报备",
            RuleRequest(
                merchant_id=1003,
                product_category="FRESH",
                product_id=30001,
                sku_id=None,
                scene_code="FRESH_SPOILAGE",
                order_amount=88.0,
                reported_hours=20,
                opened=True,
            ),
        ),
        (
            "数码功能故障，商家要求补故障视频和序列号",
            RuleRequest(
                merchant_id=1001,
                product_category="DIGITAL",
                product_id=40001,
                sku_id=None,
                scene_code="FUNCTION_FAULT",
                order_amount=2999.0,
                received_days=9,
                opened=True,
            ),
        ),
    ]


def main() -> None:
    resolver = PolicyResolverDemo(sample_rules())
    for title, request in sample_requests():
        print("=" * 88)
        print(title)
        print("- request")
        print(json.dumps(request.__dict__, ensure_ascii=False, indent=2))
        print("- resolved policy")
        print(json.dumps(resolver.resolve(request), ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    main()
