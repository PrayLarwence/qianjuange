"""
World map generator (stage 0).

Pipeline:
  1. height field   = multi-octave value noise (fractal Brownian motion)
  2. sea level cut  = quantile threshold -> ocean / land
  3. temperature    = latitude gradient + altitude penalty
  4. moisture       = noise + distance-to-ocean heuristic
  5. biome          = Whittaker-style classification (temperature x moisture)

All data is stored as numpy uint8 arrays packed into a single .npz file
on disk (one file per world). The DB only stores map_w/map_h/sea_level meta.

Layers (uint8 each, 0..255):
  - terrain: discrete code (TERRAIN_*)
  - height:  raw elevation 0..255 (sea_level marks coastline)
  - temp:    0=arctic 255=equatorial
  - moist:   0=arid 255=rainforest
  - biome:   discrete code (BIOME_*)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ...models.db import DATA_DIR


MAP_DIR = DATA_DIR / "maps"
MAP_DIR.mkdir(parents=True, exist_ok=True)


# ---- terrain codes (UI palette anchors) ----
TERRAIN_DEEP_OCEAN = 0
TERRAIN_OCEAN = 1
TERRAIN_COAST = 2
TERRAIN_BEACH = 3
TERRAIN_PLAIN = 4
TERRAIN_HILL = 5
TERRAIN_MOUNTAIN = 6
TERRAIN_PEAK = 7

TERRAIN_LABELS = {
    TERRAIN_DEEP_OCEAN: "深海",
    TERRAIN_OCEAN: "海洋",
    TERRAIN_COAST: "近岸",
    TERRAIN_BEACH: "海滩",
    TERRAIN_PLAIN: "平原",
    TERRAIN_HILL: "丘陵",
    TERRAIN_MOUNTAIN: "山地",
    TERRAIN_PEAK: "高峰",
}

# ---- biome codes ----
BIOME_OCEAN = 0
BIOME_ICE = 1
BIOME_TUNDRA = 2
BIOME_BOREAL = 3      # 北方针叶林
BIOME_TEMPERATE_FOREST = 4
BIOME_GRASSLAND = 5
BIOME_SHRUBLAND = 6
BIOME_DESERT = 7
BIOME_SAVANNA = 8
BIOME_RAINFOREST = 9  # 热带雨林
BIOME_WETLAND = 10
BIOME_ALPINE = 11

BIOME_LABELS = {
    BIOME_OCEAN: "海洋",
    BIOME_ICE: "冰原",
    BIOME_TUNDRA: "苔原",
    BIOME_BOREAL: "北方针叶林",
    BIOME_TEMPERATE_FOREST: "温带阔叶林",
    BIOME_GRASSLAND: "温带草原",
    BIOME_SHRUBLAND: "灌木地",
    BIOME_DESERT: "沙漠",
    BIOME_SAVANNA: "热带稀树草原",
    BIOME_RAINFOREST: "热带雨林",
    BIOME_WETLAND: "湿地",
    BIOME_ALPINE: "高山",
}

# Biome palette as RGB (canvas-friendly hex base for the frontend).
BIOME_COLORS = {
    BIOME_OCEAN: (24, 56, 102),
    BIOME_ICE: (235, 240, 246),
    BIOME_TUNDRA: (170, 178, 174),
    BIOME_BOREAL: (60, 100, 76),
    BIOME_TEMPERATE_FOREST: (80, 130, 70),
    BIOME_GRASSLAND: (170, 192, 110),
    BIOME_SHRUBLAND: (180, 162, 110),
    BIOME_DESERT: (224, 200, 138),
    BIOME_SAVANNA: (200, 180, 96),
    BIOME_RAINFOREST: (40, 110, 60),
    BIOME_WETLAND: (90, 130, 110),
    BIOME_ALPINE: (200, 200, 210),
}


@dataclass
class WorldGenParams:
    width: int = 512
    height: int = 384
    seed: int = 0
    sea_level: float = 0.42         # 0..1, fraction of cells under sea
    octaves: int = 6
    persistence: float = 0.55
    base_freq: float = 2.5
    warp: float = 0.12              # domain warp strength (0..0.3 reasonable)


# --------- noise primitives ---------

def _value_noise_grid(rng: np.random.Generator, h: int, w: int) -> np.ndarray:
    """Return a smooth value-noise grid (0..1) at the given resolution.

    Uses a low-res random grid + bilinear upsampling. Cheap and good enough
    for fbm composition. We avoid scipy/perlin libs to keep deps minimal.
    """
    vals = rng.random((h, w), dtype=np.float32)
    return vals


def _bilinear_upsample(src: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    sh, sw = src.shape
    ys = np.linspace(0, sh - 1, target_h, dtype=np.float32)
    xs = np.linspace(0, sw - 1, target_w, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, sh - 1)
    x1 = np.clip(x0 + 1, 0, sw - 1)
    fy = (ys - y0).reshape(-1, 1)
    fx = (xs - x0).reshape(1, -1)
    a = src[y0][:, x0]
    b = src[y0][:, x1]
    c = src[y1][:, x0]
    d = src[y1][:, x1]
    top = a * (1 - fx) + b * fx
    bot = c * (1 - fx) + d * fx
    return top * (1 - fy) + bot * fy


def fbm(rng: np.random.Generator, h: int, w: int, octaves: int, persistence: float,
        base_freq: float) -> np.ndarray:
    """Fractal Brownian motion over [0,1]."""
    out = np.zeros((h, w), dtype=np.float32)
    amp = 1.0
    total = 0.0
    freq = base_freq
    for _ in range(octaves):
        gh = max(2, int(round(h * freq / max(h, w))))
        gw = max(2, int(round(w * freq / max(h, w))))
        layer = _value_noise_grid(rng, gh, gw)
        layer = _bilinear_upsample(layer, h, w)
        out += layer * amp
        total += amp
        amp *= persistence
        freq *= 2.0
    out /= total
    # gentle sigmoid for contrast
    out = 1.0 / (1.0 + np.exp(-(out - 0.5) * 6.0))
    return out


# --------- pipeline ---------

def _continent_mask(h: int, w: int, strength: float = 0.35) -> np.ndarray:
    """Radial falloff so the world tends to be one big continent / archipelago
    rather than land touching every edge. Strength 0..1, larger = more island-y."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    rx = (xx - cx) / cx
    ry = (yy - cy) / cy
    d = np.sqrt(rx * rx + ry * ry)
    falloff = np.clip(1.0 - d, 0.0, 1.0)
    return (1.0 - strength) + strength * falloff


def _temperature(h: int, w: int, height: np.ndarray, sea_h: float) -> np.ndarray:
    yy = np.mgrid[0:h, 0:w][0].astype(np.float32)
    lat = (yy / max(1, h - 1)) * 2 - 1            # -1..1, top = north
    base = 1.0 - np.abs(lat)                      # equator hottest
    # smooth poles
    base = base ** 1.4
    # altitude: every 0.1 above sea level cuts ~0.08 temp
    alt = np.maximum(0.0, height - sea_h)
    t = base - alt * 0.9
    return np.clip(t, 0.0, 1.0)


def _distance_to_ocean(land: np.ndarray, max_steps: int = 64) -> np.ndarray:
    """BFS distance (in tiles) from each land cell to the nearest ocean cell.
    Returns float32 normalized 0..1 (clamped at max_steps).
    Implemented as iterative dilation for speed using numpy."""
    h, w = land.shape
    dist = np.full((h, w), -1, dtype=np.int16)
    dist[~land] = 0
    front = ~land
    step = 0
    while step < max_steps and front.any():
        step += 1
        nb = np.zeros_like(front)
        nb[1:, :] |= front[:-1, :]
        nb[:-1, :] |= front[1:, :]
        nb[:, 1:] |= front[:, :-1]
        nb[:, :-1] |= front[:, 1:]
        new = nb & (dist == -1)
        dist[new] = step
        front = new
    dist[dist == -1] = max_steps
    return (dist.astype(np.float32) / max_steps).clip(0, 1)


def _moisture(rng: np.random.Generator, h: int, w: int, land: np.ndarray,
              temp: np.ndarray) -> np.ndarray:
    base = fbm(rng, h, w, octaves=4, persistence=0.6, base_freq=3.0)
    d2o = _distance_to_ocean(land, max_steps=48)
    # ocean influence: closer to ocean -> wetter
    moist = base * 0.55 + (1.0 - d2o) * 0.45
    # warm air holds more water -> equatorial slight wet bonus
    moist = moist + (temp - 0.5) * 0.1
    return np.clip(moist, 0.0, 1.0)


def _classify_biomes(height: np.ndarray, sea_h: float, temp: np.ndarray,
                     moist: np.ndarray) -> np.ndarray:
    """Whittaker-ish biome assignment."""
    h, w = height.shape
    biome = np.full((h, w), BIOME_OCEAN, dtype=np.uint8)
    land = height > sea_h
    alt = (height - sea_h) / max(1e-6, 1.0 - sea_h)  # 0..1 above sea

    # alpine cap
    alpine = land & (alt > 0.78)
    biome[alpine] = BIOME_ALPINE

    cold = temp < 0.2
    cool = (temp >= 0.2) & (temp < 0.42)
    mid = (temp >= 0.42) & (temp < 0.66)
    warm = (temp >= 0.66) & (temp < 0.82)
    hot = temp >= 0.82

    arid = moist < 0.28
    semi = (moist >= 0.28) & (moist < 0.5)
    moiststripe = (moist >= 0.5) & (moist < 0.72)
    wet = moist >= 0.72

    rest = land & (biome == BIOME_OCEAN)

    biome[rest & cold & arid] = BIOME_ICE
    biome[rest & cold & ~arid] = BIOME_TUNDRA

    biome[rest & cool & arid] = BIOME_SHRUBLAND
    biome[rest & cool & semi] = BIOME_BOREAL
    biome[rest & cool & moiststripe] = BIOME_BOREAL
    biome[rest & cool & wet] = BIOME_TEMPERATE_FOREST

    biome[rest & mid & arid] = BIOME_GRASSLAND
    biome[rest & mid & semi] = BIOME_GRASSLAND
    biome[rest & mid & moiststripe] = BIOME_TEMPERATE_FOREST
    biome[rest & mid & wet] = BIOME_WETLAND

    biome[rest & warm & arid] = BIOME_DESERT
    biome[rest & warm & semi] = BIOME_SAVANNA
    biome[rest & warm & moiststripe] = BIOME_TEMPERATE_FOREST
    biome[rest & warm & wet] = BIOME_RAINFOREST

    biome[rest & hot & arid] = BIOME_DESERT
    biome[rest & hot & semi] = BIOME_SAVANNA
    biome[rest & hot & moiststripe] = BIOME_RAINFOREST
    biome[rest & hot & wet] = BIOME_RAINFOREST

    return biome


def _classify_terrain(height: np.ndarray, sea_h: float) -> np.ndarray:
    h, w = height.shape
    out = np.full((h, w), TERRAIN_PLAIN, dtype=np.uint8)
    out[height < sea_h - 0.18] = TERRAIN_DEEP_OCEAN
    out[(height >= sea_h - 0.18) & (height < sea_h - 0.04)] = TERRAIN_OCEAN
    out[(height >= sea_h - 0.04) & (height < sea_h)] = TERRAIN_COAST
    out[(height >= sea_h) & (height < sea_h + 0.02)] = TERRAIN_BEACH
    out[(height >= sea_h + 0.02) & (height < sea_h + 0.22)] = TERRAIN_PLAIN
    out[(height >= sea_h + 0.22) & (height < sea_h + 0.45)] = TERRAIN_HILL
    out[(height >= sea_h + 0.45) & (height < sea_h + 0.7)] = TERRAIN_MOUNTAIN
    out[height >= sea_h + 0.7] = TERRAIN_PEAK
    return out


def _finalize_from_height(height: np.ndarray, sea_level: float, seed: int,
                          rng: Optional[np.random.Generator] = None) -> dict:
    """Given a normalized height field (0..1, shape HxW), build the full layer set.

    Used by both random worldgen and image-based imports so that any data
    flowing through the engine looks identical downstream.
    """
    if rng is None:
        rng = np.random.default_rng(seed or None)
    height = np.clip(height.astype(np.float32), 0.0, 1.0)
    h, w = height.shape

    flat = height.flatten()
    sea_h = float(np.quantile(flat, sea_level))

    terrain = _classify_terrain(height, sea_h)
    land = height > sea_h
    temp = _temperature(h, w, height, sea_h)
    moist = _moisture(rng, h, w, land, temp)
    biome = _classify_biomes(height, sea_h, temp, moist)

    return {
        "width": w,
        "map_h": h,
        "seed": int(seed),
        "sea_level": float(sea_level),
        "sea_h": sea_h,
        "height": (height * 255).astype(np.uint8),
        "terrain": terrain.astype(np.uint8),
        "temp": (temp * 255).astype(np.uint8),
        "moist": (moist * 255).astype(np.uint8),
        "biome": biome.astype(np.uint8),
    }


def generate(params: WorldGenParams) -> dict:
    """Run the full pipeline. Returns numpy arrays + meta."""
    rng = np.random.default_rng(params.seed or None)
    h, w = params.height, params.width

    base = fbm(rng, h, w, params.octaves, params.persistence, params.base_freq)
    if params.warp > 0:
        wx = (fbm(rng, h, w, 3, 0.5, 1.5) - 0.5) * 2 * params.warp
        wy = (fbm(rng, h, w, 3, 0.5, 1.5) - 0.5) * 2 * params.warp
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        sy = np.clip(yy + wy * h, 0, h - 1).astype(np.int32)
        sx = np.clip(xx + wx * w, 0, w - 1).astype(np.int32)
        base = base[sy, sx]

    cont = _continent_mask(h, w, strength=0.45)
    height = base * cont
    height = (height - height.min()) / max(1e-6, (height.max() - height.min()))

    return _finalize_from_height(height, params.sea_level, params.seed, rng)


# ---------- image-based import (stage 2A: grayscale heightmap) ----------

@dataclass
class HeightmapImportParams:
    width: int = 512
    height: int = 384
    sea_level: float = 0.42
    invert: bool = False
    blur: float = 0.6              # gaussian blur radius in target-space pixels
    contrast: float = 1.0          # >1 stretches mid-range
    seed: int = 0                  # used by moisture noise


def import_from_heightmap(image_bytes: bytes, params: HeightmapImportParams) -> dict:
    """Treat a (grayscale or color) image as elevation, resample to target
    resolution, optionally smooth/invert, then run the standard pipeline.

    Anything PIL can decode works (PNG/JPG/BMP/TIFF/WEBP/...).
    """
    from io import BytesIO
    from PIL import Image, ImageFilter, ImageOps

    img = Image.open(BytesIO(image_bytes))
    # decode any mode to L (grayscale luminance)
    if img.mode not in ("L", "I", "F"):
        img = img.convert("L")
    else:
        img = img.convert("L")

    if params.invert:
        img = ImageOps.invert(img)

    img = img.resize((params.width, params.height), Image.Resampling.LANCZOS)

    if params.blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=float(params.blur)))

    arr = np.asarray(img, dtype=np.float32) / 255.0

    if params.contrast != 1.0:
        # symmetric contrast around 0.5
        arr = np.clip(0.5 + (arr - 0.5) * float(params.contrast), 0.0, 1.0)

    # robust normalize (use 1st/99th percentile so outliers don't squash range)
    lo = float(np.quantile(arr, 0.01))
    hi = float(np.quantile(arr, 0.99))
    if hi - lo > 1e-3:
        arr = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)

    return _finalize_from_height(arr, params.sea_level, params.seed)


def map_path(world_id: str) -> Path:
    return MAP_DIR / f"{world_id}.npz"


def save(world_id: str, data: dict) -> None:
    overlay = data.get("overlay")
    if overlay is None:
        overlay = np.zeros_like(data["terrain"], dtype=np.uint8)
    np.savez_compressed(
        map_path(world_id),
        map_w=np.int32(data["width"]),
        map_h=np.int32(data["map_h"]),
        seed=np.int64(data["seed"]),
        sea_level=np.float32(data["sea_level"]),
        sea_h=np.float32(data["sea_h"]),
        terrain=data["terrain"],
        height_field=data["height"],
        temp=data["temp"],
        moist=data["moist"],
        biome=data["biome"],
        overlay=overlay,
    )


def load(world_id: str) -> Optional[dict]:
    p = map_path(world_id)
    if not p.exists():
        return None
    with np.load(p) as f:
        keys = set(f.files)
        d = {
            "width": int(f["map_w"]),
            "map_h": int(f["map_h"]),
            "seed": int(f["seed"]),
            "sea_level": float(f["sea_level"]),
            "sea_h": float(f["sea_h"]),
            "terrain": f["terrain"].copy(),
            "height": f["height_field"].copy(),
            "temp": f["temp"].copy(),
            "moist": f["moist"].copy(),
            "biome": f["biome"].copy(),
        }
        d["overlay"] = (f["overlay"].copy() if "overlay" in keys
                        else np.zeros_like(d["terrain"], dtype=np.uint8))
        return d


def effective_terrain(data: dict) -> np.ndarray:
    """Terrain with user overlay applied (overlay > 0 wins)."""
    o = data.get("overlay")
    base = data["terrain"]
    if o is None or not o.any():
        return base
    out = base.copy()
    mask = o > 0
    # overlay stores (terrain_code + 1) so 0 means "untouched"
    out[mask] = o[mask] - 1
    return out


def effective_biome(data: dict) -> np.ndarray:
    """Biome with overlay re-classified for overlay-painted tiles.

    If a user paints a tile to a different terrain, we recompute its biome
    using its existing temp/moist (climate doesn't change just because you
    painted a mountain). Ocean overlay always becomes BIOME_OCEAN.
    """
    o = data.get("overlay")
    base = data["biome"].copy()
    if o is None or not o.any():
        return base
    eff_terrain = effective_terrain(data)
    mask = o > 0
    if not mask.any():
        return base
    # Ocean / deep ocean -> ocean biome
    is_water = (eff_terrain == TERRAIN_DEEP_OCEAN) | (eff_terrain == TERRAIN_OCEAN)
    base[mask & is_water] = BIOME_OCEAN
    # Mountain / peak -> alpine if cold, otherwise stays
    is_mountain = (eff_terrain == TERRAIN_MOUNTAIN) | (eff_terrain == TERRAIN_PEAK)
    base[mask & is_mountain] = BIOME_ALPINE
    # Beach -> shrubland-ish
    base[mask & (eff_terrain == TERRAIN_BEACH)] = BIOME_GRASSLAND
    return base


def paint(data: dict, x: int, y: int, terrain_code: int, brush: int = 1) -> int:
    """Paint a circular brush of terrain into the overlay layer.

    Returns the number of tiles modified.
    """
    h, w = data["terrain"].shape
    if not (0 <= x < w and 0 <= y < h):
        return 0
    if "overlay" not in data or data["overlay"] is None:
        data["overlay"] = np.zeros_like(data["terrain"], dtype=np.uint8)
    r = max(1, min(64, int(brush)))
    y0, y1 = max(0, y - r), min(h, y + r + 1)
    x0, x1 = max(0, x - r), min(w, x + r + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist2 = (yy - y) ** 2 + (xx - x) ** 2
    mask = dist2 <= r * r
    if terrain_code < 0:
        # erase overlay
        sub = data["overlay"][y0:y1, x0:x1]
        sub[mask] = 0
    else:
        sub = data["overlay"][y0:y1, x0:x1]
        sub[mask] = terrain_code + 1
    return int(mask.sum())


def clear_overlay(data: dict) -> int:
    if "overlay" in data and data["overlay"] is not None:
        n = int((data["overlay"] > 0).sum())
        data["overlay"][:] = 0
        return n
    return 0


def delete(world_id: str) -> bool:
    p = map_path(world_id)
    if p.exists():
        p.unlink()
        return True
    return False


def render_png_bytes(data: dict, layer: str = "biome") -> bytes:
    """Render a layer to an RGBA PNG byte buffer for the frontend canvas.

    layer: 'biome' | 'terrain' | 'height' | 'temp' | 'moist'
    """
    from io import BytesIO
    from PIL import Image

    h, w = data["height"].shape
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[..., 3] = 255

    if layer == "biome":
        biome = effective_biome(data)
        for code, rgb in BIOME_COLORS.items():
            mask = biome == code
            img[mask, 0] = rgb[0]
            img[mask, 1] = rgb[1]
            img[mask, 2] = rgb[2]
    elif layer == "terrain":
        # blue gradient for water, brown gradient for land, white peaks
        terrain_eff = effective_terrain(data)
        height_f = data["height"].astype(np.float32) / 255.0
        sea_h = data["sea_h"]
        # build a fast lookup: terrain code -> base color, then modulate by height
        for y in range(h):
            for x in range(w):
                t_code = int(terrain_eff[y, x])
                hv = height_f[y, x]
                # painted-over tiles use a synthetic height for nicer rendering
                if t_code <= TERRAIN_OCEAN:
                    th = min(hv, sea_h * 0.95)
                    t = th / max(1e-6, sea_h)
                    img[y, x, 0] = int(20 + t * 60)
                    img[y, x, 1] = int(40 + t * 80)
                    img[y, x, 2] = int(90 + t * 120)
                elif t_code <= TERRAIN_HILL:
                    t = max(0.0, (hv - sea_h)) / max(1e-6, 1.0 - sea_h)
                    img[y, x, 0] = int(120 + t * 100)
                    img[y, x, 1] = int(140 + t * 80)
                    img[y, x, 2] = int(80 + t * 60)
                else:
                    t = max(0.0, (hv - sea_h)) / max(1e-6, 1.0 - sea_h)
                    img[y, x, 0] = int(200 + min(55, t * 80))
                    img[y, x, 1] = int(200 + min(55, t * 80))
                    img[y, x, 2] = int(210 + min(45, t * 60))
    elif layer == "height":
        v = data["height"]
        img[..., 0] = v
        img[..., 1] = v
        img[..., 2] = v
    elif layer == "temp":
        v = data["temp"].astype(np.float32) / 255.0
        img[..., 0] = (v * 255).astype(np.uint8)
        img[..., 1] = ((1 - np.abs(v - 0.5) * 2) * 200).astype(np.uint8)
        img[..., 2] = ((1 - v) * 255).astype(np.uint8)
    elif layer == "moist":
        v = data["moist"].astype(np.float32) / 255.0
        img[..., 0] = ((1 - v) * 200).astype(np.uint8)
        img[..., 1] = ((1 - v) * 220).astype(np.uint8) // 2 + 60
        img[..., 2] = (v * 255).astype(np.uint8)
    else:
        raise ValueError(f"unknown layer: {layer}")

    pil = Image.fromarray(img, mode="RGBA")
    buf = BytesIO()
    pil.save(buf, format="PNG", optimize=False, compress_level=1)
    return buf.getvalue()


def tile_info(data: dict, x: int, y: int) -> dict:
    """Inspect a single tile."""
    h, w = data["biome"].shape
    if not (0 <= x < w and 0 <= y < h):
        return {}
    height_f = float(data["height"][y, x]) / 255.0
    sea_h = data["sea_h"]
    overlay = data.get("overlay")
    eff_terrain = effective_terrain(data)
    eff_biome = effective_biome(data)
    painted = bool(overlay is not None and overlay[y, x] > 0)
    return {
        "x": x,
        "y": y,
        "terrain": int(eff_terrain[y, x]),
        "terrain_label": TERRAIN_LABELS.get(int(eff_terrain[y, x]), "?"),
        "biome": int(eff_biome[y, x]),
        "biome_label": BIOME_LABELS.get(int(eff_biome[y, x]), "?"),
        "elevation": height_f,
        "elevation_m": int((height_f - sea_h) * 8000) if height_f >= sea_h else int((height_f - sea_h) * 4000),
        "temperature": float(data["temp"][y, x]) / 255.0,
        "moisture": float(data["moist"][y, x]) / 255.0,
        "is_land": bool(data["height"][y, x] / 255.0 > sea_h),
        "painted": painted,
    }
