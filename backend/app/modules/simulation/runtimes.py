"""Simulation runtimes (Strategy-style components).

Extracted from run_parallel_simulation.py to keep entry script thin and maintainable.
"""

import csv
import json
import math
import os
import random
import re
from collections import defaultdict, deque
from datetime import datetime
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
        self.known_follow_pairs: set = set()
        self.dynamic_interaction_neighbors: Dict[int, Dict[int, float]] = defaultdict(dict)
        self._dynamic_events_since_refresh = 0

        self.units: List[List[int]] = []
        self.unit_id_by_agent: Dict[int, int] = {}
        self.unit_repr_by_id: Dict[int, int] = {}

        self._build_runtime()

    def _build_runtime(self):
        self._index_agent_configs()
        self.profile_by_agent_id = self._load_platform_profiles()
        self._rebuild_agent_name_index()
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
        self.graph_pair_strength = {}
        self.graph_prior_pairs = set()
        self.graph_prior_directed = {}

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

        self.memory_file = os.path.join(simulation_dir, f"simplemem_{platform}.json")
        self.per_agent_units: Dict[int, List[Dict[str, Any]]] = {}
        self._agent_base_cache: Dict[Tuple[int, str], str] = {}
        self._seq = 0

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
                    self.per_agent_units[aid] = v
        except Exception as e:
            self.log(f"加载SimpleMem失败，使用空记忆: {e}")
            self.per_agent_units = {}
            self._seq = 0

    def _save(self):
        payload = {
            "platform": self.platform,
            "updated_at": datetime.now().isoformat(),
            "seq": self._seq,
            "per_agent_units": self.per_agent_units,
        }
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存SimpleMem失败: {e}")

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

    def _unit_similarity(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ak = set(a.get("keywords", []) or [])
        bk = set(b.get("keywords", []) or [])
        if not ak or not bk:
            return 0.0
        inter = len(ak & bk)
        union = len(ak | bk)
        return inter / union if union > 0 else 0.0

    def _merge_unit(self, base: Dict[str, Any], new_unit: Dict[str, Any]):
        base_keywords = set(base.get("keywords", []) or [])
        base_keywords.update(new_unit.get("keywords", []) or [])
        base["keywords"] = list(base_keywords)[:10]
        base["last_round"] = new_unit.get("last_round", base.get("last_round", 0))
        base["last_hour"] = new_unit.get("last_hour", base.get("last_hour", 0))
        base["count"] = int(base.get("count", 1)) + int(new_unit.get("count", 1))

        summaries = base.get("summaries", []) or []
        text = new_unit.get("summary", "")
        if text and text not in summaries:
            summaries.append(text)
        base["summaries"] = summaries[-4:]
        base["summary"] = summaries[-1] if summaries else base.get("summary", "")

    def ingest_round_actions(
        self,
        round_num: int,
        simulated_hour: int,
        actions: List[Dict[str, Any]]
    ):
        if not self.enabled or not actions:
            return

        for action in actions:
            agent_id = int(action.get("agent_id", -1))
            if agent_id < 0:
                continue

            summary = self._build_memory_text(action)
            if not summary:
                continue
            keywords = self._extract_keywords(summary, max_count=8)

            self._seq += 1
            new_unit = {
                "id": f"{self.platform}_m_{self._seq}",
                "agent_id": agent_id,
                "agent_name": action.get("agent_name", f"Agent_{agent_id}"),
                "action_type": action.get("action_type", ""),
                "summary": summary[:500],
                "summaries": [summary[:500]],
                "keywords": keywords,
                "first_round": round_num,
                "last_round": round_num,
                "last_hour": simulated_hour,
                "count": 1,
            }

            bucket = self.per_agent_units.setdefault(agent_id, [])
            merged = False
            # 在线语义合并：只看最近若干条，保持增量成本
            for old in reversed(bucket[-12:]):
                sim = self._unit_similarity(old, new_unit)
                if sim >= self.merge_jaccard_threshold:
                    self._merge_unit(old, new_unit)
                    merged = True
                    break
            if not merged:
                bucket.append(new_unit)

            if len(bucket) > self.max_units_per_agent:
                self.per_agent_units[agent_id] = bucket[-self.max_units_per_agent:]

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

    def _candidate_units(self, agent_id: int) -> List[Dict[str, Any]]:
        candidates = list(self.per_agent_units.get(agent_id, []))
        if self.topology_runtime:
            neighbors = self.topology_runtime.synthetic_adj.get(agent_id, []) or []
            # 只拿局部邻域，控制成本
            for nb in neighbors[:12]:
                units = self.per_agent_units.get(nb, [])
                if units:
                    candidates.extend(units[-8:])
        return candidates

    def _unit_score(
        self,
        unit: Dict[str, Any],
        query_keywords: set,
        current_round: int,
        for_agent_id: int
    ) -> float:
        unit_keywords = set(unit.get("keywords", []) or [])
        if query_keywords and unit_keywords:
            inter = len(query_keywords & unit_keywords)
            union = len(query_keywords | unit_keywords)
            semantic = inter / union if union > 0 else 0.0
        else:
            semantic = 0.0

        age = max(0, current_round - int(unit.get("last_round", current_round)))
        recency = math.exp(-self.recency_decay * age)

        source_agent = int(unit.get("agent_id", -1))
        source_weight = 1.0
        if self.topology_runtime and source_agent >= 0:
            source_weight += 0.25 * self.topology_runtime.importance_scaled.get(source_agent, 1.0)
            source_weight += 0.15 * self.topology_runtime.ppr_centrality.get(source_agent, 0.0)

        local_bonus = 1.2 if source_agent == for_agent_id else 1.0
        count_bonus = 1.0 + 0.05 * min(6, int(unit.get("count", 1)))
        return (0.55 * semantic + 0.45 * recency) * source_weight * local_bonus * count_bonus

    def build_memory_context(self, agent_id: int, current_round: int) -> str:
        if not self.enabled:
            return ""

        query_keywords = self._build_intent_keywords(agent_id)
        candidates = self._candidate_units(agent_id)
        if not candidates:
            return ""

        ranked = sorted(
            candidates,
            key=lambda u: self._unit_score(u, query_keywords, current_round, agent_id),
            reverse=True
        )

        selected = ranked[:self.retrieval_topk]
        lines: List[str] = []
        for u in selected:
            src_name = u.get("agent_name", f"Agent_{u.get('agent_id', '')}")
            action_type = u.get("action_type", "")
            summary = str(u.get("summary", ""))[:180]
            lines.append(f"- [{src_name}] {action_type}: {summary}")

        return "\n".join(lines)[:self.max_injected_chars]

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
