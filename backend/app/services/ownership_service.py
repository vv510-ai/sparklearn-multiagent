"""Ownership registry for generated files and external provider tasks."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import select

from ..models.db import session
from ..models.entities import ExternalTask, Resource, UserAsset
from .object_storage import backup_generated_asset, restore_generated_asset


def _walk(value: object) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield str(key), item
            else:
                yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def generated_asset_paths(payload: object) -> set[str]:
    return {
        value.split("?", 1)[0]
        for _, value in _walk(payload)
        if value.startswith("/static/gen/")
    }


def external_task_ids(payload: object) -> set[str]:
    return {
        value
        for key, value in _walk(payload)
        if key == "task_id" and value.strip()
    }


def sync_resource_ownership(user_id: str, resource_id: str, payload: object) -> None:
    """Persist all user-owned URLs and async job ids found in a resource."""
    assets = generated_asset_paths(payload)
    tasks = external_task_ids(payload)
    if not assets and not tasks:
        return
    with session() as db:
        for path in assets:
            digest = hashlib.sha256(f"{user_id}\0{path}".encode()).hexdigest()[:40]
            db.merge(UserAsset(
                id=f"asset_{digest}",
                user_id=user_id,
                path=path,
                resource_id=resource_id,
                kind="generated",
            ))
        for task_id in tasks:
            db.merge(ExternalTask(
                id=task_id,
                user_id=user_id,
                resource_id=resource_id,
                kind="video",
            ))
        db.commit()
    for path in assets:
        backup_generated_asset(user_id, path)


def asset_belongs_to_user(user_id: str, path: str) -> bool:
    normalized = str(path or "").split("?", 1)[0]
    if not normalized.startswith("/static/gen/"):
        return False
    legacy: tuple[str, object] | None = None
    with session() as db:
        owned = db.execute(
            select(UserAsset.id).where(
                UserAsset.user_id == user_id,
                UserAsset.path == normalized,
            ),
        ).first()
        if owned:
            return restore_generated_asset(user_id, normalized)

        # One-release compatibility path for assets created before the registry.
        rows = db.execute(
            select(Resource.id, Resource.payload).where(Resource.user_id == user_id),
        ).all()
        for resource_id, payload in rows:
            if normalized in generated_asset_paths(payload):
                legacy = (resource_id, payload)
                break
    if legacy:
        sync_resource_ownership(user_id, legacy[0], legacy[1])
        return restore_generated_asset(user_id, normalized)
    return False


def task_belongs_to_user(user_id: str, task_id: str) -> bool:
    legacy: tuple[str, object] | None = None
    with session() as db:
        owned = db.execute(
            select(ExternalTask.id).where(
                ExternalTask.id == task_id,
                ExternalTask.user_id == user_id,
            ),
        ).first()
        if owned:
            return True

        rows = db.execute(
            select(Resource.id, Resource.payload).where(Resource.user_id == user_id),
        ).all()
        for resource_id, payload in rows:
            if task_id in external_task_ids(payload):
                legacy = (resource_id, payload)
                break
    if legacy:
        sync_resource_ownership(user_id, legacy[0], legacy[1])
        return True
    return False
