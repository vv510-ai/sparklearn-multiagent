"""Optional durable S3-compatible backup for uploads and generated assets."""
from __future__ import annotations

import logging
import mimetypes
import re
from functools import lru_cache
from pathlib import Path

from ..config import GEN_DIR, UPLOAD_SOURCES_DIR, get_settings

log = logging.getLogger("sparklearn.object_storage")
_SAFE_TENANT = re.compile(r"[^A-Za-z0-9_.-]")


def configured() -> bool:
    settings = get_settings()
    return bool(
        settings.object_storage_bucket
        and settings.object_storage_access_key
        and settings.object_storage_secret_key
    )


@lru_cache(maxsize=1)
def _client():
    import boto3

    settings = get_settings()
    kwargs = {
        "service_name": "s3",
        "aws_access_key_id": settings.object_storage_access_key,
        "aws_secret_access_key": settings.object_storage_secret_key,
        "region_name": settings.object_storage_region or "auto",
    }
    if settings.object_storage_endpoint:
        kwargs["endpoint_url"] = settings.object_storage_endpoint
    return boto3.client(**kwargs)


def _tenant(user_id: str) -> str:
    return _SAFE_TENANT.sub("_", str(user_id))[:80]


def _upload(local: Path, key: str) -> bool:
    if not configured() or not local.is_file():
        return False
    try:
        content_type = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        _client().upload_file(
            str(local),
            get_settings().object_storage_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("object backup failed for %s: %s", key, exc)
        return False


def backup_generated_asset(user_id: str, url_path: str) -> bool:
    filename = Path(str(url_path).split("?", 1)[0]).name
    return _upload(
        GEN_DIR / filename,
        f"users/{_tenant(user_id)}/generated/{filename}",
    )


def restore_generated_asset(user_id: str, url_path: str) -> bool:
    filename = Path(str(url_path).split("?", 1)[0]).name
    local = GEN_DIR / filename
    if local.is_file():
        return True
    if not configured():
        return False
    try:
        local.parent.mkdir(parents=True, exist_ok=True)
        _client().download_file(
            get_settings().object_storage_bucket,
            f"users/{_tenant(user_id)}/generated/{filename}",
            str(local),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("object restore failed for generated/%s: %s", filename, exc)
        return False


def backup_source_files(user_id: str, *paths: Path) -> None:
    for path in paths:
        _upload(path, f"users/{_tenant(user_id)}/sources/{path.name}")


def restore_all_sources() -> int:
    """Hydrate source files before vector ingestion after an ephemeral restart."""
    if not configured():
        return 0
    restored = 0
    try:
        UPLOAD_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        paginator = _client().get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=get_settings().object_storage_bucket,
            Prefix="users/",
        ):
            for item in page.get("Contents", []):
                key = str(item.get("Key") or "")
                if "/sources/" not in key:
                    continue
                filename = Path(key).name
                if not filename:
                    continue
                target = UPLOAD_SOURCES_DIR / filename
                if target.is_file():
                    continue
                _client().download_file(
                    get_settings().object_storage_bucket,
                    key,
                    str(target),
                )
                restored += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("source restore skipped: %s", exc)
    return restored
