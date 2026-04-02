# 武汉大学品牌声誉规模扩大实验报告

## 1. 实验概览

- 生成时间: 2026-04-01T19:05:42.867040
- 输入文档: `/home/shulun/project/LightWorld/武汉大学品牌声誉深度分析报告.pdf`
- 项目 ID: `proj_f3fa5d99c95c`
- 图谱 ID: `mirofish_f5f917771d814bfd`
- 模拟 ID: `sim_706dbfc1acac`
- 模型: ``
- LLM Base URL: ``
- LLM API Key: `***`
- Zep API Key: `***`

## 2. 实验流程

1. 读取 PDF，抽取文本并执行预处理。
2. 基于文档内容生成适合品牌声誉模拟的本体定义。
3. 将全文分块送入 Zep，构建语义图谱。
4. 从图谱筛选可发声实体，生成 `entity_prompts.json`，显式写出实体 `keywords / description / semantic_prompt / topic_tags`。
5. 为实体生成双平台 profile，编译 `social_relation_graph.json`，再生成 `simulation_config.json`。
6. 启动 Twitter + Reddit 并行模拟，在运行中按轮次保存 topology 和 memory artifact。
7. 汇总实验中间产物与最终行为日志，生成本报告与 `experiment_summary.json`。

## 3. 输入与构图规模

- 文本字符数: 20833
- 文本行数: 747
- 处理文件数: 1
- 图谱节点数: 111
- 图谱边数: 131
- 图谱 chunk 数: 21
- 过滤后实体数: 31
- 生成 profile 数: 31

## 4. 创新点观察

### 4.1 给实体增加 keywords

- 央媒调查记者 (MediaOutlet): 央级媒体, 调查记者, 甲醛超标事件, 立体维权, 媒体监督, 学生权益, 武汉大学, 舆情介入
- 华北电力大学 (PeerUniversity): 华北电力大学, 电力特色高校, 教育部直属高校, “211工程”高校, “双一流”建设高校, 能源电力人才培养, 智能电网研究
- 央级媒体 (MediaOutlet): 央级媒体, 官方报道, 舆情放大器, 权威转载, 武汉大学事件, 品牌声誉传播
- 自媒体平台 (SelfMediaCreator): 自媒体平台, 不实信息传播, 校园交通事件, 武汉大学声誉危机, 舆情放大器, 校方报警, 副校长子女谣言
- 海外校友 (Alumni): 海外校友, 武汉大学, 国际声誉, 程序正义, 境外势力叙事, 立场撕裂, 北美时区, 欧洲时区
- 重庆上游新闻 (MediaOutlet): 重庆上游新闻, 权威媒体, 地方主流媒体, 重庆日报报业集团, 上游新闻客户端, 川渝媒体
- 校长 (UniversityStaff): 武汉大学校长, 高校行政权威, 舆情回应机制, 上级指令依赖, 夜间警告, 学生代表沟通
- 后勤部门 (UniversityStaff): 武汉大学后勤部门, 甲醛事件, 检测合格通报, 公信力崩塌, 学生第三方报告, 校方回应失当

观察:
- `keywords` 已经不是附属字段，而是直接进入 topology similarity、unit 构造和 memory retrieval。
- 实体语义蒸馏产物保存在 `entity_prompts.json`，为后续 cluster 和 memory 提供统一语义接口。

### 4.2 cluster 的 unit

Twitter:
- unit_count: 29
- avg_unit_size: 1.069
- largest_unit_size: 2
- Unit 1 | size=2 | repr=法律专家 | members=管理顾问, 法律专家
- Unit 0 | size=2 | repr=央视网 | members=新华网, 央视网
- Unit 28 | size=1 | repr=央媒调查记者 | members=央媒调查记者
- Unit 27 | size=1 | repr=华北电力大学 | members=华北电力大学
- Unit 26 | size=1 | repr=央级媒体 | members=央级媒体

Reddit:
- unit_count: 29
- avg_unit_size: 1.069
- largest_unit_size: 2
- Unit 1 | size=2 | repr=管理顾问 | members=管理顾问, 法律专家
- Unit 0 | size=2 | repr=新华网 | members=新华网, 京报网
- Unit 28 | size=1 | repr=央媒调查记者 | members=央媒调查记者
- Unit 27 | size=1 | repr=华北电力大学 | members=华北电力大学
- Unit 26 | size=1 | repr=央级媒体 | members=央级媒体

观察:
- unit 不是离线分析产物，而是 runtime 的协调粒度，直接决定每轮激活代表节点与补充成员的方式。
- 新增的 topology snapshot 允许回看每轮 unit 变化，不再只能看最终状态。

### 4.3 PPR 的非对称影响力

Twitter Top Central:
- 校方 | unit=20 | importance=1.680625 | ppr_centrality=0.036689 | top_outgoing=校长:0.043616, 校领导:0.043377, 自媒体平台:0.043138
- 管理顾问 | unit=1 | importance=1.334371 | ppr_centrality=0.036461 | top_outgoing=法律专家:0.065184, Media Engine:0.065184
- 学生 | unit=16 | importance=1.444625 | ppr_centrality=0.034564 | top_outgoing=央级媒体:0.045416, 央媒调查记者:0.044796, 后勤部门:0.043009
- 杨景媛 | unit=17 | importance=0.661427 | ppr_centrality=0.034338 | top_outgoing=辛某:0.065184, 肖某某:0.064826, 校领导:0.004781
- 校长 | unit=22 | importance=1.730861 | ppr_centrality=0.033736 | top_outgoing=校方:0.065423, 学生代表:0.064706, 校领导:0.003188
- 南方网 | unit=15 | importance=1.756731 | ppr_centrality=0.033141 | top_outgoing=重庆上游新闻:0.028313, 央级媒体:0.027929, 央视网:0.027487
- 央视网 | unit=0 | importance=2.0 | ppr_centrality=0.033092 | top_outgoing=京报网:0.029726, 新华网:0.02867, 重庆上游新闻:0.028485
- 京报网 | unit=9 | importance=1.752205 | ppr_centrality=0.033088 | top_outgoing=央视网:0.029757, 新华网:0.028699, 重庆上游新闻:0.028315

Twitter Top Asymmetry:
- 自媒体平台 -> 校方 | dominant=0.129413 | reverse=0.043138 | delta=0.086275
- 后勤部门 -> 学生 | dominant=0.129026 | reverse=0.043009 | delta=0.086017
- 法律专家 -> 管理顾问 | dominant=0.130369 | reverse=0.065184 | delta=0.065184
- Media Engine -> 管理顾问 | dominant=0.130369 | reverse=0.065184 | delta=0.065184
- 肖某某 -> 杨景媛 | dominant=0.129652 | reverse=0.064826 | delta=0.064826
- 学生代表 -> 校长 | dominant=0.129413 | reverse=0.064706 | delta=0.064706
- 校长 -> 校方 | dominant=0.065423 | reverse=0.043616 | delta=0.021808
- 校领导 -> 校方 | dominant=0.065065 | reverse=0.043377 | delta=0.021688

Reddit Top Central:
- 海外校友 | unit=24 | importance=1.14983 | ppr_centrality=0.044555 | top_outgoing=央视网:0.009742, 法律专家:0.009649, 央媒调查记者:0.009535
- 学生 | unit=16 | importance=1.540687 | ppr_centrality=0.039405 | top_outgoing=网易号“笔杆论道”:0.015396, 海外校友:0.015179, 校友群体:0.015033
- 央级媒体 | unit=26 | importance=1.756231 | ppr_centrality=0.039194 | top_outgoing=央媒调查记者:0.010771, 京报网:0.010469, 学生:0.010018
- 湖北省教育厅 | unit=2 | importance=1.768142 | ppr_centrality=0.037124 | top_outgoing=新华网:0.011767, 京报网:0.011592, Media Engine:0.011553
- 法律专家 | unit=1 | importance=1.400628 | ppr_centrality=0.034343 | top_outgoing=Media Engine:0.020075, 海外校友:0.01999, 央视网:0.018824
- 新华网 | unit=0 | importance=1.984011 | ppr_centrality=0.033323 | top_outgoing=京报网:0.015444, 重庆上游新闻:0.015378, 海外校友:0.01515
- 校领导 | unit=8 | importance=1.849591 | ppr_centrality=0.033105 | top_outgoing=校长:0.064827, 辛某:0.064646, 学生代表:0.002391
- 央广网 | unit=9 | importance=2.0 | ppr_centrality=0.032557 | top_outgoing=新华网:0.019391, 湖北省教育厅:0.019388, 重庆上游新闻:0.019284

Reddit Top Asymmetry:
- 985高校 -> 海外校友 | dominant=0.1275 | reverse=0.0085 | delta=0.119
- 后勤部门 -> 学生 | dominant=0.128366 | reverse=0.014263 | delta=0.114104
- 辛某 -> 校领导 | dominant=0.129293 | reverse=0.064646 | delta=0.064646
- 管理顾问 -> 海外校友 | dominant=0.065116 | reverse=0.008686 | delta=0.05643
- 校友群体 -> 学生 | dominant=0.066938 | reverse=0.015033 | delta=0.051905
- 管理顾问 -> 法律专家 | dominant=0.064777 | reverse=0.018504 | delta=0.046273
- 墩墩舆情课工作室 -> 海外校友 | dominant=0.043411 | reverse=0.008685 | delta=0.034726
- 自媒体平台 -> 海外校友 | dominant=0.043208 | reverse=0.008642 | delta=0.034567

观察:
- PPR 输出的不只是“谁更重要”，还给出有向影响差异，因此可以直接验证非对称影响力。
- 本次实验把 `top_outgoing_ppr` 和 `top_asymmetric_pairs` 落盘到 topology artifact，便于复查影响方向。

### 4.4 memory 机制

Twitter:
- agents_with_memory: 14
- total_agent_units: 34
- world_units: 24
- store_events: 50
- retrieval_events: 284
- sample_retrieval: agent=海外校友 | complexity=HIGH | selected=self:海外校友:检测合格; world:海外校友:检测合格; world:央媒调查记者:武汉大学; world:学生:珞珈裂痕

Reddit:
- agents_with_memory: 28
- total_agent_units: 108
- world_units: 65
- store_events: 245
- retrieval_events: 267
- sample_retrieval: agent=海外校友 | complexity=HIGH | selected=self:海外校友:cnas; self:海外校友:检测合格; self:海外校友:珞珈裂痕; world:校长:武汉大学

观察:
- memory 由 `memory_store`、`retrieval` 和 `memory_state` 三类 artifact 组成，可以看到写入、合并、检索与世界记忆扩展。
- 这让 memory 从“最终 `simplemem_*.json` 文件”升级成“可追踪的跨轮次认知闭环”。

## 5. 行为结果

Twitter:
- total_actions: 292
- action_types: DO_NOTHING:237; QUOTE_POST:27; CREATE_POST:14; REPOST:12; LIKE_POST:2
- top_agents: 新华网:24; 央视网:20; 央媒调查记者:18; 海外校友:18; 央广网:18; 香港01:17

Reddit:
- total_actions: 272
- action_types: CREATE_COMMENT:93; LIKE_POST:85; CREATE_POST:49; SEARCH_POSTS:21; DO_NOTHING:10; LIKE_COMMENT:8; SEARCH_USER:3; FOLLOW:2
- top_agents: 央媒调查记者:25; 央广网:23; 海外校友:18; 新华网:18; 央视网:17; 重庆上游新闻:16

## 6. 关键产物路径

- experiment_dir: `/home/shulun/project/LightWorld/backend/uploads/experiments/exp_20260401_180640_武汉大学品牌声誉深度分析报告`
- pipeline_result: `/home/shulun/project/LightWorld/backend/uploads/experiments/exp_20260401_180640_武汉大学品牌声誉深度分析报告/pipeline_result.json`
- prepare_state: `/home/shulun/project/LightWorld/backend/uploads/experiments/exp_20260401_180640_武汉大学品牌声誉深度分析报告/prepare_state.json`
- scaled_config: `/home/shulun/project/LightWorld/backend/uploads/experiments/exp_20260401_180640_武汉大学品牌声誉深度分析报告/scaled_simulation_config.json`
- simulation_config: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/simulation_config.json`
- entity_prompts: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/entity_prompts.json`
- entity_graph_snapshot: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/entity_graph_snapshot.json`
- social_relation_graph: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/social_relation_graph.json`
- twitter_topology: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/artifacts/topology/twitter/latest_topology.json`
- reddit_topology: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/artifacts/topology/reddit/latest_topology.json`
- twitter_memory: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/simplemem_twitter.json`
- reddit_memory: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/simplemem_reddit.json`
- twitter_actions: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/twitter/actions.jsonl`
- reddit_actions: `/home/shulun/project/LightWorld/backend/uploads/simulations/sim_706dbfc1acac/reddit/actions.jsonl`

## 7. 结论

- 这次实验已经把输入 PDF 到双平台模拟的端到端链路跑通，并将关键中间产物保存为可复查文件。
- `keywords -> unit -> PPR -> memory` 四条创新链路现在都有对应 artifact，可直接用于后续实验复盘、对比和论文式写作。
- 如果后续要继续放大规模，优先建议沿三条线推进：更多实体、更长时间窗、以及基于当前 artifact 做跨实验对比基准。
