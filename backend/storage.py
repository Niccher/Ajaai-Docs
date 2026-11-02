import os
import io
import time
import logging
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadminpassword")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "ajaia-documents")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes")


class StorageService:
    def __init__(self):
        self.endpoint = MINIO_ENDPOINT
        self.bucket = MINIO_BUCKET
        self.client: Minio = None
        self._initialize_client()

    def _initialize_client(self):
        try:
            self.client = Minio(
                endpoint=self.endpoint,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE,
            )
            logger.info(f"MinIO client initialized targeting {self.endpoint}")
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            self.client = None

    def ensure_bucket_exists(self, max_retries: int = 5, delay: float = 2.0):
        """Ensure the target bucket exists, creating it if necessary."""
        if not self.client:
            self._initialize_client()

        if not self.client:
            logger.warning("MinIO client not available; skipping bucket initialization.")
            return False

        for attempt in range(1, max_retries + 1):
            try:
                found = self.client.bucket_exists(self.bucket)
                if not found:
                    self.client.make_bucket(self.bucket)
                    logger.info(f"Created MinIO bucket '{self.bucket}'.")
                else:
                    logger.info(f"MinIO bucket '{self.bucket}' exists.")
                return True
            except Exception as e:
                logger.warning(f"MinIO bucket check attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    logger.error("Could not connect to MinIO after maximum retries.")
                    return False
                time.sleep(delay)
        return False

    def upload_file(self, object_name: str, data: bytes, content_type: str = "text/plain") -> str:
        """Upload raw bytes to MinIO bucket. Returns the object name."""
        if not self.client:
            raise RuntimeError("MinIO client is not initialized.")

        data_stream = io.BytesIO(data)
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=data_stream,
            length=len(data),
            content_type=content_type,
        )
        logger.info(f"Uploaded object '{object_name}' to bucket '{self.bucket}'.")
        return object_name

    def get_file(self, object_name: str) -> bytes:
        """Download object bytes from MinIO."""
        if not self.client:
            raise RuntimeError("MinIO client is not initialized.")

        response = None
        try:
            response = self.client.get_object(self.bucket, object_name)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    def delete_file(self, object_name: str):
        """Compensating delete to rollback failed writes."""
        if not self.client:
            return
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"Deleted object '{object_name}' from bucket '{self.bucket}'.")
        except Exception as e:
            logger.error(f"Failed to delete object '{object_name}': {e}")


# Singleton instance
storage_service = StorageService()
