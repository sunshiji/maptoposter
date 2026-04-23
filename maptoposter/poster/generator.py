import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config.settings import Theme, OutputFormat
from ..geo.osm_fetcher import OSMData
from ..geo.geocoder import LocationResult
from ..renderer.renderer import MapRenderer, RenderConfig, hex_to_rgba, LabelConfig
from ..renderer.svg_renderer import SVGRenderer
from ..renderer.pdf_renderer import PDFRenderer
from ..i18n.i18n import I18nManager
from .decorations import (
    add_gradient_overlay,
    add_border,
    add_decorative_lines,
    draw_text_with_outline,
    get_font,
)

logger = logging.getLogger(__name__)


@dataclass
class PosterConfig:
    width: int = 2480
    height: int = 3508
    dpi: int = 300
    margin: int = 100
    title_font_size: int = 72
    subtitle_font_size: int = 36
    coords_font_size: int = 24
    title_position: str = "bottom"
    show_coords: bool = True
    show_border: bool = True
    gradient_overlay: bool = True
    decorative_corners: bool = True
    map_ratio: float = 0.75
    labels: LabelConfig = field(default_factory=LabelConfig)


class PosterGenerator:
    def __init__(
        self,
        theme: Theme,
        config: Optional[PosterConfig] = None,
        i18n: Optional[I18nManager] = None,
    ):
        self.theme = theme
        self.config = config or PosterConfig()
        self.i18n = i18n or I18nManager()
    
    def generate(
        self,
        osm_data: OSMData,
        location: Optional[LocationResult] = None,
        custom_title: Optional[str] = None,
        custom_subtitle: Optional[str] = None,
    ) -> Image.Image:
        width = self.config.width
        height = self.config.height
        
        poster = Image.new(
            "RGBA",
            (width, height),
            hex_to_rgba(self.theme.colors.background),
        )
        
        map_height = int(height * self.config.map_ratio)
        map_width = width - 2 * self.config.margin
        
        render_config = RenderConfig(
            width=map_width,
            height=map_height,
            dpi=self.config.dpi,
            padding=0,
            labels=self.config.labels,
        )
        
        renderer = MapRenderer(self.theme, render_config)
        map_image = renderer.render(osm_data, width=map_width, height=map_height)
        
        map_x = self.config.margin
        map_y = self.config.margin if self.config.title_position == "bottom" else (height - map_height - self.config.margin)
        
        poster.paste(map_image, (map_x, map_y))
        
        if self.config.gradient_overlay:
            poster = add_gradient_overlay(
                poster,
                start_color=self.theme.colors.background,
                end_color=self.theme.colors.background,
                direction="vertical",
                opacity=0.3,
            )
            
            if self.config.title_position == "bottom":
                gradient_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                draw = ImageDraw.Draw(gradient_layer)
                for y in range(int(height * 0.7), height):
                    t = (y - int(height * 0.7)) / (height - int(height * 0.7))
                    alpha = int(128 * t)
                    color = hex_to_rgba(self.theme.colors.background, alpha / 255)
                    draw.line([(0, y), (width, y)], fill=color)
                poster = Image.alpha_composite(poster, gradient_layer)
        
        if self.config.show_border:
            poster = add_border(
                poster,
                border_color=self.theme.colors.primary,
                border_width=3,
                inner_margin=self.config.margin - 10,
            )
        
        if self.config.decorative_corners:
            poster = add_decorative_lines(
                poster,
                color=self.theme.colors.primary,
                line_width=2,
                corner_length=40,
                margin=self.config.margin - 5,
            )
        
        draw = ImageDraw.Draw(poster)
        
        title = custom_title
        if not title and location:
            title = location.name
        if not title:
            title = "Map"
        
        subtitle = custom_subtitle
        if not subtitle and location:
            subtitle_parts = []
            if location.country:
                subtitle_parts.append(location.country)
            if location.state and location.state != location.country:
                subtitle_parts.append(location.state)
            subtitle = ", ".join(subtitle_parts) if subtitle_parts else ""
        
        if self.config.title_position == "bottom":
            title_y = height - self.config.margin - 120
        else:
            title_y = self.config.margin + 20
        
        title_font = get_font(self.config.title_font_size, bold=True)
        
        bbox = draw.textbbox((0, 0), title, font=title_font, anchor="lt")
        title_width = bbox[2] - bbox[0]
        title_x = (width - title_width) // 2
        
        draw_text_with_outline(
            draw,
            (title_x, title_y),
            title,
            font=title_font,
            fill_color=self.theme.colors.primary,
            outline_color=self.theme.colors.background,
            outline_width=4,
            anchor="lt",
        )
        
        if subtitle:
            subtitle_font = get_font(self.config.subtitle_font_size, bold=False)
            bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font, anchor="lt")
            subtitle_width = bbox[2] - bbox[0]
            subtitle_x = (width - subtitle_width) // 2
            subtitle_y = title_y + self.config.title_font_size + 15
            
            draw_text_with_outline(
                draw,
                (subtitle_x, subtitle_y),
                subtitle,
                font=subtitle_font,
                fill_color=self.theme.colors.secondary,
                outline_color=self.theme.colors.background,
                outline_width=3,
                anchor="lt",
            )
        
        if self.config.show_coords and location:
            coords_font = get_font(self.config.coords_font_size, bold=False)
            
            coords_text = self.i18n.format_coords(location.latitude, location.longitude)
            
            if self.config.title_position == "bottom":
                coords_y = height - self.config.margin - 30
            else:
                coords_y = self.config.margin + map_height + 20
            
            bbox = draw.textbbox((0, 0), coords_text, font=coords_font, anchor="lt")
            coords_width = bbox[2] - bbox[0]
            coords_x = (width - coords_width) // 2
            
            draw_text_with_outline(
                draw,
                (coords_x, coords_y),
                coords_text,
                font=coords_font,
                fill_color=self.theme.colors.secondary,
                outline_color=self.theme.colors.background,
                outline_width=2,
                anchor="lt",
            )
        
        footer_font = get_font(18, bold=False)
        footer_text = self.i18n.get("generated_by")
        
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font, anchor="lt")
        footer_width = bbox[2] - bbox[0]
        footer_x = (width - footer_width) // 2
        footer_y = height - self.config.margin // 2
        
        draw.text(
            (footer_x, footer_y),
            footer_text,
            font=footer_font,
            fill=hex_to_rgba(self.theme.colors.secondary, 0.5),
            anchor="lt",
        )
        
        return poster
    
    def save(
        self,
        poster: Image.Image,
        output_path: Path,
        output_format: OutputFormat = OutputFormat.PNG,
        osm_data: Optional[OSMData] = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if output_format == OutputFormat.PNG:
            poster.save(
                str(output_path),
                "PNG",
                dpi=(self.config.dpi, self.config.dpi),
            )
            logger.info(f"Saved PNG poster to: {output_path}")
        
        elif output_format == OutputFormat.SVG:
            if osm_data is None:
                raise ValueError("OSM data is required for SVG output")
            
            svg_renderer = SVGRenderer(self.theme)
            svg_renderer.render(
                osm_data,
                output_path,
                width=self.config.width,
                height=self.config.height,
            )
            logger.info(f"Saved SVG poster to: {output_path}")
        
        elif output_format == OutputFormat.PDF:
            if osm_data is None:
                raise ValueError("OSM data is required for PDF output")
            
            pdf_renderer = PDFRenderer(
                self.theme,
                page_size="A4",
                orientation="portrait" if self.config.height > self.config.width else "landscape",
            )
            pdf_renderer.render(
                osm_data,
                output_path,
                width=self.config.width,
                height=self.config.height,
            )
            logger.info(f"Saved PDF poster to: {output_path}")
        
        else:
            raise ValueError(f"Unsupported output format: {output_format}")
        
        return output_path
