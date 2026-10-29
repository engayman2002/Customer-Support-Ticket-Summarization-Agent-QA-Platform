"""Celery worker application, queue topology, and asynchronous tasks."""

from app.worker.celery_app import (
    AI_EVALUATION_DLQ_NAME,
    AI_EVALUATION_QUEUE_NAME,
    INGESTION_QUEUE_NAME,
    celery_app,
)
from app.worker.tasks import (
    evaluate_ticket_ai_qa_task,
    handle_ai_evaluation_dlq_task,
    process_webhook_ingestion_async,
    process_webhook_ingestion_task,
    reconcile_closed_tickets_async,
    reconcile_closed_tickets_task,
)

__all__ = [
    "celery_app",
    "INGESTION_QUEUE_NAME",
    "AI_EVALUATION_QUEUE_NAME",
    "AI_EVALUATION_DLQ_NAME",
    "process_webhook_ingestion_task",
    "process_webhook_ingestion_async",
    "reconcile_closed_tickets_task",
    "reconcile_closed_tickets_async",
    "evaluate_ticket_ai_qa_task",
    "handle_ai_evaluation_dlq_task",
]

