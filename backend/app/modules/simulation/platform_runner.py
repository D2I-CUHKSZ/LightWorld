"""Platform simulation runner (application-level orchestrator).

Keeps CLI scripts thin by centralizing:
- platform-specific profile loading/agent graph generation
- round loop execution
- topology-aware + simple memory integration
"""

from __future__ import annotations

import os
import random
import sqlite3
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import oasis
from oasis import (
    ActionType,
    LLMAction,
    ManualAction,
    generate_reddit_agent_graph,
)
from oasis.social_agent import AgentGraph, SocialAgent
from oasis.social_platform.config import UserInfo

from .runtimes import SimpleMemRuntime, TopologyAwareRuntime, safe_float


TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_POST,
    ActionType.LIKE_COMMENT,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

REDDIT_ACTIONS = [
    ActionType.LIKE_POST,
    ActionType.DISLIKE_POST,
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_COMMENT,
    ActionType.DISLIKE_COMMENT,
    ActionType.SEARCH_POSTS,
    ActionType.SEARCH_USER,
    ActionType.TREND,
    ActionType.REFRESH,
    ActionType.DO_NOTHING,
    ActionType.FOLLOW,
    ActionType.MUTE,
]


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    profile_filename: str
    use_boost_model: bool
    oasis_platform: Any
    available_actions: List[Any]
    allow_multi_initial_posts_per_agent: bool = False


TWITTER_SPEC = PlatformSpec(
    name="twitter",
    profile_filename="twitter_profiles.csv",
    use_boost_model=False,
    oasis_platform=oasis.DefaultPlatformType.TWITTER,
    available_actions=TWITTER_ACTIONS,
    allow_multi_initial_posts_per_agent=True,
)

REDDIT_SPEC = PlatformSpec(
    name="reddit",
    profile_filename="reddit_profiles.json",
    use_boost_model=True,
    oasis_platform=oasis.DefaultPlatformType.REDDIT,
    available_actions=REDDIT_ACTIONS,
    allow_multi_initial_posts_per_agent=True,
)


@dataclass
class PlatformSimulation:
    env: Optional[Any] = None
    agent_graph: Optional[Any] = None
    total_actions: int = 0


def get_active_agents_for_round(
    env: Any,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int,
    topology_runtime: Optional[TopologyAwareRuntime] = None,
) -> List[Tuple[int, Any]]:
    """根据时间和配置决定本轮激活哪些 Agent。"""
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])

    base_min = time_config.get("agents_per_hour_min", 5)
    base_max = time_config.get("agents_per_hour_max", 20)

    peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])

    if current_hour in peak_hours:
        multiplier = time_config.get("peak_activity_multiplier", 1.5)
    elif current_hour in off_peak_hours:
        multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
    else:
        multiplier = 1.0

    target_count = int(random.uniform(base_min, base_max) * multiplier)
    target_count = max(1, target_count)
    if topology_runtime:
        target_count = topology_runtime.adjust_target_count(target_count)

    def is_ordinary_agent(cfg: Dict[str, Any]) -> bool:
        entity_type = str(cfg.get("entity_type", "") or "").strip().lower()
        entity_uuid = str(cfg.get("entity_uuid", "") or "").strip().lower()
        return entity_type in {"person", "student"} or entity_uuid.startswith("synthetic_")

    candidates: List[int] = []
    ordinary_candidates: List[int] = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", list(range(8, 23)))
        base_activity_level = safe_float(cfg.get("activity_level", 0.5), 0.5)

        if current_hour not in active_hours:
            continue

        if topology_runtime:
            activity_level = topology_runtime.get_activity_probability(agent_id, base_activity_level)
        else:
            activity_level = min(1.0, max(0.0, base_activity_level))

        if random.random() < activity_level:
            candidates.append(agent_id)
            if is_ordinary_agent(cfg):
                ordinary_candidates.append(agent_id)

    if topology_runtime:
        selected_ids = topology_runtime.select_agent_ids(candidates, target_count)
    else:
        selected_ids = random.sample(candidates, min(target_count, len(candidates))) if candidates else []

    if selected_ids and ordinary_candidates:
        ordinary_set = set(ordinary_candidates)
        ordinary_selected = [aid for aid in selected_ids if aid in ordinary_set]
        ordinary_target = max(1, int(round(min(len(selected_ids), target_count) * 0.4)))
        if len(ordinary_selected) < ordinary_target:
            available_ordinary = [aid for aid in ordinary_candidates if aid not in selected_ids]
            shortage = min(len(available_ordinary), ordinary_target - len(ordinary_selected))
            if shortage > 0:
                elite_selected = [aid for aid in selected_ids if aid not in ordinary_set]
                selected_ids = (
                    selected_ids[: len(selected_ids) - min(shortage, len(elite_selected))]
                    + available_ordinary[:shortage]
                )

    active_agents: List[Tuple[int, Any]] = []
    for agent_id in selected_ids:
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass
    return active_agents


async def _build_agent_graph(spec: PlatformSpec, profile_path: str, model: Any) -> Any:
    if spec.name == "twitter":
        agent_graph = AgentGraph()
        with open(profile_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                bio = str(row.get("bio", "") or "").strip()
                persona = str(row.get("persona", "") or "").strip()
                description = str(row.get("description", "") or bio).strip()
                user_profile = str(row.get("user_char", "") or "").strip()

                interested_topics = row.get("interested_topics", "[]")
                if isinstance(interested_topics, str):
                    try:
                        interested_topics = json.loads(interested_topics)
                    except Exception:
                        interested_topics = [x.strip() for x in interested_topics.split(",") if x.strip()]
                if not isinstance(interested_topics, list):
                    interested_topics = []

                structured_bits: List[str] = []
                for key in [
                    "age",
                    "gender",
                    "mbti",
                    "country",
                    "profession",
                    "source_entity_uuid",
                    "source_entity_type",
                    "friend_count",
                    "follower_count",
                    "statuses_count",
                ]:
                    val = row.get(key)
                    if val is None or str(val).strip() == "":
                        continue
                    structured_bits.append(f"{key}={str(val).strip()}")
                if interested_topics:
                    structured_bits.append("interested_topics=" + ", ".join(str(x) for x in interested_topics))

                if structured_bits:
                    user_profile = (user_profile + " Structured fields: " + "; ".join(structured_bits) + ".").strip()
                if bio and bio not in user_profile:
                    user_profile = (bio + " " + user_profile).strip()
                if persona and persona not in user_profile:
                    user_profile = (user_profile + " " + persona).strip()

                profile = {
                    "nodes": [],
                    "edges": [],
                    "other_info": {
                        "user_profile": user_profile,
                        "bio": bio,
                        "persona": persona,
                        "description": description,
                        "age": row.get("age"),
                        "gender": row.get("gender"),
                        "mbti": row.get("mbti"),
                        "country": row.get("country"),
                        "profession": row.get("profession"),
                        "interested_topics": interested_topics,
                        "friend_count": row.get("friend_count"),
                        "follower_count": row.get("follower_count"),
                        "statuses_count": row.get("statuses_count"),
                        "source_entity_uuid": row.get("source_entity_uuid"),
                        "source_entity_type": row.get("source_entity_type"),
                    },
                }

                user_info = UserInfo(
                    user_name=str(row.get("username", "") or f"user_{idx}"),
                    name=str(row.get("name", "") or row.get("username", "") or f"user_{idx}"),
                    description=description,
                    profile=profile,
                    recsys_type="twitter",
                )
                agent = SocialAgent(
                    agent_id=idx,
                    user_info=user_info,
                    model=model,
                    agent_graph=agent_graph,
                    available_actions=spec.available_actions,
                )
                agent_graph.add_agent(agent)
        return agent_graph
    return await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=spec.available_actions,
    )


def _append_initial_action(
    initial_actions: Dict[Any, Any],
    agent: Any,
    action: ManualAction,
    allow_multiple: bool,
):
    if not allow_multiple:
        initial_actions[agent] = action
        return
    if agent in initial_actions:
        if not isinstance(initial_actions[agent], list):
            initial_actions[agent] = [initial_actions[agent]]
        initial_actions[agent].append(action)
    else:
        initial_actions[agent] = action


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_scheduled_event_round(event: Dict[str, Any], minutes_per_round: int) -> Optional[int]:
    if not isinstance(event, dict):
        return None

    trigger_round = _coerce_positive_int(event.get("trigger_round"))
    if trigger_round is not None and trigger_round >= 1:
        return trigger_round

    round_offset = _coerce_positive_int(event.get("round_offset"))
    if round_offset is not None and round_offset >= 0:
        return round_offset + 1

    trigger_day = _coerce_positive_int(event.get("trigger_day"))
    trigger_hour = None
    for key in ["trigger_hour", "hour", "hour_offset"]:
        trigger_hour = _coerce_positive_int(event.get(key))
        if trigger_hour is not None:
            break

    if trigger_hour is None:
        return None

    total_hours = max(0, trigger_hour)
    if trigger_day is not None and trigger_day >= 1:
        total_hours += (trigger_day - 1) * 24

    total_minutes = total_hours * 60
    return (total_minutes // max(1, minutes_per_round)) + 1


def _get_latest_post_id_for_agent(db_path: str, agent_id: int) -> Optional[int]:
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.post_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            WHERE u.agent_id = ?
            ORDER BY p.created_at DESC, p.post_id DESC
            LIMIT 1
            """,
            (agent_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return int(row[0])
    except Exception:
        return None
    return None


def _get_latest_hot_post_id(db_path: str) -> Optional[int]:
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT post_id
            FROM post
            ORDER BY (num_shares * 2 + num_likes) DESC, created_at DESC, post_id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return int(row[0])
    except Exception:
        return None
    return None


def _resolve_target_post_id(
    db_path: str,
    config: Dict[str, Any],
    event: Dict[str, Any],
    poster_agent_id: int,
) -> Optional[int]:
    explicit_post_id = _coerce_positive_int(event.get("target_post_id"))
    if explicit_post_id is not None:
        return explicit_post_id

    target_agent_id = _coerce_positive_int(
        event.get("target_poster_agent_id", event.get("target_agent_id"))
    )
    strategy = str(event.get("target_post_strategy", "") or "latest_hot_post").strip().lower()
    if strategy in {"latest_post_by_agent", "latest_post_by_type", "latest_target_post"} and target_agent_id is not None:
        return _get_latest_post_id_for_agent(db_path, target_agent_id)
    if strategy == "latest_self_post":
        return _get_latest_post_id_for_agent(db_path, poster_agent_id)

    if strategy == "latest_hot_post":
        hot_post = _get_latest_hot_post_id(db_path)
        if hot_post is not None:
            return hot_post

    # Fallback: target agent -> latest hot post -> poster latest post
    if target_agent_id is not None:
        target_post = _get_latest_post_id_for_agent(db_path, target_agent_id)
        if target_post is not None:
            return target_post
    hot_post = _get_latest_hot_post_id(db_path)
    if hot_post is not None:
        return hot_post
    return _get_latest_post_id_for_agent(db_path, poster_agent_id)


async def _apply_scheduled_events_for_round(
    spec: PlatformSpec,
    env: Any,
    config: Dict[str, Any],
    db_path: str,
    event_config: Dict[str, Any],
    round_num: int,
    minutes_per_round: int,
    triggered_event_ids: set,
    log_info: Callable[[str], None],
) -> int:
    scheduled_events = event_config.get("scheduled_events", []) or []
    if not isinstance(scheduled_events, list):
        return 0

    post_actions: Dict[Any, Any] = {}
    comment_actions: Dict[Any, Any] = {}
    scheduled_action_count = 0

    post_events: List[Dict[str, Any]] = []
    comment_events: List[Dict[str, Any]] = []
    thread_events: List[Dict[str, Any]] = []

    for idx, event in enumerate(scheduled_events):
        if idx in triggered_event_ids or not isinstance(event, dict):
            continue

        target_round = _resolve_scheduled_event_round(event, minutes_per_round)
        if target_round is None or target_round != round_num:
            continue

        triggered_event_ids.add(idx)
        event_type = str(event.get("event_type", "") or "").strip().lower()

        if event_type == "hot_topics_update":
            current_topics = list(event_config.get("hot_topics", []) or [])
            current_set = {str(x).strip() for x in current_topics if str(x).strip()}

            for topic in event.get("hot_topics_remove", []) or []:
                current_set.discard(str(topic).strip())
            for topic in event.get("hot_topics_add", []) or []:
                topic_text = str(topic).strip()
                if topic_text:
                    current_set.add(topic_text)

            event_config["hot_topics"] = sorted(current_set)
            log_info(
                f"触发定时事件: hot_topics_update round={round_num}, "
                f"topics={len(event_config['hot_topics'])}"
            )
            continue

        if event_type == "create_post":
            post_events.append(event)
            continue
        if event_type == "create_comment":
            comment_events.append(event)
            continue
        if event_type == "create_thread":
            thread_events.append(event)
            continue

        if event_type not in {"create_post", "create_comment", "create_thread"}:
            log_info(f"跳过不支持的定时事件类型: {event_type}")
            continue

    for event in post_events:
        content = str(event.get("content", "") or "").strip()
        poster_agent_id = _coerce_positive_int(event.get("poster_agent_id"))
        if not content or poster_agent_id is None:
            log_info(f"定时发帖事件缺少内容或发布者，已跳过: round={round_num}")
            continue
        try:
            agent = env.agent_graph.get_agent(poster_agent_id)
        except Exception:
            log_info(f"定时发帖事件找不到Agent: agent_id={poster_agent_id}")
            continue
        _append_initial_action(
            initial_actions=post_actions,
            agent=agent,
            action=ManualAction(
                action_type=ActionType.CREATE_POST,
                action_args={"content": content},
            ),
            allow_multiple=spec.allow_multi_initial_posts_per_agent,
        )
        scheduled_action_count += 1

    for event in thread_events:
        root_content = str(event.get("root_content", "") or "").strip()
        poster_agent_id = _coerce_positive_int(event.get("poster_agent_id"))
        if not root_content or poster_agent_id is None:
            log_info(f"定时 thread 事件缺少主帖内容或发布者，已跳过: round={round_num}")
            continue
        try:
            agent = env.agent_graph.get_agent(poster_agent_id)
        except Exception:
            log_info(f"定时 thread 事件找不到Agent: agent_id={poster_agent_id}")
            continue
        _append_initial_action(
            initial_actions=post_actions,
            agent=agent,
            action=ManualAction(
                action_type=ActionType.CREATE_POST,
                action_args={"content": root_content},
            ),
            allow_multiple=True,
        )
        scheduled_action_count += 1

    if post_actions:
        await env.step(post_actions)
        if post_events:
            log_info(f"已执行定时事件帖子: round={round_num}, count={len(post_events)}")
        if thread_events:
            log_info(f"已执行定时线程主帖: round={round_num}, count={len(thread_events)}")

    for event in thread_events:
        poster_agent_id = _coerce_positive_int(event.get("poster_agent_id"))
        if poster_agent_id is None:
            continue
        thread_post_id = _get_latest_post_id_for_agent(db_path, poster_agent_id)
        if thread_post_id is None:
            continue
        try:
            agent = env.agent_graph.get_agent(poster_agent_id)
        except Exception:
            continue
        for reply in event.get("replies", []) or []:
            reply_text = str(reply or "").strip()
            if not reply_text:
                continue
            _append_initial_action(
                initial_actions=comment_actions,
                agent=agent,
                action=ManualAction(
                    action_type=ActionType.CREATE_COMMENT,
                    action_args={"post_id": thread_post_id, "content": reply_text},
                ),
                allow_multiple=True,
            )
            scheduled_action_count += 1

    for event in comment_events:
        content = str(event.get("content", "") or "").strip()
        poster_agent_id = _coerce_positive_int(event.get("poster_agent_id"))
        if not content or poster_agent_id is None:
            log_info(f"定时评论事件缺少内容或发布者，已跳过: round={round_num}")
            continue
        target_post_id = _resolve_target_post_id(
            db_path=db_path,
            config=config,
            event=event,
            poster_agent_id=poster_agent_id,
        )
        if target_post_id is None:
            log_info(f"定时评论事件未找到目标帖子，已跳过: round={round_num}")
            continue
        try:
            agent = env.agent_graph.get_agent(poster_agent_id)
        except Exception:
            continue
        _append_initial_action(
            initial_actions=comment_actions,
            agent=agent,
            action=ManualAction(
                action_type=ActionType.CREATE_COMMENT,
                action_args={"post_id": target_post_id, "content": content},
            ),
            allow_multiple=True,
        )
        scheduled_action_count += 1

    if comment_actions:
        await env.step(comment_actions)
        log_info(f"已执行定时评论/回复: round={round_num}, count={len(comment_actions)}")

    return scheduled_action_count


def _extract_platform_config(config: Dict[str, Any], platform_name: str) -> Dict[str, Any]:
    raw = config.get(f"{platform_name}_config")
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _set_attr_if_exists(obj: Any, candidates: List[str], value: Any) -> Optional[str]:
    for name in candidates:
        if not hasattr(obj, name):
            continue
        try:
            setattr(obj, name, value)
            return name
        except Exception:
            continue
    return None


def _apply_platform_config_best_effort(env: Any, platform_cfg: Dict[str, Any], log_info: Callable[[str], None]) -> int:
    if not platform_cfg:
        return 0

    roots = [env]
    for attr in ["platform", "rec", "recommender", "recommendation", "recommendation_system"]:
        try:
            node = getattr(env, attr)
            if node is not None:
                roots.append(node)
        except Exception:
            continue

    key_map = {
        "recency_weight": ["recency_weight", "time_weight", "recency"],
        "popularity_weight": ["popularity_weight", "hotness_weight", "pop_weight"],
        "relevance_weight": ["relevance_weight", "semantic_weight", "interest_weight"],
        "viral_threshold": ["viral_threshold", "virality_threshold", "viral_trigger_threshold"],
        "echo_chamber_strength": ["echo_chamber_strength", "echo_strength", "homophily_strength"],
    }

    applied = 0
    for cfg_key, attr_candidates in key_map.items():
        if cfg_key not in platform_cfg:
            continue
        value = platform_cfg[cfg_key]
        for root in roots:
            attr = _set_attr_if_exists(root, attr_candidates, value)
            if attr:
                applied += 1
                break

    # 若对象支持配置方法，尝试一次方法调用
    method_candidates = [
        ("set_recommendation_weights", {
            "recency_weight": platform_cfg.get("recency_weight"),
            "popularity_weight": platform_cfg.get("popularity_weight"),
            "relevance_weight": platform_cfg.get("relevance_weight"),
        }),
        ("update_recommendation_config", platform_cfg),
        ("set_recommendation_config", platform_cfg),
    ]
    for root in roots:
        for method_name, payload in method_candidates:
            method = getattr(root, method_name, None)
            if not callable(method):
                continue
            try:
                if isinstance(payload, dict) and method_name == "set_recommendation_weights":
                    kwargs = {k: v for k, v in payload.items() if v is not None}
                    if kwargs:
                        method(**kwargs)
                        applied += len(kwargs)
                else:
                    method(payload)
                    applied += len(platform_cfg)
                break
            except Exception:
                continue

    if applied > 0:
        log_info(f"已接通平台配置（best-effort）: applied={applied}")
    else:
        log_info("平台配置未能映射到OASIS对象属性，继续使用平台默认参数")
    return applied


def _create_env(
    spec: PlatformSpec,
    agent_graph: Any,
    db_path: str,
    platform_cfg: Dict[str, Any],
    log_info: Callable[[str], None],
) -> Any:
    kwargs = {
        "agent_graph": agent_graph,
        "platform": spec.oasis_platform,
        "database_path": db_path,
        "semaphore": 30,
    }

    env = None
    if platform_cfg:
        try:
            env = oasis.make(**kwargs, platform_config=platform_cfg)
            log_info("已通过 oasis.make(platform_config=...) 传入平台配置")
        except TypeError:
            env = oasis.make(**kwargs)
            _apply_platform_config_best_effort(env, platform_cfg, log_info)
        except Exception as e:
            log_info(f"通过 make 注入平台配置失败，回退默认创建: {e}")
            env = oasis.make(**kwargs)
            _apply_platform_config_best_effort(env, platform_cfg, log_info)
    else:
        env = oasis.make(**kwargs)
    return env


def _load_user_id_mapping(db_path: str) -> Tuple[Dict[int, int], Dict[int, int]]:
    agent_to_user: Dict[int, int] = {}
    user_to_agent: Dict[int, int] = {}
    if not os.path.exists(db_path):
        return agent_to_user, user_to_agent
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, user_id FROM user")
        for aid, uid in cursor.fetchall():
            if aid is None or uid is None:
                continue
            agent_to_user[int(aid)] = int(uid)
            user_to_agent[int(uid)] = int(aid)
        conn.close()
    except Exception:
        pass
    return agent_to_user, user_to_agent


def _detect_follow_columns(cursor: Any) -> Tuple[Optional[str], Optional[str], List[str]]:
    follower_col = None
    followee_col = None
    columns: List[str] = []
    try:
        cursor.execute("PRAGMA table_info(follow)")
        rows = cursor.fetchall()
    except Exception:
        return follower_col, followee_col, columns

    for row in rows:
        if len(row) < 2:
            continue
        name = str(row[1])
        columns.append(name)

    lower_to_raw = {c.lower(): c for c in columns}
    for key, raw in lower_to_raw.items():
        if "followee" in key or "target_user" in key:
            followee_col = raw
            break

    follower_candidates = [
        "follower_id",
        "user_id",
        "source_user_id",
        "source_id",
        "from_user_id",
    ]
    for cand in follower_candidates:
        if cand in lower_to_raw:
            follower_col = lower_to_raw[cand]
            break

    return follower_col, followee_col, columns


def _get_existing_follow_pairs(db_path: str, user_to_agent: Dict[int, int]) -> List[Tuple[int, int]]:
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        follower_col, followee_col, _ = _detect_follow_columns(cursor)
        if not follower_col or not followee_col:
            conn.close()
            return []

        cursor.execute(f"SELECT {follower_col}, {followee_col} FROM follow")
        rows = cursor.fetchall()
        conn.close()

        pairs: List[Tuple[int, int]] = []
        for src_uid, dst_uid in rows:
            if src_uid is None or dst_uid is None:
                continue
            src = user_to_agent.get(int(src_uid))
            dst = user_to_agent.get(int(dst_uid))
            if src is None or dst is None or src == dst:
                continue
            pairs.append((src, dst))
        return pairs
    except Exception:
        return []


def _insert_follow_pairs_into_db(
    db_path: str,
    pairs: List[Tuple[int, int]],
    agent_to_user: Dict[int, int],
) -> List[Tuple[int, int]]:
    if not pairs or not os.path.exists(db_path):
        return []

    inserted: List[Tuple[int, int]] = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        follower_col, followee_col, columns = _detect_follow_columns(cursor)
        if not follower_col or not followee_col:
            conn.close()
            return []

        existing = set()
        try:
            cursor.execute(f"SELECT {follower_col}, {followee_col} FROM follow")
            for src_uid, dst_uid in cursor.fetchall():
                if src_uid is None or dst_uid is None:
                    continue
                existing.add((int(src_uid), int(dst_uid)))
        except Exception:
            pass

        base_cols = [follower_col, followee_col]
        created_col = next((c for c in columns if c.lower() == "created_at"), None)
        updated_col = next((c for c in columns if c.lower() == "updated_at"), None)
        if created_col:
            base_cols.append(created_col)
        if updated_col and updated_col != created_col:
            base_cols.append(updated_col)

        placeholders = ",".join(["?"] * len(base_cols))
        col_text = ",".join(base_cols)
        now = datetime.now().isoformat()
        sql = f"INSERT OR IGNORE INTO follow ({col_text}) VALUES ({placeholders})"

        for src_aid, dst_aid in pairs:
            src_uid = agent_to_user.get(int(src_aid))
            dst_uid = agent_to_user.get(int(dst_aid))
            if src_uid is None or dst_uid is None or src_uid == dst_uid:
                continue
            if (src_uid, dst_uid) in existing:
                continue
            values: List[Any] = [src_uid, dst_uid]
            if created_col:
                values.append(now)
            if updated_col and updated_col != created_col:
                values.append(now)
            cursor.execute(sql, values)
            if cursor.rowcount and cursor.rowcount > 0:
                inserted.append((int(src_aid), int(dst_aid)))
                existing.add((src_uid, dst_uid))

        conn.commit()
        conn.close()
    except Exception:
        return []

    return inserted


async def _inject_follow_pairs_via_manual_action(
    env: Any,
    pairs: List[Tuple[int, int]],
    agent_names: Dict[int, str],
    agent_to_user: Dict[int, int],
    max_pairs: int = 24,
) -> int:
    if not pairs:
        return 0

    count = 0
    for src_aid, dst_aid in pairs[:max_pairs]:
        try:
            src_agent = env.agent_graph.get_agent(src_aid)
        except Exception:
            continue

        target_name = agent_names.get(dst_aid, f"Agent_{dst_aid}")
        target_uid = agent_to_user.get(dst_aid)
        arg_candidates = [
            {"target_user_name": target_name},
            {"user_name": target_name},
            {"username": target_name},
        ]
        if target_uid is not None:
            arg_candidates.extend([
                {"target_user_id": target_uid},
                {"user_id": target_uid},
                {"followee_id": target_uid},
            ])

        done = False
        for action_args in arg_candidates:
            try:
                await env.step({
                    src_agent: ManualAction(
                        action_type=ActionType.FOLLOW,
                        action_args=action_args,
                    )
                })
                done = True
                break
            except Exception:
                continue

        if done:
            count += 1
    return count


async def _sync_social_links_from_topology(
    env: Any,
    db_path: str,
    topology_runtime: Optional[TopologyAwareRuntime],
    agent_names: Dict[int, str],
    log_info: Callable[[str], None],
    max_per_agent: Optional[int] = None,
    max_total: Optional[int] = None,
    manual_fallback_max_pairs: int = 24,
) -> int:
    if not topology_runtime or not topology_runtime.enabled:
        return 0

    agent_to_user, user_to_agent = _load_user_id_mapping(db_path)
    existing_pairs = _get_existing_follow_pairs(db_path, user_to_agent)
    if existing_pairs:
        topology_runtime.register_existing_follow_pairs(existing_pairs)

    follow_plan = topology_runtime.compile_initial_follow_pairs(
        max_per_agent=max_per_agent,
        max_total=max_total,
    )
    if not follow_plan:
        return 0

    plan_pairs = [(src, dst) for src, dst, _, _ in follow_plan]
    inserted = _insert_follow_pairs_into_db(db_path, plan_pairs, agent_to_user)
    if inserted:
        topology_runtime.register_existing_follow_pairs(inserted)
        log_info(f"已注入初始社交关系: db_follow_edges={len(inserted)}")
        return len(inserted)

    # 某些平台版本可能不允许直接写表，回退到 manual FOLLOW 动作
    manual_injected = await _inject_follow_pairs_via_manual_action(
        env=env,
        pairs=plan_pairs,
        agent_names=agent_names,
        agent_to_user=agent_to_user,
        max_pairs=manual_fallback_max_pairs,
    )
    if manual_injected > 0:
        # 重新读取数据库中的 follow，转成 known pairs
        _, user_to_agent_after = _load_user_id_mapping(db_path)
        refreshed_pairs = _get_existing_follow_pairs(db_path, user_to_agent_after)
        if refreshed_pairs:
            topology_runtime.register_existing_follow_pairs(refreshed_pairs)
        log_info(f"已通过动作回退注入社交关系: follow_actions={manual_injected}")
    return manual_injected


async def run_platform_simulation(
    spec: PlatformSpec,
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[Any],
    main_logger: Optional[Any],
    max_rounds: Optional[int],
    create_model_fn: Callable[[Dict[str, Any], bool], Any],
    get_agent_names_fn: Callable[[Dict[str, Any]], Dict[int, str]],
    fetch_actions_fn: Callable[[str, int, Dict[int, str]], Tuple[List[Dict[str, Any]], int]],
    shutdown_event: Optional[Any] = None,
) -> PlatformSimulation:
    """按平台规格运行模拟。"""
    result = PlatformSimulation()

    tag = spec.name.capitalize()

    def log_info(msg: str):
        if main_logger:
            main_logger.info(f"[{tag}] {msg}")
        print(f"[{tag}] {msg}")

    log_info("初始化...")
    model = create_model_fn(config, use_boost=spec.use_boost_model)

    profile_path = os.path.join(simulation_dir, spec.profile_filename)
    if not os.path.exists(profile_path):
        log_info(f"错误: Profile文件不存在: {profile_path}")
        return result

    result.agent_graph = await _build_agent_graph(spec, profile_path, model)

    agent_names = get_agent_names_fn(config)
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, "name", f"Agent_{agent_id}")

    topology_runtime = TopologyAwareRuntime(
        config=config,
        simulation_dir=simulation_dir,
        platform=spec.name,
        logger=log_info,
    )
    simplemem_runtime = SimpleMemRuntime(
        config=config,
        simulation_dir=simulation_dir,
        platform=spec.name,
        topology_runtime=topology_runtime,
        logger=log_info,
    )

    db_path = os.path.join(simulation_dir, f"{spec.name}_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    platform_cfg = _extract_platform_config(config, spec.name)
    result.env = _create_env(
        spec=spec,
        agent_graph=result.agent_graph,
        db_path=db_path,
        platform_cfg=platform_cfg,
        log_info=log_info,
    )

    await result.env.reset()
    log_info("环境已启动")
    if platform_cfg:
        _apply_platform_config_best_effort(result.env, platform_cfg, log_info)

    # 启动前同步一次“图谱关系 -> 初始社交关系”
    await _sync_social_links_from_topology(
        env=result.env,
        db_path=db_path,
        topology_runtime=topology_runtime,
        agent_names=agent_names,
        log_info=log_info,
    )

    if action_logger:
        action_logger.log_simulation_start(config)

    total_actions = 0
    last_rowid = 0
    topo_cfg = config.get("topology_aware", {}) or {}
    social_link_sync_enabled = bool(topo_cfg.get("social_link_sync_enabled", True))
    social_link_sync_interval = max(1, int(topo_cfg.get("social_link_sync_interval", 6)))
    social_link_sync_max_total = max(
        4,
        int(topo_cfg.get("social_link_sync_max_total", max(8, len(agent_names) // 4)))
    )

    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    triggered_event_ids: set = set()

    if action_logger:
        action_logger.log_round_start(0, 0)

    initial_action_count = 0
    if initial_posts:
        initial_actions: Dict[Any, Any] = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                action = ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content},
                )
                _append_initial_action(
                    initial_actions=initial_actions,
                    agent=agent,
                    action=action,
                    allow_multiple=spec.allow_multi_initial_posts_per_agent,
                )
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content},
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass

        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"已发布 {len(initial_actions)} 条初始帖子")

    if action_logger:
        action_logger.log_round_end(0, initial_action_count)

    topology_runtime.record_round_state(
        round_num=0,
        simulated_hour=0,
        reason="post_initialization",
        active_agent_ids=[],
    )
    simplemem_runtime.record_round_state(
        round_num=0,
        simulated_hour=0,
        active_agent_ids=[],
    )

    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round

    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"轮数已截断: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")

    start_time = datetime.now()

    for round_num in range(total_rounds):
        if shutdown_event and shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"收到退出信号，在第 {round_num + 1} 轮停止模拟")
            break

        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1

        active_agents = get_active_agents_for_round(
            result.env,
            config,
            simulated_hour,
            round_num,
            topology_runtime=topology_runtime,
        )

        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)

        scheduled_action_count = await _apply_scheduled_events_for_round(
            spec=spec,
            env=result.env,
            config=config,
            db_path=db_path,
            event_config=event_config,
            round_num=round_num + 1,
            minutes_per_round=minutes_per_round,
            triggered_event_ids=triggered_event_ids,
            log_info=log_info,
        )

        if not active_agents:
            if action_logger:
                action_logger.log_round_end(round_num + 1, scheduled_action_count)
            if scheduled_action_count > 0:
                actual_actions, last_rowid = fetch_actions_fn(db_path, last_rowid, agent_names)
                for action_data in actual_actions:
                    if action_logger:
                        action_logger.log_action(
                            round_num=round_num + 1,
                            agent_id=action_data["agent_id"],
                            agent_name=action_data["agent_name"],
                            action_type=action_data["action_type"],
                            action_args=action_data["action_args"],
                        )
                        total_actions += 1

                topology_runtime.ingest_round_actions(
                    round_num=round_num + 1,
                    actions=actual_actions,
                )
                simplemem_runtime.ingest_round_actions(
                    round_num=round_num + 1,
                    simulated_hour=simulated_hour,
                    actions=actual_actions,
                )
            topology_runtime.record_round_state(
                round_num=round_num + 1,
                simulated_hour=simulated_hour,
                reason="round_idle",
                active_agent_ids=[],
            )
            simplemem_runtime.record_round_state(
                round_num=round_num + 1,
                simulated_hour=simulated_hour,
                active_agent_ids=[],
            )
            continue

        actions: Dict[Any, Any] = {}
        for active_agent_id, agent in active_agents:
            memory_context = simplemem_runtime.build_memory_context(
                agent_id=active_agent_id,
                current_round=round_num + 1,
            )
            simplemem_runtime.inject_context_into_agent(agent, memory_context)
            actions[agent] = LLMAction()
        await result.env.step(actions)

        actual_actions, last_rowid = fetch_actions_fn(db_path, last_rowid, agent_names)

        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data["agent_id"],
                    agent_name=action_data["agent_name"],
                    action_type=action_data["action_type"],
                    action_args=action_data["action_args"],
                )
                total_actions += 1
                round_action_count += 1

        round_action_count += scheduled_action_count

        topology_runtime.ingest_round_actions(
            round_num=round_num + 1,
            actions=actual_actions,
        )

        if social_link_sync_enabled and ((round_num + 1) % social_link_sync_interval == 0):
            # 用最新拓扑结果增量同步弱曝光关系，让 topology-aware 结果进入平台曝光层
            await _sync_social_links_from_topology(
                env=result.env,
                db_path=db_path,
                topology_runtime=topology_runtime,
                agent_names=agent_names,
                log_info=log_info,
                max_per_agent=1,
                max_total=social_link_sync_max_total,
                manual_fallback_max_pairs=8,
            )

        simplemem_runtime.ingest_round_actions(
            round_num=round_num + 1,
            simulated_hour=simulated_hour,
            actions=actual_actions,
        )
        topology_runtime.record_round_state(
            round_num=round_num + 1,
            simulated_hour=simulated_hour,
            reason="round_complete",
            active_agent_ids=[aid for aid, _ in active_agents],
        )
        simplemem_runtime.record_round_state(
            round_num=round_num + 1,
            simulated_hour=simulated_hour,
            active_agent_ids=[aid for aid, _ in active_agents],
        )

        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(
                f"Day {simulated_day}, {simulated_hour:02d}:00 - "
                f"Round {round_num + 1}/{total_rounds} ({progress:.1f}%)"
            )

    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)

    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"模拟循环完成! 耗时: {elapsed:.1f}秒, 总动作: {total_actions}")
    return result
