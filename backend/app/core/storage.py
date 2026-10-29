"""Storage client supporting MinIO (S3) with a local filesystem fallback."""

import io
import os
import logging
from datetime import timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from minio import Minio
    HAS_MINIO = True
except ImportError:
    HAS_MINIO = False


class StorageManager:
    """Manages document uploads and retrievals. Object names are generated server-side only."""

    def __init__(self):
        self.bucket = settings.MINIO_BUCKET
        self.local_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage_vault"))
        os.makedirs(self.local_dir, exist_ok=True)
        self.client = None

        if HAS_MINIO and settings.USE_MINIO:
            try:
                self.client = Minio(
                    settings.MINIO_ENDPOINT,
                    access_key=settings.MINIO_ACCESS_KEY,
                    secret_key=settings.MINIO_SECRET_KEY,
                    secure=settings.MINIO_SECURE,
                )
                self._ensure_bucket()
            except Exception as e:
                logger.info(f"MinIO offline ({e}); using local storage vault at {self.local_dir}")
                self.client = None

    def _ensure_bucket(self):
        if self.client and not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _local_path(self, object_name: str) -> str:
        path = os.path.abspath(os.path.join(self.local_dir, object_name.replace("/", os.sep)))
        if not path.startswith(self.local_dir + os.sep):
            raise ValueError("Invalid object name")
        return path

    def _require(self):
        if settings.REQUIRE_MINIO and not self.client:
            raise RuntimeError("MinIO is required (REQUIRE_MINIO=true) but not reachable")

    def upload_bytes(self, file_bytes: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        self._require()
        if self.client:
            try:
                self._ensure_bucket()
                self.client.put_object(
                    bucket_name=self.bucket,
                    object_name=object_name,
                    data=io.BytesIO(file_bytes),
                    length=len(file_bytes),
                    content_type=content_type,
                )
                return object_name
            except Exception as e:
                if settings.REQUIRE_MINIO:
                    raise
                logger.warning(f"MinIO upload error: {e}, falling back to disk.")

        local_path = self._local_path(object_name)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        return object_name

    def get_bytes(self, object_name: str) -> bytes:
        """Return the stored bytes; raises FileNotFoundError when the object does not exist."""
        self._require()
        if self.client:
            try:
                response = self.client.get_object(self.bucket, object_name)
                try:
                    return response.read()
                finally:
                    response.close()
                    response.release_conn()
            except Exception as e:
                if settings.REQUIRE_MINIO:
                    raise FileNotFoundError(object_name) from e
                logger.warning(f"MinIO get error: {e}, falling back to disk.")

        local_path = self._local_path(object_name)
        if not os.path.exists(local_path):
            raise FileNotFoundError(object_name)
        with open(local_path, "rb") as f:
            return f.read()

    def delete(self, object_name: str) -> None:
        if self.client:
            try:
                self.client.remove_object(self.bucket, object_name)
            except Exception as e:
                logger.warning(f"MinIO delete error: {e}")
        local_path = self._local_path(object_name)
        if os.path.exists(local_path):
            os.remove(local_path)

    def get_presigned_url(self, object_name: str, expires_seconds: int = 900) -> str | None:
        if self.client:
            try:
                return self.client.presigned_get_object(
                    self.bucket, object_name, expires=timedelta(seconds=expires_seconds)
                )
            except Exception:
                pass
        return None


storage = StorageManager()
