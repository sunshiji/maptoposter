import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import requests
import json

from ..cache import CacheManager, CacheType, cache_key
from ..config.settings import RoadType, ROAD_TYPE_PRIORITY

logger = logging.getLogger(__name__)


@dataclass
class Road:
    id: int
    name: Optional[str]
    road_type: RoadType
    coordinates: List[Tuple[float, float]]
    tags: Dict[str, str] = field(default_factory=dict)
    
    @property
    def priority(self) -> int:
        return ROAD_TYPE_PRIORITY.get(self.road_type, 0)


@dataclass
class WaterBody:
    id: int
    name: Optional[str]
    water_type: str
    coordinates: List[List[Tuple[float, float]]]
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Park:
    id: int
    name: Optional[str]
    park_type: str
    coordinates: List[List[Tuple[float, float]]]
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Building:
    id: int
    name: Optional[str]
    building_type: str
    coordinates: List[List[Tuple[float, float]]]
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class OSMData:
    roads: List[Road] = field(default_factory=list)
    water_bodies: List[WaterBody] = field(default_factory=list)
    parks: List[Park] = field(default_factory=list)
    buildings: List[Building] = field(default_factory=list)
    bounding_box: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    @property
    def all_features(self) -> int:
        return len(self.roads) + len(self.water_bodies) + len(self.parks) + len(self.buildings)


class OSMFetcher:
    def __init__(
        self,
        overpass_url: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "MapToPoster/0.1.0",
        timeout: int = 60,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.overpass_url = overpass_url
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache_manager = cache_manager
        self._session: Optional[requests.Session] = None
    
    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self.user_agent})
        return self._session
    
    def _build_overpass_query(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> str:
        bbox_str = f"{bbox[0]},{bbox[2]},{bbox[1]},{bbox[3]}"
        
        query = f"""
[out:json][timeout:{self.timeout}];

(
  way["highway"][highway!="construction"][highway!="proposed"]
    ({bbox_str});
  
  way["natural"="water"]({bbox_str});
  way["waterway"="riverbank"]({bbox_str});
  way["landuse"="reservoir"]({bbox_str});
  relation["natural"="water"]({bbox_str});
  
  way["leisure"="park"]({bbox_str});
  way["leisure"="garden"]({bbox_str});
  way["leisure"="playground"]({bbox_str});
  way["landuse"="grass"]({bbox_str});
  way["landuse"="meadow"]({bbox_str});
  way["landuse"="forest"]({bbox_str});
  way["natural"="wood"]({bbox_str});
  
  way["building"][building!="no"][building!="construction"]
    ({bbox_str});
);

(._;>;);
out body;
"""
        return query
    
    def _osm_data_to_dict(self, osm_data: OSMData) -> Dict[str, Any]:
        return {
            "bounding_box": list(osm_data.bounding_box),
            "roads": [
                {
                    "id": r.id,
                    "name": r.name,
                    "road_type": r.road_type.value,
                    "coordinates": r.coordinates,
                    "tags": r.tags,
                }
                for r in osm_data.roads
            ],
            "water_bodies": [
                {
                    "id": w.id,
                    "name": w.name,
                    "water_type": w.water_type,
                    "coordinates": w.coordinates,
                    "tags": w.tags,
                }
                for w in osm_data.water_bodies
            ],
            "parks": [
                {
                    "id": p.id,
                    "name": p.name,
                    "park_type": p.park_type,
                    "coordinates": p.coordinates,
                    "tags": p.tags,
                }
                for p in osm_data.parks
            ],
            "buildings": [
                {
                    "id": b.id,
                    "name": b.name,
                    "building_type": b.building_type,
                    "coordinates": b.coordinates,
                    "tags": b.tags,
                }
                for b in osm_data.buildings
            ],
        }
    
    def _dict_to_osm_data(self, data: Dict[str, Any]) -> OSMData:
        osm_data = OSMData()
        osm_data.bounding_box = tuple(data["bounding_box"])
        
        for road_data in data.get("roads", []):
            road = Road(
                id=road_data["id"],
                name=road_data["name"],
                road_type=RoadType(road_data["road_type"]),
                coordinates=road_data["coordinates"],
                tags=road_data.get("tags", {}),
            )
            osm_data.roads.append(road)
        
        for water_data in data.get("water_bodies", []):
            water = WaterBody(
                id=water_data["id"],
                name=water_data["name"],
                water_type=water_data["water_type"],
                coordinates=water_data["coordinates"],
                tags=water_data.get("tags", {}),
            )
            osm_data.water_bodies.append(water)
        
        for park_data in data.get("parks", []):
            park = Park(
                id=park_data["id"],
                name=park_data["name"],
                park_type=park_data["park_type"],
                coordinates=park_data["coordinates"],
                tags=park_data.get("tags", {}),
            )
            osm_data.parks.append(park)
        
        for building_data in data.get("buildings", []):
            building = Building(
                id=building_data["id"],
                name=building_data["name"],
                building_type=building_data["building_type"],
                coordinates=building_data["coordinates"],
                tags=building_data.get("tags", {}),
            )
            osm_data.buildings.append(building)
        
        return osm_data
    
    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> OSMData:
        logger.info(f"Fetching OSM data for bbox: {bbox}")
        
        cache_key_val = cache_key(bbox=bbox)
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key_val, CacheType.OSM_DATA)
            if cached_data:
                logger.debug("OSM data cache hit")
                return self._dict_to_osm_data(cached_data)
        
        query = self._build_overpass_query(bbox)
        
        try:
            session = self._get_session()
            response = session.post(
                self.overpass_url,
                data={"data": query},
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            raw_data = response.json()
            osm_data = self._parse_osm_data(raw_data, bbox)
            
            if self.cache_manager and osm_data.all_features > 0:
                self.cache_manager.set(
                    cache_key_val,
                    self._osm_data_to_dict(osm_data),
                    CacheType.OSM_DATA,
                )
            
            logger.info(f"Fetched {osm_data.all_features} features")
            return osm_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OSM fetch error: {e}")
            raise
    
    def _parse_osm_data(
        self,
        raw_data: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
    ) -> OSMData:
        nodes: Dict[int, Tuple[float, float]] = {}
        ways: Dict[int, Dict[str, Any]] = {}
        relations: Dict[int, Dict[str, Any]] = {}
        
        for element in raw_data.get("elements", []):
            element_type = element.get("type")
            element_id = element.get("id")
            
            if element_type == "node":
                nodes[element_id] = (element.get("lat"), element.get("lon"))
            elif element_type == "way":
                ways[element_id] = element
            elif element_type == "relation":
                relations[element_id] = element
        
        osm_data = OSMData()
        osm_data.bounding_box = bbox
        
        for way_id, way in ways.items():
            tags = way.get("tags", {})
            node_refs = way.get("nodes", [])
            
            if not node_refs:
                continue
            
            coordinates = []
            for node_id in node_refs:
                if node_id in nodes:
                    coordinates.append(nodes[node_id])
            
            if not coordinates:
                continue
            
            name = tags.get("name")
            
            if "highway" in tags:
                highway = tags["highway"]
                try:
                    road_type = RoadType(highway)
                except ValueError:
                    road_type = RoadType.UNCLASSIFIED
                
                road = Road(
                    id=way_id,
                    name=name,
                    road_type=road_type,
                    coordinates=coordinates,
                    tags=tags,
                )
                osm_data.roads.append(road)
            
            elif (
                tags.get("natural") == "water"
                or tags.get("waterway") == "riverbank"
                or tags.get("landuse") == "reservoir"
            ):
                water_type = (
                    tags.get("water")
                    or tags.get("natural")
                    or tags.get("landuse")
                    or "water"
                )
                water = WaterBody(
                    id=way_id,
                    name=name,
                    water_type=water_type,
                    coordinates=[coordinates],
                    tags=tags,
                )
                osm_data.water_bodies.append(water)
            
            elif (
                tags.get("leisure") in ["park", "garden", "playground"]
                or tags.get("landuse") in ["grass", "meadow", "forest"]
                or tags.get("natural") == "wood"
            ):
                park_type = (
                    tags.get("leisure")
                    or tags.get("landuse")
                    or tags.get("natural")
                    or "park"
                )
                park = Park(
                    id=way_id,
                    name=name,
                    park_type=park_type,
                    coordinates=[coordinates],
                    tags=tags,
                )
                osm_data.parks.append(park)
            
            elif "building" in tags and tags["building"] not in ["no", "construction"]:
                building_type = tags["building"]
                building = Building(
                    id=way_id,
                    name=name,
                    building_type=building_type,
                    coordinates=[coordinates],
                    tags=tags,
                )
                osm_data.buildings.append(building)
        
        osm_data.roads.sort(key=lambda r: r.priority)
        
        return osm_data
    
    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
