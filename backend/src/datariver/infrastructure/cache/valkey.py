"""Deprecated import compatibility for the former Valkey adapter names."""

from datariver.infrastructure.cache.redis import (
    CacheValueTooLarge,
    DeliveredEvent,
    RedisCache,
    RedisEventDelivery,
)

ValkeyCache = RedisCache
ValkeyEventDelivery = RedisEventDelivery

__all__ = [
    "CacheValueTooLarge",
    "DeliveredEvent",
    "RedisCache",
    "RedisEventDelivery",
    "ValkeyCache",
    "ValkeyEventDelivery",
]
