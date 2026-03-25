"""
实体语义提示提取器
参考 LightRAG 的信息蒸馏风格，为每个实体生成可用于聚类/检索的 prompts。
"""

import json
import re
from typing import Dict, Any, List, Optional, Callable

from ..infrastructure.llm_client import LLMClient
from ..infrastructure.logger import get_logger
from .zep_entity_reader import EntityNode

logger = get_logger("mirofish.entity_prompt_extractor")


class EntityPromptExtractor:
    """为实体提取 keywords + semantic prompt 的轻量服务"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
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
1. 提取 3-8 个高辨识关键词（keywords），优先实体主题词，不要空泛词。
2. 写 1 段简洁描述（description），突出该实体的角色/立场/语义边界。
3. 生成 1 条可用于检索和聚类的 semantic_prompt（1-2句）。
4. 给出 2-6 个 topic_tags（话题标签）。

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
                "content": "你是图谱语义抽取助手，输出必须是可解析JSON。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

    def _simple_keywords(self, text: str, max_count: int = 8) -> List[str]:
        text = (text or "").lower()
        tokens = re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]{2,}", text)
        stopwords = {
            "entity", "node", "this", "that", "with", "from", "for", "and", "the",
            "一个", "这个", "相关", "信息", "内容", "描述", "实体"
        }

        freq: Dict[str, int] = {}
        for t in tokens:
            if t in stopwords:
                continue
            freq[t] = freq.get(t, 0) + 1

        items = sorted(freq.items(), key=lambda x: (-x[1], len(x[0])))
        return [k for k, _ in items[:max_count]]

    def _fallback(self, entity: EntityNode) -> Dict[str, Any]:
        entity_type = entity.get_entity_type() or "Entity"
        raw_text = " ".join([
            entity.name or "",
            entity_type,
            entity.summary or "",
            json.dumps(entity.attributes or {}, ensure_ascii=False)
        ])
        keywords = self._simple_keywords(raw_text, max_count=6)

        return {
            "keywords": keywords,
            "description": (entity.summary or f"{entity_type}: {entity.name}")[:220],
            "semantic_prompt": f"实体 {entity.name}（类型: {entity_type}）。关注其核心语义、关联角色与事件影响。",
            "topic_tags": keywords[:4]
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

        # 去重并裁剪
        dedup_keywords = []
        seen = set()
        for k in keywords:
            kk = str(k).strip()
            if not kk:
                continue
            lower = kk.lower()
            if lower in seen:
                continue
            seen.add(lower)
            dedup_keywords.append(kk)
            if len(dedup_keywords) >= 8:
                break

        dedup_tags = []
        seen_tags = set()
        for t in topic_tags:
            tt = str(t).strip()
            if not tt:
                continue
            lower = tt.lower()
            if lower in seen_tags:
                continue
            seen_tags.add(lower)
            dedup_tags.append(tt)
            if len(dedup_tags) >= 6:
                break

        entity_type = entity.get_entity_type() or "Entity"
        description = str(data.get("description", "")).strip()
        semantic_prompt = str(data.get("semantic_prompt", "")).strip()

        if not description:
            description = (entity.summary or f"{entity_type}: {entity.name}")[:220]
        if not semantic_prompt:
            semantic_prompt = f"实体 {entity.name}（类型: {entity_type}），总结其立场、功能与关键关联。"
        if not dedup_keywords:
            dedup_keywords = self._simple_keywords(
                f"{entity.name} {entity.summary or ''}", max_count=6
            )

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

