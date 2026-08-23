from minio import Minio
from minio.error import S3Error
from typing import BinaryIO, Optional
import io
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """MinIO/S3-compatible storage service for audio files and transcripts."""
    
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT.replace("http://", "").replace("https://", ""),
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_ENDPOINT.startswith("https"),
        )
        self._ensure_buckets()
    
    def _ensure_buckets(self):
        """Create buckets if they don't exist."""
        for bucket in [settings.MINIO_BUCKET_AUDIO, settings.MINIO_BUCKET_TRANSCRIPTS]:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(f"Created bucket: {bucket}")
            except Exception as e:
                logger.warning(f"Could not ensure bucket {bucket} (MinIO may be unavailable): {e}")
    
    async def upload_file(
        self,
        bucket: str,
        object_name: str,
        file: BinaryIO,
        content_type: str,
    ) -> str:
        """
        Upload a file to MinIO and return a DURABLE object reference
        ("{bucket}/{object_name}"), never a presigned URL — presigned URLs
        expire and would break reprocessing.
        Use ``get_presigned_url`` / ``resolve_audio_bytes`` when transient
        access is needed.
        """
        try:
            # Get file size
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning

            self.client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=file,
                length=file_size,
                content_type=content_type,
            )

            return f"{bucket}/{object_name}"

        except S3Error as e:
            logger.error(f"MinIO upload error: {e}")
            raise

    async def resolve_audio_bytes(self, reference: str) -> bytes:
        """
        Load audio bytes from either a durable "bucket/object" reference or a
        legacy http(s) URL (rows created before durable refs existed).
        """
        if reference.startswith("http://") or reference.startswith("https://"):
            import httpx

            async with httpx.AsyncClient(timeout=120) as http_client:
                resp = await http_client.get(reference)
                resp.raise_for_status()
                return resp.content

        parts = reference.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid storage reference: {reference}")
        return await self.download_file(parts[0], parts[1])
    
    async def upload_bytes(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Upload bytes to MinIO."""
        file_obj = io.BytesIO(data)
        return await self.upload_file(bucket, object_name, file_obj, content_type)
    
    async def download_file(self, bucket: str, object_name: str) -> bytes:
        """Download a file from MinIO."""
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"MinIO download error: {e}")
            raise
    
    async def delete_file(self, url: str) -> bool:
        """Delete a file by its URL."""
        try:
            # Parse bucket and object name from URL
            # URL format: http://endpoint/bucket/object_name
            parts = url.split("/")
            if len(parts) >= 4:
                bucket = parts[3]
                object_name = "/".join(parts[4:])
                self.client.remove_object(bucket, object_name)
                return True
        except S3Error as e:
            logger.error(f"MinIO delete error: {e}")
        return False
    
    async def get_presigned_url(self, bucket: str, object_name: str, expires: int = 604800) -> str:
        """Get a presigned URL for an object."""
        try:
            return self.client.presigned_get_object(bucket, object_name, expires=expires)
        except S3Error as e:
            logger.error(f"MinIO presigned URL error: {e}")
            raise
    
    async def list_objects(self, bucket: str, prefix: str = "") -> list:
        """List objects in a bucket."""
        try:
            objects = self.client.list_objects(bucket, prefix=prefix, recursive=True)
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"MinIO list error: {e}")
            return []


class _LazyStorageService:
    """Lazy proxy so importing this module never dials MinIO at import time."""

    def __init__(self):
        self._instance: Optional[StorageService] = None

    def _get(self) -> StorageService:
        if self._instance is None:
            self._instance = StorageService()
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get(), name)


# Global lazy instance — constructed on first use, not on import
storage_service = _LazyStorageService()