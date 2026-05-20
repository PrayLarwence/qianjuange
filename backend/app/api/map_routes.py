"""Map / worldgen API.

Endpoints:
  POST  /api/worlds/{world_id}/map/generate     run worldgen, persist
  GET   /api/worlds/{world_id}/map              meta info (no array data)
  GET   /api/worlds/{world_id}/map/render.png   rendered layer image
  GET   /api/worlds/{world_id}/map/tile         single tile inspect
  POST  /api/worlds/{world_id}/map/paint        brush paint terrain overlay
  POST  /api/worlds/{world_id}/map/clear_overlay   reset all painted tiles
  GET   /api/worlds/{world_id}/map/pinned       entities with map coords
  POST  /api/worlds/{world_id}/map/pin          set entity (x,y)
  DELETE /api/worlds/{world_id}/map             drop the npz file
"""

from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..engine import worldgen
from ..engine import map_sim
from ..engine import blueprint as bp_engine
from ..engine import blueprint_render as bp_render
from ..engine.executor import active_branch_id, _new_id
from ..models import get_db, World, Entity
from ..providers import get_provider

log = logging.getLogger(__name__)
router = APIRouter(prefix="/worlds/{world_id}/map", tags=["map"])


class GenerateRequest(BaseModel):
    width: int = 512
    height: int = 384
    seed: int = 0
    sea_level: float = Field(0.42, ge=0.05, le=0.95)
    octaves: int = Field(6, ge=1, le=8)
    persistence: float = Field(0.55, ge=0.2, le=0.9)
    base_freq: float = Field(2.5, ge=0.5, le=8.0)
    warp: float = Field(0.12, ge=0.0, le=0.4)


def _world_or_404(db: Session, world_id: str) -> World:
    w = db.query(World).filter_by(id=world_id).first()
    if not w:
        raise HTTPException(404, "world not found")
    return w


@router.post("/generate")
def generate_map(world_id: str, payload: GenerateRequest, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    if payload.width * payload.height > 4_000_000:
        raise HTTPException(400, "map too large (max 4M tiles)")
    params = worldgen.WorldGenParams(
        width=payload.width,
        height=payload.height,
        seed=payload.seed,
        sea_level=payload.sea_level,
        octaves=payload.octaves,
        persistence=payload.persistence,
        base_freq=payload.base_freq,
        warp=payload.warp,
    )
    data = worldgen.generate(params)
    worldgen.save(world_id, data)

    world.map_w = payload.width
    world.map_h = payload.height
    world.map_seed = payload.seed
    world.map_meta = {
        "sea_level": payload.sea_level,
        "sea_h": data["sea_h"],
        "octaves": payload.octaves,
        "persistence": payload.persistence,
        "base_freq": payload.base_freq,
        "warp": payload.warp,
    }
    db.commit()

    import numpy as np
    biome_counts = {}
    for c in np.unique(data["biome"]):
        biome_counts[int(c)] = int((data["biome"] == c).sum())

    return {
        "ok": True,
        "width": payload.width,
        "height": payload.height,
        "seed": payload.seed,
        "sea_h": data["sea_h"],
        "biome_counts": biome_counts,
    }


class BlueprintRequest(BaseModel):
    width: int = 80
    height: int = 60
    extra_directive: str | None = None
    provider: str | None = None


@router.post("/blueprint")
def make_blueprint(world_id: str, payload: BlueprintRequest, db: Session = Depends(get_db)):
    """Generate a structured map blueprint from world.outline + description.

    Pure planning step — does NOT yet render the map. Use POST /map/generate_from_blueprint
    (stage 4C) to actually render once the blueprint looks good.
    """
    world = _world_or_404(db, world_id)
    if not (world.outline or world.description):
        raise HTTPException(400, "world has no outline or description for the LLM to work from")
    if payload.width * payload.height > 4_000_000:
        raise HTTPException(400, "map too large (max 4M tiles)")
    try:
        provider = get_provider(payload.provider)
    except Exception as e:
        raise HTTPException(503, f"no LLM provider available: {e}")
    bp = bp_engine.generate_blueprint(
        db, world, payload.width, payload.height,
        provider=provider, extra_directive=payload.extra_directive,
    )
    return bp


class GenerateFromBlueprintRequest(BaseModel):
    width: int = 80
    height: int = 60
    seed: int = 0
    sea_level: float = Field(0.42, ge=0.05, le=0.95)
    octaves: int = Field(6, ge=1, le=8)
    persistence: float = Field(0.55, ge=0.2, le=0.9)
    base_freq: float = Field(2.5, ge=0.5, le=8.0)
    warp: float = Field(0.12, ge=0.0, le=0.4)
    blueprint: dict  # {regions: [...], landmarks: [...]}
    create_landmark_entities: bool = True
    replace_existing_landmarks: bool = False  # purge previous auto-landmarks first


@router.post("/generate_from_blueprint")
def generate_from_blueprint(world_id: str, payload: GenerateFromBlueprintRequest, db: Session = Depends(get_db)):
    """Render a noise basemap, stamp blueprint regions onto its overlay, and
    materialize blueprint landmarks as location entities pinned to the map.
    """
    world = _world_or_404(db, world_id)
    if payload.width * payload.height > 4_000_000:
        raise HTTPException(400, "map too large (max 4M tiles)")

    bp = payload.blueprint or {}
    regions = bp.get("regions") or []
    landmarks = bp.get("landmarks") or []

    # 1. base noise map
    params = worldgen.WorldGenParams(
        width=payload.width, height=payload.height, seed=payload.seed,
        sea_level=payload.sea_level, octaves=payload.octaves,
        persistence=payload.persistence, base_freq=payload.base_freq,
        warp=payload.warp,
    )
    data = worldgen.generate(params)

    # 2. stamp blueprint regions into overlay
    paint_stats = bp_render.apply_blueprint_to_overlay(data, regions)

    # 3. persist npz
    worldgen.save(world_id, data)
    world.map_w = payload.width
    world.map_h = payload.height
    world.map_seed = payload.seed
    world.map_meta = {
        "sea_level": payload.sea_level,
        "sea_h": data["sea_h"],
        "octaves": payload.octaves,
        "persistence": payload.persistence,
        "base_freq": payload.base_freq,
        "warp": payload.warp,
        "from_blueprint": True,
        "blueprint_regions": len(regions),
        "blueprint_landmarks": len(landmarks),
    }

    # 4. landmarks → location entities
    bid = active_branch_id(world)
    created_entities: list[dict] = []
    skipped: list[dict] = []
    if payload.create_landmark_entities and landmarks:
        if payload.replace_existing_landmarks:
            (db.query(Entity)
                .filter(Entity.branch_id == bid, Entity.type == "location")
                .filter(Entity.attributes.isnot(None))
                .delete(synchronize_session=False))
        for lm in landmarks:
            fixed = bp_render.coerce_landmark_into_terrain(data, lm)
            if fixed is None:
                skipped.append({"name": lm.get("name"), "reason": "no passable tile near requested coords"})
                continue
            x, y = fixed
            ent = Entity(
                id=_new_id("ent"),
                branch_id=bid,
                type="location",
                name=lm["name"],
                summary=lm.get("note") or "",
                attributes={"landmark_kind": lm.get("kind", "landmark"), "from_blueprint": True},
                state={},
                map_x=x, map_y=y,
                created_at_tick=world.current_tick,
                alive=1,
            )
            db.add(ent)
            created_entities.append({"name": lm["name"], "x": x, "y": y, "kind": lm.get("kind")})

    db.commit()

    return {
        "ok": True,
        "width": payload.width, "height": payload.height, "seed": payload.seed,
        "sea_h": data["sea_h"],
        "regions_painted": len(regions),
        "painted_tiles": paint_stats["painted_tiles"],
        "by_terrain": paint_stats["by_terrain"],
        "landmarks_created": created_entities,
        "landmarks_skipped": skipped,
    }


@router.get("")
def get_map_meta(world_id: str, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    has = worldgen.map_path(world_id).exists()
    return {
        "exists": has,
        "width": world.map_w or 0,
        "height": world.map_h or 0,
        "seed": world.map_seed or 0,
        "meta": world.map_meta or {},
        "biomes": {
            str(k): {"label": v, "color": worldgen.BIOME_COLORS.get(k, (128, 128, 128))}
            for k, v in worldgen.BIOME_LABELS.items()
        },
        "terrains": {str(k): v for k, v in worldgen.TERRAIN_LABELS.items()},
    }


@router.get("/render.png")
def render_map_png(
    world_id: str,
    layer: str = Query("biome", pattern="^(biome|terrain|height|temp|moist)$"),
    db: Session = Depends(get_db),
):
    _world_or_404(db, world_id)
    data = worldgen.load(world_id)
    if data is None:
        raise HTTPException(404, "map not generated yet")
    png = worldgen.render_png_bytes(data, layer)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/tile")
def inspect_tile(
    world_id: str,
    x: int = Query(...),
    y: int = Query(...),
    db: Session = Depends(get_db),
):
    _world_or_404(db, world_id)
    data = worldgen.load(world_id)
    if data is None:
        raise HTTPException(404, "map not generated yet")
    info = worldgen.tile_info(data, x, y)
    if not info:
        raise HTTPException(400, "out of bounds")
    return info


@router.delete("")
def drop_map(world_id: str, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    deleted = worldgen.delete(world_id)
    world.map_w = 0
    world.map_h = 0
    world.map_seed = 0
    world.map_meta = {}
    db.commit()
    return {"ok": True, "removed": deleted}


@router.post("/import_heightmap")
async def import_heightmap(
    world_id: str,
    file: UploadFile = File(...),
    width: int = Form(512),
    height: int = Form(384),
    sea_level: float = Form(0.42),
    invert: bool = Form(False),
    blur: float = Form(0.6),
    contrast: float = Form(1.0),
    seed: int = Form(0),
    db: Session = Depends(get_db),
):
    """Import a grayscale image as a heightmap (stage 2A).

    The image is resampled to (width x height), optionally inverted/blurred,
    then fed through the standard worldgen pipeline so downstream the result
    is indistinguishable from a generated world.
    """
    world = _world_or_404(db, world_id)
    if width * height > 4_000_000:
        raise HTTPException(400, "map too large (max 4M tiles)")
    if not (0.05 <= sea_level <= 0.95):
        raise HTTPException(400, "sea_level out of range")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 50MB)")

    try:
        params = worldgen.HeightmapImportParams(
            width=width, height=height, sea_level=sea_level,
            invert=invert, blur=blur, contrast=contrast, seed=seed,
        )
        data = worldgen.import_from_heightmap(raw, params)
    except Exception as e:
        log.exception("heightmap import failed for world %s", world_id)
        raise HTTPException(400, f"failed to decode image: {e}")

    worldgen.save(world_id, data)

    world.map_w = width
    world.map_h = height
    world.map_seed = seed
    world.map_meta = {
        "source": "heightmap_import",
        "filename": file.filename or "",
        "sea_level": sea_level,
        "sea_h": data["sea_h"],
        "invert": invert,
        "blur": blur,
        "contrast": contrast,
    }
    db.commit()

    import numpy as np
    biome_counts = {}
    for c in np.unique(data["biome"]):
        biome_counts[int(c)] = int((data["biome"] == c).sum())

    return {
        "ok": True,
        "width": width,
        "height": height,
        "sea_h": data["sea_h"],
        "biome_counts": biome_counts,
        "source": "heightmap_import",
    }


# ---------- terrain overlay paint ----------

class PaintStroke(BaseModel):
    x: int
    y: int
    terrain: int = Field(..., description="terrain code, or -1 to erase overlay")
    brush: int = Field(2, ge=1, le=64)


class PaintBatch(BaseModel):
    strokes: list[PaintStroke]


@router.post("/paint")
def paint_terrain(world_id: str, payload: PaintBatch, db: Session = Depends(get_db)):
    _world_or_404(db, world_id)
    data = worldgen.load(world_id)
    if data is None:
        raise HTTPException(404, "map not generated yet")
    total = 0
    for s in payload.strokes:
        total += worldgen.paint(data, s.x, s.y, s.terrain, s.brush)
    worldgen.save(world_id, data)
    return {"ok": True, "painted": total}


@router.post("/clear_overlay")
def clear_overlay(world_id: str, db: Session = Depends(get_db)):
    _world_or_404(db, world_id)
    data = worldgen.load(world_id)
    if data is None:
        raise HTTPException(404, "map not generated yet")
    n = worldgen.clear_overlay(data)
    worldgen.save(world_id, data)
    return {"ok": True, "cleared": n}


# ---------- entity pinning ----------

class PinRequest(BaseModel):
    entity_id: str
    x: int | None = None
    y: int | None = None


@router.get("/pinned")
def list_pinned(world_id: str, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    bid = active_branch_id(world)
    entities = (
        db.query(Entity)
        .filter(Entity.branch_id == bid, Entity.alive == 1)
        .filter(Entity.map_x.isnot(None), Entity.map_y.isnot(None))
        .all()
    )
    return {
        "items": [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "x": e.map_x,
                "y": e.map_y,
            }
            for e in entities
        ]
    }


@router.post("/pin")
def pin_entity(world_id: str, payload: PinRequest, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    e = db.query(Entity).filter_by(id=payload.entity_id).first()
    if not e or e.branch_id != active_branch_id(world):
        raise HTTPException(404, "entity not in this world's active branch")
    if payload.x is None or payload.y is None:
        e.map_x = None
        e.map_y = None
    else:
        if world.map_w and world.map_h:
            if not (0 <= payload.x < world.map_w and 0 <= payload.y < world.map_h):
                raise HTTPException(400, "coordinates out of map bounds")
        e.map_x = int(payload.x)
        e.map_y = int(payload.y)
    db.commit()
    return {"ok": True, "id": e.id, "x": e.map_x, "y": e.map_y}


# ---------- simulation (stage 3A) ----------

class GotoRequest(BaseModel):
    x: int
    y: int
    speed: float | None = None


class SimTickRequest(BaseModel):
    ticks: int = Field(1, ge=1, le=1000)


@router.post("/entity/{entity_id}/goto")
def entity_goto(world_id: str, entity_id: str, payload: GotoRequest, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    e = db.query(Entity).filter_by(id=entity_id).first()
    if not e or e.branch_id != active_branch_id(world):
        raise HTTPException(404, "entity not in this world's active branch")
    if e.map_x is None or e.map_y is None:
        raise HTTPException(400, "entity is not pinned on the map yet")
    if world.map_w and world.map_h:
        if not (0 <= payload.x < world.map_w and 0 <= payload.y < world.map_h):
            raise HTTPException(400, "target out of map bounds")
    map_sim.set_target(e, payload.x, payload.y)
    if payload.speed is not None:
        e.move_speed = max(0.1, min(8.0, float(payload.speed)))
    db.commit()
    return {
        "ok": True, "id": e.id,
        "from": [e.map_x, e.map_y],
        "target": [e.target_x, e.target_y],
        "speed": e.move_speed,
    }


@router.post("/entity/{entity_id}/halt")
def entity_halt(world_id: str, entity_id: str, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    e = db.query(Entity).filter_by(id=entity_id).first()
    if not e or e.branch_id != active_branch_id(world):
        raise HTTPException(404, "entity not in this world's active branch")
    map_sim.set_target(e, None, None)
    db.commit()
    return {"ok": True, "id": e.id}


@router.post("/sim/tick")
def sim_tick(world_id: str, payload: SimTickRequest, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    if not worldgen.map_path(world_id).exists():
        raise HTTPException(404, "map not generated yet")
    return map_sim.sim_tick(db, world, n=payload.ticks)


@router.get("/sim/status")
def sim_status(world_id: str, db: Session = Depends(get_db)):
    world = _world_or_404(db, world_id)
    bid = active_branch_id(world)
    entities = (
        db.query(Entity)
        .filter(Entity.branch_id == bid, Entity.alive == 1)
        .filter(Entity.map_x.isnot(None), Entity.map_y.isnot(None))
        .all()
    )
    return {
        "items": [
            {
                "id": e.id, "name": e.name, "type": e.type,
                "x": e.map_x, "y": e.map_y,
                "target_x": e.target_x, "target_y": e.target_y,
                "speed": e.move_speed,
                "status": (e.sim_state or {}).get("status", "idle"),
                "blocked_reason": (e.sim_state or {}).get("blocked_reason"),
            }
            for e in entities
        ],
    }
