"""Platform simulation runner (application-level orchestrator).

Keeps CLI scripts thin by centralizing:
- platform-specific profile loading/agent graph generation
- round loop execution
- topology-aware + simple memory integration
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import oasis
from oasis import (
    ActionType,
    LLMAction,
    ManualAction,
    generate_reddit_agent_graph,
    generate_twitter_agent_graph,
)

from .runtimes import SimpleMemRuntime, TopologyAwareRuntime, safe_float


TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
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
    allow_multi_initial_posts_per_agent=False,
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

    candidates: List[int] = []
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

    if topology_runtime:
        selected_ids = topology_runtime.select_agent_ids(candidates, target_count)
    else:
        selected_ids = random.sample(candidates, min(target_count, len(candidates))) if candidates else []

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
        return await generate_twitter_agent_graph(
            profile_path=profile_path,
            model=model,
            available_actions=spec.available_actions,
        )
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

    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=spec.oasis_platform,
        database_path=db_path,
        semaphore=30,
    )

    await result.env.reset()
    log_info("环境已启动")

    if action_logger:
        action_logger.log_simulation_start(config)

    total_actions = 0
    last_rowid = 0

    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])

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

        if not active_agents:
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
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

        simplemem_runtime.ingest_round_actions(
            round_num=round_num + 1,
            simulated_hour=simulated_hour,
            actions=actual_actions,
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
