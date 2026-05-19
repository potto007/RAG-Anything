from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphLabelsResponse(BaseModel):
    labels: list[str]


class GraphNode(BaseModel):
    id: str
    labels: list[str]
    properties: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    type: str | None
    source: str
    target: str
    properties: dict[str, Any]


class KnowledgeGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    is_truncated: bool


class DeleteEntityRequest(BaseModel):
    entity_name: str


class DeleteRelationRequest(BaseModel):
    source_entity: str
    target_entity: str


class MergeEntitiesRequest(BaseModel):
    source_entities: list[str] = Field(..., min_length=1)
    target_entity: str
    merge_strategy: dict[str, str] | None = None
    target_entity_data: dict[str, Any] | None = None


class DeletionResponse(BaseModel):
    status: str
    message: str


class MergeEntitiesResponse(BaseModel):
    status: str
    message: str
    entity: dict[str, Any] | None = None
