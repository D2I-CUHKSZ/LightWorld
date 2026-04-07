"""Simulation population preparation utilities.

This module adds two pieces that materially improve simulation realism:
1. Alias merge for graph entities before profile/config generation.
2. Synthetic ordinary-user augmentation so the population is not dominated by
   official/media/high-authority actors.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from uuid import uuid4

from .zep_entity_reader import EntityNode


_PERSONAL_TYPES = {
    "person",
    "student",
    "alumni",
    "professor",
    "universitystaff",
    "legalprofessional",
    "healthcareprovider",
    "socialmediainfluencer",
}

_ELITE_TYPES = {
    "mediaoutlet",
    "university",
    "governmentagency",
    "socialmediainfluencer",
    "legalprofessional",
    "healthcareprovider",
    "professor",
    "universitystaff",
}

_KINSHIP_ROLES = {
    "母亲": "mother",
    "妈妈": "mother",
    "父亲": "father",
    "爸爸": "father",
    "家属": "family",
}

_NOISY_ROLE_PREFIXES = (
    "涉事",
    "当事",
    "相关",
)

_GENERIC_PERSON_NAMES = {
    "学生",
    "教授",
    "记者",
    "老师",
}


@dataclass
class PopulationPreparationResult:
    entities: List[EntityNode]
    alias_map: Dict[str, str] = field(default_factory=dict)
    merge_groups: List[Dict[str, Any]] = field(default_factory=list)
    synthetic_entities: List[EntityNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_count": len(self.entities),
            "merged_alias_count": len(self.alias_map),
            "merge_groups": self.merge_groups,
            "synthetic_entity_count": len(self.synthetic_entities),
            "synthetic_entities": [
                {
                    "uuid": e.uuid,
                    "name": e.name,
                    "entity_type": e.get_entity_type(),
                    "summary": e.summary,
                }
                for e in self.synthetic_entities
            ],
        }


class SimulationPopulationBuilder:
    """Prepare simulation population from graph entities."""

    def prepare(
        self,
        entities: List[EntityNode],
        simulation_requirement: str,
        ordinary_ratio_target: float = 0.55,
        max_synthetic_entities: int = 24,
    ) -> PopulationPreparationResult:
        merged_entities, alias_map, merge_groups = self.merge_alias_entities(entities)
        augmented_entities, synthetic_entities = self.add_ordinary_users(
            merged_entities,
            simulation_requirement=simulation_requirement,
            ordinary_ratio_target=ordinary_ratio_target,
            max_synthetic_entities=max_synthetic_entities,
        )
        return PopulationPreparationResult(
            entities=augmented_entities,
            alias_map=alias_map,
            merge_groups=merge_groups,
            synthetic_entities=synthetic_entities,
        )

    def merge_alias_entities(
        self,
        entities: List[EntityNode],
    ) -> Tuple[List[EntityNode], Dict[str, str], List[Dict[str, Any]]]:
        if not entities:
            return [], {}, []

        index_map = {entity.uuid: idx for idx, entity in enumerate(entities)}
        parent = list(range(len(entities)))

        def find(idx: int) -> int:
            while parent[idx] != idx:
                parent[idx] = parent[parent[idx]]
                idx = parent[idx]
            return idx

        def union(a: int, b: int):
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra

        key_to_indices: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for idx, entity in enumerate(entities):
            bucket = self._entity_bucket(entity)
            for key in self._alias_keys(entity):
                key_to_indices[(bucket, key)].append(idx)

        for indices in key_to_indices.values():
            if len(indices) < 2:
                continue
            head = indices[0]
            for other in indices[1:]:
                union(head, other)

        groups: Dict[int, List[EntityNode]] = defaultdict(list)
        for idx, entity in enumerate(entities):
            groups[find(idx)].append(entity)

        merged_entities: List[EntityNode] = []
        alias_map: Dict[str, str] = {}
        merge_groups: List[Dict[str, Any]] = []
        for members in groups.values():
            if len(members) == 1:
                merged_entities.append(members[0])
                continue

            canonical = self._pick_canonical_entity(members)
            merged = self._merge_group(canonical, members)
            merged_entities.append(merged)

            canonical_uuid = merged.uuid
            original_names = [entity.name for entity in members]
            original_uuids = [entity.uuid for entity in members]
            for entity in members:
                alias_map[entity.uuid] = canonical_uuid
            merge_groups.append(
                {
                    "canonical_uuid": canonical_uuid,
                    "canonical_name": merged.name,
                    "original_names": original_names,
                    "original_uuids": original_uuids,
                }
            )

        merged_entities.sort(key=lambda entity: entity.name)
        return merged_entities, alias_map, merge_groups

    def add_ordinary_users(
        self,
        entities: List[EntityNode],
        simulation_requirement: str,
        ordinary_ratio_target: float = 0.55,
        max_synthetic_entities: int = 24,
    ) -> Tuple[List[EntityNode], List[EntityNode]]:
        if not entities:
            return [], []

        ordinary_count = 0
        elite_count = 0
        for entity in entities:
            entity_type = (entity.get_entity_type() or "").strip().lower()
            if entity_type in {"person", "student"}:
                ordinary_count += 1
            if entity_type in _ELITE_TYPES:
                elite_count += 1

        target_total = len(entities)
        synthetic_needed = 0
        if ordinary_ratio_target > 0:
            while target_total + synthetic_needed > 0 and (
                (ordinary_count + synthetic_needed) / (target_total + synthetic_needed)
            ) < ordinary_ratio_target:
                synthetic_needed += 1
                if synthetic_needed >= max_synthetic_entities:
                    break

        if synthetic_needed <= 0 and elite_count <= ordinary_count:
            return entities, []

        if synthetic_needed <= 0:
            synthetic_needed = min(max_synthetic_entities, max(4, elite_count - ordinary_count))

        topic_hints = self._topic_hints(entities, simulation_requirement)
        archetypes = self._ordinary_archetypes(topic_hints)
        synthetic_entities: List[EntityNode] = []
        for idx in range(synthetic_needed):
            archetype = archetypes[idx % len(archetypes)]
            synthetic_entities.append(
                self._build_synthetic_entity(
                    idx=idx + 1,
                    archetype=archetype,
                    topic_hints=topic_hints,
                )
            )

        return list(entities) + synthetic_entities, synthetic_entities

    def _entity_bucket(self, entity: EntityNode) -> str:
        entity_type = (entity.get_entity_type() or "").strip().lower()
        if entity_type in _PERSONAL_TYPES:
            return "personal"
        return entity_type or "generic"

    def _normalize_name(self, value: str) -> str:
        text = re.sub(r"[\s·•_/|,，;；()（）【】\[\]“”\"'`]+", "", str(value or "")).lower()
        return text

    def _organization_aliases(self, name: str) -> Set[str]:
        aliases: Set[str] = set()
        normalized = self._normalize_name(name)
        if not normalized:
            return aliases

        aliases.add(normalized)
        if re.fullmatch(r"[\u4e00-\u9fff]{3,12}", name or ""):
            if (name or "").endswith("大学"):
                aliases.add((name or "")[0] + "大")
            if (name or "").endswith("日报") and len(name or "") >= 3:
                aliases.add((name or "")[:-2])
            if (name or "").endswith("晚报") and len(name or "") >= 3:
                aliases.add((name or "")[:-2])
        return {self._normalize_name(alias) for alias in aliases if alias}

    def _masked_person_aliases(self, name: str) -> Set[str]:
        normalized = self._normalize_name(name)
        aliases = {normalized}
        if "某" in name:
            aliases.add(self._normalize_name(name.replace("某", "")))
            if len(name) >= 2:
                aliases.add(self._normalize_name(name[0] + name[-1]))
        stripped = normalized
        for prefix in _NOISY_ROLE_PREFIXES:
            stripped = stripped.removeprefix(self._normalize_name(prefix))
        aliases.add(stripped)
        return {alias for alias in aliases if alias and len(alias) >= 2}

    def _kinship_alias_key(self, entity: EntityNode) -> Optional[str]:
        role_key = None
        for raw, canonical in _KINSHIP_ROLES.items():
            if raw in entity.name:
                role_key = canonical
                break
        if role_key is None:
            return None

        related_candidates = []
        for node in entity.related_nodes or []:
            name = str(node.get("name", "") or "").strip()
            if not name:
                continue
            related_candidates.append(self._normalize_name(name))
        if related_candidates:
            return f"{role_key}:{related_candidates[0]}"
        return None

    def _alias_keys(self, entity: EntityNode) -> Set[str]:
        name = entity.name or ""
        entity_type = (entity.get_entity_type() or "").strip().lower()
        keys: Set[str] = {self._normalize_name(name)}
        if entity_type in _PERSONAL_TYPES:
            keys.update(self._masked_person_aliases(name))
            kinship_key = self._kinship_alias_key(entity)
            if kinship_key:
                keys.add(kinship_key)
        else:
            keys.update(self._organization_aliases(name))
        return {key for key in keys if key and len(key) >= 2}

    def _pick_canonical_entity(self, members: List[EntityNode]) -> EntityNode:
        def score(entity: EntityNode) -> Tuple[int, int, int]:
            name = entity.name or ""
            masked_penalty = name.count("某")
            generic_penalty = 1 if name in _GENERIC_PERSON_NAMES else 0
            abbreviation_penalty = 1 if len(name) <= 2 else 0
            return (
                generic_penalty,
                masked_penalty,
                abbreviation_penalty,
                -len(name),
            )

        return sorted(members, key=score)[0]

    def _merge_group(self, canonical: EntityNode, members: List[EntityNode]) -> EntityNode:
        labels = []
        seen_labels = set()
        for entity in members:
            for label in entity.labels:
                if label in seen_labels:
                    continue
                seen_labels.add(label)
                labels.append(label)

        summaries = []
        seen_summary = set()
        for entity in members:
            text = str(entity.summary or "").strip()
            if not text or text in seen_summary:
                continue
            seen_summary.add(text)
            summaries.append(text)

        merged_attributes: Dict[str, Any] = dict(canonical.attributes or {})
        alias_names: List[str] = []
        merged_uuids: List[str] = []
        for entity in members:
            merged_uuids.append(entity.uuid)
            if entity.name != canonical.name:
                alias_names.append(entity.name)
            for key, value in (entity.attributes or {}).items():
                if key not in merged_attributes or merged_attributes[key] in (None, "", [], {}):
                    merged_attributes[key] = value

        if alias_names:
            merged_attributes["aliases"] = sorted(set(alias_names))
        merged_attributes["merged_entity_uuids"] = merged_uuids

        merged_related_edges = self._dedup_dicts(
            edge
            for entity in members
            for edge in (entity.related_edges or [])
        )
        merged_related_nodes = self._dedup_dicts(
            node
            for entity in members
            for node in (entity.related_nodes or [])
        )

        merged_summary = " | ".join(summaries[:4])
        return EntityNode(
            uuid=canonical.uuid,
            name=canonical.name,
            labels=labels,
            summary=merged_summary or canonical.summary,
            attributes=merged_attributes,
            related_edges=merged_related_edges,
            related_nodes=merged_related_nodes,
        )

    def _dedup_dicts(self, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = tuple(sorted((k, str(v)) for k, v in item.items()))
            if key in seen:
                continue
            seen.add(key)
            results.append(dict(item))
        return results

    def _topic_hints(self, entities: List[EntityNode], simulation_requirement: str) -> List[str]:
        counter: Counter[str] = Counter()
        for entity in entities:
            for token in re.findall(r"[\u4e00-\u9fff]{2,8}", f"{entity.name} {entity.summary or ''}"):
                if token in {"武汉大学", "学生", "事件相关", "相关事项", "相关实体"}:
                    continue
                counter[token] += 1
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}", simulation_requirement or ""):
            counter[token] += 2
        topics = [token for token, _ in counter.most_common(8)]
        return topics[:6] or ["程序正义", "校园舆情", "事实核查"]

    def _ordinary_archetypes(self, topic_hints: List[str]) -> List[Dict[str, Any]]:
        primary = topic_hints[0] if topic_hints else "校园舆情"
        secondary = topic_hints[1] if len(topic_hints) > 1 else "程序正义"
        tertiary = topic_hints[2] if len(topic_hints) > 2 else "事实核查"
        return [
            {
                "name_prefix": "围观学生",
                "label": "Student",
                "segment": "campus_observer",
                "summary": f"普通在校学生，关注{primary}与{secondary}，容易被同伴讨论和热门帖带动，会发短评和跟帖求证。",
                "stance": "uncertain",
                "topics": [primary, secondary, "校园讨论"],
            },
            {
                "name_prefix": "求证型网友",
                "label": "Person",
                "segment": "fact_checker",
                "summary": f"普通网民，习惯核对截图和时间线，重点关注{tertiary}与{secondary}，倾向追问来源和证据链。",
                "stance": "procedural",
                "topics": [tertiary, secondary, "证据链"],
            },
            {
                "name_prefix": "情绪型路人",
                "label": "Person",
                "segment": "emotional_bystander",
                "summary": f"普通围观用户，先看情绪和立场，再补看细节，容易被{primary}相关内容激发强烈表达。",
                "stance": "emotional",
                "topics": [primary, "情绪表达", "站队"],
            },
            {
                "name_prefix": "校友观察者",
                "label": "Person",
                "segment": "alumni_like",
                "summary": f"普通校友型用户，关注学校声誉、{secondary}和制度修复，倾向提出建设性意见。",
                "stance": "constructive",
                "topics": ["校誉", secondary, "制度修复"],
            },
            {
                "name_prefix": "家长视角用户",
                "label": "Person",
                "segment": "parent_view",
                "summary": f"普通家长型用户，关心学生安全、{primary}和学校处理方式，反感网暴和失控舆论。",
                "stance": "protective",
                "topics": ["学生安全", primary, "反网暴"],
            },
            {
                "name_prefix": "吃瓜转发用户",
                "label": "Person",
                "segment": "amplifier",
                "summary": f"普通社交媒体用户，偏好快速转发热帖，对{primary}和爆点信息反应快，但不一定深挖事实。",
                "stance": "amplifying",
                "topics": [primary, "热点转发", "爆点信息"],
            },
        ]

    def _build_synthetic_entity(
        self,
        idx: int,
        archetype: Dict[str, Any],
        topic_hints: List[str],
    ) -> EntityNode:
        name_prefix = str(archetype["name_prefix"])
        label = str(archetype["label"])
        segment = str(archetype["segment"])
        name = f"{name_prefix}{idx:02d}"
        summary = str(archetype["summary"])
        attributes = {
            "synthetic_population": True,
            "population_segment": segment,
            "stance_anchor": archetype.get("stance", "neutral"),
            "topic_hints": archetype.get("topics", [])[:4],
            "source": "synthetic_ordinary_population",
        }
        return EntityNode(
            uuid=f"synthetic_{segment}_{uuid4().hex[:12]}",
            name=name,
            labels=["Entity", label],
            summary=summary,
            attributes=attributes,
            related_edges=[],
            related_nodes=[],
        )
