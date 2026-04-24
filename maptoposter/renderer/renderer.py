import logging
from dataclasses import dataclass
from typing import Tuple, List, Any, Optional
from pathlib import Path

from PIL import Image, ImageDraw

from ..config.settings import Theme, ThemeColors, RoadType, ROAD_TYPE_PRIORITY
from ..geo.osm_fetcher import OSMData, Road, WaterBody, Park, Building

logger = logging.getLogger(__name__)


@dataclass
class RenderConfig:
    width: int = 2480
    height: int = 3508
    dpi: int = 300
    road_widths: dict = None
    show_buildings: bool = True
    show_water: bool = True
    show_parks: bool = True
    show_roads: bool = True
    padding: int = 0
    
    def __post_init__(self):
        if self.road_widths is None:
            self.road_widths = {
                RoadType.MOTORWAY: 12,
                RoadType.TRUNK: 10,
                RoadType.PRIMARY: 8,
                RoadType.SECONDARY: 6,
                RoadType.TERTIARY: 4,
                RoadType.RESIDENTIAL: 2,
                RoadType.SERVICE: 2,
                RoadType.PEDESTRIAN: 2,
                RoadType.CYCLEWAY: 2,
                RoadType.FOOTWAY: 1,
                RoadType.PATH: 1,
                RoadType.UNCLASSIFIED: 2,
            }


class CoordinateTransformer:
    def __init__(
        self,
        bbox: Tuple[float, float, float, float],
        canvas_width: int,
        canvas_height: int,
        padding: int = 0,
    ):
        self.bbox = bbox
        self.min_lat, self.max_lat, self.min_lon, self.max_lon = bbox
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.padding = padding
        
        self._calculate_scales()
    
    def _calculate_scales(self):
        lat_range = self.max_lat - self.min_lat
        lon_range = self.max_lon - self.min_lon
        
        center_lat = (self.min_lat + self.max_lat) / 2
        lon_scale_factor = abs(lat_range / lon_range) if lon_range != 0 else 1.0
        
        canvas_aspect = (self.canvas_height - 2 * self.padding) / (self.canvas_width - 2 * self.padding)
        data_aspect = lat_range / (lon_range * abs(lon_scale_factor)) if lon_range != 0 else 1
        
        if data_aspect > canvas_aspect:
            self.scale_y = (self.canvas_height - 2 * self.padding) / lat_range
            self.scale_x = self.scale_y / abs(lon_scale_factor)
        else:
            self.scale_x = (self.canvas_width - 2 * self.padding) / (lon_range * abs(lon_scale_factor)) if lon_range != 0 else 1
            self.scale_y = self.scale_x * abs(lon_scale_factor)
        
        map_width = (self.max_lon - self.min_lon) * self.scale_x
        map_height = (self.max_lat - self.min_lat) * self.scale_y
        
        self.offset_x = self.padding + (self.canvas_width - 2 * self.padding - map_width) / 2
        self.offset_y = self.padding + (self.canvas_height - 2 * self.padding - map_height) / 2
    
    def transform(self, lat: float, lon: float) -> Tuple[float, float]:
        x = self.offset_x + (lon - self.min_lon) * self.scale_x
        y = self.offset_y + (self.max_lat - lat) * self.scale_y
        return (x, y)
    
    def transform_coords(self, coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        return [self.transform(lat, lon) for lat, lon in coords]
    
    def transform_polygon(self, coords: List[List[Tuple[float, float]]]) -> List[List[Tuple[float, float]]]:
        return [self.transform_coords(ring) for ring in coords]


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> Tuple[int, int, int, int]:
    rgb = hex_to_rgb(hex_color)
    return (*rgb, int(alpha * 255))


class MapRenderer:
    def __init__(
        self,
        theme: Theme,
        render_config: Optional[RenderConfig] = None,
    ):
        self.theme = theme
        self.render_config = render_config or RenderConfig()
    
    def render(
        self,
        osm_data: OSMData,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Image.Image:
        width = width or self.render_config.width
        height = height or self.render_config.height
        
        transformer = CoordinateTransformer(
            bbox=osm_data.bounding_box,
            canvas_width=width,
            canvas_height=height,
            padding=self.render_config.padding,
        )
        
        image = Image.new(
            "RGBA",
            (width, height),
            hex_to_rgba(self.theme.colors.background),
        )
        draw = ImageDraw.Draw(image)
        
        if self.render_config.show_water:
            self._render_water_bodies(draw, osm_data.water_bodies, transformer)
        
        if self.render_config.show_parks:
            self._render_parks(draw, osm_data.parks, transformer)
        
        if self.render_config.show_buildings:
            self._render_buildings(draw, osm_data.buildings, transformer)
        
        if self.render_config.show_roads:
            self._render_roads(draw, osm_data.roads, transformer)
        
        return image
    
    def _render_water_bodies(
        self,
        draw: ImageDraw.ImageDraw,
        water_bodies: List[WaterBody],
        transformer: CoordinateTransformer,
    ):
        color = hex_to_rgb(self.theme.colors.water)
        for water in water_bodies:
            for ring in water.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                draw.polygon(coords, fill=color)
    
    def _render_parks(
        self,
        draw: ImageDraw.ImageDraw,
        parks: List[Park],
        transformer: CoordinateTransformer,
    ):
        color = hex_to_rgb(self.theme.colors.park)
        for park in parks:
            for ring in park.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                draw.polygon(coords, fill=color)
    
    def _render_buildings(
        self,
        draw: ImageDraw.ImageDraw,
        buildings: List[Building],
        transformer: CoordinateTransformer,
    ):
        color = hex_to_rgb(self.theme.colors.building)
        for building in buildings:
            for ring in building.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                draw.polygon(coords, fill=color)
    
    def _render_roads(
        self,
        draw: ImageDraw.ImageDraw,
        roads: List[Road],
        transformer: CoordinateTransformer,
    ):
        major_road_types = {RoadType.MOTORWAY, RoadType.TRUNK, RoadType.PRIMARY}
        secondary_road_types = {RoadType.SECONDARY, RoadType.TERTIARY}
        
        major_roads = [r for r in roads if r.road_type in major_road_types]
        secondary_roads = [r for r in roads if r.road_type in secondary_road_types]
        minor_roads = [r for r in roads if r.road_type not in major_road_types and r.road_type not in secondary_road_types]
        
        self._draw_roads(draw, minor_roads, transformer, self.theme.colors.road)
        self._draw_roads(draw, secondary_roads, transformer, self.theme.colors.major_road)
        self._draw_roads(draw, major_roads, transformer, self.theme.colors.highway)
    
    def _draw_roads(
        self,
        draw: ImageDraw.ImageDraw,
        roads: List[Road],
        transformer: CoordinateTransformer,
        color: str,
    ):
        rgb_color = hex_to_rgb(color)
        for road in roads:
            if len(road.coordinates) < 2:
                continue
            
            coords = transformer.transform_coords(road.coordinates)
            width = self.render_config.road_widths.get(road.road_type, 2)
            
            if len(coords) == 2:
                draw.line(coords, fill=rgb_color, width=width)
            else:
                for i in range(len(coords) - 1):
                    draw.line(
                        [coords[i], coords[i + 1]],
                        fill=rgb_color,
                        width=width,
                    )
    
    def save_png(
        self,
        image: Image.Image,
        output_path: Path,
        dpi: Optional[int] = None,
    ) -> None:
        dpi = dpi or self.render_config.dpi
        image.save(
            output_path,
            "PNG",
            dpi=(dpi, dpi),
        )
        logger.info(f"Saved PNG to: {output_path}")
