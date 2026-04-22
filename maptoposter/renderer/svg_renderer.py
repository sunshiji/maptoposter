import logging
from typing import Optional, List, Tuple
from pathlib import Path
import svgwrite

from ..config.settings import Theme, RoadType
from ..geo.osm_fetcher import OSMData, Road, WaterBody, Park, Building
from .renderer import RenderConfig, CoordinateTransformer

logger = logging.getLogger(__name__)


class SVGRenderer:
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
        output_path: Path,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Path:
        width = width or self.render_config.width
        height = height or self.render_config.height
        
        transformer = CoordinateTransformer(
            bbox=osm_data.bounding_box,
            canvas_width=width,
            canvas_height=height,
            padding=self.render_config.padding,
        )
        
        dwg = svgwrite.Drawing(
            str(output_path),
            size=(f"{width}px", f"{height}px"),
            viewBox=f"0 0 {width} {height}",
        )
        
        dwg.add(dwg.rect(
            insert=(0, 0),
            size=(width, height),
            fill=self.theme.colors.background,
        ))
        
        layers = {
            "water": dwg.add(dwg.g(id="layer-water")),
            "parks": dwg.add(dwg.g(id="layer-parks")),
            "buildings": dwg.add(dwg.g(id="layer-buildings")),
            "minor_roads": dwg.add(dwg.g(id="layer-roads-minor")),
            "major_roads": dwg.add(dwg.g(id="layer-roads-major")),
            "highways": dwg.add(dwg.g(id="layer-roads-highway")),
        }
        
        if self.render_config.show_water:
            self._render_water_bodies(layers["water"], osm_data.water_bodies, transformer)
        
        if self.render_config.show_parks:
            self._render_parks(layers["parks"], osm_data.parks, transformer)
        
        if self.render_config.show_buildings:
            self._render_buildings(layers["buildings"], osm_data.buildings, transformer)
        
        if self.render_config.show_roads:
            self._render_roads(layers, osm_data.roads, transformer)
        
        dwg.save()
        logger.info(f"Saved SVG to: {output_path}")
        
        return output_path
    
    def _render_water_bodies(
        self,
        layer: svgwrite.container.Group,
        water_bodies: List[WaterBody],
        transformer: CoordinateTransformer,
    ):
        for water in water_bodies:
            for ring in water.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                path_data = self._polygon_to_path(coords)
                layer.add(layer.parent.path(
                    d=path_data,
                    fill=self.theme.colors.water,
                ))
    
    def _render_parks(
        self,
        layer: svgwrite.container.Group,
        parks: List[Park],
        transformer: CoordinateTransformer,
    ):
        for park in parks:
            for ring in park.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                path_data = self._polygon_to_path(coords)
                layer.add(layer.parent.path(
                    d=path_data,
                    fill=self.theme.colors.park,
                ))
    
    def _render_buildings(
        self,
        layer: svgwrite.container.Group,
        buildings: List[Building],
        transformer: CoordinateTransformer,
    ):
        for building in buildings:
            for ring in building.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                path_data = self._polygon_to_path(coords)
                layer.add(layer.parent.path(
                    d=path_data,
                    fill=self.theme.colors.building,
                ))
    
    def _render_roads(
        self,
        layers: dict,
        roads: List[Road],
        transformer: CoordinateTransformer,
    ):
        major_road_types = {RoadType.MOTORWAY, RoadType.TRUNK, RoadType.PRIMARY}
        secondary_road_types = {RoadType.SECONDARY, RoadType.TERTIARY}
        
        for road in roads:
            if len(road.coordinates) < 2:
                continue
            
            coords = transformer.transform_coords(road.coordinates)
            width = self.render_config.road_widths.get(road.road_type, 2)
            
            if road.road_type in major_road_types:
                layer = layers["highways"]
                color = self.theme.colors.highway
            elif road.road_type in secondary_road_types:
                layer = layers["major_roads"]
                color = self.theme.colors.major_road
            else:
                layer = layers["minor_roads"]
                color = self.theme.colors.road
            
            path_data = self._line_to_path(coords)
            layer.add(layer.parent.path(
                d=path_data,
                fill="none",
                stroke=color,
                stroke_width=width,
                stroke_linecap="round",
                stroke_linejoin="round",
            ))
    
    def _polygon_to_path(self, coords: List[Tuple[float, float]]) -> str:
        if not coords:
            return ""
        
        path_parts = [f"M {coords[0][0]:.2f},{coords[0][1]:.2f}"]
        for x, y in coords[1:]:
            path_parts.append(f"L {x:.2f},{y:.2f}")
        path_parts.append("Z")
        
        return " ".join(path_parts)
    
    def _line_to_path(self, coords: List[Tuple[float, float]]) -> str:
        if not coords:
            return ""
        
        path_parts = [f"M {coords[0][0]:.2f},{coords[0][1]:.2f}"]
        for x, y in coords[1:]:
            path_parts.append(f"L {x:.2f},{y:.2f}")
        
        return " ".join(path_parts)
