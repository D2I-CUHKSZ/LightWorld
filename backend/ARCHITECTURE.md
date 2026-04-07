# 鍚庣鏋舵瀯锛堥噸鏋勭増锛?

褰撳墠浠撳簱宸茬粡鏄函鍚庣椤圭洰銆?

## 鍒嗗眰缁撴瀯

- `backend/app/cli/`
  - 鏍囧噯鍖?CLI 鍏ュ彛锛圓PI銆佹湰鍦板浘璋辨瀯寤恒€佸苟琛屾ā鎷燂級
- `backend/app/core/`
  - 鏍稿績閰嶇疆涓庤繍琛屾椂鍏变韩鍩虹璁炬柦
- `backend/app/adapters/http/`
  - HTTP 閫傞厤灞傦紙Blueprint銆佽姹傚鐞嗐€佸搷搴旂粍瑁咃級
- `backend/app/application/`
  - 搴旂敤鏈嶅姟灞傦紝渚?API 涓庤剼鏈鐢?
- `backend/app/domain/`
  - 棰嗗煙瀵硅薄涓庣姸鎬佺鐞嗭紙project/task/simulation锛?
- `backend/app/infrastructure/`
  - 鍩虹璁炬柦宸ュ叿锛圠LM client銆佹棩蹇椼€佹枃浠惰В鏋愩€佸垎椤点€侀噸璇曪級
- `backend/app/modules/`
  - 浠ュ満鏅负涓績鐨勯噸鏋勬ā鍧?

## 涓昏妯″潡

- `backend/app/modules/graph/local_pipeline.py`
  - `LocalGraphPipeline`锛氭湰鍦版枃妗ｉ┍鍔ㄧ殑鍥捐氨鏋勫缓娴佺▼
  - `LocalPipelineOptions`锛氭湰鍦扮绾胯緭鍏ュ弬鏁?
- `backend/app/modules/simulation/runtimes.py`
  - `TopologyAwareRuntime`锛歵opology-aware 鍗忚皟涓庡樊寮傚寲婵€娲?
  - `SimpleMemRuntime`锛氳交閲忓閲忚蹇嗕笌妫€绱㈡敞鍏?
- `backend/app/modules/simulation/platform_runner.py`
  - `PlatformSpec`锛氬钩鍙板樊寮傞厤缃?
  - `run_platform_simulation`锛歍witter / Reddit 鍏辩敤杩愯涓诲惊鐜?
  - `TWITTER_SPEC` / `REDDIT_SPEC`锛氬钩鍙拌鏍煎疄渚?

## 褰撳墠閲囩敤鐨勮璁℃ā寮?

- Strategy
  - 骞冲彴宸紓閫氳繃 `PlatformSpec` 琛ㄨ揪锛岃€屼笉鏄湪杩愯涓婚€昏緫閲屽爢鍒嗘敮銆?
- Application Service
  - 澶嶆潅鐢ㄤ緥鐢?`LocalGraphPipeline`銆乣SimulationManager`銆乣run_platform_simulation` 璐熻矗缂栨帓銆?
- Thin Entry Script
  - `scripts/run_local_pipeline.py` 涓?`scripts/run_parallel_simulation.py` 涓昏璐熻矗 CLI 涓庡弬鏁拌浆鍙戙€?

## 杩愯鍏ュ彛

- API 鏈嶅姟
  - `cd backend && uv run mirofish-api`
- 鏈湴鍥捐氨鏋勫缓
  - `cd backend && uv run mirofish-local-pipeline ...`
- 骞惰妯℃嫙
  - `cd backend && uv run mirofish-parallel-sim --config <path>`

## 閰嶇疆妯℃澘

- 瀹屾暣 simulation 閰嶇疆妯℃澘锛堝寘鍚?topology-aware銆乻implemem銆乴ight-mode锛?
  - `backend/scripts/config_templates/simulation_config.full.template.json`

## 鍏煎鍖呰

- `backend/run.py` 涓?`backend/scripts/run_local_pipeline.py`
  - 浣滀负鍏煎鍏ュ彛淇濈暀銆?
- `backend/scripts/run_twitter_simulation.py` 涓?`backend/scripts/run_reddit_simulation.py`
  - 鐜板湪宸茬粡鏀逛负濮旀墭缁熶竴鍏ュ彛 `run_parallel_simulation.py`
  - 鍒嗗埆閫氳繃 `--twitter-only` / `--reddit-only` 杩愯鍗曞钩鍙版ā鎷?

## 绔埌绔暟鎹祦

褰撳墠鍚庣鐨勭湡瀹炶矾寰勪笉鏄畝鍗曠殑鈥滄枃妗?-> 鍥捐氨鈥濇垨鈥減rofile -> OASIS鈥濓紝鑰屾槸涓嬮潰杩欐潯瀹屾暣閾捐矾锛?

1. 鏈湴鏂囨。涓?`simulation_requirement` 杩涘叆鏈湴鍥捐氨鏋勫缓绠＄嚎銆?
2. 绠＄嚎瀹屾垚鏂囨湰鎻愬彇銆侀澶勭悊銆乷ntology 鐢熸垚涓?Zep 璇箟鍥捐氨鏋勫缓銆?
3. 浠庤涔夊浘璋变腑璇诲洖鑺傜偣涓庤竟锛屽苟绛涢€夊嚭鍙ā鎷熷疄浣撱€?
4. 鍥寸粫杩欎簺瀹炰綋缁х画鐢熸垚锛?
   - `entity_prompts`
   - OASIS `profiles`
   - `simulation_config`
   - 鏄惧紡 `social_relation_graph`
5. 杩欎簺涓棿浜х墿鍐嶈缂栬瘧杩?OASIS 杩愯鏃讹細
   - profile 鏂囦欢鐢ㄤ簬鍒涘缓 agent graph
   - simulation config 椹卞姩鏃堕棿銆佷簨浠躲€乼opology銆乵emory
   - social relation graph 琚浆鎴愬垵濮?`follow` 杈规敞鍏?OASIS 鏁版嵁搴?
6. 杩愯鏃跺姩浣滅户缁洖娴佸埌锛?
   - OASIS 鏁版嵁搴撹〃
   - topology-aware 鏇存柊
   - SimpleMem

### 娴佺▼鍥?

```mermaid
flowchart TD
    A["杈撳叆
- 鏈湴鏂囨。
- simulation_requirement
- 鐜鍙橀噺"] --> B["LocalGraphPipeline"]

    B --> C["鏂囨湰鎻愬彇涓庨澶勭悊"]
    C --> D["OntologyGenerator
- entity_types
- edge_types
- analysis_summary"]
    D --> E["GraphBuilderService
- 鍒涘缓 Zep graph
- 璁剧疆 ontology
- 鍙戦€佹枃鏈?chunks"]
    E --> F["Zep 璇箟鍥捐氨
- nodes
- edges"]

    F --> G["椤圭洰浜х墿
- extracted_text.txt
- project.json"]
    F --> H["SimulationManager.prepare_simulation"]

    H --> I["ZepEntityReader
- 绛涢€夋ā鎷熷疄浣?]
    I --> J["entity_graph_snapshot.json"]
    I --> K["EntityPromptExtractor"]
    K --> L["entity_prompts.json"]
    I --> M["OasisProfileGenerator"]
    M --> N["twitter_profiles.csv / reddit_profiles.json"]
    I --> O["SimulationConfigGenerator"]
    O --> P["simulation_config.json"]
    J --> Q["SocialRelationGraphCompiler"]
    O --> Q
    Q --> R["social_relation_graph.json"]

    N --> S["run_parallel_simulation.py
鎴?twitter/reddit 鍖呰鍏ュ彛"]
    P --> S
    L --> S
    J --> S
    R --> S

    S --> T["TopologyAwareRuntime"]
    S --> U["SimpleMemRuntime"]
    T --> V["缂栬瘧杩愯鏃剁粨鏋?
- structure_vec
- synthetic_adj
- PPR
- units"]
    R --> V
    T --> W["娉ㄥ叆鍒濆 follow 杈?]
    W --> X["OASIS 鏁版嵁搴?
- user
- post
- follow
- trace
- rec"]

    P --> Y["浜嬩欢灞?
- initial_posts
- scheduled_events
- hot_topics_update"]
    Y --> X

    X --> Z["閫愯疆妯℃嫙
- 閫夋嫨娲昏穬 agent
- memory 娉ㄥ叆
- env.step()"]
    Z --> AA["鍔ㄤ綔鍥炴祦
- trace/post/follow
- topology ingest
- simplemem ingest"]
    AA --> T
    AA --> U
```

## 浜х墿鏂囦欢

### 椤圭洰鏋勫缓闃舵

浜х墿鐩綍锛?

- `backend/input2graph/projects/<project_id>/`

涓昏鏂囦欢锛?

- `extracted_text.txt`
  - 棰勫鐞嗗悗鐨勯」鐩骇鎷兼帴鏂囨湰
- `project.json`
  - 椤圭洰鐘舵€併€乷ntology 鎽樿銆乬raph id銆佸浘璋辩粺璁′俊鎭?

### Simulation Prepare 闃舵

浜х墿鐩綍锛?

- `output/simulations/<simulation_id>/`

涓昏鏂囦欢锛?

- `entity_graph_snapshot.json`
  - 杩囨护鍚庣殑瀹炰綋锛屼互鍙婁笌 simulation 鐩稿叧鐨勫浘璋辫竟蹇収
- `entity_prompts.json`
  - 鐢ㄤ簬鑱氱被 / 妫€绱㈢殑瀹炰綋璇箟钂搁缁撴灉
- `twitter_profiles.csv` 鎴?`reddit_profiles.json`
  - OASIS 鍙洿鎺ヨ鍙栫殑 profile 鏂囦欢
- `simulation_config.json`
  - 鏃堕棿閰嶇疆銆乤gent 閰嶇疆銆佷簨浠堕厤缃€乼opology 閰嶇疆銆乵emory 閰嶇疆
- `social_relation_graph.json`
  - 鏄惧紡 agent-agent 绀句氦鍏崇郴鍥撅紝鍖呭惈锛?
    - `exposure_weight`
    - `trust_weight`
    - `hostility_weight`
    - `alliance_weight`
    - `interaction_prior`

### Runtime 闃舵

浠嶇劧浜у嚭鍦ㄧ浉鍚?simulation 鐩綍涓嬶細

- `twitter_simulation.db` / `reddit_simulation.db`
  - OASIS 杩愯鏃舵暟鎹簱
- `simulation.log`
  - 涓昏繘绋嬫棩蹇?
- `env_status.json`
  - 鐜鐢熷懡鍛ㄦ湡鐘舵€?
- `twitter/actions.jsonl` / `reddit/actions.jsonl`
  - 缁撴瀯鍖栧姩浣滄棩蹇?
- `simplemem_twitter.json` / `simplemem_reddit.json`
  - 鍘嬬缉鍚庣殑澧為噺璁板繂鏂囦欢

## 绀轰緥璇存槑

### 绀轰緥 1锛氭渶灏?README 椹卞姩寤哄浘

杈撳叆锛?

- 鏂囨。锛歚README.md`
- 闇€姹傦細`Use README content to build a minimal public-opinion simulation`

杈撳嚭杩囩▼锛?

1. `LocalGraphPipeline` 璇诲彇 `README.md`
2. `OntologyGenerator` 鍩轰簬鏂囨。鏂囨湰鍜岄渶姹傜敓鎴?ontology
3. `GraphBuilderService` 鏋勫缓 Zep 鍥捐氨
4. `project.json` 淇濆瓨鐢熸垚鐨?`graph_id`

涓€娆℃垚鍔熻繍琛屽緱鍒帮細

- project 鐩綍
  - `/home/shulun/project/LightWorld/backend/input2graph/projects/proj_6d56e4817baf`
- graph id
  - `mirofish_9f0d1c84b2164adf`

### 绀轰緥 2锛氬熀浜庤鍥捐氨鍑嗗 simulation

杈撳叆锛?

- `project_id = proj_6d56e4817baf`
- `graph_id = mirofish_9f0d1c84b2164adf`
- 涓€涓渶灏?Twitter smoke test 鐨?simulation requirement

prepare 闃舵浜х墿锛?

- simulation 鐩綍
  - `/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb`
- 鍏抽敭鏂囦欢
  - [`entity_graph_snapshot.json`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/entity_graph_snapshot.json)
  - [`entity_prompts.json`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/entity_prompts.json)
  - [`twitter_profiles.csv`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/twitter_profiles.csv)
  - [`simulation_config.json`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/simulation_config.json)
  - [`social_relation_graph.json`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/social_relation_graph.json)

杩欎簺鏂囦欢鍚勮嚜鐨勪綔鐢細

- `entity_graph_snapshot.json`
  - 璇箟鍥捐氨鍒?simulation 鐨勬ˉ鎺ユ枃浠?
- `entity_prompts.json`
  - 涓?runtime 鎻愪緵璇箟鐩镐技搴︿笌璁板繂妫€绱㈡彁绀?
- `twitter_profiles.csv`
  - OASIS 鍒涘缓 agents 鏃剁洿鎺ヨ鍙?
- `simulation_config.json`
  - LightWorld 鑷繁璇诲彇锛岀敤浜庨┍鍔ㄦ椂闂淬€佷簨浠躲€乺untime 琛屼负
- `social_relation_graph.json`
  - LightWorld 鏄惧紡绀句氦鍏崇郴鍏堥獙锛屽悗缁細琚紪璇戞垚鍒濆 follow 杈?

### 绀轰緥 3锛氳繍琛屾椂濡備綍缂栬瘧杩?OASIS DB

褰?runtime 鍚姩鏃讹紝娴佺▼鏄細

1. `twitter_profiles.csv` 琚姞杞芥垚 OASIS agent graph
2. `simulation_config.json` 鍚敤锛?
   - topology-aware runtime
   - simple memory
   - initial posts
   - scheduled events
3. `social_relation_graph.json` 琚?`TopologyAwareRuntime` 璇诲彇
4. 鍒濆绀句氦杈硅鍐欏叆 OASIS 鐨?`follow` 琛?
5. 杩愯鏃跺姩浣滅户缁啓鍏ワ細
   - `post`
   - `follow`
   - `trace`
   - `rec`

涓€娆″凡缁忛獙璇佹垚鍔熺殑鍗曞钩鍙拌繍琛屼骇鐢熶簡锛?

- runtime DB
  - [`twitter_simulation.db`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/twitter_simulation.db)
- 鐜鐘舵€佹枃浠?
  - [`env_status.json`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/env_status.json)
- 涓绘棩蹇?
  - [`simulation.log`](/home/shulun/project/LightWorld/output/simulations/sim_826a7c28a5eb/simulation.log)

杩欐楠岃瘉涓彲浠ユ槑纭湅鍒帮細

- 鍒濆 follow 杈瑰湪 round loop 寮€濮嬪墠宸茬粡琚敞鍏ユ暟鎹簱
- 涓€涓?`scheduled create_post` 浜嬩欢琚Е鍙戯紝骞朵笖鐪熷疄鍐欏叆浜?`post` 琛?
- 涓€涓?`hot_topics_update` 浜嬩欢鍦ㄨ繍琛屾椂琚Е鍙?

## 瀹為檯鐞嗚В鏂瑰紡

瑕佹纭悊瑙ｈ繖濂楃郴缁燂紝鏈€閲嶈鐨勬槸鍖哄垎涓ょ被瀵硅薄锛?

- `social_relation_graph.json`
  - LightWorld 鑷繁缁存姢鐨勬樉寮忓叧绯诲厛楠屾枃浠?
- `twitter_simulation.db` / `reddit_simulation.db`
  - OASIS 鐪熸鎵ц鏃剁殑涓栫晫鐘舵€佹暟鎹簱

杩愯鏃朵笉鏄€滄妸 JSON 鐩存帴鍠傜粰 OASIS 灏辩粨鏉熶簡鈥濄€?
鏇村噯纭湴璇达紝LightWorld 鍏堟妸鑷繁鐨勪腑闂翠骇鐗╃紪璇戣繘 OASIS 鐘舵€侀噷锛?
鑰岀湡姝ｆ墽琛屾ā鎷熺殑搴曞眰涓栫晫锛屾槸鏁版嵁搴撲腑鐨勮繍琛屾椂鐘舵€併€?

