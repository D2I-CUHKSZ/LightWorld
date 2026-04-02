"""Compile an explicit agent-agent social relation graph.

This module fills the gap between:
semantic graph -> simulated agents -> runtime topology graph

It materializes a directed social relation graph with explicit edge weights so
later runtime stages can use a stable prior instead of only implicit pairwise
similarity.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


class SocialRelationGraphCompiler:
    """Compile explicit social relation weights from graph snapshot edges."""

    _FOLLOW_KEYWORDS = ("follow", "关注", "subscriber", "follower")
    _AMPLIFY_KEYWORDS = ("repost", "retweet", "quote", "转发", "引用", "share", "amplif")
    _TRUST_KEYWORDS = ("trust", "endorse", "support", "approve", "信任", "支持", "背书")
    _ALLY_KEYWORDS = (
        "ally",
        "alliance",
        "coalition",
        "cooperate",
        "collaborate",
        "partner",
        "friend",
        "联盟",
        "合作",
        "伙伴",
    )
    _HOSTILE_KEYWORDS = (
        "oppose",
        "conflict",
        "attack",
        "criticize",
        "dispute",
        "block",
        "mute",
        "反对",
        "冲突",
        "攻击",
        "批评",
        "屏蔽",
    )
    _WEAK_EXPOSURE_KEYWORDS = ("mention", "report", "comment", "reply", "提及", "报道", "评论", "回应")

    def _edge_metrics(self, edge_name: str, fact: str) -> Dict[str, float]:
        text = f"{edge_name} {fact}".lower()

        exposure = 0.10
        trust = 0.0
        hostility = 0.0
        alliance = 0.0

        if any(k in text for k in self._FOLLOW_KEYWORDS):
            exposure += 0.60
            trust += 0.10

        if any(k in text for k in self._AMPLIFY_KEYWORDS):
            exposure += 0.55
            trust += 0.20

        if any(k in text for k in self._TRUST_KEYWORDS):
            exposure += 0.12
            trust += 0.55

        if any(k in text for k in self._ALLY_KEYWORDS):
            exposure += 0.10
            alliance += 0.65
            trust += 0.15

        if any(k in text for k in self._HOSTILE_KEYWORDS):
            hostility += 0.75
            exposure += 0.08

        if any(k in text for k in self._WEAK_EXPOSURE_KEYWORDS):
            exposure += 0.25

        exposure = _clamp(exposure, 0.0, 1.0)
        trust = _clamp(trust, 0.0, 1.0)
        hostility = _clamp(hostility, 0.0, 1.0)
        alliance = _clamp(alliance, 0.0, 1.0)

        interaction_prior = (
            0.35 * exposure
            + 0.30 * trust
            + 0.25 * alliance
            - 0.45 * hostility
        )
        interaction_prior = _clamp(interaction_prior, -1.0, 1.0)

        return {
            "exposure_weight": round(exposure, 4),
            "trust_weight": round(trust, 4),
            "hostility_weight": round(hostility, 4),
            "alliance_weight": round(alliance, 4),
            "interaction_prior": round(interaction_prior, 4),
        }

    def compile(
        self,
        graph_snapshot_path: str,
        agent_configs: List[Any],
        simulation_id: str,
        graph_id: str,
    ) -> Dict[str, Any]:
        with open(graph_snapshot_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        raw_edges = snapshot.get("edges", []) if isinstance(snapshot, dict) else []
        if not isinstance(raw_edges, list):
            raw_edges = []

        agent_nodes: List[Dict[str, Any]] = []
        uuid_to_agent: Dict[str, Dict[str, Any]] = {}
        for item in agent_configs:
            if hasattr(item, "__dict__"):
                row = dict(item.__dict__)
            else:
                row = dict(item)

            agent_id = _safe_int(row.get("agent_id"), -1)
            entity_uuid = str(row.get("entity_uuid", "") or "").strip()
            if agent_id < 0 or not entity_uuid:
                continue

            node = {
                "agent_id": agent_id,
                "entity_uuid": entity_uuid,
                "entity_name": str(row.get("entity_name", "") or ""),
                "entity_type": str(row.get("entity_type", "") or ""),
            }
            agent_nodes.append(node)
            uuid_to_agent[entity_uuid.lower()] = node

        aggregated: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue

            src_uuid = str(edge.get("source_node_uuid", "") or "").strip().lower()
            dst_uuid = str(edge.get("target_node_uuid", "") or "").strip().lower()
            if not src_uuid or not dst_uuid:
                continue

            src_agent = uuid_to_agent.get(src_uuid)
            dst_agent = uuid_to_agent.get(dst_uuid)
            if not src_agent or not dst_agent:
                continue
            if src_agent["agent_id"] == dst_agent["agent_id"]:
                continue

            metrics = self._edge_metrics(
                str(edge.get("name", "") or ""),
                str(edge.get("fact", "") or ""),
            )
            key = (src_agent["agent_id"], dst_agent["agent_id"])

            payload = aggregated.setdefault(
                key,
                {
                    "source_agent_id": src_agent["agent_id"],
                    "target_agent_id": dst_agent["agent_id"],
                    "source_entity_uuid": src_agent["entity_uuid"],
                    "target_entity_uuid": dst_agent["entity_uuid"],
                    "source_entity_name": src_agent["entity_name"],
                    "target_entity_name": dst_agent["entity_name"],
                    "facts": [],
                    "relation_names": [],
                    "exposure_weight": 0.0,
                    "trust_weight": 0.0,
                    "hostility_weight": 0.0,
                    "alliance_weight": 0.0,
                    "interaction_prior": -1.0,
                },
            )

            fact = str(edge.get("fact", "") or "").strip()
            relation_name = str(edge.get("name", "") or "").strip()
            if fact and fact not in payload["facts"]:
                payload["facts"].append(fact)
            if relation_name and relation_name not in payload["relation_names"]:
                payload["relation_names"].append(relation_name)

            payload["exposure_weight"] = max(payload["exposure_weight"], metrics["exposure_weight"])
            payload["trust_weight"] = max(payload["trust_weight"], metrics["trust_weight"])
            payload["hostility_weight"] = max(payload["hostility_weight"], metrics["hostility_weight"])
            payload["alliance_weight"] = max(payload["alliance_weight"], metrics["alliance_weight"])

        edges: List[Dict[str, Any]] = []
        for payload in aggregated.values():
            interaction_prior = (
                0.35 * payload["exposure_weight"]
                + 0.30 * payload["trust_weight"]
                + 0.25 * payload["alliance_weight"]
                - 0.45 * payload["hostility_weight"]
            )
            payload["interaction_prior"] = round(_clamp(interaction_prior, -1.0, 1.0), 4)
            payload["relation_fact"] = " | ".join(payload["facts"][:5])
            payload["relation_name"] = ",".join(payload["relation_names"][:4])
            edges.append(payload)

        edges.sort(
            key=lambda row: (
                -abs(float(row.get("interaction_prior", 0.0))),
                -float(row.get("exposure_weight", 0.0)),
                row.get("source_agent_id", 0),
                row.get("target_agent_id", 0),
            )
        )

        return {
            "simulation_id": simulation_id,
            "graph_id": graph_id,
            "generated_at": datetime.now().isoformat(),
            "node_count": len(agent_nodes),
            "edge_count": len(edges),
            "nodes": sorted(agent_nodes, key=lambda row: row["agent_id"]),
            "edges": edges,
        }

    def save(self, payload: Dict[str, Any], file_path: str) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
