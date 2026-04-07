"""Keyword extraction helpers for SimpleMem.

The goal here is not generic keyword mining from raw text. We prefer
high-signal structured candidates and aggressive noise filtering so the
memory layer does not amplify URLs, field names, dates, or templated junk.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional


class MemoryKeywordExtractor:
    _GENERIC_STOPWORDS = {
        "相关", "信息", "内容", "情况", "事项", "事件", "问题", "方面", "进行", "持续",
        "官方", "通报", "说明", "依据", "表示", "发布", "指出", "认为", "回应",
        "强调", "更新", "内容", "帖子", "评论", "平台", "用户", "作者", "文本",
        "一个", "这个", "那个", "其中", "全部", "当前", "后续", "今日", "目前",
        "please", "latest", "update", "general",
    }
    _SCHEMA_NOISE = {
        "content", "query", "post", "comment", "user", "agent", "author",
        "post_content", "comment_content", "original_content", "quote_content",
        "target_user_name", "post_author_name", "comment_author_name",
        "original_author_name", "target_agent_id", "post_author_agent_id",
        "comment_author_agent_id", "original_author_agent_id", "action_type",
        "rowid", "post_id", "comment_id", "follow_id", "like_id", "dislike_id",
        "event_type", "created_at", "updated_at", "source_agent_id", "unit_id",
        "summary", "keywords", "entities", "topic", "scope", "world", "self",
        "neighbor", "counter", "query_keywords", "query_entities",
    }
    _ACTION_NOISE = {
        "create_post", "create_comment", "like_post", "like_comment",
        "dislike_post", "dislike_comment", "repost", "quote_post", "follow",
        "search_posts", "search_user", "do_nothing", "mute", "trend", "refresh",
    }
    _DOMAIN_NOISE = {
        "http", "https", "www", "com", "cn", "edu", "org", "net", "html",
        "htm", "php", "jsp", "hk", "uk", "gov", "pdf", "jpg", "png",
    }
    _ALLOWLIST_EN = {
        "ptsd", "llm", "api", "mbti", "phd", "硕士", "博士",
    }
    _NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")
    _TEMPORAL_RE = re.compile(
        r"^(?:(?:19|20)\d{2}|(?:19|20)\d{2}[-_/年]\d{1,2}(?:[-_/月]\d{1,2}[日号]?)?)$"
    )
    _URL_RE = re.compile(r"https?://\S+|www\.\S+")
    _PHRASE_SPLIT_RE = re.compile(r"[，,。；;、/\n\r\t（）()【】\[\]<>《》“”\"':：!?！？]+")
    _CN_CONNECTOR_RE = re.compile(
        r"(?:围绕|呼吁|认为|指出|刊发|报道|决定|启动|进行|公开|持续|发声|强调|说明|回应|推动|"
        r"引发|对于|关于|并在|并且|以及|同时|并|和|与|及|在|将|已|仍|被|于|由|等)"
    )
    _CN_SECONDARY_SPLIT_RE = re.compile(r"(?:成为|的|之|与|和|及|并|在|就|让|将|把|被|从|向|同)")
    _EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,20}")
    _CN_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")

    def __init__(
        self,
        config: Dict[str, Any],
        topology_runtime: Optional[Any] = None,
    ):
        self.config = config
        self.topology_runtime = topology_runtime

    def extract(
        self,
        action_data: Dict[str, Any],
        summary: str,
        target_agent_ids: List[int],
        max_count: int = 8,
    ) -> List[str]:
        scores: Dict[str, float] = defaultdict(float)
        surfaces: Dict[str, str] = {}

        source_agent_id = self._safe_int(action_data.get("agent_id"), default=-1)
        action_args = action_data.get("action_args", {}) or {}

        # Highest priority: actor / target names.
        for name in self._structured_names(action_data):
            self._add_candidate(scores, surfaces, name, 10.0)

        # Source agent semantic hints.
        if self.topology_runtime and source_agent_id >= 0:
            self._add_ranked(
                scores,
                surfaces,
                [self.topology_runtime.agent_entity_name.get(source_agent_id, "")],
                9.5,
            )
            self._add_ranked(
                scores,
                surfaces,
                sorted(self.topology_runtime.agent_semantic_keywords.get(source_agent_id, set())),
                7.8,
            )
            source_profile = self.topology_runtime.profile_by_agent_id.get(source_agent_id, {}) or {}
            self._add_ranked(
                scores,
                surfaces,
                list(source_profile.get("interested_topics", []) or []),
                6.6,
            )

        # Target agents are also strong candidates.
        if self.topology_runtime:
            for idx, aid in enumerate(target_agent_ids[:4]):
                self._add_ranked(
                    scores,
                    surfaces,
                    [self.topology_runtime.agent_entity_name.get(aid, "")],
                    8.2 - idx * 0.3,
                )
                self._add_ranked(
                    scores,
                    surfaces,
                    sorted(self.topology_runtime.agent_semantic_keywords.get(aid, set())),
                    6.2 - idx * 0.2,
                )

        # Hot topics that are actually mentioned in the summary should be lifted.
        summary_lower = str(summary or "").lower()
        for topic in self._hot_topics():
            if topic.lower() in summary_lower:
                self._add_candidate(scores, surfaces, topic, 8.6)

        # Pull short phrases from key text fields, but with much lower weight.
        weighted_text_fields = [
            ("content", 3.5),
            ("query", 3.2),
            ("quote_content", 2.8),
            ("post_content", 2.4),
            ("comment_content", 2.3),
            ("original_content", 2.1),
        ]
        for field_name, weight in weighted_text_fields:
            text = action_args.get(field_name, "")
            if not text:
                continue
            self._add_ranked(scores, surfaces, self._extract_text_candidates(str(text)), weight)

        # Backstop with summary phrases, but keep them below structured sources.
        self._add_ranked(scores, surfaces, self._extract_text_candidates(summary), 2.0)

        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], len(surfaces[item[0]]), surfaces[item[0]]),
        )
        results: List[str] = []
        seen = set()
        for key, _ in ranked:
            value = surfaces[key]
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            results.append(value)
            if len(results) >= max_count:
                break
        return results

    def _structured_names(self, action_data: Dict[str, Any]) -> List[str]:
        args = action_data.get("action_args", {}) or {}
        names = [action_data.get("agent_name", "")]
        for key in [
            "target_user_name",
            "post_author_name",
            "comment_author_name",
            "original_author_name",
            "parent_author_name",
        ]:
            names.append(args.get(key, ""))

        results: List[str] = []
        for item in names:
            canonical = self._canonicalize_name(item)
            if canonical:
                results.append(canonical)
        return results

    def _hot_topics(self) -> List[str]:
        event_cfg = self.config.get("event_config", {}) or {}
        return [str(x).strip() for x in (event_cfg.get("hot_topics", []) or []) if str(x).strip()]

    def _canonicalize_name(self, value: Any) -> str:
        text = self._normalize_text(value)
        if not text:
            return ""
        if self.topology_runtime and hasattr(self.topology_runtime, "_normalize_agent_name"):
            key = self.topology_runtime._normalize_agent_name(text)
            if key:
                aid = self.topology_runtime.agent_id_by_name.get(key)
                if aid is not None:
                    canonical = self.topology_runtime.agent_entity_name.get(aid, "") or text
                    return self._normalize_text(canonical)
        return text

    def _extract_text_candidates(self, text: str) -> List[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []
        normalized = self._URL_RE.sub(" ", normalized)
        normalized = re.sub(r"(?:19|20)\d{2}[-_/年]\d{1,2}(?:[-_/月]\d{1,2}[日号]?)?", " ", normalized)
        normalized = re.sub(r"(?:19|20)\d{2}", " ", normalized)

        candidates: List[str] = []
        for phrase in self._PHRASE_SPLIT_RE.split(normalized):
            phrase = self._normalize_text(phrase)
            if not phrase:
                continue
            for part in self._CN_CONNECTOR_RE.split(phrase):
                part = self._normalize_text(part)
                if not part:
                    continue
                if 2 <= len(part) <= 12:
                    self._append_candidate(candidates, part)
                elif len(part) > 8:
                    for sub in self._CN_SECONDARY_SPLIT_RE.split(part):
                        sub = self._normalize_text(sub)
                        if 2 <= len(sub) <= 8:
                            self._append_candidate(candidates, sub)

        for token in self._CN_TOKEN_RE.findall(normalized):
            self._append_candidate(candidates, token)
        for token in self._EN_TOKEN_RE.findall(normalized):
            self._append_candidate(candidates, token)
        return candidates

    def _append_candidate(self, candidates: List[str], value: str):
        normalized = self._normalize_text(value)
        if normalized:
            candidates.append(normalized)

    def _add_ranked(
        self,
        scores: Dict[str, float],
        surfaces: Dict[str, str],
        items: Iterable[Any],
        base_score: float,
    ):
        for idx, item in enumerate(items):
            self._add_candidate(scores, surfaces, item, max(0.5, base_score - idx * 0.18))

    def _add_candidate(
        self,
        scores: Dict[str, float],
        surfaces: Dict[str, str],
        item: Any,
        score: float,
    ):
        normalized = self._normalize_text(item)
        if self._is_noise_keyword(normalized):
            return
        key = normalized.lower()
        scores[key] += score
        existing = surfaces.get(key, "")
        if not existing or len(normalized) < len(existing):
            surfaces[key] = normalized

    def _is_noise_keyword(self, value: str) -> bool:
        text = self._normalize_text(value)
        if len(text) < 2:
            return True
        lower = text.lower()

        if lower in self._GENERIC_STOPWORDS or lower in self._SCHEMA_NOISE or lower in self._ACTION_NOISE:
            return True
        if lower in self._DOMAIN_NOISE:
            return True
        if self._NUMERIC_RE.fullmatch(lower):
            return True
        if self._TEMPORAL_RE.fullmatch(lower):
            return True
        if lower.startswith(("http://", "https://", "www.")):
            return True
        if "://" in lower or "/" in lower:
            return True
        if "_" in lower and lower == re.sub(r"[^a-z0-9_]", "", lower):
            return True
        if lower.endswith(("号",)) and (("xx" in lower) or ("xxx" in lower) or re.search(r"\d", lower)):
            return True
        if re.fullmatch(r"x{2,}\w*", lower):
            return True
        if re.fullmatch(r"[a-z][a-z0-9\-]{2,20}", lower) and lower not in self._ALLOWLIST_EN:
            return True
        if len(lower) <= 2 and not re.search(r"[\u4e00-\u9fff]", lower):
            return True
        if any(marker in lower for marker in ("post_content", "comment_content", "original_content", "quote_content")):
            return True
        return False

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" \t\r\n\"'`“”‘’[]{}()<>.,，。:：;；!?！？")
        return text

    def _safe_int(self, value: Any, default: int = -1) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except Exception:
            return default
