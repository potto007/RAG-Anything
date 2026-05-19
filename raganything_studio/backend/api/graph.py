from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from raganything_studio.backend.core.errors import api_error
from raganything_studio.backend.core.settings_store import SettingsStore
from raganything_studio.backend.dependencies import get_rag_service, get_settings_store, settings as studio_settings
from raganything_studio.backend.schemas.graph import (
    DeleteEntityRequest,
    DeleteRelationRequest,
    DeletionResponse,
    GraphLabelsResponse,
    KnowledgeGraphResponse,
    MergeEntitiesRequest,
    MergeEntitiesResponse,
)
from raganything_studio.backend.services.raganything_service import RAGAnythingService

router = APIRouter()

_IMG_PATH_RE = re.compile(r"'img_path':\s*'([^']+\.(png|jpg|jpeg|webp|gif))'", re.IGNORECASE)
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _dump_model(model: object) -> dict:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump()
    legacy_dump = getattr(model, "dict", None)
    if callable(legacy_dump):
        return legacy_dump()
    return dict(model)  # type: ignore[arg-type]


def _serialize_kg(kg: object) -> KnowledgeGraphResponse:
    return KnowledgeGraphResponse(
        nodes=[
            {"id": n.id, "labels": n.labels, "properties": n.properties}
            for n in getattr(kg, "nodes", [])
        ],
        edges=[
            {
                "id": e.id,
                "type": e.type,
                "source": e.source,
                "target": e.target,
                "properties": e.properties,
            }
            for e in getattr(kg, "edges", [])
        ],
        is_truncated=bool(getattr(kg, "is_truncated", False)),
    )


async def _get_overview_graph(lightrag: object, max_nodes: int) -> KnowledgeGraphResponse:
    labels = await lightrag.get_graph_labels()
    label_list = list(labels) if labels else []
    if not label_list:
        return KnowledgeGraphResponse(nodes=[], edges=[], is_truncated=False)

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    is_truncated = len(label_list) > max_nodes

    for label in label_list[: min(len(label_list), 8)]:
        if len(nodes) >= max_nodes:
            is_truncated = True
            break
        kg = await lightrag.get_knowledge_graph(
            node_label=label,
            max_depth=1,
            max_nodes=max(1, max_nodes - len(nodes)),
        )
        serialized = _serialize_kg(kg)
        is_truncated = is_truncated or serialized.is_truncated
        for node in serialized.nodes:
            if len(nodes) >= max_nodes and node.id not in nodes:
                is_truncated = True
                continue
            nodes[node.id] = _dump_model(node)
        for edge in serialized.edges:
            if edge.source in nodes and edge.target in nodes:
                edges[edge.id] = _dump_model(edge)

    if not nodes:
        for label in label_list[:max_nodes]:
            nodes[label] = {"id": label, "labels": [label], "properties": {}}

    return KnowledgeGraphResponse(
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        is_truncated=is_truncated,
    )


@router.get("/labels", response_model=GraphLabelsResponse)
async def get_graph_labels(
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> GraphLabelsResponse:
    settings = settings_store.get()
    try:
        rag = await rag_service.get_rag(profile_id=profile_id or settings.active_profile_id)
        initializer = getattr(rag, "_ensure_lightrag_initialized", None)
        if callable(initializer):
            await initializer()
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None:
            return GraphLabelsResponse(labels=[])
        labels = await lightrag.get_graph_labels()
        return GraphLabelsResponse(labels=list(labels) if labels else [])
    except Exception as exc:
        raise api_error(
            "GRAPH_FETCH_FAILED",
            f"Failed to fetch graph labels: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.get("/subgraph", response_model=KnowledgeGraphResponse)
async def get_subgraph(
    node_label: str | None = Query(default=None),
    max_depth: int = Query(default=3, ge=1, le=6),
    max_nodes: int = Query(default=150, ge=1, le=1000),
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> KnowledgeGraphResponse:
    settings = settings_store.get()
    try:
        rag = await rag_service.get_rag(profile_id=profile_id or settings.active_profile_id)
        initializer = getattr(rag, "_ensure_lightrag_initialized", None)
        if callable(initializer):
            await initializer()
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None:
            return KnowledgeGraphResponse(nodes=[], edges=[], is_truncated=False)
        if not node_label:
            return await _get_overview_graph(lightrag, max_nodes=max_nodes)
        kg = await lightrag.get_knowledge_graph(
            node_label=node_label,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        return _serialize_kg(kg)
    except Exception as exc:
        raise api_error(
            "GRAPH_FETCH_FAILED",
            f"Failed to fetch knowledge graph: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


async def _get_lightrag(
    rag_service: RAGAnythingService,
    settings_store: SettingsStore,
    profile_id: str | None = None,
) -> object:
    settings = settings_store.get()
    rag = await rag_service.get_rag(profile_id=profile_id or settings.active_profile_id)
    initializer = getattr(rag, "_ensure_lightrag_initialized", None)
    if callable(initializer):
        await initializer()
    lightrag = getattr(rag, "lightrag", None)
    if lightrag is None:
        raise api_error(
            "GRAPH_NOT_AVAILABLE",
            "LightRAG instance is not available",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return lightrag


@router.post("/entities/delete", response_model=DeletionResponse)
async def delete_entity(
    request: DeleteEntityRequest,
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> DeletionResponse:
    try:
        lightrag = await _get_lightrag(rag_service, settings_store, profile_id)
        result = await lightrag.adelete_by_entity(request.entity_name)
        return DeletionResponse(
            status=result.status,
            message=result.message,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise api_error(
            "DELETE_ENTITY_FAILED",
            f"Failed to delete entity: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.post("/relations/delete", response_model=DeletionResponse)
async def delete_relation(
    request: DeleteRelationRequest,
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> DeletionResponse:
    try:
        lightrag = await _get_lightrag(rag_service, settings_store, profile_id)
        result = await lightrag.adelete_by_relation(
            request.source_entity, request.target_entity
        )
        return DeletionResponse(
            status=result.status,
            message=result.message,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise api_error(
            "DELETE_RELATION_FAILED",
            f"Failed to delete relation: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.post("/entities/merge", response_model=MergeEntitiesResponse)
async def merge_entities(
    request: MergeEntitiesRequest,
    profile_id: str | None = Query(default=None),
    rag_service: RAGAnythingService = Depends(get_rag_service),
    settings_store: SettingsStore = Depends(get_settings_store),
) -> MergeEntitiesResponse:
    try:
        lightrag = await _get_lightrag(rag_service, settings_store, profile_id)
        result = await lightrag.amerge_entities(
            source_entities=request.source_entities,
            target_entity=request.target_entity,
            merge_strategy=request.merge_strategy,
            target_entity_data=request.target_entity_data,
        )
        return MergeEntitiesResponse(
            status="success",
            message=f"Merged {len(request.source_entities)} entities into '{request.target_entity}'",
            entity=result,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise api_error(
            "MERGE_ENTITIES_FAILED",
            f"Failed to merge entities: {exc}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


@router.get("/node-media/{node_id:path}")
async def get_node_media(
    node_id: str,
    source_id: str | None = Query(default=None),
) -> FileResponse:
    """Return the image file for an image-type graph node.

    Uses source_id (chunk key) for direct O(1) lookup when provided;
    falls back to scanning all chunks by node_id substring when absent.
    """
    chunks_file = studio_settings.data_dir / "rag_storage" / "kv_store_text_chunks.json"
    if not chunks_file.exists():
        raise HTTPException(status_code=404, detail="Chunk store not found")

    with chunks_file.open() as f:
        chunks: dict = json.load(f)

    img_path: Path | None = None

    def _extract_img_path(chunk: dict) -> Path | None:
        content = chunk.get("content", "")
        m = _IMG_PATH_RE.search(content)
        return Path(m.group(1)) if m else None

    if source_id and source_id in chunks:
        img_path = _extract_img_path(chunks[source_id])
    else:
        # Fallback: find first image chunk whose img_path filename appears in node_id,
        # or simply return the first available image chunk as a best-effort preview.
        first_image: Path | None = None
        for chunk in chunks.values():
            candidate = _extract_img_path(chunk)
            if candidate is None:
                continue
            if first_image is None:
                first_image = candidate
            if candidate.stem in node_id or node_id in candidate.stem:
                img_path = candidate
                break
        if img_path is None:
            img_path = first_image

    if img_path is None:
        raise HTTPException(status_code=404, detail="No image found for this node")

    # Security: path must be inside data_dir
    try:
        img_path.resolve().relative_to(studio_settings.data_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if img_path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=403, detail="File type not allowed")

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    return FileResponse(img_path, media_type=f"image/{img_path.suffix.lstrip('.').lower()}")
