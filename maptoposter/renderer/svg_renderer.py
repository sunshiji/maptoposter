import logging
from typing import Optional, List, Tuple
from pathlib import Path
import svgwrite

from ..config.settings import Theme, RoadType
from ..geo.osm_fetcher import OSMData, Road, WaterBody, Park, Building, Place, PlaceType
from .renderer import RenderConfig, CoordinateTransformer, LabelConfig

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
            "labels": dwg.add(dwg.g(id="layer-labels")),
        }
        
        if self.render_config.show_water:
            self._render_water_bodies(layers["water"], osm_data.water_bodies, transformer)
        
        if self.render_config.show_parks:
            self._render_parks(layers["parks"], osm_data.parks, transformer)
        
        if self.render_config.show_buildings:
            self._render_buildings(layers["buildings"], osm_data.buildings, transformer)
        
        if self.render_config.show_roads:
            self._render_roads(layers, osm_data.roads, transformer)
        
        if self.render_config.labels and self.render_config.labels.show_labels:
            self._render_labels(layers["labels"], osm_data.places, transformer, width, height)
        
        dwg.save()
        logger.info(f"Saved SVG to: {output_path}")
        
        return output_path
    
    def _filter_places(self, places: List[Place]) -> List[Place]:
        labels_config = self.render_config.labels
        if labels_config is None:
            return []
            
        filtered = []
        
        for place in places:
            if not place.display_name:
                continue
            
            place_type = place.place_type
            
            if place_type == PlaceType.CITY and not labels_config.show_city:
                continue
            if place_type == PlaceType.COUNTY and not labels_config.show_county:
                continue
            if place_type == PlaceType.DISTRICT and not labels_config.show_district:
                continue
            if place_type == PlaceType.TOWN and not labels_config.show_town:
                continue
            if place_type == PlaceType.MUNICIPALITY and not labels_config.show_town:
                continue
            if place_type == PlaceType.VILLAGE and not labels_config.show_village:
                continue
            if place_type == PlaceType.SUBURB and not labels_config.show_suburb:
                continue
            if place_type == PlaceType.QUARTER and not labels_config.show_suburb:
                continue
            if place_type == PlaceType.NEIGHBOURHOOD and not labels_config.show_suburb:
                continue
            if place_type == PlaceType.STATE and not labels_config.show_state:
                continue
            if place_type == PlaceType.REGION and not labels_config.show_region:
                continue
            
            filtered.append(place)
        
        filtered.sort(key=lambda p: p.priority, reverse=True)
        
        return filtered[:labels_config.max_labels]
    
    def _get_font_size_for_place(self, place: Place) -> int:
        labels_config = self.render_config.labels
        if labels_config is None:
            labels_config = LabelConfig()
            
        place_type = place.place_type
        
        if place_type == PlaceType.STATE:
            size = 48
        elif place_type == PlaceType.REGION:
            size = 42
        elif place_type == PlaceType.CITY:
            size = 40
        elif place_type == PlaceType.COUNTY:
            size = 32
        elif place_type == PlaceType.DISTRICT:
            size = 28
        elif place_type in [PlaceType.TOWN, PlaceType.MUNICIPALITY]:
            size = 22
        elif place_type == PlaceType.VILLAGE:
            size = 18
        else:
            size = 16
        
        if place.population:
            if place.population > 1000000:
                size += 12
            elif place.population > 500000:
                size += 8
            elif place.population > 100000:
                size += 4
            elif place.population > 50000:
                size += 2
        
        size = max(labels_config.min_font_size, min(labels_config.max_font_size, size))
        
        return size
    
    def _check_overlap(
        self,
        bbox: Tuple[float, float, float, float],
        occupied: List[Tuple[float, float, float, float]],
    ) -> bool:
        x1, y1, x2, y2 = bbox
        
        for (ox1, oy1, ox2, oy2) in occupied:
            if not (x2 < ox1 or x1 > ox2 or y2 < oy1 or y1 > oy2):
                return True
        
        return False
    
    def _find_best_offset(
        self,
        label_bbox: Tuple[float, float, float, float],
        occupied_areas: List[Tuple[float, float, float, float]],
        canvas_width: int,
        canvas_height: int,
    ) -> Tuple[Optional[float], Optional[float]]:
        offsets = [
            (0, 0),
            (0, 30), (0, -30), (30, 0), (-30, 0),
            (30, 30), (30, -30), (-30, 30), (-30, -30),
            (0, 60), (0, -60), (60, 0), (-60, 0),
            (60, 30), (60, -30), (-60, 30), (-60, -30),
            (30, 60), (30, -60), (-30, 60), (-30, -60),
            (0, 90), (0, -90), (90, 0), (-90, 0),
        ]
        
        for offset_x, offset_y in offsets:
            if offset_x == 0 and offset_y == 0:
                continue
                
            test_bbox = (
                label_bbox[0] + offset_x,
                label_bbox[1] + offset_y,
                label_bbox[2] + offset_x,
                label_bbox[3] + offset_y,
            )
            
            if not self._check_overlap(test_bbox, occupied_areas):
                return offset_x, offset_y
        
        return None, None
    
    def _is_bbox_visible(
        self,
        bbox: Tuple[float, float, float, float],
        canvas_width: int,
        canvas_height: int,
    ) -> bool:
        x1, y1, x2, y2 = bbox
        margin = 20
        return (
            x2 > margin
            and x1 < canvas_width - margin
            and y2 > margin
            and y1 < canvas_height - margin
        )
    
    def _render_labels(
        self,
        layer: svgwrite.container.Group,
        places: List[Place],
        transformer: CoordinateTransformer,
        canvas_width: int,
        canvas_height: int,
    ):
        labels_config = self.render_config.labels
        if labels_config is None:
            return
        
        if not places:
            return
        
        filtered_places = self._filter_places(places)
        
        if not filtered_places:
            return
        
        occupied_areas: List[Tuple[float, float, float, float]] = []
        
        text_color = self.theme.colors.primary
        outline_color = self.theme.colors.background
        
        for place in filtered_places:
            x, y = transformer.transform(place.latitude, place.longitude)
            
            if x < 0 or x > canvas_width or y < 0 or y > canvas_height:
                continue
            
            font_size = self._get_font_size_for_place(place)
            
            text = place.display_name
            
            approx_char_width = font_size * 0.6
            text_width = len(text) * approx_char_width
            text_height = font_size
            
            padding = 10
            label_bbox = (
                x - text_width / 2 - padding,
                y - text_height / 2 - padding,
                x + text_width / 2 + padding,
                y + text_height / 2 + padding,
            )
            
            if labels_config.avoid_overlap and self._check_overlap(label_bbox, occupied_areas):
                offset_x, offset_y = self._find_best_offset(
                    label_bbox, occupied_areas, canvas_width, canvas_height
                )
                
                if offset_x is None or offset_y is None:
                    continue
                
                x += offset_x
                y += offset_y
                label_bbox = (
                    label_bbox[0] + offset_x,
                    label_bbox[1] + offset_y,
                    label_bbox[2] + offset_x,
                    label_bbox[3] + offset_y,
                )
            
            if not self._is_bbox_visible(label_bbox, canvas_width, canvas_height):
                continue
            
            occupied_areas.append(label_bbox)
            
            if labels_config.label_outline:
                outline_width = labels_config.label_outline_width
                for dx in range(-outline_width, outline_width + 1):
                    for dy in range(-outline_width, outline_width + 1):
                        if dx == 0 and dy == 0:
                            continue
                        if dx * dx + dy * dy <= outline_width * outline_width:
                            layer.add(layer.parent.text(
                                text,
                                insert=(x + dx, y + dy),
                                fill=outline_color,
                                font_size=font_size,
                                font_weight="bold",
                                text_anchor="middle",
                                dominant_baseline="middle",
                                font_family="Arial, sans-serif",
                            ))
            
            layer.add(layer.parent.text(
                text,
                insert=(x, y),
                fill=text_color,
                font_size=font_size,
                font_weight="bold",
                text_anchor="middle",
                dominant_baseline="middle",
                font_family="Arial, sans-serif",
            ))
    
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
