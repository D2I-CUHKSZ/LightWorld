# 模拟系统改造报告

日期：2026-04-03

## 改造范围

本次改动对应你提出的几项核心问题，已在代码层面完成以下改造：

1. 给 Twitter 增加 reply/thread 能力，并为 Reddit 补评论树视图。
2. 把 persona 从长传记式 2000 字压缩为 300 到 600 字的行为型人设卡。
3. 重写 `event_config` 生成策略，增加冲突型事件与对抗型内容。
4. 重做 retrieval，加入反向记忆和 novelty 惩罚。
5. 在 prepare 阶段加入 alias merge，再重新驱动 entity prompts / profiles / config。
6. 为模拟人口补充普通用户，避免主体长期被官方/媒体节点主导。

## 具体改动

### 1. Twitter reply/thread 与 Reddit 评论树

涉及文件：

- `app/core/settings.py`
- `app/modules/simulation/platform_runner.py`
- `scripts/run_parallel_simulation.py`
- `app/adapters/http/simulation.py`
- `scripts/action_logger.py`

已完成：

- 为 Twitter 动作集合加入 `CREATE_COMMENT` 和 `LIKE_COMMENT`。
- 允许 Twitter 在同一轮对同一 agent 注入多个手动动作，支持线程式事件。
- 扩展定时事件执行器，新增支持：
  - `create_comment`
  - `create_thread`
  - `hot_topics_update`
- 为评论类事件增加目标帖解析策略：
  - 显式 `target_post_id`
  - `latest_post_by_agent`
  - `latest_post_by_type`
  - `latest_self_post`
  - `latest_hot_post`
- 对 `create_thread`，运行器会先发根帖，再对该帖连续发出一个或多个 `CREATE_COMMENT`。
- 对 `CREATE_COMMENT` 的 trace 解析做了增强，动作日志现在能恢复：
  - `comment_content`
  - `post_id`
  - `post_content`
  - `post_author_name`
  - 启发式 `parent_comment_id`
  - 启发式 `parent_author_name`
- `/api/simulation/<id>/comments` 现在会返回轻量线程信息：
  - `parent_comment_id`
  - `depth`
- 修正了模拟日志中 `total_rounds` 的计算方式，现在会正确考虑 `minutes_per_round`。

说明：

- OASIS 底层评论表仍然是平的，没有原生 `parent_comment_id`。因此当前 Reddit 评论树属于“启发式树状视图”，不是底层原生嵌套结构。

### 2. Persona 生成人设压缩与规整

涉及文件：

- `app/application/oasis_profile_generator.py`

已完成：

- 重写了个人实体和机构实体的人设 prompt：
  - 原来目标：约 2000 字的人物/机构长叙事
  - 现在目标：300 到 600 字的行为型 persona
- prompt 重点从“完整传记”改为：
  - 角色身份
  - 立场先验
  - 发言风格
  - 互动习惯
  - 触发条件
  - 与事件相关的记忆锚点
- 增加了 profile 归一化逻辑：
  - 限制 `bio` 长度
  - 限制 `persona` 长度
  - 自动补全缺失的 `interested_topics`
  - 清理过度冗长输出
- 为 synthetic 普通用户单独增加一套 profile 生成逻辑，避免普通用户也被扩写成不真实的长传记。
- 对 `user_char` 注入内容增加长度截断，避免人设文本过长稀释 runtime prompt。

### 3. 冲突型事件生成

涉及文件：

- `app/application/simulation_config_generator.py`
- `app/modules/simulation/platform_runner.py`

已完成：

- 重写了事件生成 prompt，明确要求事件配置里覆盖：
  - 官方/机构通报
  - 媒体追问或核查
  - 普通用户情绪表达
  - 对前帖的反驳/质疑/补充
  - 推动热点升级的新信息
- 配置生成和解析层现在支持：
  - `create_post`
  - `create_comment`
  - `create_thread`
  - `hot_topics_update`
- 对 comment 类事件支持基于 `target_poster_type` 做目标 agent 分配。
- 对 thread 类事件支持 `replies` 解析。
- 对 comment 类事件补充 `target_post_strategy` 归一化。

### 4. Retrieval：反向记忆与 novelty

涉及文件：

- `app/modules/simulation/runtimes.py`
- `app/application/simulation_config_generator.py`

已完成：

- 为 SimpleMem 配置新增参数：
  - `counter_scope_max`
  - `counter_opinion_gap`
  - `novelty_lookback`
  - `unit_repeat_penalty`
  - `topic_repeat_penalty`
- 在 retrieval 打分中加入 novelty 惩罚，降低重复命中：
  - 相同 memory unit
  - 相同 topic
- 增加 counterpoint memory 选择逻辑：
  - 优先抽取与当前 agent 立场差距更大、关键词重叠更低的记忆
  - 作为 `[COUNTERPOINT MEMORY]` 注入
- 为每个 agent 记录短期 retrieval 历史，防止连续几轮拿到几乎相同的上下文。

预期效果：

- 降低“所有 agent 说的话越来越像”的问题
- 增加平台内部分歧和响应多样性
- 减弱同质化编辑部口径收敛

### 5. Alias merge：先合并再生成 prompts / profiles / config

涉及文件：

- `app/application/simulation_population.py`
- `app/application/simulation_manager.py`

已完成：

- 新增 `SimulationPopulationBuilder`。
- 在 prompt 提取和 profile 生成之前加入 alias merge。
- 当前合并策略已覆盖：
  - 规范化后完全重复实体
  - 常见高校简称，如 `武汉大学 / 武大`
  - 部分掩码式人名变体
  - 部分亲属角色别名（结合 related node）
- 新增 `population_adjustments.json` 产物，记录：
  - merge groups
  - alias map
  - synthetic user additions
- `simulation_manager.prepare_simulation()` 已改为下游统一使用：
  - 合并后的实体
  - 补充后的普通用户人口
  - 重写后的实体快照元数据

### 6. 普通用户扩充

涉及文件：

- `app/application/simulation_population.py`
- `app/application/simulation_manager.py`
- `app/modules/simulation/platform_runner.py`

已完成：

- 新增 synthetic 普通用户 archetype：
  - `围观学生XX`
  - `求证型网友XX`
  - `情绪型路人XX`
  - `校友观察者XX`
  - `家长视角用户XX`
  - `吃瓜转发用户XX`
- 当普通用户占比过低时，population builder 会自动补普通用户。
- 当前默认目标是 `ordinary_ratio_target = 0.55`，上限 `max_synthetic_entities = 24`。
- 在 `get_active_agents_for_round()` 中加入普通用户激活配额，避免每轮又被媒体/官方全部占满。

基于历史 WHU 快照的本地检查结果：

- 原始实体数：`55`
- 合并并补充后实体数：`74`
- alias merge 组数：`2`
- synthetic 普通用户新增：`21`

补充后实体类型分布：

- `Person`: 31
- `Student`: 10
- `MediaOutlet`: 19
- `University`: 7
- 其余类型基本保持不变

## 验证情况

### 自动化检查

执行命令：

```bash
./.venv/bin/pytest tests/test_entity_prompt_extractor.py tests/test_simulation_population.py tests/test_simulation_config_events.py -q
python -m py_compile app/application/__init__.py app/application/simulation_population.py app/application/oasis_profile_generator.py app/application/simulation_manager.py app/application/simulation_config_generator.py app/modules/simulation/platform_runner.py app/modules/simulation/runtimes.py app/adapters/http/simulation.py scripts/run_parallel_simulation.py scripts/action_logger.py
```

结果：

- `6 passed`
- 所有修改模块通过 Python 编译检查

### 新增测试

测试文件：

- `tests/test_simulation_population.py`
- `tests/test_simulation_config_events.py`
- 既有 `tests/test_entity_prompt_extractor.py` 保持通过

覆盖内容：

- 高校简称 alias merge（`武汉大学 / 武大`）
- 当人口过于精英化时是否能触发普通用户补充
- `create_comment` / `create_thread` 的事件配置解析
- 评论事件的 target agent 分配

## 当前仍然存在的限制

1. Reddit 评论树仍是启发式结构。  
原因：  
OASIS 原始 comment schema 仍然是平表（`comment_id`, `post_id`, `user_id`, `content`, ...`），底层没有真正的嵌套回复字段。

2. Twitter 的 thread 目前实现方式是：  
根帖 + 对该根帖的一条或多条评论/回复。  
它已经比原来的纯 quote/repost 结构强很多，但还不是第一类原生 tweet-thread 对象。

3. Alias merge 目前是保守策略。  
现在已经能抓到明显重复和简称，但还不能覆盖全部语义别名。

4. 这次 coding pass 没有做完整端到端重跑。  
当前验证主要停留在：
  - 单测
  - 编译检查
  - 基于历史快照的局部验证  
要看到最终行为变化，仍然需要重新跑一次完整流程，重新生成：
  - `entity_prompts.json`
  - `reddit_profiles.json`
  - `twitter_profiles.csv`
  - `simulation_config.json`
  - 平台动作日志与最终报告

## 建议的下一步

基于同一份 WHU 示例重新执行一次 prepare / full run，然后重点对比以下指标：

- 普通用户占比
- Twitter reply 占比
- 内容重复率
- Reddit 每帖评论数
- 双平台活跃 agent 覆盖率
- 改造前后 report 的语言与平台判断差异
