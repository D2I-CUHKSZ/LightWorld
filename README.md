<div align="center">


<img src="https://capsule-render.vercel.app/api?type=venom&height=250&text=LIGHTWORLD&fontColor=00ffcc&stroke=00ffcc&color=0:050505,50:0f1115,100:000000&animation=fadeIn&fontAlignY=38&desc=Lightweight%20Omni-Modal%20Emergent%20Social%20Simulation%20Engine&descAlignY=60" width="100%" />

# `L I G H T W O R L D`

### Matrix / Cyberpunk Protocol

**Lightweight · Omni-Modal · Emergent Social Simulation & Prediction Engine**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-050505.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=00ffcc)](https://opensource.org/licenses/AGPL-3.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-050505.svg?style=for-the-badge&logo=python&logoColor=00ffcc)](#-quick-start--boot-protocol)
[![Omni-Modal](https://img.shields.io/badge/Inputs-Graph%20%7C%20Text%20%7C%20Image%20%7C%20Video-050505.svg?style=for-the-badge&logo=graphql&logoColor=00ffcc)](#-matrix-architecture)
[![Concurrency](https://img.shields.io/badge/Agent%20Scale-100k%2B-050505.svg?style=for-the-badge&logo=apachespark&logoColor=00ffcc)](#-core-capabilities)

<img src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&size=19&duration=2300&pause=650&color=00FFCC&center=true&vCenter=true&width=980&lines=Booting+distributed+agent+civilization...;Injecting+real-world+signals+into+sandbox+physics...;Forecasting+collective+trajectories+before+they+happen..." alt="typing-banner" />

*"In minimalist code, we simulate the reflection of the entire world."*

[English](#) · [简体中文](#) · [Project Whitepaper](#) · [Video Demo](#)

</div>

---

## `> system.dashboard`

| Channel         | Status | Throughput   | Note                              |
| --------------- | ------ | ------------ | --------------------------------- |
| Graph Ingestion | ONLINE | 98%          | topology + influence edges        |
| Text Stream     | ONLINE | 82%          | news, posts, narratives           |
| Image Parser    | ONLINE | 91%          | meme semantics + visual sentiment |
| Video Tracker   | ONLINE | 76%          | event timeline + motion cues      |
| Swarm Runtime   | ACTIVE | 100k+ agents | debate, clustering, polarization  |

```bash
$ lightworld --init matrix
> [SYSTEM] Booting Light Engine... [OK]
> [DATA] Graph/Text/Image/Video streams attached... [OK]
> [AGENT] 100,000 autonomous agents online... [OK]
> [STATUS] Simulation ACTIVE. Predicting trajectory shifts...
┌───────────────────────── LIGHTWORLD RUNTIME MATRIX ─────────────────────────┐
│ Attention Heatmap   ████████████░░░░  72%                                   │
│ Narrative Volatility █████████████░░░  79%                                   │
│ Polarization Index   ██████████░░░░░░  63%                                   │
│ Intervention Window  ███████████████░  91%                                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 👁️‍🗨️ Concept: `LIGHT + WORLD`

Current AI agent systems often face three bottlenecks:

- **Token Waste**: repeated heavyweight context and expensive monolithic calls.
- **Zero Sharing**: isolated execution with limited experiential transfer.
- **Text-Only Blindness**: weak grounding in visual and dynamic reality.

**lightworld** breaks this deadlock through two design axes:

- **⚡ LIGHT (Minimalist & Lightweight)**  
  Experience sharing + dynamic context compression reduce concurrent simulation cost by orders of magnitude.

- **🌍 WORLD (Real-World Mapping)**  
  Native ingestion for **Graph (social topology)**, **Text (public narratives)**, **Image (visual sentiment)**, and **Video (event dynamics)**.

---

## 🧬 Core Capabilities

<details>
<summary><b>🕸️ Multi-Source Graph Injection</b></summary>
<br>
Import social topology (e.g., X/Twitter) as first-class simulation physics. The engine reconstructs implicit power networks from follows, reposts, and likes to model KOLs, bot swarms, and peripheral groups.
</details>


<details>
<summary><b>🎬 Omni-Modal Sensory Input</b></summary>
<br>
Agents ingest not just text reports, but also videos and memes. Visual sentiment and event cues are injected directly into decision and emotion update modules.
</details>


<details>
<summary><b>🧠 Self-Evolving Swarm Intelligence</b></summary>
<br>
20+ social actions (follow, repost, debate, block, coalition, etc.) produce emergent phenomena such as echo chambers, cascades, and polarization.
</details>


<details>
<summary><b>📈 Temporal What-If Forecaster</b></summary>
<br>
Inject shocks at runtime (debunk release, node failure, policy intervention) and measure trajectory divergence across demographics over time.
</details>


---

## 🧱 Matrix Architecture

*Dynamic data flow and system architecture:*

```mermaid
graph TD
    %% 强制使用明亮清爽的默认主题，文字清晰可见
    %%{init: {'theme': 'default', 'themeVariables': { 'fontFamily': 'sans-serif'}}}%%

    %% 定义明亮高对比度的样式类
    classDef input fill:#ffffff,stroke:#d0d7de,stroke-width:2px,color:#24292f,rx:8,ry:8;
    classDef core fill:#e6f0ff,stroke:#0969da,stroke-width:3px,color:#0969da,shadow:true;
    classDef swarm fill:#f3fdf8,stroke:#1a7f37,stroke-width:2px,color:#116329,stroke-dasharray: 4 4,rx:20,ry:20;
    classDef kg fill:#fff8f2,stroke:#bf8700,stroke-width:2px,color:#9a6700,rx:5,ry:5;
    classDef output fill:#f6f8fa,stroke:#8250df,stroke-width:2px,color:#6639ba,rx:8,ry:8;

    %% 1. 现实世界数据源
    subgraph Reality [🌍 Real-World Data Sources]
        direction LR
        G[🕸️ Graph<br>Twitter-X]:::input
        T[📜 Text<br>News/Blogs]:::input
        I[👁️ Image<br>Memes/Pics]:::input
        V[🎬 Video<br>Events/Streams]:::input
    end

    %% 2. 核心大模型融合引擎
    M(((🧠 Multi-Modal<br>Fusion Engine))):::core

    %% 3. 数字沙盒世界 (明亮的浅蓝灰背景)
    subgraph Sandbox [🏛️ LightWorld Sandbox Environment]
        K[(🌐 Dynamic<br>Knowledge Graph)]:::kg
        
        A1(🤖 Agent Swarm Alpha):::swarm
        A2(🤖 Agent Swarm Beta):::swarm
        A3(🤖 Agent Swarm Gamma):::swarm
        
        %% 智能体与知识图谱的交互
        A1 <==> K
        A2 <==> K
        A3 <==> K
        
        %% 智能体之间的社会关系网络
        A1 <-.->|Debate / Block| A2
        A2 <-.->|Influence| A3
        A3 <-.->|Coalition| A1
    end

    %% 4. 输出预测报告
    O{{📊 Temporal Prediction Report}}:::output

    %% ================= 连线逻辑 =================
    G --> M
    T --> M
    I --> M
    V --> M
    
    M ==>|Ontology Compilation| K
    M ==>|Persona Initialization| A1
    M ==>|Persona Initialization| A2
    M ==>|Persona Initialization| A3
    
    Sandbox ==> O

    %% ================= 子图美化 =================
    %% 外部虚线框
    style Reality fill:transparent,stroke:#d0d7de,stroke-width:2px,stroke-dasharray: 5 5,rx:10,ry:10
    %% 沙盒区域使用非常柔和的浅色底（#f3f6f9），完全不黑了
    style Sandbox fill:#f3f6f9,stroke:#c0d3e6,stroke-width:2px,rx:10,ry:10
```

---

## ⚙️ Action Space Snapshot

| Layer       | Representative Actions                       | Emergent Effect          |
| ----------- | -------------------------------------------- | ------------------------ |
| Information | read, summarize, amplify, suppress           | narrative drift          |
| Social      | follow, mention, debate, block, cluster      | faction formation        |
| Cognitive   | update memory, adjust bias, confidence decay | belief polarization      |
| Strategic   | coordinate campaign, react to intervention   | cascade or stabilization |

---

## 🧪 Scenario Injection Examples

- **Deepfake Shock**: inject high-intensity visual rumor at `t=3`.
- **Debunk Counterwave**: release correction narrative at `t=9`.
- **Node Failure**: disable key financial/information hub at runtime.
- **Policy Intervention**: increase moderation threshold for a target cluster.

---

## 📦 Quick Start | Boot Protocol

```bash
# 1) Access the Matrix
git clone https://github.com/JayLZhou/LightWorld.git
cd LightWorld

# 2) Install cybernetic implants
pip install -r requirements.txt
playwright install

# 3) Ignite the world
python engine.py --mode matrix \
  --graph ./data/twitter_seed.json \
  --video ./data/breaking_news.mp4
```

### Minimal Graph Seed (`data/twitter_seed.json`)

```json
{
  "nodes": [
    {"id": "kol_01", "role": "KOL", "stance": 0.65, "followers": 320000},
    {"id": "group_a_01", "role": "citizen", "stance": 0.20, "followers": 540},
    {"id": "bot_01", "role": "bot", "stance": -0.75, "followers": 1200}
  ],
  "edges": [
    {"source": "group_a_01", "target": "kol_01", "type": "follow", "weight": 0.80},
    {"source": "bot_01", "target": "group_a_01", "type": "repost", "weight": 0.60}
  ],
  "events": [
    {"t": 3, "type": "video_injection", "payload": {"sentiment": -0.4}},
    {"t": 9, "type": "debunk_release", "payload": {"strength": 0.7}}
  ]
}
```

> 💡 **Offline Protocol**: For zero-API-cost local deployment, see `Offline-Deployment-Guide.md`.

---

## 🏆 Hall of Inspiration & Acknowledgments

**lightworld** stands on the work of pioneering open-source teams:

- 🐟 **[MiroFish](https://github.com/666ghj/MiroFish) (by @666ghj)**  
  *"The micro-laboratory for predicting everything."* Foundational digital-sandbox interaction ideas and graph-memory mechanisms.
- 🏝️ **[OASIS](https://github.com/camel-ai/oasis) (by CAMEL-AI)**  
  *"The lawgiver of million-agent societies."* Core inspiration for large-scale social-action architecture.

---

## 🛣️ Roadmap Signal

- [ ] Public benchmark scenarios (financial rumor / election narrative / crisis communication)
- [ ] Plug-in adapters for Reddit, Discord, and newswire feeds
- [ ] Reproducible evaluation suite for intervention policy tests
- [ ] End-to-end offline million-agent deployment tutorial

<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:050505,100:00ffcc&height=120&section=footer" width="100%" />
</div>
