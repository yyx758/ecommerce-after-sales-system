"""Infrastructure package — shared cross-cutting concerns.

Public API:
  - resilience: CircuitBreaker
  - embedding_service: EmbeddingService for embedding HTTP calls
  - knowledge_repository: KnowledgeRepository protocol and psycopg-backed
    PsycopgKnowledgeRepository
  - observability: request_tracing, agent_metrics, tracing (trace id,
    step timing, Prometheus metrics, trace history), trace_store (durable
    trace persistence)
  - review_checkpoint: LangGraph checkpointer lifecycle for formal review
"""
from __future__ import annotations

from .embedding_service import EmbeddingService, embedding_error_info
from .knowledge_repository import (
    ActiveDocumentRow,
    KnowledgeRepository,
    PsycopgKnowledgeRepository,
)
from .resilience import CircuitBreaker, CircuitOpenError
from .request_tracing import (
    TraceRecorder,
    TraceStep,
    bind_trace_id,
    current_trace_id,
    new_trace_id,
    normalize_trace_id,
    trace_id_from_seed,
    install_trace_logging_filter,
    TraceIdLoggingFilter,
)
from .agent_metrics import AGENT_RUNTIME_METRICS, AgentRuntimeMetrics
from .tracing import TRACE_HISTORY, record_trace_event
from .trace_store import TRACE_STORE, TraceStore, build_trace_store_from_env

__all__ = [
    "ActiveDocumentRow",
    "CircuitBreaker",
    "CircuitOpenError",
    "EmbeddingService",
    "embedding_error_info",
    "KnowledgeRepository",
    "PsycopgKnowledgeRepository",
    "TraceRecorder",
    "TraceStep",
    "bind_trace_id",
    "current_trace_id",
    "new_trace_id",
    "normalize_trace_id",
    "trace_id_from_seed",
    "install_trace_logging_filter",
    "TraceIdLoggingFilter",
    "AGENT_RUNTIME_METRICS",
    "AgentRuntimeMetrics",
    "TRACE_HISTORY",
    "TRACE_STORE",
    "TraceStore",
    "build_trace_store_from_env",
    "record_trace_event",
]
