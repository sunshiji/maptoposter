import logging
from typing import Optional, List, Tuple
from pathlib import Path

from reportlab.lib.pagesizes import letter, A4, A3
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas as pdf_canvas

from ..config.settings import Theme, RoadType
from ..geo.osm_fetcher import OSMData, Road, WaterBody, Park, Building
from .renderer import RenderConfig, CoordinateTransformer, hex_to_rgb

logger = logging.getLogger(__name__)


class PDFRenderer:
    def __init__(
        self,
        theme: Theme,
        render_config: Optional[RenderConfig] = None,
        page_size: str = "A4",
        orientation: str = "portrait",
    ):
        self.theme = theme
        self.render_config = render_config or RenderConfig()
        self.page_size = page_size
        self.orientation = orientation
    
    def _get_page_dimensions(self) -> Tuple[float, float]:
        page_sizes = {
            "letter": letter,
            "A4": A4,
            "A3": A3,
        }
        
        base_size = page_sizes.get(self.page_size.upper(), A4)
        
        if self.orientation.lower() == "landscape":
            return (base_size[1], base_size[0])
        
        return base_size
    
    def render(
        self,
        osm_data: OSMData,
        output_path: Path,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Path:
        page_width, page_height = self._get_page_dimensions()
        
        if width and height:
            scale = min(page_width / width, page_height / height)
            render_width = width
            render_height = height
        else:
            render_width = int(page_width)
            render_height = int(page_height)
        
        transformer = CoordinateTransformer(
            bbox=osm_data.bounding_box,
            canvas_width=render_width,
            canvas_height=render_height,
            padding=self.render_config.padding,
        )
        
        c = pdf_canvas.Canvas(
            str(output_path),
            pagesize=(page_width, page_height),
        )
        
        self._fill_background(c, page_width, page_height)
        
        scale_x = page_width / render_width if width else 1
        scale_y = page_height / render_height if height else 1
        
        c.saveState()
        c.scale(scale_x, scale_y)
        
        if self.render_config.show_water:
            self._render_water_bodies(c, osm_data.water_bodies, transformer)
        
        if self.render_config.show_parks:
            self._render_parks(c, osm_data.parks, transformer)
        
        if self.render_config.show_buildings:
            self._render_buildings(c, osm_data.buildings, transformer)
        
        if self.render_config.show_roads:
            self._render_roads(c, osm_data.roads, transformer)
        
        c.restoreState()
        
        c.showPage()
        c.save()
        
        logger.info(f"Saved PDF to: {output_path}")
        return output_path
    
    def _fill_background(
        self,
        c: pdf_canvas.Canvas,
        width: float,
        height: float,
    ):
        c.setFillColorRGB(*[x / 255 for x in hex_to_rgb(self.theme.colors.background)])
        c.rect(0, 0, width, height, fill=1, stroke=0)
    
    def _render_water_bodies(
        self,
        c: pdf_canvas.Canvas,
        water_bodies: List[WaterBody],
        transformer: CoordinateTransformer,
    ):
        c.setFillColorRGB(*[x / 255 for x in hex_to_rgb(self.theme.colors.water)])
        c.setStrokeColorRGB(0, 0, 0, 0)
        
        for water in water_bodies:
            for ring in water.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                self._draw_polygon(c, coords)
    
    def _render_parks(
        self,
        c: pdf_canvas.Canvas,
        parks: List[Park],
        transformer: CoordinateTransformer,
    ):
        c.setFillColorRGB(*[x / 255 for x in hex_to_rgb(self.theme.colors.park)])
        c.setStrokeColorRGB(0, 0, 0, 0)
        
        for park in parks:
            for ring in park.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                self._draw_polygon(c, coords)
    
    def _render_buildings(
        self,
        c: pdf_canvas.Canvas,
        buildings: List[Building],
        transformer: CoordinateTransformer,
    ):
        c.setFillColorRGB(*[x / 255 for x in hex_to_rgb(self.theme.colors.building)])
        c.setStrokeColorRGB(0, 0, 0, 0)
        
        for building in buildings:
            for ring in building.coordinates:
                if len(ring) < 3:
                    continue
                coords = transformer.transform_coords(ring)
                self._draw_polygon(c, coords)
    
    def _render_roads(
        self,
        c: pdf_canvas.Canvas,
        roads: List[Road],
        transformer: CoordinateTransformer,
    ):
        major_road_types = {RoadType.MOTORWAY, RoadType.TRUNK, RoadType.PRIMARY}
        secondary_road_types = {RoadType.SECONDARY, RoadType.TERTIARY}
        
        major_roads = [r for r in roads if r.road_type in major_road_types]
        secondary_roads = [r for r in roads if r.road_type in secondary_road_types]
        minor_roads = [r for r in roads if r.road_type not in major_road_types and r.road_type not in secondary_road_types]
        
        self._draw_roads(c, minor_roads, transformer, self.theme.colors.road)
        self._draw_roads(c, secondary_roads, transformer, self.theme.colors.major_road)
        self._draw_roads(c, major_roads, transformer, self.theme.colors.highway)
    
    def _draw_roads(
        self,
        c: pdf_canvas.Canvas,
        roads: List[Road],
        transformer: CoordinateTransformer,
        color: str,
    ):
        c.setStrokeColorRGB(*[x / 255 for x in hex_to_rgb(color)])
        c.setFillColorRGB(0, 0, 0, 0)
        
        for road in roads:
            if len(road.coordinates) < 2:
                continue
            
            coords = transformer.transform_coords(road.coordinates)
            width = self.render_config.road_widths.get(road.road_type, 2)
            
            c.setLineWidth(width)
            c.setLineCap(1)
            c.setLineJoin(1)
            
            self._draw_polyline(c, coords)
    
    def _draw_polygon(
        self,
        c: pdf_canvas.Canvas,
        coords: List[Tuple[float, float]],
    ):
        if len(coords) < 3:
            return
        
        p = c.beginPath()
        p.moveTo(coords[0][0], coords[0][1])
        for x, y in coords[1:]:
            p.lineTo(x, y)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
    
    def _draw_polyline(
        self,
        c: pdf_canvas.Canvas,
        coords: List[Tuple[float, float]],
    ):
        if len(coords) < 2:
            return
        
        p = c.beginPath()
        p.moveTo(coords[0][0], coords[0][1])
        for x, y in coords[1:]:
            p.lineTo(x, y)
        c.drawPath(p, fill=0, stroke=1)
