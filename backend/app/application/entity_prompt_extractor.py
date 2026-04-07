"""
实体语义提示提取器
参考 LightRAG 的信息蒸馏风格，为每个实体生成可用于聚类/检索的 prompts。
"""

import json
import re
from collections import defaultdict
from typing import Callable, Dict, Any, Iterable, List, Optional, Tuple

from ..infrastructure.llm_client import LLMClient
from ..infrastructure.logger import get_logger
from ..config import Config
from .zep_entity_reader import EntityNode

logger = get_logger("mirofish.entity_prompt_extractor")


class EntityPromptExtractor:
    """为实体提取 keywords + semantic prompt 的轻量服务"""

    _GENERIC_STOPWORDS = {
        "entity", "node", "this", "that", "with", "from", "for", "and", "the",
        "一个", "这个", "相关", "信息", "内容", "描述", "实体", "事项", "事件相关方之一", "评论",
        "其中", "关于", "以及", "进行", "用于", "总结", "关注", "核心", "影响", "表示",
    }
    _EN_STOPWORDS = {
        "a", "an", "as", "at", "by", "for", "from", "in", "into", "is", "it",
        "of", "on", "or", "to", "up", "via", "no", "not", "none", "null",
        "true", "false", "unknown", "other", "others",
    }
    _SCHEMA_NOISE = {
        "name", "names", "type", "types", "label", "labels", "summary",
        "description", "attributes", "attribute", "fact", "facts", "keyword",
        "keywords", "topic", "topics", "topic_tags", "semantic_prompt",
        "entity_uuid", "entity_name", "entity_type", "source", "target",
        "source_node_uuid", "target_node_uuid", "id", "uuid", "value", "values",
        "media_type", "jurisdiction", "specialty", "institution", "case_role",
        "bar_association", "organization_type", "platform_handle",
        "content_niche", "role", "department", "title", "research_field",
        "full_name", "org_name", "location", "student_id", "enrollment_year",
        "school_college", "nationality", "profession", "created_at", "updated_at",
        "analysis_summary",
    }
    _TOKEN_SPLIT_RE = re.compile(r"[\s,，;；/|]+")
    _PHRASE_SPLIT_RE = re.compile(r"[，,。；;、/\n\r\t（）()【】\[\]<>《》“”\"':：!?！？]+")
    _CN_CONNECTOR_RE = re.compile(
        r"(?:围绕|呼吁|认为|指出|刊发|报道|决定|启动|进行|公开|持续|发声|强调|说明|回应|推动|引发|"
        r"对于|关于|并在|并且|以及|同时|并|和|与|及|在|将|已|仍|被|于|由|等)"
    )
    _CN_SECONDARY_SPLIT_RE = re.compile(r"(?:成为|的|之|与|和|及|并|在|对|就|让|将|把|被|从|向|同)")
    _TEMPORAL_RE = re.compile(
        r"^(?:(?:19|20)\d{2}|(?:19|20)\d{2}[-_/年]\d{1,2}(?:[-_/月]\d{1,2}[日号]?)?)$"
    )
    _NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")
    _EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,20}")
    _LEADING_ACTION_PREFIXES = (
        "评论", "报道", "刊发", "呼吁", "指出", "认为", "强调", "说明", "回应",
        "决定", "启动", "进行", "公开", "持续", "推动", "引发", "不要让",
    )
    _CLAUSE_NOISE_MARKERS = (
        "相关方之一", "事件时", "事件中", "根据", "表示", "宣布", "implied",
        "based on", "note", "though no explicit", "only his name",
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        use_llm: Optional[bool] = None,
    ):
        self.use_llm = (
            Config.SIMULATION_ENTITY_PROMPTS_USE_LLM
            if use_llm is None
            else bool(use_llm)
        )
        self.llm = None
        if self.use_llm:
            self.llm = LLMClient(
                api_key=api_key,
                base_url=base_url,
                model=model_name
            )

    def _build_messages(self, entity: EntityNode, simulation_requirement: str = "") -> List[Dict[str, str]]:
        entity_type = entity.get_entity_type() or "Entity"
        related_nodes = [n.get("name", "") for n in (entity.related_nodes or [])[:8] if n.get("name")]
        related_facts = [e.get("fact", "") for e in (entity.related_edges or [])[:8] if e.get("fact")]

        attrs = entity.attributes or {}
        attrs_preview = json.dumps(attrs, ensure_ascii=False)[:1500]

        prompt = f"""
你需要为一个图谱实体生成结构化语义提示，风格参考 LightRAG 的“实体摘要 + 关键词”抽取方式。

【任务要求】
1. 提取 4-8 个高辨识关键词（keywords），优先实体主题词、角色词、议题词，不要空泛词。
2. 写 1 段简洁描述（description），突出该实体的角色/立场/语义边界。
3. 生成 1 条可用于检索和聚类的 semantic_prompt（1-2句）。
4. 给出 2-6 个 topic_tags（话题标签）。
5. 关键词必须避免以下内容：
   - 占位词或空值：null / none / unknown
   - JSON字段名、schema字段、英文属性名：name / media_type / case_role / institution 等
   - 纯日期、纯数字、时间碎片：2025 / 08 / 07-30 / 2025-08-01
   - 过长的完整句子或带明显语法残片的短语

【实体信息】
- name: {entity.name}
- type: {entity_type}
- summary: {entity.summary or ""}
- attributes: {attrs_preview}
- related_nodes: {related_nodes}
- related_facts: {related_facts}
- simulation_requirement: {simulation_requirement or ""}

仅返回 JSON，对应字段如下：
{{
  "keywords": ["..."],
  "description": "...",
  "semantic_prompt": "...",
  "topic_tags": ["..."]
}}
""".strip()

        return [
            {
                "role": "system",
                "content": "你是图谱语义抽取助手，输出必须是高质量、可解析的JSON。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _normalize_token(self, token: str) -> str:
        token = self._normalize_text(token)
        token = token.strip(" \t\r\n\"'`“”‘’[]{}()<>.,，。:：;；!?！？-_")
        return token

    def _entity_name_variants(self, entity: EntityNode) -> set:
        variants = set()
        for part in re.split(r"[／/|·•,，;；（）()【】\[\]\s]+", entity.name or ""):
            normalized = self._normalize_token(part)
            if len(normalized) >= 2:
                variants.add(normalized.lower())
        normalized_name = self._normalize_token(entity.name or "")
        if normalized_name:
            variants.add(normalized_name.lower())
        return variants

    def _is_noise_token(self, token: str, entity: EntityNode) -> bool:
        normalized = self._normalize_token(token)
        if len(normalized) < 2:
            return True

        lower = normalized.lower()
        if lower in self._GENERIC_STOPWORDS or lower in self._EN_STOPWORDS or lower in self._SCHEMA_NOISE:
            return True
        if self._NUMERIC_RE.fullmatch(lower):
            return True
        if self._TEMPORAL_RE.fullmatch(lower):
            return True
        if lower.startswith(("http://", "https://", "www.")):
            return True
        if "_" in lower and lower == re.sub(r"[^a-z0-9_]", "", lower):
            return True
        if lower.endswith(("_id", "_uuid", "_name", "_type", "_role", "_time", "_date", "_count")):
            return True
        if lower == (entity.get_entity_type() or "").strip().lower():
            return True
        if len(lower) <= 2 and not re.search(r"[\u4e00-\u9fff]", lower):
            return True
        if re.fullmatch(r"[a-z][a-z0-9\-]{2,20}", lower) and lower not in {"ptsd", "phd", "mba", "ai"}:
            return True
        if re.fullmatch(r"(?:19|20)\d{2}(?:\d{2})?", lower):
            return True
        if any(marker in lower for marker in self._CLAUSE_NOISE_MARKERS):
            return True
        if " " in normalized and re.search(r"[A-Za-z]", normalized):
            return True
        if normalized.endswith(("在", "中", "时", "后", "前")) and len(normalized) > 3:
            return True
        return False

    def _flatten_attribute_values(self, value: Any) -> Iterable[str]:
        if value is None:
            return
        if isinstance(value, str):
            text = self._normalize_text(value)
            if text:
                yield text
            return
        if isinstance(value, (int, float, bool)):
            yield str(value)
            return
        if isinstance(value, list):
            for item in value:
                yield from self._flatten_attribute_values(item)
            return
        if isinstance(value, dict):
            for nested in value.values():
                yield from self._flatten_attribute_values(nested)

    def _extract_text_candidates(self, text: str) -> List[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        candidates: List[str] = []
        for phrase in self._PHRASE_SPLIT_RE.split(normalized):
            phrase = self._normalize_text(phrase)
            if not phrase:
                continue
            phrase = re.sub(r"(?:19|20)\d{2}[-_/年]\d{1,2}(?:[-_/月]\d{1,2}[日号]?)?", " ", phrase)
            phrase = re.sub(r"(?:19|20)\d{2}", " ", phrase)
            for part in self._CN_CONNECTOR_RE.split(phrase):
                part = self._normalize_token(part)
                for prefix in self._LEADING_ACTION_PREFIXES:
                    if part.startswith(prefix) and len(part) - len(prefix) >= 2:
                        part = part[len(prefix):]
                        break
                if 2 <= len(part) <= 12:
                    candidates.append(part)
                elif len(part) > 8:
                    for sub in self._CN_SECONDARY_SPLIT_RE.split(part):
                        sub = self._normalize_token(sub)
                        if 2 <= len(sub) <= 8:
                            candidates.append(sub)

        for token in self._EN_TOKEN_RE.findall(normalized):
            token = self._normalize_token(token)
            if token:
                candidates.append(token)
        return candidates

    def _add_candidate(
        self,
        scores: Dict[str, float],
        surfaces: Dict[str, str],
        entity: EntityNode,
        candidate: str,
        score: float,
    ):
        normalized = self._normalize_token(candidate)
        if self._is_noise_token(normalized, entity):
            return

        key = normalized.lower()
        scores[key] += score
        existing = surfaces.get(key, "")
        if not existing or len(normalized) < len(existing):
            surfaces[key] = normalized

    def _rank_keywords(self, entity: EntityNode, max_count: int = 8) -> List[str]:
        entity_type = entity.get_entity_type() or "Entity"
        name_variants = self._entity_name_variants(entity)
        scores: Dict[str, float] = defaultdict(float)
        surfaces: Dict[str, str] = {}

        def add_many(items: Iterable[str], base_score: float):
            for idx, item in enumerate(items):
                self._add_candidate(
                    scores=scores,
                    surfaces=surfaces,
                    entity=entity,
                    candidate=item,
                    score=max(0.5, base_score - idx * 0.15),
                )

        normalized_name = self._normalize_token(entity.name or "")
        if normalized_name:
            self._add_candidate(scores, surfaces, entity, normalized_name, 10.0)

        attr_candidates: List[str] = []
        for value in self._flatten_attribute_values(entity.attributes or {}):
            normalized = self._normalize_text(value)
            if not normalized:
                continue
            if 2 <= len(normalized) <= 12:
                attr_candidates.append(normalized)
            attr_candidates.extend(self._extract_text_candidates(normalized))
        add_many(attr_candidates, 6.5)

        related_names = [
            self._normalize_text(node.get("name", ""))
            for node in (entity.related_nodes or [])
            if node.get("name")
        ]
        add_many(related_names, 4.8)

        summary_candidates = self._extract_text_candidates(entity.summary or "")
        add_many(summary_candidates, 4.2)

        for edge in (entity.related_edges or [])[:8]:
            fact = self._normalize_text(edge.get("fact", ""))
            add_many(self._extract_text_candidates(fact), 2.2)
            edge_name = self._normalize_text(edge.get("name", ""))
            add_many([edge_name], 1.4)

        filtered: List[Tuple[str, float]] = []
        for key, score in scores.items():
            surface = surfaces[key]
            bonus = 0.0
            if key in name_variants:
                bonus += 3.0
            if re.search(r"[\u4e00-\u9fff]", surface):
                bonus += 0.2
            if len(surface) <= 3:
                bonus -= 0.3
            if surface.lower() == entity_type.lower():
                bonus -= 1.0
            filtered.append((surface, score + bonus))

        filtered.sort(key=lambda item: (-item[1], len(item[0]), item[0]))

        result: List[str] = []
        seen = set()
        for token, _ in filtered:
            lower = token.lower()
            if lower in seen:
                continue
            seen.add(lower)
            result.append(token)
            if len(result) >= max_count:
                break
        return result

    def _fallback(self, entity: EntityNode) -> Dict[str, Any]:
        entity_type = entity.get_entity_type() or "Entity"
        keywords = self._rank_keywords(entity, max_count=6)

        description = self._normalize_text(entity.summary or "")
        if not description:
            description = f"{entity_type}: {entity.name}"
        description = description[:220]

        topic_tags = [kw for kw in keywords if kw.lower() != (entity.name or "").strip().lower()][:4]
        if not topic_tags:
            topic_tags = keywords[:4]

        return {
            "keywords": keywords,
            "description": description,
            "semantic_prompt": (
                f"实体 {entity.name}（类型: {entity_type}）。"
                f"重点关注其角色定位、相关议题与关键关联词：{', '.join(keywords[:4])}。"
            ),
            "topic_tags": topic_tags
        }

    def _normalize(self, entity: EntityNode, data: Dict[str, Any]) -> Dict[str, Any]:
        keywords = data.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in re.split(r"[，,;；\s]+", keywords) if k.strip()]
        if not isinstance(keywords, list):
            keywords = []

        topic_tags = data.get("topic_tags", [])
        if isinstance(topic_tags, str):
            topic_tags = [k.strip() for k in re.split(r"[，,;；\s]+", topic_tags) if k.strip()]
        if not isinstance(topic_tags, list):
            topic_tags = []

        entity_type = entity.get_entity_type() or "Entity"
        description = self._normalize_text(data.get("description", ""))
        semantic_prompt = self._normalize_text(data.get("semantic_prompt", ""))

        heuristic_keywords = self._rank_keywords(entity, max_count=8)
        merged_scores: Dict[str, float] = defaultdict(float)
        merged_surfaces: Dict[str, str] = {}

        def add_ranked(items: List[str], base: float):
            for idx, item in enumerate(items):
                normalized = self._normalize_token(item)
                if self._is_noise_token(normalized, entity):
                    continue
                key = normalized.lower()
                merged_scores[key] += max(0.5, base - idx * 0.2)
                existing = merged_surfaces.get(key, "")
                if not existing or len(normalized) < len(existing):
                    merged_surfaces[key] = normalized

        normalized_name = self._normalize_token(entity.name or "")
        if normalized_name:
            add_ranked([normalized_name], 12.0)
        add_ranked(keywords, 9.0)
        add_ranked(topic_tags, 6.5)
        add_ranked(heuristic_keywords, 7.5)

        dedup_keywords = [
            merged_surfaces[key]
            for key, _ in sorted(
                merged_scores.items(),
                key=lambda item: (-item[1], len(merged_surfaces[item[0]]), merged_surfaces[item[0]]),
            )[:8]
        ]

        dedup_tags: List[str] = []
        seen_tags = set()
        for item in topic_tags + heuristic_keywords:
            normalized = self._normalize_token(item)
            if self._is_noise_token(normalized, entity):
                continue
            lower = normalized.lower()
            if lower in seen_tags:
                continue
            seen_tags.add(lower)
            dedup_tags.append(normalized)
            if len(dedup_tags) >= 6:
                break

        if not description:
            description = (entity.summary or f"{entity_type}: {entity.name}")[:220]
        if not semantic_prompt:
            semantic_prompt = f"实体 {entity.name}（类型: {entity_type}），总结其立场、功能与关键关联。"
        if not dedup_keywords:
            dedup_keywords = heuristic_keywords[:6]
        if not dedup_tags:
            dedup_tags = [kw for kw in dedup_keywords if kw.lower() != normalized_name.lower()][:4]
            if not dedup_tags:
                dedup_tags = dedup_keywords[:4]

        return {
            "entity_uuid": entity.uuid,
            "entity_name": entity.name,
            "entity_type": entity_type,
            "keywords": dedup_keywords,
            "description": description,
            "semantic_prompt": semantic_prompt,
            "topic_tags": dedup_tags
        }

    def extract_prompt_for_entity(
        self,
        entity: EntityNode,
        simulation_requirement: str = ""
    ) -> Dict[str, Any]:
        if not self.use_llm or self.llm is None:
            return self._normalize(entity, self._fallback(entity))
        try:
            messages = self._build_messages(entity, simulation_requirement)
            result = self.llm.chat_json(messages=messages, temperature=0.2, max_tokens=1000)
            return self._normalize(entity, result)
        except Exception as e:
            logger.warning(f"实体 {entity.name} prompt 提取失败，使用回退: {e}")
            return self._normalize(entity, self._fallback(entity))

    def extract_prompts(
        self,
        entities: List[EntityNode],
        simulation_requirement: str = "",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict[str, Any]]:
        total = len(entities)
        results: List[Dict[str, Any]] = []

        for idx, entity in enumerate(entities, start=1):
            prompt_data = self.extract_prompt_for_entity(
                entity=entity,
                simulation_requirement=simulation_requirement
            )
            results.append(prompt_data)

            if progress_callback:
                progress_callback(idx, total, f"提取实体prompt: {entity.name}")

        return results

    def save_prompts(self, prompts: List[Dict[str, Any]], file_path: str):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
        logger.info(f"实体 prompts 已保存: {file_path}, count={len(prompts)}")
