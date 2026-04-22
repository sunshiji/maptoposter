import logging
from typing import Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

from ..renderer.renderer import hex_to_rgba

logger = logging.getLogger(__name__)


def add_gradient_overlay(
    image: Image.Image,
    start_color: str,
    end_color: str,
    direction: str = "vertical",
    opacity: float = 0.5,
) -> Image.Image:
    width, height = image.size
    
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)
    
    start_rgba = hex_to_rgba(start_color, opacity)
    end_rgba = hex_to_rgba(end_color, opacity)
    
    if direction == "vertical":
        for y in range(height):
            t = y / (height - 1) if height > 1 else 0
            color = (
                int(start_rgba[0] + (end_rgba[0] - start_rgba[0]) * t),
                int(start_rgba[1] + (end_rgba[1] - start_rgba[1]) * t),
                int(start_rgba[2] + (end_rgba[2] - start_rgba[2]) * t),
                int(start_rgba[3] + (end_rgba[3] - start_rgba[3]) * t),
            )
            draw.line([(0, y), (width, y)], fill=color)
    elif direction == "horizontal":
        for x in range(width):
            t = x / (width - 1) if width > 1 else 0
            color = (
                int(start_rgba[0] + (end_rgba[0] - start_rgba[0]) * t),
                int(start_rgba[1] + (end_rgba[1] - start_rgba[1]) * t),
                int(start_rgba[2] + (end_rgba[2] - start_rgba[2]) * t),
                int(start_rgba[3] + (end_rgba[3] - start_rgba[3]) * t),
            )
            draw.line([(x, 0), (x, height)], fill=color)
    elif direction == "diagonal":
        max_dist = (width ** 2 + height ** 2) ** 0.5
        for y in range(height):
            for x in range(width):
                dist = (x ** 2 + y ** 2) ** 0.5
                t = dist / max_dist if max_dist > 0 else 0
                color = (
                    int(start_rgba[0] + (end_rgba[0] - start_rgba[0]) * t),
                    int(start_rgba[1] + (end_rgba[1] - start_rgba[1]) * t),
                    int(start_rgba[2] + (end_rgba[2] - start_rgba[2]) * t),
                    int(start_rgba[3] + (end_rgba[3] - start_rgba[3]) * t),
                )
                draw.point((x, y), fill=color)
    
    return Image.alpha_composite(image.convert("RGBA"), gradient)


def add_border(
    image: Image.Image,
    border_color: str,
    border_width: int = 10,
    inner_margin: int = 20,
) -> Image.Image:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    
    border_color_rgb = hex_to_rgba(border_color)
    
    outer_rect = [
        (inner_margin, inner_margin),
        (width - inner_margin - 1, height - inner_margin - 1),
    ]
    draw.rectangle(outer_rect, outline=border_color_rgb, width=border_width)
    
    inner_rect = [
        (inner_margin + border_width, inner_margin + border_width),
        (width - inner_margin - border_width - 1, height - inner_margin - border_width - 1),
    ]
    draw.rectangle(inner_rect, outline=border_color_rgb, width=1)
    
    return image


def add_decorative_lines(
    image: Image.Image,
    color: str,
    line_width: int = 2,
    corner_length: int = 50,
    margin: int = 30,
) -> Image.Image:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    
    color_rgb = hex_to_rgba(color)
    
    draw.line([(margin, margin), (margin + corner_length, margin)], fill=color_rgb, width=line_width)
    draw.line([(margin, margin), (margin, margin + corner_length)], fill=color_rgb, width=line_width)
    
    draw.line([(width - margin - corner_length, margin), (width - margin, margin)], fill=color_rgb, width=line_width)
    draw.line([(width - margin, margin), (width - margin, margin + corner_length)], fill=color_rgb, width=line_width)
    
    draw.line([(margin, height - margin), (margin + corner_length, height - margin)], fill=color_rgb, width=line_width)
    draw.line([(margin, height - margin - corner_length), (margin, height - margin)], fill=color_rgb, width=line_width)
    
    draw.line([(width - margin - corner_length, height - margin), (width - margin, height - margin)], fill=color_rgb, width=line_width)
    draw.line([(width - margin, height - margin - corner_length), (width - margin, height - margin)], fill=color_rgb, width=line_width)
    
    return image


def draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    position: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill_color: str,
    outline_color: Optional[str] = None,
    outline_width: int = 2,
    align: str = "left",
    anchor: str = "lt",
) -> None:
    fill_rgb = hex_to_rgba(fill_color)
    
    if outline_color and outline_width > 0:
        outline_rgb = hex_to_rgba(outline_color)
        
        x, y = position
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy <= outline_width * outline_width:
                    draw.text(
                        (x + dx, y + dy),
                        text,
                        font=font,
                        fill=outline_rgb,
                        anchor=anchor,
                    )
    
    draw.text(
        position,
        text,
        font=font,
        fill=fill_rgb,
        anchor=anchor,
    )


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        if bold:
            return ImageFont.truetype("arialbd.ttf", size)
        return ImageFont.truetype("arial.ttf", size)
    except:
        try:
            if bold:
                return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except:
            return ImageFont.load_default()
