"""Render a blueprint onto an existing/fresh map.

The blueprint comes from `blueprint.generate_blueprint`; here we
materialize its regions into the map's overlay layer (same layer the
user's brush paint writes to), and return landmark info for the API
layer to convert into location entities.

Why overlay rather than a fresh terrain field?
  - User paint and blueprint regions live in the same plane already.
  - Reverting / regenerating with a different blueprint just clears
    overlay; the noise-based base map stays intact and recoverable.
  - Falls through transparently via `worldgen.effective_terrain`.
"""

from __future__ import annotations
import logging
from typing import Optional

import numpy as np

from . import worldgen
from .blueprint import ALLOWED_TERRAIN

log = logging.getLogger(__name__)


def apply_blueprint_to_overlay(
    data: dict,
    regions: list[dict],
    *,
    feather: int = 1,
) -> dict:
    """Stamp regions into `data['overlay']` in-place.

    Order of operations matters: regions are stamped in input order, so the
    LLM is expected to emit large background regions first (ocean/mountain
    range) and smaller specific ones (lake, peak) afterward — the system
    prompt instructs it to do so.

    Args:
        data:    map dict from worldgen.generate / load (modified in-place)
        regions: blueprint regions list
        feather: shrink radius mask check by this many tiles for "core"
                 stamping; >0 leaves a soft margin where base terrain shows
                 through (we don't currently use it; reserved for future
                 blending). 0 = hard circle.

    Returns:
        {"painted_tiles": int, "by_terrain": {code: tiles}}
    """
    h, w = data["terrain"].shape
    overlay = data.get("overlay")
    if overlay is None:
        overlay = np.zeros_like(data["terrain"], dtype=np.uint8)
        data["overlay"] = overlay

    yy, xx = np.mgrid[0:h, 0:w]
    by_terrain: dict[int, int] = {}
    total_painted = 0

    for r in regions:
        terrain_code = ALLOWED_TERRAIN.get(r.get("terrain", "").lower())
        if terrain_code is None:
            log.warning("region %r has unknown terrain, skipping", r.get("name"))
            continue
        cx, cy, rad = int(r["cx"]), int(r["cy"]), int(r["radius"])
        # circular mask
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= rad * rad
        # overlay encodes (terrain_code + 1) so 0 = untouched
        overlay[mask] = terrain_code + 1
        cnt = int(mask.sum())
        total_painted += cnt
        by_terrain[terrain_code] = by_terrain.get(terrain_code, 0) + cnt

    return {
        "painted_tiles": total_painted,
        "by_terrain": by_terrain,
    }


def landmarks_to_entity_specs(
    landmarks: list[dict],
    *,
    branch_id: str,
) -> list[dict]:
    """Convert LLM landmarks into entity-creation specs.

    Returns a list of dicts ready for the route layer to instantiate as
    Entity rows. We don't write to the DB here so this stays pure.
    """
    out = []
    for lm in landmarks:
        out.append({
            "branch_id": branch_id,
            "type": "location",
            "name": lm["name"],
            "summary": lm.get("note") or "",
            "attributes": {"landmark_kind": lm.get("kind", "landmark")},
            "state": {},
            "map_x": int(lm["x"]),
            "map_y": int(lm["y"]),
            "alive": 1,
        })
    return out


def coerce_landmark_into_terrain(
    data: dict,
    lm: dict,
    *,
    require_land: bool = True,
) -> Optional[tuple[int, int]]:
    """If a landmark sits on impassable/wrong terrain, nudge it to the nearest
    passable tile within a small search radius. Returns (x, y) or None if
    no fix is possible within the radius.

    For now this only ensures land-vs-water for non-harbor landmarks, since
    the LLM was already told the rules; this is a safety net, not a
    primary placement engine.
    """
    eff = worldgen.effective_terrain(data)
    h, w = eff.shape
    x0, y0 = int(lm["x"]), int(lm["y"])
    if not (0 <= x0 < w and 0 <= y0 < h):
        return None

    kind = (lm.get("kind") or "").lower()
    water_kinds = {"harbor", "river_mouth", "lake", "bridge"}
    wants_water = kind in water_kinds

    def good(cell: int) -> bool:
        is_water = cell in (worldgen.TERRAIN_DEEP_OCEAN,
                            worldgen.TERRAIN_OCEAN,
                            worldgen.TERRAIN_COAST)
        if wants_water:
            return is_water or cell == worldgen.TERRAIN_BEACH
        if require_land and is_water:
            return False
        return True

    if good(int(eff[y0, x0])):
        return x0, y0

    # spiral search up to radius 4
    for r in range(1, 5):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if abs(dx) != r and abs(dy) != r:
                    continue
                nx, ny = x0 + dx, y0 + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if good(int(eff[ny, nx])):
                    return nx, ny
    return None
