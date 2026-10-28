"""Deterministic, allowlisted model observations and public tool traces."""

from __future__ import annotations

import json
from typing import Any

from ....tools import ToolResult
from ...facts import trusted_policy_hits
from ...facts.extractors import evidence_fingerprint


ORDER_FIELDS = ("order_id", "order_no", "status", "product_name", "category", "amount",
                "merchant_code", "create_time", "existing_ticket_id", "existing_ticket_status")
TICKET_FIELDS = ("ticket_id", "ticket_no", "order_id", "status", "after_sales_type",
                 "merchant_code", "category", "reason", "description", "refund_amount", "policy_version",
                 "context_version", "evidence_revision", "ai_review_status", "ai_review_result")
MERCHANT_POLICY_FIELDS = ("merchant_code", "catalog_version", "source", "config_scope")


class ContextProjector:
    version = "1"

    @staticmethod
    def _fields(row: Any, names: tuple[str, ...]) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        return {key: row[key] for key in names if key in row and not isinstance(row[key], (dict, list))}

    def project(self, result: ToolResult) -> dict[str, Any]:
        if not result.ok:
            return {"ok": False, "error_category": result.error_category,
                    "error_code": result.error_code, "retryable": result.retryable}
        data = result.data
        name = result.name
        if name in {"search_user_orders", "get_order_detail"}:
            rows = data if isinstance(data, list) else [data]
            return {"ok": True, "orders": [self._fields(row, ORDER_FIELDS)
                                           for row in rows if isinstance(row, dict)][:10]}
        if name in {"get_existing_after_sales", "get_after_sales_ticket"}:
            ticket = self._fields(data, TICKET_FIELDS)
            if isinstance(data, dict) and data.get("evidence_urls"):
                ticket["evidence_refs"] = list(dict.fromkeys(
                    evidence_fingerprint(url) for url in data["evidence_urls"] if str(url).strip()
                ))
            return {"ok": True, "ticket": ticket or None}
        if name == "retrieve_knowledge":
            knowledge = data if isinstance(data, dict) else {}
            hits = trusted_policy_hits(knowledge)
            excerpts = []
            for hit in hits[:5]:
                citation = (hit.get("citations") or [{}])[0]
                excerpts.append({
                    "source_code": citation.get("source_code"),
                    "chunk_id": citation.get("chunk_id") or citation.get("document_id"),
                    "policy_version": hit.get("policy_version") or citation.get("policy_version"),
                    "quote": str(hit.get("snippet") or "")[:500],
                    "source_status": "published_verified",
                    "applicability_status": "unverified",
                })
            return {"ok": True, "mode": knowledge.get("mode"),
                    "filter_level": knowledge.get("filter_level"),
                    "trusted_policy_available": bool(hits), "hits": excerpts}
        if name == "review_images":
            review = data if isinstance(data, dict) else {}
            return {"ok": True, "evidence_consistent": review.get("evidence_consistent"),
                    "confidence": review.get("confidence"),
                    "issue_types": list(review.get("observed_issue_types") or [])[:5],
                    "missing_visual_evidence": list(review.get("missing_visual_evidence") or [])[:5],
                    "verification_limitations": list(review.get("verification_limitations") or [])[:5],
                    "observation_status": "model_observed" if review.get("success") else "unverifiable"}
        if name == "get_merchant_policy":
            policy = data if isinstance(data, dict) else {}
            service = policy.get("service_policy") if isinstance(policy.get("service_policy"), dict) else {}
            evidence = service.get("evidence_policy") if isinstance(service.get("evidence_policy"), dict) else {}
            return {"ok": True, "policy": {
                **self._fields(policy, MERCHANT_POLICY_FIELDS),
                **self._fields(service, ("policy_code", "policy_version", "display_name")),
                "default_scene_evidence": {
                    str(scene): [str(item) for item in items]
                    for scene, items in (evidence.get("default_scene_evidence") or {}).items()
                    if isinstance(items, list)
                } if isinstance(evidence.get("default_scene_evidence"), dict) else {},
            }}
        return {"ok": True}

    def public_trace(self, result: ToolResult) -> dict[str, Any]:
        projected = self.project(result)
        raw = json.dumps(result.data, ensure_ascii=False, default=str) if result.data is not None else ""
        compact = json.dumps(projected, ensure_ascii=False, default=str)
        references: list[str] = []
        for row in projected.get("orders", []):
            references.append(str(row.get("order_id") or row.get("order_no")))
        ticket = projected.get("ticket")
        if isinstance(ticket, dict):
            references.append(str(ticket.get("ticket_id") or ticket.get("ticket_no")))
        for hit in projected.get("hits", []):
            references.append(f"{hit.get('source_code')}@{hit.get('chunk_id')}")
        if isinstance(result.data, dict):
            allowed = {
                "get_order_detail": ORDER_FIELDS,
                "get_after_sales_ticket": TICKET_FIELDS,
                "get_existing_after_sales": TICKET_FIELDS,
                "get_merchant_policy": MERCHANT_POLICY_FIELDS + ("service_policy",),
            }.get(result.name, ())
            omitted = sorted(set(result.data) - set(allowed))[:20] if allowed else []
        else:
            omitted = []
        return {"tool": result.name, "ok": result.ok,
                "error_code": result.error_code, "error_category": result.error_category,
                "retryable": result.retryable, "source_refs": [ref for ref in references if ref],
                "projection_version": self.version, "raw_size": len(raw),
                "projected_size": len(compact), "omitted_fields": omitted}
