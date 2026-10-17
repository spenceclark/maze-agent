"""Canonical serialization and hashing (spec §16)."""

import hashlib
import json

from pydantic import BaseModel


def canonical_json(value: BaseModel | dict[str, object] | list[object]) -> str:
    """Sorted-key, whitespace-free JSON. Byte-identical for equal values."""
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(value: BaseModel | dict[str, object] | list[object]) -> str:
    return sha256_hex(canonical_json(value))
