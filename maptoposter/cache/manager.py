import json
import hashlib
import time
import os
from pathlib import Path
from enum import Enum
from typing import Any, Optional, Dict
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


class CacheType(Enum):
    GEOCODE = "geocode"
    OSM_DATA = "osm_data"
    RENDERED_MAP = "rendered_map"
    POSTER = "poster"


@dataclass
class CacheEntry:
    key: str
    data: Any
    cache_type: str
    created_at: float
    ttl_seconds: Optional[float] = None
    
    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return time.time() - self.created_at > self.ttl_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "data": self.data,
            "cache_type": self.cache_type,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CacheEntry":
        return cls(
            key=d["key"],
            data=d["data"],
            cache_type=d["cache_type"],
            created_at=d["created_at"],
            ttl_seconds=d.get("ttl_seconds"),
        )


def cache_key(*args, **kwargs) -> str:
    key_parts = list(args)
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}:{v}")
    combined = "|".join(str(p) for p in key_parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


class CacheManager:
    def __init__(
        self,
        cache_dir: Path,
        enabled: bool = True,
        default_ttl_days: int = 30,
        max_size_mb: int = 500,
    ):
        self.cache_dir = cache_dir
        self.enabled = enabled
        self.default_ttl_seconds = default_ttl_days * 24 * 60 * 60
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._ensure_cache_dir()
        
    def _ensure_cache_dir(self) -> None:
        for cache_type in CacheType:
            type_dir = self.cache_dir / cache_type.value
            type_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str, cache_type: CacheType) -> Path:
        return self.cache_dir / cache_type.value / f"{key}.json"
    
    def _get_cache_size(self) -> int:
        total_size = 0
        for root, _, files in os.walk(self.cache_dir):
            for file in files:
                filepath = Path(root) / file
                total_size += filepath.stat().st_size
        return total_size
    
    def _cleanup_old_entries(self) -> None:
        if self._get_cache_size() <= self.max_size_bytes:
            return
        
        entries = []
        for root, _, files in os.walk(self.cache_dir):
            for file in files:
                if file.endswith(".json"):
                    filepath = Path(root) / file
                    stat = filepath.stat()
                    entries.append((filepath, stat.st_mtime, stat.st_size))
        
        entries.sort(key=lambda x: x[1])
        
        current_size = self._get_cache_size()
        for filepath, _, size in entries:
            if current_size <= self.max_size_bytes * 0.8:
                break
            try:
                filepath.unlink()
                current_size -= size
                logger.debug(f"Cleaned up old cache: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to delete cache file {filepath}: {e}")
    
    def get(self, key: str, cache_type: CacheType) -> Optional[Any]:
        if not self.enabled:
            return None
        
        cache_path = self._get_cache_path(key, cache_type)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            entry = CacheEntry.from_dict(data)
            
            if entry.is_expired:
                logger.debug(f"Cache expired for key: {key}")
                cache_path.unlink()
                return None
            
            return entry.data
        except Exception as e:
            logger.warning(f"Failed to read cache for key {key}: {e}")
            return None
    
    def set(
        self,
        key: str,
        data: Any,
        cache_type: CacheType,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        if not self.enabled:
            return
        
        try:
            entry = CacheEntry(
                key=key,
                data=data,
                cache_type=cache_type.value,
                created_at=time.time(),
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
            )
            
            cache_path = self._get_cache_path(key, cache_type)
            
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Cached data for key: {key}, type: {cache_type.value}")
            
            self._cleanup_old_entries()
            
        except Exception as e:
            logger.warning(f"Failed to cache data for key {key}: {e}")
    
    def delete(self, key: str, cache_type: CacheType) -> bool:
        cache_path = self._get_cache_path(key, cache_type)
        if cache_path.exists():
            try:
                cache_path.unlink()
                logger.debug(f"Deleted cache for key: {key}")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete cache for key {key}: {e}")
        return False
    
    def clear(self, cache_type: Optional[CacheType] = None) -> int:
        count = 0
        if cache_type:
            type_dir = self.cache_dir / cache_type.value
            if type_dir.exists():
                for filepath in type_dir.glob("*.json"):
                    try:
                        filepath.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {filepath}: {e}")
        else:
            for root, _, files in os.walk(self.cache_dir):
                for file in files:
                    if file.endswith(".json"):
                        filepath = Path(root) / file
                        try:
                            filepath.unlink()
                            count += 1
                        except Exception as e:
                            logger.warning(f"Failed to delete {filepath}: {e}")
        
        logger.info(f"Cleared {count} cache entries")
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "enabled": self.enabled,
            "cache_dir": str(self.cache_dir),
            "max_size_mb": self.max_size_bytes / (1024 * 1024),
            "current_size_mb": 0,
            "entries_by_type": {},
        }
        
        total_size = 0
        for cache_type in CacheType:
            type_dir = self.cache_dir / cache_type.value
            if type_dir.exists():
                count = 0
                size = 0
                for filepath in type_dir.glob("*.json"):
                    count += 1
                    size += filepath.stat().st_size
                total_size += size
                stats["entries_by_type"][cache_type.value] = {
                    "count": count,
                    "size_mb": size / (1024 * 1024),
                }
        
        stats["current_size_mb"] = total_size / (1024 * 1024)
        return stats
