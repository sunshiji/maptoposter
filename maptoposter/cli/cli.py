import logging
import sys
from pathlib import Path
from typing import Optional, Tuple
import re

import click

from .. import __version__
from ..config.settings import (
    load_config, Config, ThemeName, OutputFormat, Language
)
from ..cache.manager import CacheManager, CacheType
from ..geo.geocoder import Geocoder, LocationResult
from ..geo.osm_fetcher import OSMFetcher
from ..themes.manager import ThemeManager, list_available_themes
from ..i18n.i18n import I18nManager, supported_languages
from ..poster.generator import PosterGenerator, PosterConfig
from ..renderer.renderer import MapRenderer, RenderConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

config: Optional[Config] = None
cache_manager: Optional[CacheManager] = None
i18n: Optional[I18nManager] = None


def _get_config() -> Config:
    global config
    if config is None:
        config = load_config()
    return config


def _get_cache_manager() -> CacheManager:
    global cache_manager
    if cache_manager is None:
        cfg = _get_config()
        cache_manager = CacheManager(
            cache_dir=cfg.cache_path,
            enabled=cfg.cache.enabled,
            default_ttl_days=cfg.cache.ttl_days,
            max_size_mb=cfg.cache.max_size_mb,
        )
    return cache_manager


def _get_i18n() -> I18nManager:
    global i18n
    if i18n is None:
        cfg = _get_config()
        i18n = I18nManager(language=cfg.language.value)
    return i18n


def parse_coordinates(input_str: str) -> Optional[Tuple[float, float]]:
    pattern = r'^(-?\d+\.?\d*)\s*[,°\s]+\s*(-?\d+\.?\d*)$'
    match = re.match(pattern, input_str.strip())
    
    if match:
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
            
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        except ValueError:
            pass
    
    return None


def expand_bbox(
    bbox: Tuple[float, float, float, float],
    ratio: float = 1.2,
) -> Tuple[float, float, float, float]:
    min_lat, max_lat, min_lon, max_lon = bbox
    
    lat_range = max_lat - min_lat
    lon_range = max_lon - min_lon
    
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    
    new_lat_range = lat_range * ratio
    new_lon_range = lon_range * ratio
    
    if new_lon_range < 0.02:
        new_lon_range = 0.02
    if new_lat_range < 0.02:
        new_lat_range = 0.02
    
    return (
        center_lat - new_lat_range / 2,
        center_lat + new_lat_range / 2,
        center_lon - new_lon_range / 2,
        center_lon + new_lon_range / 2,
    )


@click.group()
@click.version_option(__version__, '-v', '--version')
@click.option('--language', '-l', type=click.Choice(supported_languages()), 
              default='zh', help='设置界面语言')
@click.option('--config', '-c', 'config_file', type=click.Path(exists=True, dir_okay=False),
              help='配置文件路径')
@click.pass_context
def cli(ctx, language, config_file):
    """
    MapToPoster - 城市极简风地图海报生成工具
    
    从 OpenStreetMap 获取地图数据，生成精美的可打印海报。
    
    示例:
        maptoposter generate "北京市"
        maptoposter generate 39.9042,116.4074 --theme neon
        maptoposter generate "上海市" --format svg --output my_poster.svg
    """
    global i18n
    i18n = I18nManager(language=language)
    
    if config_file:
        from ..config.settings import load_config
        global config
        config = load_config(config_file)


@cli.command('generate')
@click.argument('location')
@click.option('--theme', '-t', 
              type=click.Choice([t.value for t in ThemeName]),
              default='dark', help='选择海报主题')
@click.option('--format', '-f', 
              type=click.Choice([f.value for f in OutputFormat]),
              default='png', help='输出格式')
@click.option('--output', '-o', type=click.Path(), 
              help='输出文件路径')
@click.option('--width', type=int, default=2480, help='海报宽度（像素）')
@click.option('--height', type=int, default=3508, help='海报高度（像素）')
@click.option('--dpi', type=int, default=300, help='DPI分辨率')
@click.option('--margin', type=int, default=100, help='边距大小')
@click.option('--no-coords', is_flag=True, help='不显示坐标')
@click.option('--no-border', is_flag=True, help='不显示边框')
@click.option('--no-gradient', is_flag=True, help='不显示渐变遮罩')
@click.option('--title', help='自定义标题')
@click.option('--subtitle', help='自定义副标题')
@click.option('--bbox-ratio', type=float, default=1.2, 
              help='边界框扩展比例')
@click.option('--title-position', type=click.Choice(['top', 'bottom']),
              default='bottom', help='标题位置')
@click.option('--no-labels', is_flag=True, help='不显示地名标签')
@click.option('--no-city-labels', is_flag=True, help='不显示城市标签')
@click.option('--no-county-labels', is_flag=True, help='不显示县/县级市标签')
@click.option('--no-district-labels', is_flag=True, help='不显示市辖区标签')
@click.option('--no-town-labels', is_flag=True, help='不显示乡镇标签')
@click.option('--max-labels', type=int, default=50, help='最大标签数量')
@click.pass_context
def generate_poster(
    ctx,
    location,
    theme,
    format,
    output,
    width,
    height,
    dpi,
    margin,
    no_coords,
    no_border,
    no_gradient,
    title,
    subtitle,
    bbox_ratio,
    title_position,
    no_labels,
    no_city_labels,
    no_county_labels,
    no_district_labels,
    no_town_labels,
    max_labels,
):
    """
    生成地图海报
    
    LOCATION: 城市名称或经纬度坐标（如 "北京市" 或 "39.9042,116.4074"）
    
    示例:
        maptoposter generate "北京市"
        maptoposter generate "New York" --theme neon
        maptoposter generate 31.2304,121.4737 --format svg
    """
    _i18n = _get_i18n()
    _cfg = _get_config()
    _cache = _get_cache_manager()
    
    theme_manager = ThemeManager()
    selected_theme = theme_manager.get_theme(theme)
    
    click.echo(f"[INFO] MapToPoster v{__version__}")
    click.echo(f"[INFO] {_i18n('searching_location')}")
    
    coords = parse_coordinates(location)
    location_result: Optional[LocationResult] = None
    
    geocoder = Geocoder(
        user_agent=_cfg.osm.user_agent,
        timeout=_cfg.osm.timeout,
        cache_manager=_cache,
    )
    
    try:
        if coords:
            location_result = geocoder.reverse_geocode(
                coords[0],
                coords[1],
                language=_i18n.language,
            )
            if location_result:
                click.echo(f"   找到位置: {location_result.display_name}")
            else:
                location_result = LocationResult(
                    name=f"{coords[0]}, {coords[1]}",
                    display_name=f"{coords[0]}, {coords[1]}",
                    latitude=coords[0],
                    longitude=coords[1],
                    bounding_box=(
                        coords[0] - 0.05,
                        coords[0] + 0.05,
                        coords[1] - 0.05,
                        coords[1] + 0.05,
                    ),
                )
        else:
            results = geocoder.geocode(
                location,
                language=_i18n.language,
                limit=5,
            )
            
            if not results:
                click.echo(f"[ERROR] {_i18n('location_not_found')}")
                sys.exit(1)
            
            if len(results) == 1:
                location_result = results[0]
                click.echo(f"   找到: {location_result.display_name}")
            else:
                click.echo("   找到多个位置，请选择:")
                for i, result in enumerate(results, 1):
                    click.echo(f"   {i}. {result.display_name}")
                
                choice = click.prompt("   请选择序号", type=int, default=1)
                if 1 <= choice <= len(results):
                    location_result = results[choice - 1]
                else:
                    location_result = results[0]
        
    except Exception as e:
        click.echo(f"[ERROR] {_i18n('error')}: {e}")
        sys.exit(1)
    finally:
        geocoder.close()
    
    if not location_result:
        click.echo(f"[ERROR] {_i18n('location_not_found')}")
        sys.exit(1)
    
    click.echo(f"[INFO] {_i18n('fetching_data')}")
    click.echo(f"   提示: 对于大城市或偏远地区，数据获取可能需要较长时间，请耐心等待...")
    
    bbox = expand_bbox(location_result.bounding_box, bbox_ratio)
    
    osm_fetcher = OSMFetcher(
        overpass_url=_cfg.osm.overpass_url,
        overpass_urls=_cfg.osm.overpass_urls,
        user_agent=_cfg.osm.user_agent,
        timeout=_cfg.osm.timeout,
        cache_manager=_cache,
        max_retries=_cfg.osm.max_retries,
        retry_delay=_cfg.osm.retry_delay,
    )
    
    try:
        osm_data = osm_fetcher.fetch(bbox)
        
        if osm_data.all_features == 0:
            click.echo(f"[WARN]  {_i18n('no_map_data')}")
            click.echo("   尝试使用更大的 --bbox-ratio 值")
        
        click.echo(f"   获取到 {osm_data.roads} 条道路, {len(osm_data.water_bodies)} 个水体, {len(osm_data.parks)} 个公园, {len(osm_data.buildings)} 个建筑, {len(osm_data.places)} 个地名")
        
    except Exception as e:
        click.echo(f"[ERROR] {_i18n('error')}: {e}")
        sys.exit(1)
    finally:
        osm_fetcher.close()
    
    click.echo(f"[INFO] {_i18n('generating_poster')}")
    
    from ..renderer.renderer import LabelConfig
    
    labels_config = LabelConfig(
        show_labels=not no_labels,
        show_city=not no_city_labels,
        show_county=not no_county_labels,
        show_district=not no_district_labels,
        show_town=not no_town_labels,
        max_labels=max_labels,
    )
    
    poster_config = PosterConfig(
        width=width,
        height=height,
        dpi=dpi,
        margin=margin,
        show_coords=not no_coords,
        show_border=not no_border,
        gradient_overlay=not no_gradient,
        title_position=title_position,
        labels=labels_config,
    )
    
    poster_generator = PosterGenerator(
        theme=selected_theme,
        config=poster_config,
        i18n=_i18n,
    )
    
    try:
        poster = poster_generator.generate(
            osm_data=osm_data,
            location=location_result,
            custom_title=title,
            custom_subtitle=subtitle,
        )
        
        if output:
            output_path = Path(output)
            output_path = output_path.resolve()
        else:
            safe_name = re.sub(r'[^\w\-_.]', '_', location_result.name)
            output_filename = f"{safe_name}_{theme}.{format}"
            output_path = _cfg.output_path / output_filename
            output_path = output_path.resolve()
        
        output_dir = output_path.parent
        click.echo(f"[INFO] {_i18n('saving_file')}")
        click.echo(f"   输出目录: {output_dir}")
        click.echo(f"   文件名: {output_path.name}")
        
        output_format = OutputFormat(format)
        poster_generator.save(
            poster=poster,
            output_path=output_path,
            output_format=output_format,
            osm_data=osm_data,
        )
        
        click.echo(f"[OK] {_i18n('success')}")
        click.echo(f"")
        click.echo(f"   [路径] {output_path}")
        click.echo(f"   [大小] {output_path.stat().st_size / 1024:.1f} KB")
        click.echo(f"   [格式] {format.upper()}")
        click.echo(f"   [尺寸] {width} x {height} 像素 @ {dpi} DPI")
        click.echo(f"")
        click.echo(f"   提示: 可以使用 --output 参数自定义输出路径")
        
        return poster
        
    except Exception as e:
        click.echo(f"[ERROR] {_i18n('error')}: {e}")
        logger.exception("Poster generation error")
        sys.exit(1)


@cli.command('themes')
@click.option('--preview', '-p', is_flag=True, help='显示主题预览')
def list_themes(preview):
    """
    列出所有可用的主题
    
    示例:
        maptoposter themes
        maptoposter themes --preview
    """
    theme_manager = ThemeManager()
    themes = theme_manager.list_themes()
    
    click.echo("[INFO] 可用主题:")
    for theme_name in themes:
        if preview:
            theme_info = theme_manager.get_theme_info(theme_name)
            click.echo(f"\n[INFO] {theme_name}")
            if theme_info:
                click.echo(f"   描述: {theme_info.get('description', '')}")
                click.echo(f"   内置: {'是' if theme_info.get('is_builtin') else '否'}")
                if theme_info.get('colors'):
                    colors = theme_info['colors']
                    click.echo(f"   颜色:")
                    click.echo(f"      背景: {colors.get('background')}")
                    click.echo(f"      主色: {colors.get('primary')}")
                    click.echo(f"      次要: {colors.get('secondary')}")
                    click.echo(f"      强调: {colors.get('accent')}")
        else:
            click.echo(f"  - {theme_name}")


@cli.command('cache')
@click.option('--clear', '-c', is_flag=True, help='清除缓存')
@click.option('--stats', '-s', is_flag=True, help='显示缓存统计')
def manage_cache(clear, stats):
    """
    管理缓存
    
    示例:
        maptoposter cache --stats
        maptoposter cache --clear
    """
    _cache = _get_cache_manager()
    
    if clear:
        count = _cache.clear()
        click.echo(f"[INFO] 已清除 {count} 个缓存文件")
    
    if stats or not clear:
        stats_info = _cache.get_stats()
        click.echo("[INFO] 缓存统计:")
        click.echo(f"   状态: {'启用' if stats_info.get('enabled') else '禁用'}")
        click.echo(f"   目录: {stats_info.get('cache_dir')}")
        click.echo(f"   已使用: {stats_info.get('current_size_mb', 0):.2f} MB")
        click.echo(f"   最大限制: {stats_info.get('max_size_mb', 0):.2f} MB")
        
        entries = stats_info.get('entries_by_type', {})
        if entries:
            click.echo(f"\n   按类型统计:")
            for cache_type, info in entries.items():
                click.echo(f"      {cache_type}: {info.get('count', 0)} 个文件, {info.get('size_mb', 0):.2f} MB")


@cli.command('languages')
def list_languages():
    """
    列出所有支持的语言
    """
    langs = supported_languages()
    
    lang_names = {
        'en': 'English',
        'zh': '中文',
        'ja': '日本語',
        'ko': '한국어',
    }
    
    click.echo("[INFO] 支持的语言:")
    for lang in langs:
        click.echo(f"  - {lang}: {lang_names.get(lang, lang)}")


def run_cli():
    """
    运行命令行接口的入口函数
    """
    cli()


if __name__ == '__main__':
    run_cli()
