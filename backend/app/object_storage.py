import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
import jwt

from .config import Settings, get_settings


class ObjectStorageError(RuntimeError):
    pass


class ObjectNotFoundError(ObjectStorageError):
    pass


@dataclass(frozen=True)
class UploadGrant:
    method: str
    url: str
    fields: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ObjectMetadata:
    size_bytes: int
    content_type: str
    etag: str | None = None


class ObjectStorage:
    mode = "unknown"

    async def start(self) -> None:
        raise NotImplementedError

    async def is_ready(self) -> bool:
        raise NotImplementedError

    async def create_upload_grant(
        self,
        attachment_id: str,
        storage_key: str,
        content_type: str,
        max_bytes: int,
    ) -> UploadGrant:
        raise NotImplementedError

    async def put(self, storage_key: str, content: bytes, content_type: str) -> ObjectMetadata:
        raise NotImplementedError

    async def head(self, storage_key: str) -> ObjectMetadata:
        raise NotImplementedError

    async def read(self, storage_key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, storage_key: str) -> None:
        raise NotImplementedError

    async def promote(self, source_key: str, destination_key: str) -> ObjectMetadata:
        raise NotImplementedError

    async def create_download_url(
        self,
        attachment_id: str,
        storage_key: str,
        filename: str,
    ) -> str:
        raise NotImplementedError


class LocalObjectStorage(ObjectStorage):
    mode = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.storage_local_path).expanduser().resolve()
        self.started = False

    async def start(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        self.started = True

    async def is_ready(self) -> bool:
        return self.started and self.root.is_dir()

    async def create_upload_grant(
        self,
        attachment_id: str,
        storage_key: str,
        content_type: str,
        max_bytes: int,
    ) -> UploadGrant:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self.settings.storage_presign_seconds
        )
        token = jwt.encode(
            {
                "sub": attachment_id,
                "storage_key": storage_key,
                "content_type": content_type,
                "max_bytes": max_bytes,
                "purpose": "object_upload",
                "exp": expires_at,
            },
            self.settings.auth_secret,
            algorithm="HS256",
        )
        return UploadGrant(
            method="PUT",
            url=f"/api/v1/storage/uploads/{attachment_id}",
            headers={
                "Content-Type": content_type,
                "X-FlowForge-Storage-Token": token,
            },
            expires_at=expires_at,
        )

    def verify_upload_token(self, attachment_id: str, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self.settings.auth_secret, algorithms=["HS256"])
        except jwt.PyJWTError as error:
            raise ObjectStorageError("The upload authorization is invalid or expired.") from error
        if payload.get("purpose") != "object_upload" or payload.get("sub") != attachment_id:
            raise ObjectStorageError("The upload authorization does not match this file.")
        return payload

    async def put(self, storage_key: str, content: bytes, content_type: str) -> ObjectMetadata:
        path = self._path(storage_key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)
        return ObjectMetadata(size_bytes=len(content), content_type=content_type)

    async def head(self, storage_key: str) -> ObjectMetadata:
        path = self._path(storage_key)
        if not path.is_file():
            raise ObjectNotFoundError("Stored object was not found.")
        return ObjectMetadata(
            size_bytes=(await asyncio.to_thread(path.stat)).st_size,
            content_type="application/octet-stream",
        )

    async def read(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        if not path.is_file():
            raise ObjectNotFoundError("Stored object was not found.")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return

    async def promote(self, source_key: str, destination_key: str) -> ObjectMetadata:
        source = self._path(source_key)
        destination = self._path(destination_key)
        if not source.is_file():
            return await self.head(destination_key)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(source.replace, destination)
        return await self.head(destination_key)

    async def create_download_url(
        self,
        attachment_id: str,
        storage_key: str,
        filename: str,
    ) -> str:
        raise ObjectStorageError("Local objects must be streamed by an authenticated route.")

    def _path(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ObjectStorageError("Invalid object key.")
        return candidate


class S3ObjectStorage(ObjectStorage):
    mode = "s3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        client_options = {
            "service_name": "s3",
            "region_name": settings.storage_region,
            "endpoint_url": settings.storage_endpoint_url,
            "aws_access_key_id": settings.storage_access_key_id,
            "aws_secret_access_key": settings.storage_secret_access_key,
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        self.client = boto3.client(**client_options)
        public_options = {**client_options, "endpoint_url": settings.storage_public_endpoint_url}
        self.public_client = boto3.client(**public_options)
        self.started = False

    async def start(self) -> None:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.settings.storage_bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if not self.settings.storage_auto_create_bucket or code not in {"404", "NoSuchBucket", "NotFound"}:
                raise ObjectStorageError("Object-storage bucket is unavailable.") from error
            parameters: dict[str, Any] = {"Bucket": self.settings.storage_bucket}
            if self.settings.storage_region != "us-east-1":
                parameters["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.settings.storage_region
                }
            await asyncio.to_thread(self.client.create_bucket, **parameters)
        except BotoCoreError as error:
            raise ObjectStorageError("Object storage is unavailable.") from error
        self.started = True

    async def is_ready(self) -> bool:
        if not self.started:
            return False
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.settings.storage_bucket)
            return True
        except (BotoCoreError, ClientError):
            return False

    async def create_upload_grant(
        self,
        attachment_id: str,
        storage_key: str,
        content_type: str,
        max_bytes: int,
    ) -> UploadGrant:
        try:
            grant = await asyncio.to_thread(
                self.public_client.generate_presigned_post,
                self.settings.storage_bucket,
                storage_key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=self.settings.storage_presign_seconds,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Could not authorize the object upload.") from error
        return UploadGrant(
            method="POST",
            url=grant["url"],
            fields=grant["fields"],
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=self.settings.storage_presign_seconds),
        )

    async def put(self, storage_key: str, content: bytes, content_type: str) -> ObjectMetadata:
        try:
            response = await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.settings.storage_bucket,
                Key=storage_key,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Could not store the attachment.") from error
        return ObjectMetadata(
            size_bytes=len(content),
            content_type=content_type,
            etag=str(response.get("ETag", "")).strip('"') or None,
        )

    async def head(self, storage_key: str) -> ObjectMetadata:
        try:
            response = await asyncio.to_thread(
                self.client.head_object,
                Bucket=self.settings.storage_bucket,
                Key=storage_key,
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError("Stored object was not found.") from error
            raise ObjectStorageError("Could not inspect the stored attachment.") from error
        except BotoCoreError as error:
            raise ObjectStorageError("Could not inspect the stored attachment.") from error
        return ObjectMetadata(
            size_bytes=int(response["ContentLength"]),
            content_type=str(response.get("ContentType") or "application/octet-stream")[:160],
            etag=str(response.get("ETag", "")).strip('"') or None,
        )

    async def read(self, storage_key: str) -> bytes:
        def read_object() -> bytes:
            response = self.client.get_object(Bucket=self.settings.storage_bucket, Key=storage_key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()

        try:
            return await asyncio.to_thread(read_object)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError("Stored object was not found.") from error
            raise ObjectStorageError("Could not read the stored attachment.") from error
        except BotoCoreError as error:
            raise ObjectStorageError("Could not read the stored attachment.") from error

    async def delete(self, storage_key: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.delete_object,
                Bucket=self.settings.storage_bucket,
                Key=storage_key,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Could not delete the stored attachment.") from error

    async def promote(self, source_key: str, destination_key: str) -> ObjectMetadata:
        try:
            await asyncio.to_thread(
                self.client.copy_object,
                Bucket=self.settings.storage_bucket,
                Key=destination_key,
                CopySource={"Bucket": self.settings.storage_bucket, "Key": source_key},
            )
            metadata = await self.head(destination_key)
            await self.delete(source_key)
            return metadata
        except ObjectNotFoundError:
            return await self.head(destination_key)
        except (BotoCoreError, ClientError) as error:
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return await self.head(destination_key)
            raise ObjectStorageError("Could not promote the scanned attachment.") from error

    async def create_download_url(
        self,
        attachment_id: str,
        storage_key: str,
        filename: str,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self.public_client.generate_presigned_url,
                "get_object",
                Params={
                    "Bucket": self.settings.storage_bucket,
                    "Key": storage_key,
                    "ResponseContentDisposition": (
                        f"attachment; filename*=UTF-8''{quote(filename)}"
                    ),
                },
                ExpiresIn=self.settings.storage_presign_seconds,
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStorageError("Could not authorize the attachment download.") from error


def build_object_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend.strip().lower() == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings)


def clean_storage_key(storage_key: str) -> str:
    if "/quarantine/" in storage_key:
        return storage_key.replace("/quarantine/", "/clean/", 1)
    return f"{storage_key}.clean"


object_storage = build_object_storage(get_settings())
