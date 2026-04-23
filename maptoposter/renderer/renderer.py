import logging
import sys
from dataclasses import dataclass
from typing import Tuple, List, Any, Optional, Set
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config.settings import Theme, ThemeColors, RoadType, ROAD_TYPE_PRIORITY
from ..geo.osm_fetcher import OSMData, Road, WaterBody, Park, Building, Place, PlaceType, PLACE_TYPE_PRIORITY

logger = logging.getLogger(__name__)

_font_cache: dict = {}

CANDIDATE_FONTS = {
    "zh": [
        "msyh.ttc",
        "msyhbd.ttc",
        "simhei.ttf",
        "simsun.ttc",
        "simkai.ttf",
        "simfang.ttf",
        "STHeiti Medium.ttc",
        "PingFang.ttc",
        "NotoSansCJKsc-Regular.otf",
        "NotoSansCJK-Regular.ttc",
        "DroidSansFallback.ttf",
        "wqy-zenhei.ttc",
        "uming.ttc",
    ],
    "ja": [
        "meiryo.ttc",
        "meiryob.ttc",
        "msmincho.ttc",
        "msgothic.ttc",
        "NotoSansCJKjp-Regular.otf",
    ],
    "ko": [
        "malgun.ttf",
        "malgunbd.ttf",
        "gulim.ttc",
        "batang.ttc",
        "NotoSansCJKkr-Regular.otf",
    ],
    "en": [
        "arial.ttf",
        "arialbd.ttf",
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Regular.ttf",
        "LiberationSans-Bold.ttf",
    ],
}

CANDIDATE_FONT_PATHS = [
    Path("C:/Windows/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path("~/.fonts").expanduser(),
    Path("~/.local/share/fonts").expanduser(),
    Path("/usr/share/fonts"),
    Path("/usr/share/fonts/truetype"),
    Path("/usr/share/fonts/opentype"),
]


@dataclass
class LabelConfig:
    show_labels: bool = True
    show_city: bool = True
    show_county: bool = True
    show_district: bool = True
    show_town: bool = True
    show_village: bool = True
    show_suburb: bool = True
    show_state: bool = True
    show_region: bool = True
    max_labels: int = 50
    min_font_size: int = 12
    max_font_size: int = 60
    label_outline: bool = True
    label_outline_width: int = 2
    avoid_overlap: bool = True


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
    labels: LabelConfig = None
    
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
        if self.labels is None:
            self.labels = LabelConfig()


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


def _find_font_file(font_name: str) -> Optional[Path]:
    font_name_lower = font_name.lower()
    
    for font_path in CANDIDATE_FONT_PATHS:
        if not font_path.exists():
            continue
        
        try:
            for file_path in font_path.rglob("*"):
                if file_path.is_file() and file_path.name.lower() == font_name_lower:
                    return file_path
        except (PermissionError, OSError):
            continue
    
    return None


def _find_best_font(language_preference: str = "zh") -> Tuple[Optional[Path], Optional[Path]]:
    if language_preference not in CANDIDATE_FONTS:
        language_preference = "zh"
    
    font_files = CANDIDATE_FONTS[language_preference] + CANDIDATE_FONTS["en"]
    
    regular_font = None
    bold_font = None
    
    for font_name in font_files:
        if regular_font and bold_font:
            break
            
        font_path = _find_font_file(font_name)
        if font_path:
            if "bd" in font_name.lower() or "bold" in font_name.lower():
                if bold_font is None:
                    bold_font = font_path
            else:
                if regular_font is None:
                    regular_font = font_path
    
    if bold_font is None and regular_font is not None:
        bold_font = regular_font
    
    if regular_font is None and bold_font is not None:
        regular_font = bold_font
    
    return regular_font, bold_font


def _get_font_path(bold: bool = False) -> Optional[Path]:
    if "regular" in _font_cache and "bold" in _font_cache:
        return _font_cache["bold"] if bold else _font_cache["regular"]
    
    regular, bold = _find_best_font("zh")
    _font_cache["regular"] = regular
    _font_cache["bold"] = bold
    
    return bold if bold else regular


class MapRenderer:
    SUPERSAMPLING_FACTOR = 2
    
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
        use_antialiasing: bool = True,
    ) -> Image.Image:
        target_width = width or self.render_config.width
        target_height = height or self.render_config.height
        
        if use_antialiasing:
            render_width = int(target_width * self.SUPERSAMPLING_FACTOR)
            render_height = int(target_height * self.SUPERSAMPLING_FACTOR)
        else:
            render_width = target_width
            render_height = target_height
        
        transformer = CoordinateTransformer(
            bbox=osm_data.bounding_box,
            canvas_width=render_width,
            canvas_height=render_height,
            padding=int(self.render_config.padding * self.SUPERSAMPLING_FACTOR) if use_antialiasing else self.render_config.padding,
        )
        
        image = Image.new(
            "RGBA",
            (render_width, render_height),
            hex_to_rgba(self.theme.colors.background),
        )
        draw = ImageDraw.Draw(image)
        
        road_widths_scaled = {}
        if use_antialiasing:
            for road_type, width in self.render_config.road_widths.items():
                road_widths_scaled[road_type] = int(width * self.SUPERSAMPLING_FACTOR)
        
        original_road_widths = self.render_config.road_widths.copy()
        if use_antialiasing:
            self.render_config.road_widths = road_widths_scaled
        
        if self.render_config.show_water:
            self._render_water_bodies(draw, osm_data.water_bodies, transformer)
        
        if self.render_config.show_parks:
            self._render_parks(draw, osm_data.parks, transformer)
        
        if self.render_config.show_buildings:
            self._render_buildings(draw, osm_data.buildings, transformer)
        
        if self.render_config.show_roads:
            self._render_roads(draw, osm_data.roads, transformer)
        
        if self.render_config.labels and self.render_config.labels.show_labels:
            if use_antialiasing:
                original_labels = self.render_config.labels
                scaled_labels = LabelConfig(
                    show_labels=original_labels.show_labels,
                    show_city=original_labels.show_city,
                    show_county=original_labels.show_county,
                    show_district=original_labels.show_district,
                    show_town=original_labels.show_town,
                    show_village=original_labels.show_village,
                    show_suburb=original_labels.show_suburb,
                    show_state=original_labels.show_state,
                    show_region=original_labels.show_region,
                    max_labels=original_labels.max_labels,
                    min_font_size=int(original_labels.min_font_size * self.SUPERSAMPLING_FACTOR),
                    max_font_size=int(original_labels.max_font_size * self.SUPERSAMPLING_FACTOR),
                    label_outline=original_labels.label_outline,
                    label_outline_width=int(original_labels.label_outline_width * self.SUPERSAMPLING_FACTOR),
                    avoid_overlap=original_labels.avoid_overlap,
                )
                self.render_config.labels = scaled_labels
            
            self._render_labels(draw, osm_data.places, transformer, render_width, render_height)
            
            if use_antialiasing:
                self.render_config.labels = original_labels
        
        if use_antialiasing:
            self.render_config.road_widths = original_road_widths
        
        if use_antialiasing and (render_width != target_width or render_height != target_height):
            image = image.resize(
                (target_width, target_height),
                resample=Image.LANCZOS,
            )
        
        return image
    
    def _get_font(self, size: int, bold: bool = False) -> ImageFont.ImageFont:
        cache_key = (size, bold)
        if cache_key in _font_cache:
            return _font_cache[cache_key]
        
        font_path = _get_font_path(bold)
        
        if font_path:
            try:
                font = ImageFont.truetype(str(font_path), size)
                _font_cache[cache_key] = font
                return font
            except Exception as e:
                logger.warning(f"Failed to load font {font_path}: {e}")
        
        fallback_fonts = [
            "arial.ttf",
            "arialbd.ttf",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
        
        for fallback in fallback_fonts:
            try:
                font = ImageFont.truetype(fallback, size)
                _font_cache[cache_key] = font
                logger.info(f"Using fallback font: {fallback}")
                return font
            except:
                continue
        
        logger.warning("Using default font (may not support Chinese characters)")
        default_font = ImageFont.load_default()
        _font_cache[cache_key] = default_font
        return default_font
    
    def _filter_places(self, places: List[Place]) -> List[Place]:
        labels_config = self.render_config.labels
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
    
    def _get_font_size_for_place(self, place: Place, base_size: int = 24) -> int:
        labels_config = self.render_config.labels
        priority = place.priority
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
    
    def _render_labels(
        self,
        draw: ImageDraw.ImageDraw,
        places: List[Place],
        transformer: CoordinateTransformer,
        canvas_width: int,
        canvas_height: int,
    ):
        labels_config = self.render_config.labels
        
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
            font = self._get_font(font_size, bold=True)
            
            text = place.display_name
            
            bbox = draw.textbbox((x, y), text, font=font, anchor="mm")
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
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
                            draw.text(
                                (x + dx, y + dy),
                                text,
                                font=font,
                                fill=hex_to_rgba(outline_color),
                                anchor="mm",
                            )
            
            draw.text(
                (x, y),
                text,
                font=font,
                fill=hex_to_rgba(text_color),
                anchor="mm",
            )
    
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
