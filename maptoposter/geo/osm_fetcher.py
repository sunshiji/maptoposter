import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import requests
import json

from ..cache import CacheManager, CacheType, cache_key
from ..config.settings import RoadType, ROAD_TYPE_PRIORITY

logger = logging.getLogger(__name__)

MAX_BBOX_SIZE = 1.0


class PlaceType(Enum):
    COUNTRY = "country"
    STATE = "state"
    REGION = "region"
    COUNTY = "county"
    DISTRICT = "district"
    CITY = "city"
    TOWN = "town"
    MUNICIPALITY = "municipality"
    VILLAGE = "village"
    SUBURB = "suburb"
    QUARTER = "quarter"
    NEIGHBOURHOOD = "neighbourhood"
    HAMLET = "hamlet"
    LOCALITY = "locality"


PLACE_TYPE_PRIORITY = {
    PlaceType.COUNTRY: 20,
    PlaceType.STATE: 18,
    PlaceType.REGION: 16,
    PlaceType.COUNTY: 14,
    PlaceType.DISTRICT: 13,
    PlaceType.CITY: 12,
    PlaceType.TOWN: 10,
    PlaceType.MUNICIPALITY: 9,
    PlaceType.VILLAGE: 8,
    PlaceType.SUBURB: 6,
    PlaceType.QUARTER: 5,
    PlaceType.NEIGHBOURHOOD: 4,
    PlaceType.HAMLET: 3,
    PlaceType.LOCALITY: 2,
}


@dataclass
class Place:
    id: int
    name: Optional[str]
    name_en: Optional[str]
    name_local: Optional[str]
    place_type: PlaceType
    latitude: float
    longitude: float
    population: Optional[int] = None
    admin_level: Optional[int] = None
    tags: Dict[str, str] = field(default_factory=dict)
    
    @property
    def priority(self) -> int:
        pop_priority = 0
        if self.population:
            if self.population > 1000000:
                pop_priority = 100
            elif self.population > 500000:
                pop_priority = 80
            elif self.population > 100000:
                pop_priority = 60
            elif self.population > 50000:
                pop_priority = 40
            elif self.population > 10000:
                pop_priority = 20
        
        type_priority = PLACE_TYPE_PRIORITY.get(self.place_type, 0)
        
        return type_priority + pop_priority
    
    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.name_local:
            return self.name_local
        if self.name_en:
            return self.name_en
        return ""


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
    places: List[Place] = field(default_factory=list)
    bounding_box: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    @property
    def all_features(self) -> int:
        return len(self.roads) + len(self.water_bodies) + len(self.parks) + len(self.buildings) + len(self.places)


class OSMFetcher:
    def __init__(
        self,
        overpass_url: str = "https://overpass-api.de/api/interpreter",
        overpass_urls: Optional[List[str]] = None,
        user_agent: str = "MapToPoster/0.1.0",
        timeout: int = 120,
        cache_manager: Optional[CacheManager] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ):
        self.overpass_url = overpass_url
        self.overpass_urls = overpass_urls or [overpass_url]
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache_manager = cache_manager
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session: Optional[requests.Session] = None
    
    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": self.user_agent})
        return self._session
    
    def _check_bbox_size(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> Tuple[float, float, float, float]:
        min_lat, max_lat, min_lon, max_lon = bbox
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon
        
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        
        if lat_range > MAX_BBOX_SIZE or lon_range > MAX_BBOX_SIZE:
            logger.warning(
                f"Bounding box too large ({lat_range:.2f}° x {lon_range:.2f}°), "
                f"limiting to {MAX_BBOX_SIZE}° for faster query"
            )
            
            half_size = MAX_BBOX_SIZE / 2
            new_bbox = (
                center_lat - half_size,
                center_lat + half_size,
                center_lon - half_size,
                center_lon + half_size,
            )
            return new_bbox
        
        return bbox
    
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
  
  node["place"]({bbox_str});
  
  relation["boundary"="administrative"]["admin_level"]({bbox_str});
  relation["boundary"="administrative"]["name"]({bbox_str});
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
            "places": [
                {
                    "id": p.id,
                    "name": p.name,
                    "name_en": p.name_en,
                    "name_local": p.name_local,
                    "place_type": p.place_type.value,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "population": p.population,
                    "admin_level": p.admin_level,
                    "tags": p.tags,
                }
                for p in osm_data.places
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
        
        for place_data in data.get("places", []):
            place = Place(
                id=place_data["id"],
                name=place_data.get("name"),
                name_en=place_data.get("name_en"),
                name_local=place_data.get("name_local"),
                place_type=PlaceType(place_data["place_type"]),
                latitude=place_data["latitude"],
                longitude=place_data["longitude"],
                population=place_data.get("population"),
                admin_level=place_data.get("admin_level"),
                tags=place_data.get("tags", {}),
            )
            osm_data.places.append(place)
        
        return osm_data
    
    def fetch(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> OSMData:
        original_bbox = bbox
        bbox = self._check_bbox_size(bbox)
        
        if bbox != original_bbox:
            logger.info(f"Adjusted bbox from {original_bbox} to {bbox}")
        
        logger.info(f"Fetching OSM data for bbox: {bbox}")
        
        cache_key_val = cache_key(bbox=bbox)
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key_val, CacheType.OSM_DATA)
            if cached_data:
                logger.debug("OSM data cache hit")
                return self._dict_to_osm_data(cached_data)
        
        query = self._build_overpass_query(bbox)
        
        last_exception = None
        
        for url_index, overpass_url in enumerate(self.overpass_urls):
            for attempt in range(self.max_retries):
                try:
                    logger.info(
                        f"Querying Overpass API (server {url_index + 1}/{len(self.overpass_urls)}, "
                        f"attempt {attempt + 1}/{self.max_retries}): {overpass_url}"
                    )
                    
                    session = self._get_session()
                    response = session.post(
                        overpass_url,
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
                    
                    logger.info(f"Successfully fetched {osm_data.all_features} features")
                    return osm_data
                    
                except requests.exceptions.RequestException as e:
                    last_exception = e
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_retries} failed for {overpass_url}: {e}"
                    )
                    
                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay * (attempt + 1)
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
            
            if url_index < len(self.overpass_urls) - 1:
                logger.info(f"Trying next Overpass API server...")
        
        logger.error(f"All Overpass API servers failed after {self.max_retries} attempts each")
        raise last_exception or Exception("Failed to fetch OSM data")
    
    def _parse_osm_data(
        self,
        raw_data: Dict[str, Any],
        bbox: Tuple[float, float, float, float],
    ) -> OSMData:
        nodes: Dict[int, Tuple[float, float]] = {}
        ways: Dict[int, Dict[str, Any]] = {}
        relations: Dict[int, Dict[str, Any]] = {}
        place_nodes: List[Dict[str, Any]] = []
        
        for element in raw_data.get("elements", []):
            element_type = element.get("type")
            element_id = element.get("id")
            
            if element_type == "node":
                nodes[element_id] = (element.get("lat"), element.get("lon"))
                tags = element.get("tags", {})
                if "place" in tags:
                    place_nodes.append(element)
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
        
        for place_node in place_nodes:
            tags = place_node.get("tags", {})
            place_type_str = tags.get("place")
            
            if not place_type_str:
                continue
            
            try:
                place_type = PlaceType(place_type_str)
            except ValueError:
                try:
                    place_type = PlaceType(place_type_str.lower())
                except ValueError:
                    place_type = PlaceType.LOCALITY
            
            population = None
            pop_str = tags.get("population")
            if pop_str:
                try:
                    population = int(pop_str.replace(",", ""))
                except ValueError:
                    pass
            
            admin_level = None
            admin_str = tags.get("admin_level")
            if admin_str:
                try:
                    admin_level = int(admin_str)
                except ValueError:
                    pass
            
            name = tags.get("name")
            name_en = tags.get("name:en")
            name_local = tags.get("name:zh") or tags.get("name:ja") or tags.get("name:ko")
            
            place = Place(
                id=place_node.get("id"),
                name=name,
                name_en=name_en,
                name_local=name_local,
                place_type=place_type,
                latitude=place_node.get("lat"),
                longitude=place_node.get("lon"),
                population=population,
                admin_level=admin_level,
                tags=tags,
            )
            osm_data.places.append(place)
        
        for rel_id, relation in relations.items():
            tags = relation.get("tags", {})
            
            if tags.get("boundary") != "administrative":
                continue
            
            name = tags.get("name")
            if not name:
                continue
            
            admin_level = None
            admin_str = tags.get("admin_level")
            if admin_str:
                try:
                    admin_level = int(admin_str)
                except ValueError:
                    pass
            
            place_type = self._admin_level_to_place_type(admin_level, tags)
            
            members = relation.get("members", [])
            center_lat, center_lon = self._calculate_relation_center(members, nodes, ways)
            
            if center_lat is None or center_lon is None:
                continue
            
            population = None
            pop_str = tags.get("population")
            if pop_str:
                try:
                    population = int(pop_str.replace(",", ""))
                except ValueError:
                    pass
            
            name_en = tags.get("name:en")
            name_local = tags.get("name:zh") or tags.get("name:ja") or tags.get("name:ko")
            
            existing_ids = {p.id for p in osm_data.places}
            if rel_id in existing_ids:
                continue
            
            place = Place(
                id=rel_id,
                name=name,
                name_en=name_en,
                name_local=name_local,
                place_type=place_type,
                latitude=center_lat,
                longitude=center_lon,
                population=population,
                admin_level=admin_level,
                tags=tags,
            )
            osm_data.places.append(place)
        
        osm_data.roads.sort(key=lambda r: r.priority)
        osm_data.places.sort(key=lambda p: p.priority, reverse=True)
        
        return osm_data
    
    def _admin_level_to_place_type(self, admin_level: Optional[int], tags: Dict[str, str]) -> PlaceType:
        place_str = tags.get("place")
        if place_str:
            try:
                return PlaceType(place_str)
            except ValueError:
                pass
        
        if admin_level is None:
            return PlaceType.LOCALITY
        
        if admin_level <= 3:
            return PlaceType.STATE
        elif admin_level <= 5:
            return PlaceType.REGION
        elif admin_level <= 7:
            return PlaceType.CITY
        elif admin_level <= 9:
            return PlaceType.COUNTY
        elif admin_level <= 11:
            return PlaceType.DISTRICT
        elif admin_level <= 13:
            return PlaceType.TOWN
        else:
            return PlaceType.LOCALITY
    
    def _calculate_relation_center(
        self,
        members: List[Dict[str, Any]],
        nodes: Dict[int, Tuple[float, float]],
        ways: Dict[int, Dict[str, Any]],
    ) -> Tuple[Optional[float], Optional[float]]:
        all_lats: List[float] = []
        all_lons: List[float] = []
        
        for member in members:
            member_type = member.get("type")
            member_ref = member.get("ref")
            
            if member_type == "node" and member_ref in nodes:
                lat, lon = nodes[member_ref]
                all_lats.append(lat)
                all_lons.append(lon)
            elif member_type == "way" and member_ref in ways:
                way = ways[member_ref]
                node_refs = way.get("nodes", [])
                for node_ref in node_refs:
                    if node_ref in nodes:
                        lat, lon = nodes[node_ref]
                        all_lats.append(lat)
                        all_lons.append(lon)
        
        if not all_lats:
            return None, None
        
        center_lat = sum(all_lats) / len(all_lats)
        center_lon = sum(all_lons) / len(all_lons)
        
        return center_lat, center_lon
    
    def close(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
