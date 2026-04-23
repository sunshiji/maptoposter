import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
import requests

from ..cache import CacheManager, CacheType, cache_key

logger = logging.getLogger(__name__)


@dataclass
class LocationResult:
    name: str
    display_name: str
    latitude: float
    longitude: float
    bounding_box: Tuple[float, float, float, float]
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    osm_type: Optional[str] = None
    osm_id: Optional[int] = None
    
    @property
    def coords(self) -> Tuple[float, float]:
        return (self.latitude, self.longitude)
    
    @property
    def bbox_str(self) -> str:
        return f"{self.bounding_box[0]},{self.bounding_box[1]},{self.bounding_box[2]},{self.bounding_box[3]}"


class Geocoder:
    def __init__(
        self,
        nominatim_url: str = "https://nominatim.openstreetmap.org/search",
        user_agent: str = "MapToPoster/0.1.0",
        timeout: int = 30,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.nominatim_url = nominatim_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache_manager = cache_manager
        self._session: Optional[requests.Session] = None
    
    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self.user_agent})
        return self._session
    
    def _geocode_from_cache(self, query: str, language: str = "zh") -> Optional[LocationResult]:
        if self.cache_manager is None:
            return None
        
        cache_key_val = cache_key(query=query, language=language)
        cached_data = self.cache_manager.get(cache_key_val, CacheType.GEOCODE)
        
        if cached_data:
            logger.debug(f"Geocode cache hit for: {query}")
            return LocationResult(**cached_data)
        
        return None
    
    def _cache_geocode_result(self, result: LocationResult, query: str, language: str = "zh") -> None:
        if self.cache_manager is None:
            return
        
        cache_key_val = cache_key(query=query, language=language)
        cache_data = {
            "name": result.name,
            "display_name": result.display_name,
            "latitude": result.latitude,
            "longitude": result.longitude,
            "bounding_box": result.bounding_box,
            "country": result.country,
            "state": result.state,
            "city": result.city,
            "osm_type": result.osm_type,
            "osm_id": result.osm_id,
        }
        self.cache_manager.set(cache_key_val, cache_data, CacheType.GEOCODE)
    
    def geocode(
        self,
        query: str,
        language: str = "zh",
        limit: int = 5,
    ) -> List[LocationResult]:
        logger.info(f"Geocoding: {query} (language: {language})")
        
        cached = self._geocode_from_cache(query, language)
        if cached:
            return [cached]
        
        params = {
            "q": query,
            "format": "json",
            "limit": limit,
            "accept-language": language,
            "addressdetails": 1,
            "polygon_geojson": 0,
        }
        
        try:
            session = self._get_session()
            response = session.get(
                self.nominatim_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            if not data:
                logger.warning(f"No geocode results found for: {query}")
                return []
            
            results = []
            for item in data:
                address = item.get("address", {})
                
                bbox = item.get("boundingbox", [])
                if len(bbox) == 4:
                    bounding_box = (
                        float(bbox[0]),
                        float(bbox[1]),
                        float(bbox[2]),
                        float(bbox[3]),
                    )
                else:
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    bounding_box = (lat - 0.1, lat + 0.1, lon - 0.1, lon + 0.1)
                
                result = LocationResult(
                    name=item.get("name", item.get("display_name", query)),
                    display_name=item.get("display_name", query),
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                    bounding_box=bounding_box,
                    country=address.get("country"),
                    state=address.get("state") or address.get("province"),
                    city=address.get("city") or address.get("town") or address.get("village"),
                    osm_type=item.get("osm_type"),
                    osm_id=item.get("osm_id"),
                )
                results.append(result)
            
            if results:
                self._cache_geocode_result(results[0], query, language)
            
            logger.info(f"Found {len(results)} results for: {query}")
            return results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Geocoding error for {query}: {e}")
            raise
    
    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        language: str = "zh",
    ) -> Optional[LocationResult]:
        logger.info(f"Reverse geocoding: ({latitude}, {longitude})")
        
        cache_key_val = cache_key(lat=latitude, lon=longitude, language=language)
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key_val, CacheType.GEOCODE)
            if cached_data:
                logger.debug("Reverse geocode cache hit")
                return LocationResult(**cached_data)
        
        reverse_url = self.nominatim_url.replace("/search", "/reverse")
        params = {
            "lat": latitude,
            "lon": longitude,
            "format": "json",
            "accept-language": language,
            "addressdetails": 1,
        }
        
        try:
            session = self._get_session()
            response = session.get(
                reverse_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            if not data or "lat" not in data:
                logger.warning(f"No reverse geocode results found for: ({latitude}, {longitude})")
                return None
            
            address = data.get("address", {})
            
            name_parts = []
            if address.get("city"):
                name_parts.append(address["city"])
            elif address.get("town"):
                name_parts.append(address["town"])
            elif address.get("village"):
                name_parts.append(address["village"])
            
            if address.get("state"):
                name_parts.append(address["state"])
            if address.get("country"):
                name_parts.append(address["country"])
            
            name = ", ".join(name_parts) if name_parts else data.get("display_name", f"{latitude}, {longitude}")
            
            bbox = data.get("boundingbox", [])
            if len(bbox) == 4:
                bounding_box = (
                    float(bbox[0]),
                    float(bbox[1]),
                    float(bbox[2]),
                    float(bbox[3]),
                )
            else:
                bounding_box = (
                    latitude - 0.05,
                    latitude + 0.05,
                    longitude - 0.05,
                    longitude + 0.05,
                )
            
            result = LocationResult(
                name=name,
                display_name=data.get("display_name", name),
                latitude=float(data["lat"]),
                longitude=float(data["lon"]),
                bounding_box=bounding_box,
                country=address.get("country"),
                state=address.get("state") or address.get("province"),
                city=address.get("city") or address.get("town") or address.get("village"),
                osm_type=data.get("osm_type"),
                osm_id=data.get("osm_id"),
            )
            
            if self.cache_manager:
                cache_data = {
                    "name": result.name,
                    "display_name": result.display_name,
                    "latitude": result.latitude,
                    "longitude": result.longitude,
                    "bounding_box": result.bounding_box,
                    "country": result.country,
                    "state": result.state,
                    "city": result.city,
                    "osm_type": result.osm_type,
                    "osm_id": result.osm_id,
                }
                self.cache_manager.set(cache_key_val, cache_data, CacheType.GEOCODE)
            
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Reverse geocoding error for ({latitude}, {longitude}): {e}")
            raise
    
    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
