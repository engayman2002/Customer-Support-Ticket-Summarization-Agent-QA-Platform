from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings

INGESTION_QUEUE_NAME = "ingestion_queue"
AI_EVALUATION_QUEUE_NAME = "ai_evaluation_queue"
AI_EVALUATION_DLQ_NAME = "ai_evaluation_dlq"

default_exchange = Exchange("qa_platform", type="direct")

celery_app = Celery(
    "qa_platform_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=INGESTION_QUEUE_NAME,
    task_default_exchange="qa_platform",
    task_default_routing_key="ingestion.webhook",
    task_queues=(
        Queue(
            INGESTION_QUEUE_NAME,
            exchange=default_exchange,
            routing_key="ingestion.webhook",
        ),
        Queue(
            AI_EVALUATION_QUEUE_NAME,
            exchange=default_exchange,
            routing_key="ai.evaluate",
        ),
        Queue(
            AI_EVALUATION_DLQ_NAME,
            exchange=default_exchange,
            routing_key="ai.dlq",
        ),
    ),
    task_routes={
        "app.worker.tasks.process_webhook_ingestion_task": {
            "queue": INGESTION_QUEUE_NAME,
            "routing_key": "ingestion.webhook",
        },
        "app.worker.tasks.reconcile_closed_tickets_task": {
            "queue": INGESTION_QUEUE_NAME,
            "routing_key": "ingestion.webhook",
        },
        "app.worker.tasks.evaluate_ticket_ai_qa_task": {
            "queue": AI_EVALUATION_QUEUE_NAME,
            "routing_key": "ai.evaluate",
        },
        "app.worker.tasks.handle_ai_evaluation_dlq_task": {
            "queue": AI_EVALUATION_DLQ_NAME,
            "routing_key": "ai.dlq",
        },
    },
    beat_schedule={
        "reconcile-closed-tickets-every-15-minutes": {
            "task": "app.worker.tasks.reconcile_closed_tickets_task",
            "schedule": 900.0,  # 15 minutes
        },
    },
)

