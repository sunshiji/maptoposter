import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class OutputFormat(Enum):
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"


class Language(Enum):
    EN = "en"
    ZH = "zh"
    JA = "ja"
    KO = "ko"


class ThemeName(Enum):
    DARK = "dark"
    BLUEPRINT = "blueprint"
    NEON = "neon"
    MINIMAL = "minimal"
    RETRO = "retro"


class RoadType(Enum):
    MOTORWAY = "motorway"
    TRUNK = "trunk"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    RESIDENTIAL = "residential"
    SERVICE = "service"
    PEDESTRIAN = "pedestrian"
    CYCLEWAY = "cycleway"
    FOOTWAY = "footway"
    PATH = "path"
    UNCLASSIFIED = "unclassified"


ROAD_TYPE_PRIORITY = {
    RoadType.MOTORWAY: 10,
    RoadType.TRUNK: 9,
    RoadType.PRIMARY: 8,
    RoadType.SECONDARY: 7,
    RoadType.TERTIARY: 6,
    RoadType.RESIDENTIAL: 5,
    RoadType.SERVICE: 4,
    RoadType.PEDESTRIAN: 3,
    RoadType.CYCLEWAY: 3,
    RoadType.FOOTWAY: 2,
    RoadType.PATH: 1,
    RoadType.UNCLASSIFIED: 0,
}


@dataclass
class ThemeColors:
    background: str = "#000000"
    primary: str = "#ffffff"
    secondary: str = "#888888"
    accent: str = "#ff4444"
    water: str = "#1a1a2e"
    park: str = "#16213e"
    building: str = "#0f3460"
    road: str = "#e94560"
    major_road: str = "#ff6b6b"
    highway: str = "#ff8787"


@dataclass
class Theme:
    name: str
    colors: ThemeColors
    description: str = ""


DEFAULT_THEMES: Dict[str, Theme] = {
    ThemeName.DARK.value: Theme(
        name=ThemeName.DARK.value,
        colors=ThemeColors(
            background="#000000",
            primary="#ffffff",
            secondary="#666666",
            accent="#ff4444",
            water="#0a0a1e",
            park="#0d1117",
            building="#161b22",
            road="#e6edf3",
            major_road="#f0f6fc",
            highway="#ffffff",
        ),
        description="深色简约风格，适合打印",
    ),
    ThemeName.BLUEPRINT.value: Theme(
        name=ThemeName.BLUEPRINT.value,
        colors=ThemeColors(
            background="#003366",
            primary="#cce5ff",
            secondary="#6699cc",
            accent="#ffff00",
            water="#004080",
            park="#005599",
            building="#002244",
            road="#b3d9ff",
            major_road="#cce5ff",
            highway="#e6f2ff",
        ),
        description="工程蓝图风格",
    ),
    ThemeName.NEON.value: Theme(
        name=ThemeName.NEON.value,
        colors=ThemeColors(
            background="#0a0e27",
            primary="#00ffff",
            secondary="#ff00ff",
            accent="#ffff00",
            water="#1a1a3e",
            park="#151530",
            building="#1f1f47",
            road="#ff00ff",
            major_road="#00ffff",
            highway="#ffff00",
        ),
        description="赛博朋克霓虹风格",
    ),
    ThemeName.MINIMAL.value: Theme(
        name=ThemeName.MINIMAL.value,
        colors=ThemeColors(
            background="#f5f5f5",
            primary="#333333",
            secondary="#999999",
            accent="#e74c3c",
            water="#e8f4f8",
            park="#e8f5e9",
            building="#f0f0f0",
            road="#bdbdbd",
            major_road="#757575",
            highway="#424242",
        ),
        description="极简浅色风格",
    ),
    ThemeName.RETRO.value: Theme(
        name=ThemeName.RETRO.value,
        colors=ThemeColors(
            background="#f4e4bc",
            primary="#5c4033",
            secondary="#8b7355",
            accent="#d2691e",
            water="#c1d4b6",
            park="#a8c686",
            building="#d4c4a8",
            road="#b8956e",
            major_road="#8b6914",
            highway="#5c4033",
        ),
        description="复古地图风格",
    ),
}


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


@dataclass
class CacheConfig:
    enabled: bool = True
    directory: str = ".cache"
    ttl_days: int = 30
    max_size_mb: int = 500


@dataclass
class OSMConfig:
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_urls: list = field(default_factory=lambda: [
        "https://overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ])
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    timeout: int = 120
    user_agent: str = "MapToPoster/0.1.0"
    max_retries: int = 3
    retry_delay: float = 5.0


@dataclass
class Config:
    language: Language = Language.ZH
    default_theme: ThemeName = ThemeName.DARK
    default_output_format: OutputFormat = OutputFormat.PNG
    output_directory: str = "outputs"
    poster: PosterConfig = field(default_factory=PosterConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    osm: OSMConfig = field(default_factory=OSMConfig)
    themes: Dict[str, Theme] = field(default_factory=lambda: DEFAULT_THEMES.copy())

    @property
    def base_path(self) -> Path:
        return Path(__file__).parent.parent.parent

    @property
    def cache_path(self) -> Path:
        path = self.base_path / self.cache.directory
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def output_path(self) -> Path:
        path = self.base_path / self.output_directory
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_theme(self, theme_name: str) -> Theme:
        return self.themes.get(theme_name, self.themes[ThemeName.DARK.value])

    def add_theme(self, theme: Theme) -> None:
        self.themes[theme.name] = theme


def load_config(env_file: Optional[str] = None) -> Config:
    if env_file:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    
    config = Config()
    
    language = os.getenv("MAPTOPOSTER_LANGUAGE")
    if language:
        try:
            config.language = Language(language.lower())
        except ValueError:
            pass
    
    default_theme = os.getenv("MAPTOPOSTER_DEFAULT_THEME")
    if default_theme:
        try:
            config.default_theme = ThemeName(default_theme.lower())
        except ValueError:
            pass
    
    default_format = os.getenv("MAPTOPOSTER_DEFAULT_FORMAT")
    if default_format:
        try:
            config.default_output_format = OutputFormat(default_format.lower())
        except ValueError:
            pass
    
    output_dir = os.getenv("MAPTOPOSTER_OUTPUT_DIR")
    if output_dir:
        config.output_directory = output_dir
    
    cache_enabled = os.getenv("MAPTOPOSTER_CACHE_ENABLED")
    if cache_enabled:
        config.cache.enabled = cache_enabled.lower() in ("true", "1", "yes")
    
    cache_dir = os.getenv("MAPTOPOSTER_CACHE_DIR")
    if cache_dir:
        config.cache.directory = cache_dir
    
    return config
