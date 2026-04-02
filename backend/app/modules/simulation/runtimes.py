"""Simulation runtimes (Strategy-style components).

Extracted from run_parallel_simulation.py to keep entry script thin and maintainable.
"""

import ast
import csv
import json
import math
import os
import random
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


class TopologyAwareRuntime:
    """
    TopoSim-lite 运行时：
    1) Coordination: 结构相似 + 状态相近的 Agent 进行单元级激活，降低冗余推理
    2) Differentiation: 使用拓扑重要性调制激活概率，恢复非对称影响
    """

    def __init__(
        self,
        config: Dict[str, Any],
        simulation_dir: str,
        platform: str,
        logger: Optional[Callable[[str], None]] = None
    ):
        self.config = config
        self.simulation_dir = simulation_dir
        self.platform = platform
        self.log = logger or (lambda _: None)

        topo_cfg = config.get("topology_aware", {}) or {}
        light_cfg = config.get("light_mode", {}) or {}

        self.enabled = bool(topo_cfg.get("enabled", False))
        self.coordination_enabled = bool(topo_cfg.get("coordination_enabled", True))
        self.differentiation_enabled = bool(topo_cfg.get("differentiation_enabled", True))
        self.similarity_threshold = _safe_float(topo_cfg.get("similarity_threshold", 0.92), 0.92)
        self.min_unit_size = max(2, int(topo_cfg.get("min_unit_size", 2)))
        self.extra_member_prob = min(1.0, max(0.0, _safe_float(topo_cfg.get("extra_member_prob", 0.12), 0.12)))
        self.importance_alpha = max(0.0, _safe_float(topo_cfg.get("importance_alpha", 0.7), 0.7))
        self.sentiment_diff_threshold = _safe_float(topo_cfg.get("sentiment_diff_threshold", 0.35), 0.35)

        # 参考 struc2vec_cluster/test/cluster.py 的聚类阈值
        self.opinion_threshold = _safe_float(topo_cfg.get("opinion_threshold", 0.5), 0.5)
        self.stubbornness_threshold = _safe_float(topo_cfg.get("stubbornness_threshold", 0.5), 0.5)
        self.influence_threshold = _safe_float(topo_cfg.get("influence_threshold", 0.5), 0.5)
        self.top_pairs_ratio = min(1.0, max(0.001, _safe_float(topo_cfg.get("top_pairs_ratio", 0.02), 0.02)))
        self.ppr_alpha = min(0.99, max(0.01, _safe_float(topo_cfg.get("ppr_alpha", 0.85), 0.85)))
        self.ppr_eps = max(1e-8, _safe_float(topo_cfg.get("ppr_eps", 1e-4), 1e-4))
        self.semantic_threshold = min(1.0, max(0.0, _safe_float(topo_cfg.get("semantic_threshold", 0.1), 0.1)))
        self.keyword_jaccard_threshold = min(
            1.0, max(0.0, _safe_float(topo_cfg.get("keyword_jaccard_threshold", 0.12), 0.12))
        )
        self.keyword_overlap_min = max(0, int(topo_cfg.get("keyword_overlap_min", 1)))
        self.graph_prior_similarity_boost = min(
            0.8, max(0.0, _safe_float(topo_cfg.get("graph_prior_similarity_boost", 0.35), 0.35))
        )
        self.graph_prior_extra_ratio = min(
            1.0, max(0.0, _safe_float(topo_cfg.get("graph_prior_extra_ratio", 0.25), 0.25))
        )
        self.dynamic_update_enabled = bool(topo_cfg.get("dynamic_update_enabled", True))
        self.dynamic_update_interval = max(1, int(topo_cfg.get("dynamic_update_interval", 4)))
        self.dynamic_update_min_events = max(1, int(topo_cfg.get("dynamic_update_min_events", 6)))
        self.dynamic_interaction_min_weight = max(
            0.05, _safe_float(topo_cfg.get("dynamic_interaction_min_weight", 0.25), 0.25)
        )
        self.dynamic_neighbors_per_agent = max(1, int(topo_cfg.get("dynamic_neighbors_per_agent", 6)))
        self.initial_follow_max_per_agent = max(1, int(topo_cfg.get("initial_follow_max_per_agent", 3)))
        self.initial_follow_max_total = max(0, int(topo_cfg.get("initial_follow_max_total", 0)))

        self.light_enabled = bool(light_cfg.get("enabled", False))
        self.light_agent_ratio = min(1.0, max(0.1, _safe_float(light_cfg.get("agent_ratio", 0.6), 0.6)))

        # light 模式默认启用 topology-aware（除非显式关闭）
        if self.light_enabled and "enabled" not in topo_cfg:
            self.enabled = True

        self.agent_cfg_by_id: Dict[int, Dict[str, Any]] = {}
        self.profile_by_agent_id: Dict[int, Dict[str, Any]] = {}
        self.importance_raw: Dict[int, float] = {}
        self.importance_scaled: Dict[int, float] = {}
        self.structure_vec: Dict[int, List[float]] = {}
        self.opinion_by_agent: Dict[int, float] = {}
        self.stubbornness_by_agent: Dict[int, float] = {}
        self.synthetic_adj: Dict[int, List[int]] = {}
        self.top_pair_records: List[Tuple[int, int, float]] = []
        self.top_pairs: set = set()
        self.neighbor_influence: Dict[int, float] = {}
        self.ppr_scores: Dict[int, Dict[int, float]] = {}
        self.ppr_centrality: Dict[int, float] = {}
        self.agent_entity_uuid: Dict[int, str] = {}
        self.agent_entity_name: Dict[int, str] = {}
        self.agent_semantic_keywords: Dict[int, set] = {}
        self.agent_semantic_text: Dict[int, str] = {}
        self.agent_id_by_name: Dict[str, int] = {}
        self.graph_pair_strength: Dict[Tuple[int, int], float] = {}
        self.graph_prior_pairs: set = set()
        self.graph_prior_directed: Dict[Tuple[int, int], float] = {}
        self.social_relation_directed: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.social_relation_pair_metrics: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.known_follow_pairs: set = set()
        self.dynamic_interaction_neighbors: Dict[int, Dict[int, float]] = defaultdict(dict)
        self._dynamic_events_since_refresh = 0

        self.units: List[List[int]] = []
        self.unit_id_by_agent: Dict[int, int] = {}
        self.unit_repr_by_id: Dict[int, int] = {}
        self.topology_artifact_dir = os.path.join(simulation_dir, "artifacts", "topology", platform)
        self.topology_snapshot_dir = os.path.join(self.topology_artifact_dir, "snapshots")
        self.topology_trace_file = os.path.join(self.topology_artifact_dir, "topology_trace.jsonl")
        self.topology_latest_file = os.path.join(self.topology_artifact_dir, "latest_topology.json")
        os.makedirs(self.topology_snapshot_dir, exist_ok=True)

        self._build_runtime()

    def _build_runtime(self):
        self._index_agent_configs()
        self.profile_by_agent_id = self._load_platform_profiles()
        self._rebuild_agent_name_index()
        self._load_social_relation_graph()
        self._load_graph_prior()
        self._load_entity_prompts()
        self._build_structure_vectors()
        self._build_similarity_graph()
        self._build_neighbor_influence_with_ppr()
        self._build_coordination_units()
        self._build_importance_scores()

        if self.enabled:
            avg_unit = (sum(len(u) for u in self.units) / max(len(self.units), 1)) if self.units else 1.0
            self.log(
                f"Topology-aware已启用: coordination={self.coordination_enabled}, "
                f"differentiation={self.differentiation_enabled}, "
                f"units={len(self.units)}, avg_unit_size={avg_unit:.2f}, "
                f"light={self.light_enabled}, top_pairs={len(self.top_pairs)}"
            )
        self.record_round_state(round_num=0, simulated_hour=None, reason="initial")

    def _write_json(self, path: str, payload: Dict[str, Any]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _append_jsonl(self, path: str, payload: Dict[str, Any]):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _agent_display_name(self, agent_id: int) -> str:
        if agent_id in self.agent_entity_name and self.agent_entity_name.get(agent_id):
            return str(self.agent_entity_name.get(agent_id))
        profile = self.profile_by_agent_id.get(agent_id, {}) or {}
        for key in ["name", "user_name", "username"]:
            value = str(profile.get(key, "") or "").strip()
            if value:
                return value
        return f"Agent_{agent_id}"

    def _top_outgoing_ppr(self, agent_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        scores = self.ppr_scores.get(agent_id, {}) or {}
        items = []
        for target, weight in scores.items():
            if target == agent_id or weight <= 0.0:
                continue
            items.append({
                "target_agent_id": target,
                "target_agent_name": self._agent_display_name(target),
                "weight": round(float(weight), 6),
                "target_unit_id": self.unit_id_by_agent.get(target),
            })
        items.sort(key=lambda x: x["weight"], reverse=True)
        return items[:limit]

    def _top_asymmetric_pairs(self, limit: int = 12) -> List[Dict[str, Any]]:
        agent_ids = sorted(self.agent_cfg_by_id.keys())
        records: List[Dict[str, Any]] = []
        for idx, aid in enumerate(agent_ids):
            for bid in agent_ids[idx + 1:]:
                ab = float((self.ppr_scores.get(aid, {}) or {}).get(bid, 0.0))
                ba = float((self.ppr_scores.get(bid, {}) or {}).get(aid, 0.0))
                if ab <= 0.0 and ba <= 0.0:
                    continue
                dominant_source, dominant_target, dominant, weaker = (
                    (aid, bid, ab, ba) if ab >= ba else (bid, aid, ba, ab)
                )
                records.append({
                    "dominant_source_agent_id": dominant_source,
                    "dominant_source_agent_name": self._agent_display_name(dominant_source),
                    "dominant_target_agent_id": dominant_target,
                    "dominant_target_agent_name": self._agent_display_name(dominant_target),
                    "dominant_weight": round(dominant, 6),
                    "reverse_weight": round(weaker, 6),
                    "delta": round(abs(dominant - weaker), 6),
                    "source_unit_id": self.unit_id_by_agent.get(dominant_source),
                    "target_unit_id": self.unit_id_by_agent.get(dominant_target),
                })
        records.sort(key=lambda x: (x["delta"], x["dominant_weight"]), reverse=True)
        return records[:limit]

    def _unit_records(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for unit_id, members in enumerate(self.units):
            representative = self.unit_repr_by_id.get(unit_id, members[0] if members else -1)
            member_records = []
            for aid in members:
                member_records.append({
                    "agent_id": aid,
                    "agent_name": self._agent_display_name(aid),
                    "importance": round(float(self.importance_scaled.get(aid, 1.0)), 6),
                    "ppr_centrality": round(float(self.ppr_centrality.get(aid, 0.0)), 6),
                    "neighbor_influence": round(float(self.neighbor_influence.get(aid, 0.0)), 6),
                    "keywords": sorted(self.agent_semantic_keywords.get(aid, set()))[:8],
                })
            records.append({
                "unit_id": unit_id,
                "size": len(members),
                "representative_agent_id": representative,
                "representative_agent_name": self._agent_display_name(representative),
                "members": member_records,
            })
        return records

    def build_state_snapshot(
        self,
        round_num: int,
        simulated_hour: Optional[int],
        reason: str = "round",
        active_agent_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        unit_sizes = [len(unit) for unit in self.units]
        largest_units = sorted(self._unit_records(), key=lambda x: (x["size"], x["unit_id"]), reverse=True)[:8]
        top_central_agents = sorted(
            self.agent_cfg_by_id.keys(),
            key=lambda aid: (
                self.ppr_centrality.get(aid, 0.0),
                self.importance_scaled.get(aid, 0.0),
            ),
            reverse=True,
        )[:12]

        return {
            "platform": self.platform,
            "generated_at": datetime.now().isoformat(),
            "round": round_num,
            "simulated_hour": simulated_hour,
            "reason": reason,
            "enabled": self.enabled,
            "coordination_enabled": self.coordination_enabled,
            "differentiation_enabled": self.differentiation_enabled,
            "agent_count": len(self.agent_cfg_by_id),
            "active_agent_ids": [int(aid) for aid in (active_agent_ids or [])],
            "active_agent_names": [self._agent_display_name(int(aid)) for aid in (active_agent_ids or [])],
            "unit_count": len(self.units),
            "unit_size_distribution": unit_sizes,
            "avg_unit_size": round(sum(unit_sizes) / max(len(unit_sizes), 1), 4) if unit_sizes else 0.0,
            "largest_unit_size": max(unit_sizes) if unit_sizes else 0,
            "singleton_units": sum(1 for size in unit_sizes if size == 1),
            "largest_units": largest_units,
            "top_pairs": [
                {
                    "source_agent_id": int(a),
                    "source_agent_name": self._agent_display_name(int(a)),
                    "target_agent_id": int(b),
                    "target_agent_name": self._agent_display_name(int(b)),
                    "distance": round(float(dist), 6),
                }
                for a, b, dist in sorted(self.top_pair_records, key=lambda x: x[2])[:24]
            ],
            "top_central_agents": [
                {
                    "agent_id": aid,
                    "agent_name": self._agent_display_name(aid),
                    "unit_id": self.unit_id_by_agent.get(aid),
                    "importance": round(float(self.importance_scaled.get(aid, 1.0)), 6),
                    "ppr_centrality": round(float(self.ppr_centrality.get(aid, 0.0)), 6),
                    "neighbor_influence": round(float(self.neighbor_influence.get(aid, 0.0)), 6),
                    "top_outgoing_ppr": self._top_outgoing_ppr(aid),
                }
                for aid in top_central_agents
            ],
            "top_asymmetric_pairs": self._top_asymmetric_pairs(),
        }

    def record_round_state(
        self,
        round_num: int,
        simulated_hour: Optional[int],
        reason: str = "round",
        active_agent_ids: Optional[List[int]] = None,
    ):
        snapshot = self.build_state_snapshot(
            round_num=round_num,
            simulated_hour=simulated_hour,
            reason=reason,
            active_agent_ids=active_agent_ids,
        )
        filename = f"round_{int(round_num):04d}_{reason}.json"
        snapshot_path = os.path.join(self.topology_snapshot_dir, filename)
        self._write_json(snapshot_path, snapshot)

        trace_entry = {
            "platform": self.platform,
            "generated_at": snapshot["generated_at"],
            "round": round_num,
            "simulated_hour": simulated_hour,
            "reason": reason,
            "agent_count": snapshot["agent_count"],
            "unit_count": snapshot["unit_count"],
            "avg_unit_size": snapshot["avg_unit_size"],
            "largest_unit_size": snapshot["largest_unit_size"],
            "singleton_units": snapshot["singleton_units"],
            "top_central_agents": snapshot["top_central_agents"][:5],
            "top_asymmetric_pairs": snapshot["top_asymmetric_pairs"][:5],
        }
        self._append_jsonl(self.topology_trace_file, trace_entry)
        self._write_json(self.topology_latest_file, snapshot)

    def _index_agent_configs(self):
        for item in self.config.get("agent_configs", []):
            agent_id = item.get("agent_id")
            if agent_id is None:
                continue
            aid = int(agent_id)
            self.agent_cfg_by_id[aid] = item
            self.agent_entity_uuid[aid] = str(item.get("entity_uuid", "") or "")
            self.agent_entity_name[aid] = str(item.get("entity_name", "") or "")

    def _normalize_agent_name(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _rebuild_agent_name_index(self):
        self.agent_id_by_name = {}
        for aid, cfg in self.agent_cfg_by_id.items():
            candidates = [
                self.agent_entity_name.get(aid, ""),
                cfg.get("entity_name", ""),
                cfg.get("name", ""),
            ]
            profile = self.profile_by_agent_id.get(aid, {}) or {}
            candidates.extend([
                profile.get("name", ""),
                profile.get("user_name", ""),
                profile.get("username", ""),
            ])
            for raw in candidates:
                key = self._normalize_agent_name(raw)
                if key and key not in self.agent_id_by_name:
                    self.agent_id_by_name[key] = aid

    def _load_platform_profiles(self) -> Dict[int, Dict[str, Any]]:
        data: Dict[int, Dict[str, Any]] = {}

        if self.platform == "twitter":
            path = os.path.join(self.simulation_dir, "twitter_profiles.csv")
            if not os.path.exists(path):
                return data
            try:
                with open(path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        agent_id = row.get("user_id")
                        if agent_id is None:
                            continue
                        topics = row.get("interested_topics")
                        if isinstance(topics, str) and topics.strip():
                            try:
                                parsed = json.loads(topics)
                            except Exception:
                                try:
                                    parsed = ast.literal_eval(topics)
                                except Exception:
                                    parsed = [x.strip() for x in re.split(r"[，,;；]+", topics) if x.strip()]
                            if isinstance(parsed, list):
                                row["interested_topics"] = parsed
                        for key in ["age", "friend_count", "follower_count", "statuses_count"]:
                            val = row.get(key)
                            if val is None or val == "":
                                continue
                            try:
                                row[key] = int(float(val))
                            except Exception:
                                pass
                        data[int(agent_id)] = row
            except Exception as e:
                self.log(f"读取twitter_profiles.csv失败: {e}")
            return data

        path = os.path.join(self.simulation_dir, "reddit_profiles.json")
        if not os.path.exists(path):
            return data
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                for idx, row in enumerate(items):
                    if not isinstance(row, dict):
                        continue
                    agent_id = row.get("user_id", idx)
                    data[int(agent_id)] = row
        except Exception as e:
            self.log(f"读取reddit_profiles.json失败: {e}")
        return data

    def _load_entity_prompts(self):
        """读取 simulation_dir 下的 entity_prompts.json，并映射到 agent_id。"""
        config_file = self.config.get("entity_prompts_file", "entity_prompts.json")
        prompt_path = os.path.join(self.simulation_dir, config_file)
        if not os.path.exists(prompt_path):
            return

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            self.log(f"读取 entity prompts 失败: {e}")
            return

        if not isinstance(rows, list):
            return

        by_uuid: Dict[str, Dict[str, Any]] = {}
        by_name: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            uuid_key = str(row.get("entity_uuid", "") or "").strip().lower()
            name_key = str(row.get("entity_name", "") or "").strip().lower()
            if uuid_key:
                by_uuid[uuid_key] = row
            if name_key:
                by_name[name_key] = row

        for aid in self.agent_cfg_by_id.keys():
            entity_uuid = self.agent_entity_uuid.get(aid, "").strip().lower()
            entity_name = self.agent_entity_name.get(aid, "").strip().lower()
            row = None
            if entity_uuid:
                row = by_uuid.get(entity_uuid)
            if row is None and entity_name:
                row = by_name.get(entity_name)
            if row is None:
                continue

            keywords_raw = row.get("keywords", []) or []
            if isinstance(keywords_raw, str):
                keywords_raw = re.split(r"[，,;；\s]+", keywords_raw)
            keywords = {
                str(k).strip().lower()
                for k in keywords_raw
                if str(k).strip()
            }
            semantic_text = " ".join([
                str(row.get("description", "") or ""),
                str(row.get("semantic_prompt", "") or ""),
                " ".join(str(t) for t in (row.get("topic_tags", []) or []))
            ]).strip().lower()

            self.agent_semantic_keywords[aid] = keywords
            self.agent_semantic_text[aid] = semantic_text

    def _edge_prior_strength(self, edge_name: str, fact: str) -> float:
        text = f"{edge_name} {fact}".lower()
        score = 0.45

        strong_pos = [
            "follow", "ally", "alliance", "support", "cooperate", "collaborate",
            "partner", "friend", "trust", "endorse", "retweet", "repost", "quote",
            "关注", "支持", "合作", "联盟", "信任", "转发", "引用",
        ]
        weak_pos = [
            "mention", "related", "associate", "connect", "work with",
            "提及", "关联", "联系",
        ]
        neg = [
            "oppose", "conflict", "attack", "criticize", "dispute", "block", "mute",
            "反对", "冲突", "攻击", "批评", "屏蔽",
        ]

        if any(k in text for k in strong_pos):
            score += 0.35
        elif any(k in text for k in weak_pos):
            score += 0.20

        if any(k in text for k in neg):
            score -= 0.30

        return min(1.0, max(0.05, score))

    def _load_graph_prior(self):
        """
        读取 prepare 阶段保存的图谱快照，编译 entity->agent 的关系先验。
        产物：
        - graph_prior_directed: 有向关系及强度（用于初始follow）
        - graph_prior_pairs / graph_pair_strength: 无向关系（用于相似图先验）
        """
        graph_file = self.config.get("entity_graph_file", "entity_graph_snapshot.json")
        path = os.path.join(self.simulation_dir, graph_file)
        if not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            self.log(f"读取图谱快照失败: {e}")
            return

        edges = payload.get("edges", []) if isinstance(payload, dict) else []
        if not isinstance(edges, list):
            return

        aid_by_uuid: Dict[str, int] = {}
        for aid, uuid in self.agent_entity_uuid.items():
            key = str(uuid or "").strip().lower()
            if key:
                aid_by_uuid[key] = aid

        mapped = 0
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src_uuid = str(edge.get("source_node_uuid", "") or "").strip().lower()
            dst_uuid = str(edge.get("target_node_uuid", "") or "").strip().lower()
            if not src_uuid or not dst_uuid:
                continue

            src_aid = aid_by_uuid.get(src_uuid)
            dst_aid = aid_by_uuid.get(dst_uuid)
            if src_aid is None or dst_aid is None or src_aid == dst_aid:
                continue

            strength = self._edge_prior_strength(
                str(edge.get("name", "") or ""),
                str(edge.get("fact", "") or ""),
            )

            directed_key = (src_aid, dst_aid)
            old_directed = self.graph_prior_directed.get(directed_key, 0.0)
            self.graph_prior_directed[directed_key] = max(old_directed, strength)

            pair = (min(src_aid, dst_aid), max(src_aid, dst_aid))
            old_pair = self.graph_pair_strength.get(pair, 0.0)
            self.graph_pair_strength[pair] = max(old_pair, strength)
            self.graph_prior_pairs.add(pair)
            mapped += 1

        if mapped > 0:
            self.log(
                f"已加载图谱关系先验: directed={len(self.graph_prior_directed)}, "
                f"undirected={len(self.graph_prior_pairs)}"
            )

    def _load_social_relation_graph(self):
        relation_file = self.config.get("social_relation_graph_file", "social_relation_graph.json")
        path = os.path.join(self.simulation_dir, relation_file)
        if not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            self.log(f"读取显式社交关系图失败: {e}")
            return

        edges = payload.get("edges", []) if isinstance(payload, dict) else []
        if not isinstance(edges, list):
            return

        mapped = 0
        for edge in edges:
            if not isinstance(edge, dict):
                continue

            try:
                src = int(edge.get("source_agent_id", -1))
                dst = int(edge.get("target_agent_id", -1))
            except Exception:
                continue

            if src < 0 or dst < 0 or src == dst:
                continue

            metrics = {
                "exposure_weight": max(0.0, min(1.0, _safe_float(edge.get("exposure_weight", 0.0), 0.0))),
                "trust_weight": max(0.0, min(1.0, _safe_float(edge.get("trust_weight", 0.0), 0.0))),
                "hostility_weight": max(0.0, min(1.0, _safe_float(edge.get("hostility_weight", 0.0), 0.0))),
                "alliance_weight": max(0.0, min(1.0, _safe_float(edge.get("alliance_weight", 0.0), 0.0))),
                "interaction_prior": max(-1.0, min(1.0, _safe_float(edge.get("interaction_prior", 0.0), 0.0))),
            }
            self.social_relation_directed[(src, dst)] = metrics

            pair = (min(src, dst), max(src, dst))
            pair_metrics = self.social_relation_pair_metrics.setdefault(
                pair,
                {
                    "exposure_weight": 0.0,
                    "trust_weight": 0.0,
                    "hostility_weight": 0.0,
                    "alliance_weight": 0.0,
                    "interaction_prior": -1.0,
                },
            )
            for key in ["exposure_weight", "trust_weight", "hostility_weight", "alliance_weight"]:
                pair_metrics[key] = max(pair_metrics[key], metrics[key])
            pair_metrics["interaction_prior"] = max(
                pair_metrics["interaction_prior"],
                abs(metrics["interaction_prior"]),
            )

            positive_prior = max(
                0.0,
                0.45 * metrics["exposure_weight"]
                + 0.25 * metrics["trust_weight"]
                + 0.20 * metrics["alliance_weight"]
                + 0.10 * max(0.0, metrics["interaction_prior"])
                - 0.20 * metrics["hostility_weight"],
            )
            self.graph_prior_directed[(src, dst)] = max(
                self.graph_prior_directed.get((src, dst), 0.0),
                positive_prior,
            )
            self.graph_pair_strength[pair] = max(
                self.graph_pair_strength.get(pair, 0.0),
                positive_prior,
                pair_metrics["exposure_weight"],
                pair_metrics["trust_weight"],
                pair_metrics["alliance_weight"],
            )
            self.graph_prior_pairs.add(pair)
            mapped += 1

        if mapped > 0:
            self.log(
                f"已加载显式社交关系图: directed={len(self.social_relation_directed)}, "
                f"undirected={len(self.social_relation_pair_metrics)}"
            )

    def _build_importance_scores(self):
        for agent_id, cfg in self.agent_cfg_by_id.items():
            profile = self.profile_by_agent_id.get(agent_id, {})
            influence_weight = _safe_float(cfg.get("influence_weight", 1.0), 1.0)
            activity_level = _safe_float(cfg.get("activity_level", 0.5), 0.5)
            posts_per_hour = _safe_float(cfg.get("posts_per_hour", 1.0), 1.0)
            comments_per_hour = _safe_float(cfg.get("comments_per_hour", 1.0), 1.0)

            followers = _safe_float(profile.get("follower_count", profile.get("followers", 0)), 0.0)
            friends = _safe_float(profile.get("friend_count", profile.get("friends", 0)), 0.0)
            statuses = _safe_float(profile.get("statuses_count", 0), 0.0)
            karma = _safe_float(profile.get("karma", 0), 0.0)
            ppr_signal = self.ppr_centrality.get(agent_id, 0.0)

            topology_signal = math.log1p(max(
                karma,
                followers + 0.6 * friends + 0.1 * statuses
            ) + max(0.0, ppr_signal))
            behavior_signal = math.log1p(max(0.0, posts_per_hour) + max(0.0, comments_per_hour))

            raw = (
                0.45 * max(0.0, influence_weight)
                + 0.30 * max(0.0, activity_level)
                + 0.15 * behavior_signal
                + 0.10 * topology_signal
            )
            self.importance_raw[agent_id] = max(0.01, raw)

        if not self.importance_raw:
            return

        values = list(self.importance_raw.values())
        min_v = min(values)
        max_v = max(values)
        if abs(max_v - min_v) < 1e-9:
            for aid in self.importance_raw:
                self.importance_scaled[aid] = 1.0
            return

        for aid, raw in self.importance_raw.items():
            norm = (raw - min_v) / (max_v - min_v)
            self.importance_scaled[aid] = 0.35 + 1.65 * norm

    def _build_structure_vectors(self):
        stance_map = {
            "supportive": 1.0,
            "opposing": -1.0,
            "neutral": 0.0,
            "observer": 0.2,
        }
        for agent_id, cfg in self.agent_cfg_by_id.items():
            profile = self.profile_by_agent_id.get(agent_id, {})
            active_hours = cfg.get("active_hours", list(range(8, 23))) or []
            if active_hours:
                center = sum(active_hours) / len(active_hours) / 24.0
                span = (max(active_hours) - min(active_hours) + 1) / 24.0
            else:
                center = 0.5
                span = 0.0

            activity_level = _safe_float(cfg.get("activity_level", 0.5), 0.5)
            influence_weight = _safe_float(cfg.get("influence_weight", 1.0), 1.0)
            posts_per_hour = _safe_float(cfg.get("posts_per_hour", 1.0), 1.0)
            comments_per_hour = _safe_float(cfg.get("comments_per_hour", 1.0), 1.0)
            sentiment_bias = _safe_float(cfg.get("sentiment_bias", 0.0), 0.0)
            stance = str(cfg.get("stance", "neutral")).lower()

            # struc2vec_cluster 里的 opinion/stubbornness 对应变量
            opinion = max(-1.0, min(1.0, sentiment_bias))
            stubbornness = cfg.get("stubbornness")
            if stubbornness is None:
                # 默认将低活跃度视为更“固执”（可被配置覆盖）
                stubbornness = 1.0 - max(0.0, min(1.0, activity_level))
            stubbornness = max(0.0, min(1.0, _safe_float(stubbornness, 0.5)))
            self.opinion_by_agent[agent_id] = opinion
            self.stubbornness_by_agent[agent_id] = stubbornness

            followers = _safe_float(profile.get("follower_count", profile.get("followers", 0)), 0.0)
            friends = _safe_float(profile.get("friend_count", profile.get("friends", 0)), 0.0)
            statuses = _safe_float(profile.get("statuses_count", 0), 0.0)
            karma = _safe_float(profile.get("karma", 0), 0.0)
            topology_mass = math.log1p(max(karma, followers + 0.6 * friends + 0.1 * statuses))

            self.structure_vec[agent_id] = [
                max(0.0, activity_level),
                math.log1p(max(0.0, posts_per_hour)),
                math.log1p(max(0.0, comments_per_hour)),
                max(0.0, influence_weight),
                center,
                span,
                sentiment_bias,
                stance_map.get(stance, 0.0),
                topology_mass,
            ]

    def _tokenize_semantic_text(self, text: str) -> set:
        tokens = re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]{2,}", (text or "").lower())
        return set(tokens)

    def _keyword_overlap(self, aid: int, bid: int) -> Tuple[int, float]:
        kws_a = self.agent_semantic_keywords.get(aid, set())
        kws_b = self.agent_semantic_keywords.get(bid, set())
        if not kws_a or not kws_b:
            return 0, 0.0

        inter = len(kws_a & kws_b)
        union = len(kws_a | kws_b)
        jaccard = inter / union if union > 0 else 0.0
        return inter, jaccard

    def _semantic_similarity(self, aid: int, bid: int) -> float:
        kws_a = self.agent_semantic_keywords.get(aid, set())
        kws_b = self.agent_semantic_keywords.get(bid, set())
        txt_a = self.agent_semantic_text.get(aid, "")
        txt_b = self.agent_semantic_text.get(bid, "")

        key_sim = 0.0
        if kws_a and kws_b:
            inter = len(kws_a & kws_b)
            union = len(kws_a | kws_b)
            key_sim = inter / union if union > 0 else 0.0

        txt_sim = 0.0
        if txt_a and txt_b:
            ta = self._tokenize_semantic_text(txt_a)
            tb = self._tokenize_semantic_text(txt_b)
            if ta and tb:
                inter = len(ta & tb)
                union = len(ta | tb)
                txt_sim = inter / union if union > 0 else 0.0

        if key_sim > 0 and txt_sim > 0:
            return 0.7 * key_sim + 0.3 * txt_sim
        return max(key_sim, txt_sim)

    def _build_similarity_graph(self):
        """参考 struc2vec_cluster: 基于向量距离选取 top-k 候选对。"""
        agent_ids = sorted(self.structure_vec.keys())
        self.synthetic_adj = {aid: [] for aid in agent_ids}
        self.top_pair_records = []
        self.top_pairs = set()

        if len(agent_ids) < 2:
            return

        records: List[Tuple[int, int, float]] = []
        backup_records: List[Tuple[int, int, float]] = []
        pair_dist: Dict[Tuple[int, int], float] = {}
        for idx, aid in enumerate(agent_ids):
            vec_i = self.structure_vec.get(aid, [])
            for bid in agent_ids[idx + 1:]:
                vec_j = self.structure_vec.get(bid, [])
                # 与参考实现一致：使用欧氏距离排名
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(vec_i, vec_j)))
                semantic_sim = self._semantic_similarity(aid, bid)
                if semantic_sim > 0:
                    # 语义越相近，距离越小（提升进入 top-k 的概率）
                    dist *= (1.0 - 0.3 * semantic_sim)
                overlap_count, overlap_jaccard = self._keyword_overlap(aid, bid)
                if overlap_count > 0:
                    # 关键词重叠单独加权，确保关键词对候选对排序有实质影响
                    dist *= (1.0 - min(0.35, 0.2 + 0.15 * overlap_jaccard))

                # 图谱关系先验：若实体关系在语义图中已存在，则提升入图概率
                pair = (min(aid, bid), max(aid, bid))
                prior_strength = self.graph_pair_strength.get(pair, 0.0)
                if prior_strength > 0.0:
                    boost = self.graph_prior_similarity_boost * min(1.0, prior_strength)
                    dist *= max(0.15, 1.0 - boost)

                relation_metrics = self.social_relation_pair_metrics.get(pair)
                if relation_metrics:
                    positive = max(
                        relation_metrics.get("exposure_weight", 0.0),
                        relation_metrics.get("trust_weight", 0.0),
                        relation_metrics.get("alliance_weight", 0.0),
                        max(0.0, relation_metrics.get("interaction_prior", 0.0)),
                    )
                    hostility = relation_metrics.get("hostility_weight", 0.0)
                    if positive > 0.0:
                        dist *= max(0.12, 1.0 - 0.45 * min(1.0, positive))
                    if hostility > 0.0:
                        dist *= (1.0 + 0.35 * min(1.0, hostility))

                pair = (aid, bid, dist)
                backup_records.append(pair)
                pair_dist[(min(aid, bid), max(aid, bid))] = dist
                if _cosine_similarity(vec_i, vec_j) >= self.similarity_threshold:
                    records.append(pair)

        # 避免阈值过高导致无候选对
        if not records:
            records = backup_records

        records.sort(key=lambda x: x[2])
        top_k = max(1, int(math.ceil(len(records) * self.top_pairs_ratio)))
        selected = list(records[:top_k])

        # 图谱先验补边：在 top-k 基础上追加少量图谱关系边，避免被纯向量相似完全淹没
        if self.graph_prior_pairs and self.graph_prior_extra_ratio > 0.0:
            extra_k = max(1, int(math.ceil(top_k * self.graph_prior_extra_ratio)))
            existing = {(min(a, b), max(a, b)) for a, b, _ in selected}
            prior_candidates: List[Tuple[int, int, float]] = []
            for pair in self.graph_prior_pairs:
                if pair in existing:
                    continue
                a, b = pair
                if a not in self.synthetic_adj or b not in self.synthetic_adj:
                    continue
                dist = pair_dist.get(pair, 1e9)
                prior_candidates.append((a, b, dist))
            prior_candidates.sort(key=lambda x: x[2])
            selected.extend(prior_candidates[:extra_k])

        self.top_pair_records = selected
        self.top_pairs = set((min(a, b), max(a, b)) for a, b, _ in selected)

        for a, b, _ in selected:
            self.synthetic_adj[a].append(b)
            self.synthetic_adj[b].append(a)

    def _approximate_ppr_single_source(self, source: int) -> Dict[int, float]:
        """参考 struc2vec_cluster/test/cluster.py 的 push-based 近似PPR。"""
        p = defaultdict(float)
        r = defaultdict(float)
        r[source] = 1.0
        q = deque([source])

        while q:
            u = q.popleft()
            nbrs = self.synthetic_adj.get(u, [])
            deg_u = len(nbrs)

            if deg_u == 0:
                p[u] += r[u]
                r[u] = 0.0
                continue

            if r[u] / deg_u <= self.ppr_eps:
                continue

            push_val = r[u]
            p[u] += self.ppr_alpha * push_val
            remain = (1.0 - self.ppr_alpha) * push_val
            share = remain / deg_u
            r[u] = 0.0

            for v in nbrs:
                prev = r[v]
                r[v] += share
                deg_v = len(self.synthetic_adj.get(v, []))
                if deg_v > 0 and prev / deg_v <= self.ppr_eps and r[v] / deg_v > self.ppr_eps:
                    q.append(v)

        return dict(p)

    def _build_neighbor_influence_with_ppr(self):
        """参考 struc2vec_cluster: 用PPR权重聚合邻居观点。"""
        agent_ids = sorted(self.structure_vec.keys())
        self.neighbor_influence = {}
        self.ppr_scores = {}
        self.ppr_centrality = {}
        incoming_mass = defaultdict(float)

        for aid in agent_ids:
            nbrs = self.synthetic_adj.get(aid, [])
            if not nbrs:
                self.neighbor_influence[aid] = 0.0
                self.ppr_scores[aid] = {aid: 1.0}
                incoming_mass[aid] += 1.0
                continue

            ppr = self._approximate_ppr_single_source(aid)
            self.ppr_scores[aid] = ppr

            wsum = 0.0
            weighted = 0.0
            for nb in nbrs:
                w = ppr.get(nb, 0.0)
                if w <= 0.0:
                    continue
                weighted += self.opinion_by_agent.get(nb, 0.0) * w
                wsum += w

            if wsum > 0:
                self.neighbor_influence[aid] = weighted / wsum
            else:
                self.neighbor_influence[aid] = (
                    sum(self.opinion_by_agent.get(nb, 0.0) for nb in nbrs) / max(len(nbrs), 1)
                )

            for target, mass in ppr.items():
                incoming_mass[target] += mass

        denom = max(len(agent_ids), 1)
        for aid in agent_ids:
            self.ppr_centrality[aid] = incoming_mass.get(aid, 0.0) / denom

    def _is_similar_struc2vec_style(self, n1: int, n2: int) -> bool:
        """参考 cluster.py 的三重过滤：opinion/stubbornness/PPR影响。"""
        op1 = self.opinion_by_agent.get(n1, 0.0)
        op2 = self.opinion_by_agent.get(n2, 0.0)
        if abs(op1 - op2) >= max(self.opinion_threshold, self.sentiment_diff_threshold):
            return False

        s1 = self.stubbornness_by_agent.get(n1, 0.5)
        s2 = self.stubbornness_by_agent.get(n2, 0.5)
        if abs(s1 - s2) >= self.stubbornness_threshold:
            return False

        inf1 = self.neighbor_influence.get(n1, 0.0)
        inf2 = self.neighbor_influence.get(n2, 0.0)
        if abs(inf1 - inf2) > self.influence_threshold:
            return False
        if inf1 * inf2 < 0:
            return False

        pair = (min(n1, n2), max(n1, n2))
        relation_metrics = self.social_relation_pair_metrics.get(pair)
        if relation_metrics:
            hostility = relation_metrics.get("hostility_weight", 0.0)
            alliance = relation_metrics.get("alliance_weight", 0.0)
            trust = relation_metrics.get("trust_weight", 0.0)
            if hostility >= 0.60 and max(alliance, trust) < 0.30:
                return False

        # 工程增强：当两侧都有语义信息时，加一层语义一致性约束
        has_semantic = (
            (n1 in self.agent_semantic_keywords or n1 in self.agent_semantic_text)
            and (n2 in self.agent_semantic_keywords or n2 in self.agent_semantic_text)
        )
        if has_semantic:
            overlap_count, overlap_jaccard = self._keyword_overlap(n1, n2)
            # 关键词硬门槛：有关键词时必须满足最小重叠
            if self.keyword_overlap_min > 0:
                has_keywords_both = (
                    bool(self.agent_semantic_keywords.get(n1))
                    and bool(self.agent_semantic_keywords.get(n2))
                )
                if has_keywords_both:
                    if overlap_count < self.keyword_overlap_min:
                        return False
                    if overlap_jaccard < self.keyword_jaccard_threshold:
                        return False
            if self._semantic_similarity(n1, n2) < self.semantic_threshold:
                return False

        return True

    def _build_coordination_units(self):
        agent_ids = sorted(self.agent_cfg_by_id.keys())
        if not agent_ids:
            self.units = []
            self.unit_id_by_agent = {}
            self.unit_repr_by_id = {}
            return

        if not self.enabled or not self.coordination_enabled:
            self.units = [[aid] for aid in agent_ids]
            self.unit_id_by_agent = {aid: idx for idx, aid in enumerate(agent_ids)}
            self.unit_repr_by_id = {idx: aid for idx, aid in enumerate(agent_ids)}
            return

        # 参考 struc2vec_cluster 的“top-k候选对 + 相似性扩团”流程
        records = list(self.top_pair_records)
        top_pairs = self.top_pairs
        units: List[List[int]] = []
        visited = set()

        for node1, node2, _ in records:
            if node1 in visited or node2 in visited:
                continue
            if not self._is_similar_struc2vec_style(node1, node2):
                continue

            group = set([node1, node2])
            updated = True
            while updated:
                updated = False
                for nid in agent_ids:
                    if nid in group or nid in visited:
                        continue
                    if all(
                        self._is_similar_struc2vec_style(nid, member)
                        and (min(nid, member), max(nid, member)) in top_pairs
                        for member in group
                    ):
                        group.add(nid)
                        updated = True

            group_sorted = sorted(group)
            if len(group_sorted) < self.min_unit_size:
                for aid in group_sorted:
                    units.append([aid])
                    visited.add(aid)
            else:
                units.append(group_sorted)
                visited.update(group_sorted)

        # 未分到组的节点补成单节点组（与参考实现一致）
        for aid in agent_ids:
            if aid not in visited:
                units.append([aid])
                visited.add(aid)

        units = sorted(units, key=lambda m: (len(m), m[0]), reverse=True)
        self.units = units
        self.unit_id_by_agent = {}
        self.unit_repr_by_id = {}

        for unit_id, members in enumerate(units):
            for aid in members:
                self.unit_id_by_agent[aid] = unit_id
            representative = max(
                members,
                key=lambda x: self.importance_scaled.get(x, 1.0)
            )
            self.unit_repr_by_id[unit_id] = representative

    def adjust_target_count(self, target_count: int) -> int:
        if self.light_enabled:
            target_count = max(1, int(round(target_count * self.light_agent_ratio)))
        return max(1, target_count)

    def get_activity_probability(self, agent_id: int, base_activity: float) -> float:
        prob = min(1.0, max(0.0, base_activity))
        if self.enabled and self.differentiation_enabled:
            importance = self.importance_scaled.get(agent_id, 1.0)
            # importance>1 的节点更容易触发更新，importance<1 的节点更新频率下降
            importance_boost = importance ** self.importance_alpha
            prob *= (0.65 + 0.35 * importance_boost)
        return min(0.98, max(0.01, prob))

    def _weighted_sample_without_replacement(
        self,
        items: List[int],
        weights: List[float],
        k: int
    ) -> List[int]:
        pool = list(items)
        w = [max(0.0, x) for x in weights]
        selected: List[int] = []
        k = min(max(0, k), len(pool))

        for _ in range(k):
            if not pool:
                break
            if sum(w) <= 1e-9:
                idx = random.randrange(len(pool))
            else:
                idx = random.choices(range(len(pool)), weights=w, k=1)[0]
            selected.append(pool.pop(idx))
            w.pop(idx)
        return selected

    def select_agent_ids(self, candidate_ids: List[int], target_count: int) -> List[int]:
        if not candidate_ids:
            return []

        candidate_ids = list(dict.fromkeys(candidate_ids))
        target_count = min(target_count, len(candidate_ids))
        if target_count <= 0:
            return []

        if not self.enabled:
            return random.sample(candidate_ids, target_count)

        if not self.coordination_enabled:
            weights = [
                self.importance_scaled.get(aid, 1.0) if self.differentiation_enabled else 1.0
                for aid in candidate_ids
            ]
            return self._weighted_sample_without_replacement(candidate_ids, weights, target_count)

        # Coordination：按单元采样，仅让代表节点触发 LLM 推理，必要时让少量成员补充
        unit_candidates: Dict[int, List[int]] = {}
        for aid in candidate_ids:
            unit_id = self.unit_id_by_agent.get(aid)
            if unit_id is None:
                continue
            unit_candidates.setdefault(unit_id, []).append(aid)

        if not unit_candidates:
            return random.sample(candidate_ids, target_count)

        unit_ids = list(unit_candidates.keys())
        avg_unit_size = sum(len(unit_candidates[u]) for u in unit_ids) / max(len(unit_ids), 1)
        target_units = max(1, int(round(target_count / max(avg_unit_size, 1.0))))
        target_units = min(target_units, len(unit_ids))

        unit_weights: List[float] = []
        for uid in unit_ids:
            members = unit_candidates[uid]
            imp = max(self.importance_scaled.get(aid, 1.0) for aid in members)
            size_bonus = len(members) ** 0.25
            unit_weights.append(imp * size_bonus)

        selected_unit_ids = self._weighted_sample_without_replacement(unit_ids, unit_weights, target_units)

        selected: List[int] = []
        selected_set = set()
        for uid in selected_unit_ids:
            members = unit_candidates[uid]
            representative = max(members, key=lambda aid: self.importance_scaled.get(aid, 1.0))
            if representative not in selected_set:
                selected.append(representative)
                selected_set.add(representative)

            if len(members) > 1 and random.random() < self.extra_member_prob:
                extras = [aid for aid in members if aid != representative]
                if extras:
                    extra_weights = [self.importance_scaled.get(aid, 1.0) for aid in extras]
                    extra = self._weighted_sample_without_replacement(extras, extra_weights, 1)
                    if extra and extra[0] not in selected_set:
                        selected.append(extra[0])
                        selected_set.add(extra[0])

        if len(selected) < target_count:
            remaining = [aid for aid in candidate_ids if aid not in selected_set]
            if remaining:
                weights = [
                    self.importance_scaled.get(aid, 1.0) if self.differentiation_enabled else 1.0
                    for aid in remaining
                ]
                fill = self._weighted_sample_without_replacement(remaining, weights, target_count - len(selected))
                selected.extend(fill)

        if len(selected) > target_count:
            weights = [
                self.importance_scaled.get(aid, 1.0) if self.differentiation_enabled else 1.0
                for aid in selected
            ]
            selected = self._weighted_sample_without_replacement(selected, weights, target_count)

        return selected

    def register_existing_follow_pairs(self, pairs: List[Tuple[int, int]]):
        for src, dst in pairs:
            if src == dst:
                continue
            self.known_follow_pairs.add((int(src), int(dst)))

    def compile_initial_follow_pairs(
        self,
        max_per_agent: Optional[int] = None,
        max_total: Optional[int] = None,
    ) -> List[Tuple[int, int, float, str]]:
        """
        编译初始 follow 建议边（有向）：
        1) 优先使用语义图谱中的有向关系
        2) 用 synthetic_adj + 重要性做补充弱曝光边
        """
        per_agent_limit = self.initial_follow_max_per_agent if max_per_agent is None else max(1, int(max_per_agent))
        total_limit = self.initial_follow_max_total if max_total is None else max(0, int(max_total))
        if total_limit <= 0:
            total_limit = max(12, len(self.agent_cfg_by_id) * per_agent_limit)

        by_src: Dict[int, List[Tuple[int, float, str]]] = defaultdict(list)

        for (src, dst), metrics in self.social_relation_directed.items():
            if src == dst:
                continue
            if (src, dst) in self.known_follow_pairs:
                continue

            exposure = metrics.get("exposure_weight", 0.0)
            trust = metrics.get("trust_weight", 0.0)
            alliance = metrics.get("alliance_weight", 0.0)
            hostility = metrics.get("hostility_weight", 0.0)
            prior = metrics.get("interaction_prior", 0.0)
            score = (
                0.38 * exposure
                + 0.24 * trust
                + 0.20 * alliance
                + 0.18 * max(0.0, prior)
                - 0.28 * hostility
            )
            if score <= 0.05:
                continue
            by_src[src].append((dst, score, "social_relation_graph"))

        for (src, dst), rel_strength in self.graph_prior_directed.items():
            if src == dst:
                continue
            if (src, dst) in self.known_follow_pairs:
                continue
            dst_imp = self.importance_scaled.get(dst, 1.0)
            score = 0.72 * rel_strength + 0.28 * min(2.0, dst_imp) / 2.0
            by_src[src].append((dst, score, "graph_prior"))

        for src, nbrs in self.synthetic_adj.items():
            if not nbrs:
                continue
            for dst in nbrs:
                if src == dst:
                    continue
                if (src, dst) in self.known_follow_pairs:
                    continue
                ppr = self.ppr_scores.get(src, {}).get(dst, 0.0)
                dst_imp = self.importance_scaled.get(dst, 1.0)
                score = 0.5 * min(1.0, ppr) + 0.3 * min(1.0, dst_imp / 2.0) + 0.2
                by_src[src].append((dst, score, "topology_weak_exposure"))

        selected: List[Tuple[int, int, float, str]] = []
        for src, candidates in by_src.items():
            # 去重并保留更高分
            best_by_dst: Dict[int, Tuple[float, str]] = {}
            for dst, score, reason in candidates:
                prev = best_by_dst.get(dst)
                if prev is None or score > prev[0]:
                    best_by_dst[dst] = (score, reason)
            ranked = sorted(best_by_dst.items(), key=lambda x: x[1][0], reverse=True)
            for dst, (score, reason) in ranked[:per_agent_limit]:
                selected.append((src, dst, score, reason))

        selected.sort(key=lambda x: x[2], reverse=True)
        selected = selected[:total_limit]
        return selected

    def _interaction_weight(self, action_type: str) -> float:
        action = str(action_type or "").upper()
        weight_map = {
            "FOLLOW": 1.00,
            "REPOST": 0.85,
            "QUOTE_POST": 0.80,
            "CREATE_COMMENT": 0.70,
            "LIKE_POST": 0.55,
            "LIKE_COMMENT": 0.50,
            "SEARCH_USER": 0.35,
            "DISLIKE_POST": -0.30,
            "DISLIKE_COMMENT": -0.25,
            "MUTE": -0.80,
        }
        return weight_map.get(action, 0.0)

    def _extract_target_agent_ids(self, action_args: Dict[str, Any]) -> List[int]:
        if not isinstance(action_args, dict):
            return []

        ids: List[int] = []
        id_keys = [
            "target_agent_id",
            "post_author_agent_id",
            "comment_author_agent_id",
            "original_author_agent_id",
        ]
        for k in id_keys:
            val = action_args.get(k)
            if val is None:
                continue
            try:
                ids.append(int(val))
            except Exception:
                continue

        name_keys = [
            "target_user_name",
            "post_author_name",
            "comment_author_name",
            "original_author_name",
        ]
        for k in name_keys:
            name = action_args.get(k)
            key = self._normalize_agent_name(name)
            if not key:
                continue
            aid = self.agent_id_by_name.get(key)
            if aid is not None:
                ids.append(aid)

        dedup = []
        seen = set()
        for aid in ids:
            if aid in seen:
                continue
            seen.add(aid)
            dedup.append(aid)
        return dedup

    def _refresh_topology_from_interactions(self):
        if not self.synthetic_adj:
            return

        added = 0
        for src, nb_scores in self.dynamic_interaction_neighbors.items():
            if src not in self.synthetic_adj:
                continue
            ranked = sorted(nb_scores.items(), key=lambda x: x[1], reverse=True)
            keep = 0
            for dst, score in ranked:
                if dst == src:
                    continue
                if score < self.dynamic_interaction_min_weight:
                    continue
                if dst not in self.synthetic_adj:
                    continue
                pair = (min(src, dst), max(src, dst))
                if dst not in self.synthetic_adj[src]:
                    self.synthetic_adj[src].append(dst)
                    self.synthetic_adj[dst].append(src)
                    self.top_pairs.add(pair)
                    self.top_pair_records.append((pair[0], pair[1], 0.0))
                    added += 1
                keep += 1
                if keep >= self.dynamic_neighbors_per_agent:
                    break

        # 交互边会改变局部传播和聚类，刷新 PPR / unit / importance
        self._build_neighbor_influence_with_ppr()
        self._build_coordination_units()
        self._build_importance_scores()
        self._dynamic_events_since_refresh = 0

        if added > 0:
            self.log(f"Topology-aware 动态更新: 新增交互边={added}, units={len(self.units)}")

    def ingest_round_actions(self, round_num: int, actions: List[Dict[str, Any]]):
        if not self.enabled or not self.dynamic_update_enabled or not actions:
            return

        touched = 0
        for row in actions:
            if not isinstance(row, dict):
                continue
            try:
                src = int(row.get("agent_id", -1))
            except Exception:
                continue
            if src < 0:
                continue

            action_type = row.get("action_type", "")
            weight = self._interaction_weight(action_type)
            if abs(weight) <= 1e-9:
                continue

            targets = self._extract_target_agent_ids(row.get("action_args", {}) or {})
            for dst in targets:
                if dst == src or dst not in self.agent_cfg_by_id:
                    continue

                old = self.dynamic_interaction_neighbors.get(src, {}).get(dst, 0.0)
                new_val = max(-2.0, min(4.0, old + weight))
                self.dynamic_interaction_neighbors.setdefault(src, {})[dst] = new_val

                # follow 是有向关系，记录下来避免重复注入
                if str(action_type).upper() == "FOLLOW":
                    self.known_follow_pairs.add((src, dst))

                # 正向互动提供弱双向关联，帮助邻域检索和聚类收敛
                if weight > 0:
                    old_back = self.dynamic_interaction_neighbors.get(dst, {}).get(src, 0.0)
                    back_val = max(-2.0, min(4.0, old_back + weight * 0.25))
                    self.dynamic_interaction_neighbors.setdefault(dst, {})[src] = back_val

                touched += 1

        if touched <= 0:
            return

        self._dynamic_events_since_refresh += touched
        if (round_num % self.dynamic_update_interval == 0) and (
            self._dynamic_events_since_refresh >= self.dynamic_update_min_events
        ):
            self._refresh_topology_from_interactions()


class SimpleMemRuntime:
    """
    SimpleMem 风格的轻量增量记忆：
    1) 每轮 ingest 动作并进行在线语义合并（incremental synthesis）
    2) 每轮为活跃 agent 检索相关记忆并注入上下文（intent-aware retrieval）
    """

    MEM_MARKER = "\n\n[SimpleMem Retrieved]\n"
    ABSTRACT_HEADER = "[ABSTRACT REPRESENTATIONS]"
    DETAIL_HEADER = "[DETAILED MEMORY UNITS]"

    def __init__(
        self,
        config: Dict[str, Any],
        simulation_dir: str,
        platform: str,
        topology_runtime: Optional[TopologyAwareRuntime] = None,
        logger: Optional[Callable[[str], None]] = None
    ):
        self.config = config
        self.simulation_dir = simulation_dir
        self.platform = platform
        self.topology_runtime = topology_runtime
        self.log = logger or (lambda _: None)

        mem_cfg = config.get("simplemem", {}) or {}
        self.enabled = bool(mem_cfg.get("enabled", True))
        self.max_units_per_agent = max(20, int(mem_cfg.get("max_units_per_agent", 120)))
        self.retrieval_topk = max(1, int(mem_cfg.get("retrieval_topk", 5)))
        self.merge_jaccard_threshold = min(
            1.0, max(0.0, _safe_float(mem_cfg.get("merge_jaccard_threshold", 0.45), 0.45))
        )
        self.max_injected_chars = max(300, int(mem_cfg.get("max_injected_chars", 1200)))
        self.recency_decay = max(0.001, _safe_float(mem_cfg.get("recency_decay", 0.08), 0.08))
        self.min_salience_to_store = min(
            1.0, max(0.0, _safe_float(mem_cfg.get("min_salience_to_store", 0.28), 0.28))
        )
        self.world_salience_threshold = min(
            1.0, max(0.0, _safe_float(mem_cfg.get("world_salience_threshold", 0.60), 0.60))
        )
        self.merge_compare_window = max(4, int(mem_cfg.get("merge_compare_window", 12)))
        self.max_world_units = max(20, int(mem_cfg.get("max_world_units", 120)))
        self.abstract_topk = max(1, int(mem_cfg.get("abstract_topk", 3)))
        self.detail_topk = max(1, int(mem_cfg.get("detail_topk", 4)))
        self.self_scope_max = max(1, int(mem_cfg.get("self_scope_max", 3)))
        self.neighbor_scope_max = max(1, int(mem_cfg.get("neighbor_scope_max", 2)))
        self.world_scope_max = max(1, int(mem_cfg.get("world_scope_max", 2)))
        self.enable_world_memory = bool(mem_cfg.get("enable_world_memory", True))

        self.memory_file = os.path.join(simulation_dir, f"simplemem_{platform}.json")
        self.memory_artifact_dir = os.path.join(simulation_dir, "artifacts", "memory", platform)
        self.memory_trace_file = os.path.join(self.memory_artifact_dir, "memory_trace.jsonl")
        self.retrieval_trace_file = os.path.join(self.memory_artifact_dir, "retrieval_trace.jsonl")
        self.memory_state_file = os.path.join(self.memory_artifact_dir, "memory_state.jsonl")
        self.memory_latest_file = os.path.join(self.memory_artifact_dir, "latest_memory_state.json")
        os.makedirs(self.memory_artifact_dir, exist_ok=True)
        self.per_agent_units: Dict[int, List[Dict[str, Any]]] = {}
        self.world_units: List[Dict[str, Any]] = []
        self._agent_base_cache: Dict[Tuple[int, str], str] = {}
        self._seq = 0
        self._sim_start = self._resolve_simulation_start()

        if self.enabled:
            self._load()
            self.log(
                f"SimpleMem已启用: platform={platform}, agents={len(self.per_agent_units)}, "
                f"retrieval_topk={self.retrieval_topk}, max_units_per_agent={self.max_units_per_agent}"
            )

    def _load(self):
        if not os.path.exists(self.memory_file):
            return
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._seq = int(data.get("seq", 0))
            raw = data.get("per_agent_units", {})
            for k, v in raw.items():
                try:
                    aid = int(k)
                except Exception:
                    continue
                if isinstance(v, list):
                    self.per_agent_units[aid] = [self._normalize_loaded_unit(unit, aid) for unit in v]
            raw_world = data.get("world_units", [])
            if isinstance(raw_world, list):
                self.world_units = [self._normalize_loaded_unit(unit, None) for unit in raw_world]
        except Exception as e:
            self.log(f"加载SimpleMem失败，使用空记忆: {e}")
            self.per_agent_units = {}
            self.world_units = []
            self._seq = 0

    def _save(self):
        payload = {
            "platform": self.platform,
            "updated_at": datetime.now().isoformat(),
            "seq": self._seq,
            "per_agent_units": self.per_agent_units,
            "world_units": self.world_units,
        }
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存SimpleMem失败: {e}")

    def _append_jsonl(self, path: str, payload: Dict[str, Any]):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _write_json(self, path: str, payload: Dict[str, Any]):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _agent_display_name(self, agent_id: int) -> str:
        if self.topology_runtime:
            return self.topology_runtime._agent_display_name(agent_id)
        return f"Agent_{agent_id}"

    def _resolve_simulation_start(self) -> datetime:
        raw = self.config.get("generated_at") or self.config.get("created_at")
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.strip())
            except Exception:
                pass
        return datetime.now()

    def _make_timestamp(self, round_num: int) -> str:
        minutes_per_round = max(1, int((self.config.get("time_config", {}) or {}).get("minutes_per_round", 60)))
        offset_minutes = max(0, round_num - 1) * minutes_per_round
        return (self._sim_start + timedelta(minutes=offset_minutes)).isoformat()

    def _coerce_int(self, value: Any, default: Optional[int] = None) -> Optional[int]:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _dedup_texts(self, values: List[Any], limit: int) -> List[str]:
        results: List[str] = []
        seen = set()
        for raw in values:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(text)
            if len(results) >= limit:
                break
        return results

    def _salience_label(self, score: float) -> str:
        if score >= 0.75:
            return "high"
        if score >= 0.45:
            return "medium"
        return "low"

    def _extract_keywords(self, text: str, max_count: int = 8) -> List[str]:
        tokens = re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]{2,}", (text or "").lower())
        stopwords = {
            "create_post", "like_post", "repost", "quote_post", "follow", "do_nothing",
            "create_comment", "like_comment", "dislike_comment", "search_posts", "search_user",
            "trend", "refresh", "interview", "content", "post", "user", "agent",
            "的", "了", "和", "是", "在", "对", "与", "进行", "一个"
        }
        freq: Dict[str, int] = {}
        for t in tokens:
            if t in stopwords:
                continue
            freq[t] = freq.get(t, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: (-x[1], len(x[0])))
        return [k for k, _ in ranked[:max_count]]

    def _build_memory_text(self, action_data: Dict[str, Any]) -> str:
        action_type = str(action_data.get("action_type", ""))
        args = action_data.get("action_args", {}) or {}
        fragments: List[str] = [action_type]

        for key in [
            "content", "query", "post_content", "post_author_name",
            "comment_content", "comment_author_name", "original_content",
            "quote_content", "target_user_name"
        ]:
            val = args.get(key)
            if not val:
                continue
            fragments.append(f"{key}:{str(val)}")

        return " | ".join(fragments)

    def _extract_entities(self, action_data: Dict[str, Any]) -> List[str]:
        args = action_data.get("action_args", {}) or {}
        values = [action_data.get("agent_name", "")]
        for key in [
            "target_user_name",
            "post_author_name",
            "comment_author_name",
            "original_author_name",
        ]:
            values.append(args.get(key, ""))
        return self._dedup_texts(values, limit=6)

    def _extract_target_agent_ids(self, action_data: Dict[str, Any]) -> List[int]:
        ids: List[int] = []
        args = action_data.get("action_args", {}) or {}
        for key in [
            "target_agent_id",
            "post_author_agent_id",
            "comment_author_agent_id",
            "original_author_agent_id",
        ]:
            val = self._coerce_int(args.get(key))
            if val is not None:
                ids.append(val)
        if self.topology_runtime and hasattr(self.topology_runtime, "_extract_target_agent_ids"):
            try:
                ids.extend(self.topology_runtime._extract_target_agent_ids(args))
            except Exception:
                pass
        dedup: List[int] = []
        seen = set()
        for aid in ids:
            if aid in seen:
                continue
            seen.add(aid)
            dedup.append(aid)
        return dedup

    def _infer_topic(self, action_data: Dict[str, Any], summary: str, keywords: List[str]) -> str:
        text = summary.lower()
        event_cfg = self.config.get("event_config", {}) or {}
        hot_topics = [str(x).strip() for x in (event_cfg.get("hot_topics", []) or []) if str(x).strip()]
        matched_topics = [topic for topic in hot_topics if topic.lower() in text]
        if matched_topics:
            return " / ".join(matched_topics[:2])

        action_type = str(action_data.get("action_type", "") or "").upper()
        topical_keywords = [kw for kw in keywords if len(kw) >= 3]
        if action_type in {"FOLLOW", "MUTE"}:
            return "social_relation"
        if action_type in {"REPOST", "QUOTE_POST"}:
            return topical_keywords[0] if topical_keywords else "content_amplification"
        if action_type == "CREATE_COMMENT":
            return topical_keywords[0] if topical_keywords else "discussion"
        if action_type == "CREATE_POST":
            return topical_keywords[0] if topical_keywords else "new_post"
        return topical_keywords[0] if topical_keywords else "general"

    def _estimate_salience(
        self,
        action_data: Dict[str, Any],
        topic: str,
        target_agent_ids: List[int],
        keywords: List[str],
    ) -> float:
        action_type = str(action_data.get("action_type", "") or "").upper()
        base = {
            "CREATE_POST": 0.75,
            "QUOTE_POST": 0.80,
            "REPOST": 0.72,
            "FOLLOW": 0.64,
            "CREATE_COMMENT": 0.58,
            "SEARCH_USER": 0.34,
            "LIKE_POST": 0.28,
            "LIKE_COMMENT": 0.26,
            "DISLIKE_POST": 0.34,
            "DISLIKE_COMMENT": 0.32,
            "MUTE": 0.55,
        }.get(action_type, 0.20)

        event_cfg = self.config.get("event_config", {}) or {}
        hot_topics = {str(x).strip().lower() for x in (event_cfg.get("hot_topics", []) or []) if str(x).strip()}
        if topic and topic.lower() in hot_topics:
            base += 0.10
        if any(kw.lower() in hot_topics for kw in keywords):
            base += 0.06
        if target_agent_ids:
            base += 0.08

        source_agent = self._coerce_int(action_data.get("agent_id"), -1)
        if self.topology_runtime and source_agent is not None and source_agent >= 0:
            base += 0.05 * max(0.0, self.topology_runtime.importance_scaled.get(source_agent, 1.0) - 1.0)
            base += 0.08 * min(1.0, self.topology_runtime.ppr_centrality.get(source_agent, 0.0))

        return max(0.0, min(1.0, base))

    def _synthesize_abstract_summary(self, unit: Dict[str, Any]) -> str:
        topic = str(unit.get("topic", "general") or "general").strip()
        entities = self._dedup_texts(unit.get("entities", []) or [], limit=4)
        entity_text = ", ".join(entities) if entities else "unknown entities"
        latest_summary = str(unit.get("summary", "") or "").strip()
        latest_summary = latest_summary[:180]
        timestamp = str(unit.get("timestamp", "") or "").strip()
        prefix = f"[{topic}] {entity_text}"
        if timestamp:
            prefix += f" @ {timestamp}"
        if latest_summary:
            return f"{prefix}: {latest_summary}"
        return prefix

    def _normalize_loaded_unit(self, unit: Dict[str, Any], fallback_agent_id: Optional[int]) -> Dict[str, Any]:
        if not isinstance(unit, dict):
            unit = {}
        summary = str(unit.get("summary", "") or "").strip()
        summaries = unit.get("summaries", [])
        if not isinstance(summaries, list):
            summaries = []
        detail_units = unit.get("detail_units", [])
        if not isinstance(detail_units, list):
            detail_units = []

        if not summaries and summary:
            summaries = [summary]
        if not detail_units and summaries:
            detail_units = [
                {
                    "id": unit.get("id"),
                    "summary": s,
                    "timestamp": unit.get("timestamp", ""),
                    "action_type": unit.get("action_type", ""),
                    "agent_name": unit.get("agent_name", ""),
                }
                for s in summaries[-6:]
            ]

        agent_id = self._coerce_int(unit.get("agent_id"), fallback_agent_id if fallback_agent_id is not None else -1)
        entities = unit.get("entities", [])
        if not isinstance(entities, list):
            entities = []
        if not entities and unit.get("agent_name"):
            entities = [unit.get("agent_name")]

        keywords = unit.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []

        normalized = {
            "id": unit.get("id", f"{self.platform}_legacy_{self._seq + 1}"),
            "agent_id": agent_id,
            "source_agent_id": self._coerce_int(unit.get("source_agent_id"), agent_id),
            "agent_name": unit.get("agent_name", f"Agent_{agent_id}"),
            "source_agent_name": unit.get("source_agent_name", unit.get("agent_name", f"Agent_{agent_id}")),
            "action_type": unit.get("action_type", ""),
            "content": unit.get("content", summary),
            "summary": summary,
            "abstract_summary": unit.get("abstract_summary", self._synthesize_abstract_summary({
                **unit,
                "summary": summary,
                "entities": entities,
                "topic": unit.get("topic", "general"),
                "timestamp": unit.get("timestamp", ""),
            })),
            "summaries": summaries[-6:],
            "detail_units": detail_units[-6:],
            "keywords": self._dedup_texts(keywords, limit=10),
            "entities": self._dedup_texts(entities, limit=8),
            "topic": unit.get("topic", "general"),
            "timestamp": unit.get("timestamp", ""),
            "salience": unit.get("salience", "medium"),
            "salience_score": _safe_float(unit.get("salience_score", 0.5), 0.5),
            "first_round": self._coerce_int(unit.get("first_round"), 0) or 0,
            "last_round": self._coerce_int(unit.get("last_round"), 0) or 0,
            "last_hour": self._coerce_int(unit.get("last_hour"), 0) or 0,
            "count": self._coerce_int(unit.get("count"), 1) or 1,
            "target_agent_ids": unit.get("target_agent_ids", []) or [],
            "supporting_ids": unit.get("supporting_ids", [unit.get("id")]) or [unit.get("id")],
            "scope": unit.get("scope", "self"),
        }
        return normalized

    def _unit_similarity(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ak = set(a.get("keywords", []) or [])
        bk = set(b.get("keywords", []) or [])
        kw_sim = 0.0
        if ak and bk:
            inter = len(ak & bk)
            union = len(ak | bk)
            kw_sim = inter / union if union > 0 else 0.0

        ae = {str(x).strip().lower() for x in (a.get("entities", []) or []) if str(x).strip()}
        be = {str(x).strip().lower() for x in (b.get("entities", []) or []) if str(x).strip()}
        ent_sim = 0.0
        if ae and be:
            inter = len(ae & be)
            union = len(ae | be)
            ent_sim = inter / union if union > 0 else 0.0

        topic_sim = 1.0 if str(a.get("topic", "")).strip().lower() == str(b.get("topic", "")).strip().lower() and str(a.get("topic", "")).strip() else 0.0
        return 0.5 * kw_sim + 0.3 * ent_sim + 0.2 * topic_sim

    def _merge_unit(self, base: Dict[str, Any], new_unit: Dict[str, Any]):
        base_keywords = set(base.get("keywords", []) or [])
        base_keywords.update(new_unit.get("keywords", []) or [])
        base["keywords"] = self._dedup_texts(list(base_keywords), limit=10)

        merged_entities = list(base.get("entities", []) or []) + list(new_unit.get("entities", []) or [])
        base["entities"] = self._dedup_texts(merged_entities, limit=8)

        merged_targets = list(base.get("target_agent_ids", []) or []) + list(new_unit.get("target_agent_ids", []) or [])
        dedup_targets = []
        seen_targets = set()
        for aid in merged_targets:
            try:
                val = int(aid)
            except Exception:
                continue
            if val in seen_targets:
                continue
            seen_targets.add(val)
            dedup_targets.append(val)
        base["target_agent_ids"] = dedup_targets

        base["last_round"] = new_unit.get("last_round", base.get("last_round", 0))
        base["last_hour"] = new_unit.get("last_hour", base.get("last_hour", 0))
        base["timestamp"] = new_unit.get("timestamp", base.get("timestamp", ""))
        base["count"] = int(base.get("count", 1)) + int(new_unit.get("count", 1))
        base["salience_score"] = max(
            _safe_float(base.get("salience_score", 0.0), 0.0),
            _safe_float(new_unit.get("salience_score", 0.0), 0.0),
        )
        base["salience"] = self._salience_label(_safe_float(base.get("salience_score", 0.0), 0.0))

        summaries = list(base.get("summaries", []) or [])
        text = str(new_unit.get("summary", "") or "")
        if text and text not in summaries:
            summaries.append(text)
        base["summaries"] = summaries[-6:]
        base["summary"] = summaries[-1] if summaries else base.get("summary", "")

        detail_units = list(base.get("detail_units", []) or [])
        detail_unit = {
            "id": new_unit.get("id"),
            "summary": new_unit.get("summary", ""),
            "timestamp": new_unit.get("timestamp", ""),
            "action_type": new_unit.get("action_type", ""),
            "agent_name": new_unit.get("source_agent_name", new_unit.get("agent_name", "")),
        }
        if detail_unit["summary"]:
            detail_units.append(detail_unit)
        base["detail_units"] = detail_units[-6:]

        supporting_ids = list(base.get("supporting_ids", []) or []) + list(new_unit.get("supporting_ids", []) or [new_unit.get("id")])
        base["supporting_ids"] = self._dedup_texts(supporting_ids, limit=20)

        if not str(base.get("topic", "")).strip() and str(new_unit.get("topic", "")).strip():
            base["topic"] = new_unit.get("topic")

        base["abstract_summary"] = self._synthesize_abstract_summary(base)

    def _estimate_unit_complexity(self, query_keywords: set, agent_id: int) -> str:
        score = len(query_keywords)
        if self.per_agent_units.get(agent_id):
            score += min(2, len(self.per_agent_units.get(agent_id, [])[-2:]))
        hot_topics = (self.config.get("event_config", {}) or {}).get("hot_topics", []) or []
        if len(hot_topics) >= 3:
            score += 1
        if score >= 6:
            return "HIGH"
        if score >= 3:
            return "MEDIUM"
        return "LOW"

    def _build_retrieval_plan(self, agent_id: int, current_round: int) -> Dict[str, Any]:
        query_keywords = self._build_intent_keywords(agent_id)
        query_entities = set()
        if self.topology_runtime:
            entity_name = self.topology_runtime.agent_entity_name.get(agent_id, "")
            if entity_name:
                query_entities.add(str(entity_name).strip().lower())
        profile = {}
        if self.topology_runtime:
            profile = self.topology_runtime.profile_by_agent_id.get(agent_id, {}) or {}
        for topic in profile.get("interested_topics", []) or []:
            if topic:
                query_entities.add(str(topic).strip().lower())

        complexity = self._estimate_unit_complexity(query_keywords, agent_id)
        if complexity == "HIGH":
            depth = min(max(self.retrieval_topk, 8), self.max_units_per_agent)
            self_k = min(self.self_scope_max + 1, depth)
            neighbor_k = min(self.neighbor_scope_max + 1, depth)
            world_k = min(self.world_scope_max + 1, depth)
            recent_window = 24
        elif complexity == "MEDIUM":
            depth = max(self.retrieval_topk, 5)
            self_k = self.self_scope_max
            neighbor_k = self.neighbor_scope_max
            world_k = self.world_scope_max
            recent_window = 12
        else:
            depth = max(3, self.retrieval_topk)
            self_k = max(1, self.self_scope_max - 1)
            neighbor_k = max(1, self.neighbor_scope_max - 1)
            world_k = 1
            recent_window = 6

        return {
            "complexity": complexity,
            "retrieval_depth": depth,
            "query_keywords": query_keywords,
            "query_entities": query_entities,
            "recent_round_window": recent_window,
            "self_k": self_k,
            "neighbor_k": neighbor_k,
            "world_k": world_k,
            "include_world": self.enable_world_memory and (complexity != "LOW" or bool((self.config.get("event_config", {}) or {}).get("hot_topics"))),
        }

    def _unit_score(
        self,
        unit: Dict[str, Any],
        plan: Dict[str, Any],
        current_round: int,
        for_agent_id: int,
        scope: str,
    ) -> float:
        query_keywords = plan.get("query_keywords", set()) or set()
        query_entities = plan.get("query_entities", set()) or set()
        unit_keywords = set(unit.get("keywords", []) or [])
        keyword_sim = 0.0
        if query_keywords and unit_keywords:
            inter = len(query_keywords & unit_keywords)
            union = len(query_keywords | unit_keywords)
            keyword_sim = inter / union if union > 0 else 0.0

        unit_entities = {str(x).strip().lower() for x in (unit.get("entities", []) or []) if str(x).strip()}
        entity_sim = 0.0
        if query_entities and unit_entities:
            inter = len(query_entities & unit_entities)
            union = len(query_entities | unit_entities)
            entity_sim = inter / union if union > 0 else 0.0

        age = max(0, current_round - int(unit.get("last_round", current_round)))
        recency = math.exp(-self.recency_decay * age)
        if age > int(plan.get("recent_round_window", 12)):
            recency *= 0.7

        source_agent = int(unit.get("source_agent_id", unit.get("agent_id", -1)))
        source_weight = 1.0
        if self.topology_runtime and source_agent >= 0:
            source_weight += 0.25 * self.topology_runtime.importance_scaled.get(source_agent, 1.0)
            source_weight += 0.15 * self.topology_runtime.ppr_centrality.get(source_agent, 0.0)

        salience_score = _safe_float(unit.get("salience_score", 0.5), 0.5)
        salience_bonus = 0.9 + 0.35 * salience_score
        local_bonus = 1.2 if source_agent == for_agent_id else 1.0
        scope_bonus = {
            "self": 1.10,
            "neighbor": 1.0,
            "world": 0.95 if plan.get("complexity") == "LOW" else 1.05,
        }.get(scope, 1.0)
        count_bonus = 1.0 + 0.05 * min(6, int(unit.get("count", 1)))
        topic_bonus = 1.08 if str(unit.get("topic", "")).strip().lower() in query_keywords else 1.0

        return (
            (0.45 * keyword_sim + 0.20 * entity_sim + 0.35 * recency)
            * source_weight
            * salience_bonus
            * local_bonus
            * scope_bonus
            * count_bonus
            * topic_bonus
        )

    def _build_world_unit(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        world_unit = dict(unit)
        world_unit["scope"] = "world"
        world_unit["id"] = f"{unit.get('id')}_world"
        world_unit["supporting_ids"] = list(unit.get("supporting_ids", []) or [unit.get("id")])
        return world_unit

    def _ingest_world_unit(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "stored": False,
            "merged": False,
            "world_unit_id": None,
        }
        if not self.enable_world_memory:
            return result
        if _safe_float(unit.get("salience_score", 0.0), 0.0) < self.world_salience_threshold:
            return result

        world_unit = self._build_world_unit(unit)
        merged = False
        for old in reversed(self.world_units[-self.merge_compare_window:]):
            sim = self._unit_similarity(old, world_unit)
            if sim >= self.merge_jaccard_threshold:
                self._merge_unit(old, world_unit)
                merged = True
                result["stored"] = True
                result["merged"] = True
                result["world_unit_id"] = old.get("id")
                break
        if not merged:
            self.world_units.append(world_unit)
            result["stored"] = True
            result["world_unit_id"] = world_unit.get("id")
        if len(self.world_units) > self.max_world_units:
            self.world_units = self.world_units[-self.max_world_units:]
        return result

    def _record_memory_store(
        self,
        round_num: int,
        simulated_hour: int,
        unit: Dict[str, Any],
        merged: bool,
        merged_into_id: Optional[str],
        world_result: Dict[str, Any],
    ):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "platform": self.platform,
            "event_type": "memory_store",
            "round": round_num,
            "simulated_hour": simulated_hour,
            "agent_id": unit.get("agent_id"),
            "agent_name": unit.get("agent_name"),
            "unit_id": unit.get("id"),
            "topic": unit.get("topic"),
            "keywords": unit.get("keywords", []) or [],
            "entities": unit.get("entities", []) or [],
            "salience": unit.get("salience"),
            "salience_score": unit.get("salience_score"),
            "merged": bool(merged),
            "merged_into_id": merged_into_id,
            "world_stored": bool(world_result.get("stored")),
            "world_merged": bool(world_result.get("merged")),
            "world_unit_id": world_result.get("world_unit_id"),
            "summary": str(unit.get("summary", "") or "")[:300],
        }
        self._append_jsonl(self.memory_trace_file, payload)

    def _record_retrieval_trace(
        self,
        agent_id: int,
        current_round: int,
        plan: Dict[str, Any],
        selected: List[Tuple[str, Dict[str, Any], float]],
        memory_context: str,
        miss_reason: str = "",
    ):
        query_keywords = sorted(plan.get("query_keywords", set()) or set())
        query_entities = sorted(plan.get("query_entities", set()) or set())
        payload = {
            "timestamp": datetime.now().isoformat(),
            "platform": self.platform,
            "event_type": "retrieval",
            "round": current_round,
            "agent_id": agent_id,
            "agent_name": self._agent_display_name(agent_id),
            "plan": {
                "complexity": plan.get("complexity"),
                "retrieval_depth": plan.get("retrieval_depth"),
                "recent_round_window": plan.get("recent_round_window"),
                "self_k": plan.get("self_k"),
                "neighbor_k": plan.get("neighbor_k"),
                "world_k": plan.get("world_k"),
                "include_world": plan.get("include_world"),
                "query_keywords": query_keywords,
                "query_entities": query_entities,
            },
            "miss_reason": miss_reason,
            "selected_units": [
                {
                    "scope": scope,
                    "unit_id": unit.get("id"),
                    "source_agent_id": unit.get("source_agent_id", unit.get("agent_id")),
                    "source_agent_name": unit.get("source_agent_name", unit.get("agent_name")),
                    "topic": unit.get("topic"),
                    "keywords": unit.get("keywords", []) or [],
                    "salience_score": unit.get("salience_score"),
                    "score": round(float(score), 6),
                    "summary": str(unit.get("summary", "") or "")[:220],
                }
                for scope, unit, score in selected[:8]
            ],
            "context_preview": memory_context[:600],
        }
        self._append_jsonl(self.retrieval_trace_file, payload)

    def _top_units(self, units: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
        ranked = sorted(
            units,
            key=lambda u: (
                _safe_float(u.get("salience_score", 0.0), 0.0),
                int(u.get("count", 1) or 1),
                int(u.get("last_round", 0) or 0),
            ),
            reverse=True,
        )
        return [
            {
                "unit_id": unit.get("id"),
                "agent_id": unit.get("agent_id"),
                "agent_name": unit.get("agent_name"),
                "topic": unit.get("topic"),
                "salience_score": round(float(_safe_float(unit.get("salience_score", 0.0), 0.0)), 6),
                "count": int(unit.get("count", 1) or 1),
                "keywords": unit.get("keywords", []) or [],
                "summary": str(unit.get("summary", "") or "")[:220],
            }
            for unit in ranked[:limit]
        ]

    def record_round_state(
        self,
        round_num: int,
        simulated_hour: int,
        active_agent_ids: Optional[List[int]] = None,
    ):
        all_units: List[Dict[str, Any]] = []
        for units in self.per_agent_units.values():
            all_units.extend(units)

        payload = {
            "timestamp": datetime.now().isoformat(),
            "platform": self.platform,
            "round": round_num,
            "simulated_hour": simulated_hour,
            "active_agent_ids": [int(aid) for aid in (active_agent_ids or [])],
            "active_agent_names": [self._agent_display_name(int(aid)) for aid in (active_agent_ids or [])],
            "agents_with_memory": len(self.per_agent_units),
            "total_agent_units": sum(len(units) for units in self.per_agent_units.values()),
            "world_units": len(self.world_units),
            "top_agent_units": self._top_units(all_units),
            "top_world_units": self._top_units(self.world_units),
        }
        self._append_jsonl(self.memory_state_file, payload)
        self._write_json(self.memory_latest_file, payload)

    def _build_memory_unit(
        self,
        action_data: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Optional[Dict[str, Any]]:
        agent_id = self._coerce_int(action_data.get("agent_id"), -1)
        if agent_id is None or agent_id < 0:
            return None

        summary = self._build_memory_text(action_data)
        if not summary:
            return None

        keywords = self._extract_keywords(summary, max_count=8)
        entities = self._extract_entities(action_data)
        target_agent_ids = self._extract_target_agent_ids(action_data)
        topic = self._infer_topic(action_data, summary, keywords)
        salience_score = self._estimate_salience(action_data, topic, target_agent_ids, keywords)
        if salience_score < self.min_salience_to_store:
            return None

        self._seq += 1
        unit = {
            "id": f"{self.platform}_m_{self._seq}",
            "agent_id": agent_id,
            "source_agent_id": agent_id,
            "agent_name": action_data.get("agent_name", f"Agent_{agent_id}"),
            "source_agent_name": action_data.get("agent_name", f"Agent_{agent_id}"),
            "action_type": action_data.get("action_type", ""),
            "content": summary[:500],
            "summary": summary[:500],
            "summaries": [summary[:500]],
            "detail_units": [],
            "keywords": keywords,
            "entities": entities,
            "topic": topic,
            "timestamp": self._make_timestamp(round_num),
            "salience": self._salience_label(salience_score),
            "salience_score": round(salience_score, 4),
            "first_round": round_num,
            "last_round": round_num,
            "last_hour": simulated_hour,
            "count": 1,
            "target_agent_ids": target_agent_ids,
            "supporting_ids": [],
            "scope": "self",
        }
        unit["detail_units"] = [{
            "id": unit["id"],
            "summary": unit["summary"],
            "timestamp": unit["timestamp"],
            "action_type": unit["action_type"],
            "agent_name": unit["source_agent_name"],
        }]
        unit["supporting_ids"] = [unit["id"]]
        unit["abstract_summary"] = self._synthesize_abstract_summary(unit)
        return unit

    def ingest_round_actions(
        self,
        round_num: int,
        simulated_hour: int,
        actions: List[Dict[str, Any]]
    ):
        if not self.enabled or not actions:
            return

        for action in actions:
            unit = self._build_memory_unit(action, round_num, simulated_hour)
            if unit is None:
                continue

            agent_id = int(unit.get("agent_id", -1))
            bucket = self.per_agent_units.setdefault(agent_id, [])
            merged = False
            merged_into_id = None
            for old in reversed(bucket[-self.merge_compare_window:]):
                sim = self._unit_similarity(old, unit)
                if sim >= self.merge_jaccard_threshold:
                    self._merge_unit(old, unit)
                    merged = True
                    merged_into_id = str(old.get("id", "") or "")
                    break
            if not merged:
                bucket.append(unit)

            if len(bucket) > self.max_units_per_agent:
                self.per_agent_units[agent_id] = bucket[-self.max_units_per_agent:]

            world_result = self._ingest_world_unit(unit)
            self._record_memory_store(
                round_num=round_num,
                simulated_hour=simulated_hour,
                unit=unit,
                merged=merged,
                merged_into_id=merged_into_id,
                world_result=world_result,
            )

        self._save()

    def _build_intent_keywords(self, agent_id: int) -> set:
        intent = set()
        event_cfg = self.config.get("event_config", {}) or {}
        for topic in event_cfg.get("hot_topics", []) or []:
            if topic:
                intent.add(str(topic).strip().lower())

        if self.topology_runtime:
            profile = self.topology_runtime.profile_by_agent_id.get(agent_id, {}) or {}
            for t in profile.get("interested_topics", []) or []:
                if t:
                    intent.add(str(t).strip().lower())

        # 引入该agent最近记忆关键词作为近期意图
        recent = self.per_agent_units.get(agent_id, [])
        if recent:
            for k in (recent[-1].get("keywords", []) or []):
                if k:
                    intent.add(str(k).strip().lower())

        return {x for x in intent if x}

    def _candidate_units(self, agent_id: int, plan: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {
            "self": list(self.per_agent_units.get(agent_id, [])),
            "neighbor": [],
            "world": list(self.world_units) if plan.get("include_world") else [],
        }
        if self.topology_runtime:
            neighbors = self.topology_runtime.synthetic_adj.get(agent_id, []) or []
            for nb in neighbors[:12]:
                units = self.per_agent_units.get(nb, [])
                if units:
                    buckets["neighbor"].extend(units[-8:])
        return buckets

    def build_memory_context(self, agent_id: int, current_round: int) -> str:
        if not self.enabled:
            return ""

        plan = self._build_retrieval_plan(agent_id, current_round)
        candidate_buckets = self._candidate_units(agent_id, plan)
        if not any(candidate_buckets.values()):
            self._record_retrieval_trace(
                agent_id=agent_id,
                current_round=current_round,
                plan=plan,
                selected=[],
                memory_context="",
                miss_reason="no_candidate_units",
            )
            return ""

        selected: List[Tuple[str, Dict[str, Any], float]] = []
        for scope, limit_key in [("self", "self_k"), ("neighbor", "neighbor_k"), ("world", "world_k")]:
            scope_units = candidate_buckets.get(scope, [])
            if not scope_units:
                continue
            ranked = sorted(
                scope_units,
                key=lambda u: self._unit_score(u, plan, current_round, agent_id, scope),
                reverse=True,
            )
            for unit in ranked[: int(plan.get(limit_key, 0) or 0)]:
                score = self._unit_score(unit, plan, current_round, agent_id, scope)
                selected.append((scope, unit, score))

        if not selected:
            self._record_retrieval_trace(
                agent_id=agent_id,
                current_round=current_round,
                plan=plan,
                selected=[],
                memory_context="",
                miss_reason="no_selected_units",
            )
            return ""

        selected.sort(key=lambda x: x[2], reverse=True)

        seen = set()
        dedup_selected: List[Tuple[str, Dict[str, Any], float]] = []
        for scope, unit, score in selected:
            uid = unit.get("id")
            if uid in seen:
                continue
            seen.add(uid)
            dedup_selected.append((scope, unit, score))

        abstracts: List[str] = []
        details: List[str] = []
        for idx, (scope, u, _) in enumerate(dedup_selected):
            src_name = u.get("agent_name", f"Agent_{u.get('agent_id', '')}")
            abstract = str(u.get("abstract_summary", "") or "")[:220]
            detail = str(u.get("summary", "") or "")[:180]
            timestamp = str(u.get("timestamp", "") or "")
            action_type = str(u.get("action_type", "") or "")
            salience = str(u.get("salience", "") or "")
            if idx < self.abstract_topk and abstract:
                abstracts.append(f"- ({scope}) [{src_name}] {abstract}")
            if idx < self.detail_topk and detail:
                details.append(f"- ({scope}) [{src_name}] {action_type} @ {timestamp} [{salience}]: {detail}")

        lines: List[str] = [
            f"[Retrieval Plan] complexity={plan.get('complexity')} depth={plan.get('retrieval_depth')}",
        ]
        query_keywords = sorted(plan.get("query_keywords", set()) or set())
        if query_keywords:
            lines.append(f"[Intent Keywords] {', '.join(query_keywords[:8])}")
        if abstracts:
            lines.append(self.ABSTRACT_HEADER)
            lines.extend(abstracts)
        if details:
            lines.append(self.DETAIL_HEADER)
            lines.extend(details)

        memory_context = "\n".join(lines)[:self.max_injected_chars]
        self._record_retrieval_trace(
            agent_id=agent_id,
            current_round=current_round,
            plan=plan,
            selected=dedup_selected,
            memory_context=memory_context,
        )
        return memory_context

    def inject_context_into_agent(self, agent: Any, memory_context: str):
        if not self.enabled or not memory_context:
            return

        marker = self.MEM_MARKER
        suffix = "\n[/SimpleMem]"
        target_attrs = ["user_char", "persona", "bio", "description"]

        for attr in target_attrs:
            if not hasattr(agent, attr):
                continue
            try:
                key = (id(agent), attr)
                current = str(getattr(agent, attr) or "")
                if key not in self._agent_base_cache:
                    base = current.split(marker)[0].rstrip()
                    self._agent_base_cache[key] = base
                base_text = self._agent_base_cache[key]
                new_val = f"{base_text}{marker}{memory_context}{suffix}"
                setattr(agent, attr, new_val[:self.max_injected_chars + len(base_text) + 80])
                return
            except Exception:
                continue

        # 兜底：挂在自定义字段
        try:
            setattr(agent, "memory_context", memory_context[:self.max_injected_chars])
        except Exception:
            pass



# Public alias for external callers.
def safe_float(value: Any, default: float = 0.0) -> float:
    return _safe_float(value, default)

__all__ = [
    'TopologyAwareRuntime',
    'SimpleMemRuntime',
    'safe_float',
]
