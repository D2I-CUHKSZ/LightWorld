# LightWorld

这个版本的 README 只面向一件事：

在已经把 `apikey`、`base_url`、`model` 写进 Python 配置文件的前提下，如何用尽量少的终端指令，把项目整条流程跑起来。

默认流程是：

1. 读取本地文本 / 图片 / 视频
2. 生成本体并构建图谱
3. 自动准备 Twitter / Reddit 双平台模拟
4. 启动并行模拟
5. 按需生成报告

默认不依赖 `.env`，而是直接使用：

```text
backend/app/core/settings.py
```

里的配置。

## 1. 一条命令跑全流程

### 方式 A：在仓库根目录执行

推荐命令：

```bash
uv sync --project backend
uv run --project backend mirofish-full-run --config event_inputs/baike_wuda_event/full_run.config.json
```

如果不用 `uv`：

```bash
pip install -r backend/requirements.txt
python backend/scripts/run_full_pipeline.py --config event_inputs/baike_wuda_event/full_run.config.json
```

### 方式 B：在 `backend` 目录执行

如果你更习惯先进入 `backend`，那就用你说的这套相对路径：

```bash
cd backend
uv sync
uv run mirofish-full-run --config ../event_inputs/baike_wuda_event/full_run.config.json
```

或者：

```bash
cd backend
pip install -r requirements.txt
python scripts/run_full_pipeline.py --config ../event_inputs/baike_wuda_event/full_run.config.json
```

上面的第二条命令会自动完成整条链路，不需要再手动分别调用本地管线、模拟准备、并行模拟。

## 2. 默认示例输入

仓库已经准备好一套可直接跑的演示输入，目录就是：

```text
event_inputs/baike_wuda_event
```

全流程配置文件：

```text
event_inputs/baike_wuda_event/full_run.config.json
```

输入文件列表：

```text
event_inputs/baike_wuda_event/input_files.txt
```

这份示例会自动读取：

- `event_overview.md`
- `event_timeline.txt`
- `images/*.jpg`
- `videos/*.mp4`

如果你要替换成自己的输入，最省事的方法是只改：

```text
event_inputs/baike_wuda_event/input_files.txt
```

如果你想连任务描述一起改，就改：

```text
event_inputs/baike_wuda_event/full_run.config.json
```

## 3. 哪些参数去哪改

### 3.1 模型和 API Key

改这里：

```text
backend/app/core/settings.py
```

最重要的字段：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_NAME`
- `ZEP_API_KEY`
- `MULTIMODAL_VISION_MODEL_NAME`
- `MULTIMODAL_AUDIO_MODEL_NAME`

### 3.2 输入、任务目标、运行参数

改这里：

```text
event_inputs/baike_wuda_event/full_run.config.json
```

常用字段：

- `project_name`
- `graph_name`
- `simulation_requirement`
- `additional_context`
- `files`
- `files_from`
- `pipeline`
- `simulation`
- `run`
- `report`

如果你想新建一份配置，可以直接复制模板：

```text
backend/scripts/config_templates/full_run.template.json
```

## 4. 跑完以后去哪里看结果

每次全流程运行后，会自动生成一个运行目录：

```text
backend/uploads/full_runs/
```

最先看这两个文件：

```text
backend/uploads/full_runs/latest.json
backend/uploads/full_runs/<某次运行目录>/run_manifest.json
```

`run_manifest.json` 会把关键产物路径都列出来，包括：

- `pipeline_result.json`
- `prepare_state.json`
- `simulation_config.final.json`
- `project_dir`
- `simulation_dir`
- 如果开启了报告，还会有 `report_dir` 和 `full_report`

模拟详细产物通常在：

```text
backend/uploads/simulations/<simulation_id>/
```

常看的文件有：

- `twitter/actions.jsonl`
- `reddit/actions.jsonl`
- `entity_prompts.json`
- `social_relation_graph.json`
- `simulation_config.json`

## 5. 常用补充命令

只启动后端 API：

```bash
uv run --project backend mirofish-api
```

如果你已经有某个 `simulation_config.json`，只想重跑并行模拟：

```bash
uv run --project backend mirofish-parallel-sim --config backend/uploads/simulations/<simulation_id>/simulation_config.json --no-wait
```

或者在 `backend` 目录执行：

```bash
python scripts/run_parallel_simulation.py --config uploads/simulations/<simulation_id>/simulation_config.json --no-wait
```

## 6. 推荐实际用法

第一次跑，直接用仓库自带示例：

```bash
cd backend
uv sync
uv run mirofish-full-run --config ../event_inputs/baike_wuda_event/full_run.config.json
```

确认链路没问题之后，再复制模板配置，替换成你自己的输入文件和任务描述。
