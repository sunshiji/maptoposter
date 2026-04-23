import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
import json

from ..config.settings import (
    Theme, ThemeColors, DEFAULT_THEMES, ThemeName
)

logger = logging.getLogger(__name__)


class ThemeManager:
    def __init__(self, custom_themes_dir: Optional[Path] = None):
        self._themes: Dict[str, Theme] = DEFAULT_THEMES.copy()
        self._custom_themes_dir = custom_themes_dir
        
        if custom_themes_dir:
            self._load_custom_themes()
    
    def _load_custom_themes(self) -> None:
        if not self._custom_themes_dir:
            return
        
        self._custom_themes_dir.mkdir(parents=True, exist_ok=True)
        
        for theme_file in self._custom_themes_dir.glob("*.json"):
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                theme = self._theme_from_dict(data)
                self._themes[theme.name] = theme
                logger.debug(f"Loaded custom theme: {theme.name}")
                
            except Exception as e:
                logger.warning(f"Failed to load theme from {theme_file}: {e}")
    
    def _theme_from_dict(self, data: Dict[str, Any]) -> Theme:
        colors_data = data.get("colors", {})
        colors = ThemeColors(
            background=colors_data.get("background", "#000000"),
            primary=colors_data.get("primary", "#ffffff"),
            secondary=colors_data.get("secondary", "#888888"),
            accent=colors_data.get("accent", "#ff4444"),
            water=colors_data.get("water", "#1a1a2e"),
            park=colors_data.get("park", "#16213e"),
            building=colors_data.get("building", "#0f3460"),
            road=colors_data.get("road", "#e94560"),
            major_road=colors_data.get("major_road", "#ff6b6b"),
            highway=colors_data.get("highway", "#ff8787"),
        )
        
        return Theme(
            name=data.get("name", "custom"),
            colors=colors,
            description=data.get("description", ""),
        )
    
    def _theme_to_dict(self, theme: Theme) -> Dict[str, Any]:
        return {
            "name": theme.name,
            "description": theme.description,
            "colors": {
                "background": theme.colors.background,
                "primary": theme.colors.primary,
                "secondary": theme.colors.secondary,
                "accent": theme.colors.accent,
                "water": theme.colors.water,
                "park": theme.colors.park,
                "building": theme.colors.building,
                "road": theme.colors.road,
                "major_road": theme.colors.major_road,
                "highway": theme.colors.highway,
            },
        }
    
    def get_theme(self, name: str) -> Theme:
        if name not in self._themes:
            logger.warning(f"Theme '{name}' not found, using default dark theme")
            return self._themes[ThemeName.DARK.value]
        return self._themes[name]
    
    def add_theme(self, theme: Theme, save: bool = False) -> None:
        self._themes[theme.name] = theme
        
        if save and self._custom_themes_dir:
            self._save_theme(theme)
        
        logger.info(f"Added theme: {theme.name}")
    
    def _save_theme(self, theme: Theme) -> None:
        if not self._custom_themes_dir:
            return
        
        theme_file = self._custom_themes_dir / f"{theme.name}.json"
        
        try:
            with open(theme_file, "w", encoding="utf-8") as f:
                json.dump(self._theme_to_dict(theme), f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved theme to: {theme_file}")
        except Exception as e:
            logger.warning(f"Failed to save theme {theme.name}: {e}")
    
    def remove_theme(self, name: str) -> bool:
        if name not in self._themes:
            return False
        
        if name in [t.value for t in ThemeName]:
            logger.warning(f"Cannot remove built-in theme: {name}")
            return False
        
        del self._themes[name]
        
        if self._custom_themes_dir:
            theme_file = self._custom_themes_dir / f"{name}.json"
            if theme_file.exists():
                theme_file.unlink()
        
        logger.info(f"Removed theme: {name}")
        return True
    
    def list_themes(self) -> List[str]:
        return list(self._themes.keys())
    
    def get_theme_info(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self._themes:
            return None
        
        theme = self._themes[name]
        return {
            "name": theme.name,
            "description": theme.description,
            "colors": {
                "background": theme.colors.background,
                "primary": theme.colors.primary,
                "secondary": theme.colors.secondary,
                "accent": theme.colors.accent,
                "water": theme.colors.water,
                "park": theme.colors.park,
                "building": theme.colors.building,
                "road": theme.colors.road,
                "major_road": theme.colors.major_road,
                "highway": theme.colors.highway,
            },
            "is_builtin": name in [t.value for t in ThemeName],
        }
    
    def preview_colors(self, name: str) -> str:
        theme = self.get_theme(name)
        
        preview = f"""
Theme: {theme.name}
Description: {theme.description}

Colors:
  Background: {theme.colors.background}
  Primary:    {theme.colors.primary}
  Secondary:  {theme.colors.secondary}
  Accent:     {theme.colors.accent}
  Water:      {theme.colors.water}
  Park:       {theme.colors.park}
  Building:   {theme.colors.building}
  Road:       {theme.colors.road}
  Major Road: {theme.colors.major_road}
  Highway:    {theme.colors.highway}
"""
        return preview


def create_custom_theme(
    name: str,
    background: str = "#000000",
    primary: str = "#ffffff",
    secondary: str = "#888888",
    accent: str = "#ff4444",
    water: str = "#1a1a2e",
    park: str = "#16213e",
    building: str = "#0f3460",
    road: str = "#e94560",
    major_road: str = "#ff6b6b",
    highway: str = "#ff8787",
    description: str = "",
) -> Theme:
    colors = ThemeColors(
        background=background,
        primary=primary,
        secondary=secondary,
        accent=accent,
        water=water,
        park=park,
        building=building,
        road=road,
        major_road=major_road,
        highway=highway,
    )
    
    return Theme(name=name, colors=colors, description=description)


def list_available_themes() -> List[str]:
    return [t.value for t in ThemeName]
