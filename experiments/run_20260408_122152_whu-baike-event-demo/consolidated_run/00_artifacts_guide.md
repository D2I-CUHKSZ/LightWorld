# Run Artifact Guide

- 运行目录: `<repo-root>/backend/uploads/full_runs/run_20260408_122152_whu-baike-event-demo`
- 项目ID: `proj_17f12f355259`
- 图谱ID: `mirofish_ebb8693de4024891`
- 模拟ID: `sim_91e21a6aade3`

这个时间戳目录是本次实验的集中视图。
真实文件仍然保存在 `input2graph/projects`、`output/simulations`、`output/reports` 中，以保持现有逻辑兼容。
这里提供的是更容易寻找的同目录入口；大多数条目是符号链接，少数环境下会自动退回为复制。

## 01_project_artifacts

- `project_workspace`: 项目原始目录入口
- `input_files`: 本次项目复制后的输入文件
- `project_metadata.json`: 项目元数据
- `extracted_text.txt`: 提取出的全文文本
- `parsed_content.json`: 多模态解析结果
- `source_manifest.json`: 输入文件清单

## 02_simulation_artifacts

- `simulation_workspace`: 模拟原始目录入口
- `simulation_status.json`: 模拟准备状态
- `simulation_env_status.json`: 运行结束状态
- `simulation_runtime_log.log`: 主日志
- `generated_simulation_config.json`: 实际运行使用的模拟配置
- `original_simulation_config.json`: 覆盖前的原始模拟配置
- `entity_prompts.json`: 实体画像提示
- `entity_graph_snapshot.json`: 初始实体图快照
- `social_relation_graph.json`: 社交关系图
- `twitter_profiles.csv` / `reddit_profiles.json`: 双平台人设文件
- `twitter_actions.jsonl` / `reddit_actions.jsonl`: 双平台动作日志
- `twitter_simulation.db` / `reddit_simulation.db`: 双平台数据库
- `twitter_memory.json` / `reddit_memory.json`: 双平台记忆产物

## 03_report_artifacts

- `report_workspace`
- `report_metadata.json`
- `report_outline.json`
- `report_progress.json`
- `full_report.md`
- `agent_log.jsonl`
- `console_log.txt`
