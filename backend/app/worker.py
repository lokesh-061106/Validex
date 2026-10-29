"""Celery worker entrypoint: celery -A app.worker.celery worker -Q heavy,light,default"""

from app.core.celery_app import celery

__all__ = ["celery"]
