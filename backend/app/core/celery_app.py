"""Celery application: separate queues for heavy AI work and light source lookups."""

from celery import Celery

from app.core.config import settings

celery = Celery(
    "aicte_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.verification_tasks",
        "app.tasks.notification_tasks",
    ],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "heavy"},          # OCR, forensics, YOLO
        "app.tasks.verification_tasks.*": {"queue": "light"},      # issuing-authority lookups
        "app.tasks.notification_tasks.*": {"queue": "light"},
    },
    task_default_queue="default",
    beat_schedule={
        # Off-peak sweep re-trying sources that were unavailable or pending
        "retry-unavailable-verifications": {
            "task": "app.tasks.verification_tasks.retry_due_verifications",
            "schedule": 900.0,
        },
        "process-application-deadlines": {
            "task": "app.tasks.notification_tasks.process_application_deadlines",
            "schedule": 300.0,
        },
    },
)
