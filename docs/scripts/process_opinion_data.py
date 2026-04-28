import json
from collections import defaultdict
from pathlib import Path

AMPLIFIER_AGENTS = {"吴根浩", "情绪型路人03", "吃瓜转发用户06", "大刘", "安苏敏"}
VERIFICATION_AGENTS = {
    "Nature 杂志",
    "马普所",
    "中科院物理所",
    "LBNL",
    "伊利诺伊大学",
    "高丽大学化学系",
    "北京大学量子材料科学中心",
    "华中科技大学",
    "金志勋",
    "金贤卓",
    "崔东植",
    "崔东植教授",
    "李世培",
}
CLAIM_AGENTS = {"韩国量子能源研究中心团队", "LK-99"}

ACTION_WEIGHT = {
    "CREATE_POST": 3,
    "CREATE_COMMENT": 2,
    "QUOTE_POST": 2,
    "REPOST": 1,
    "LIKE_POST": 1,
    "DISLIKE_POST": 1,
    "LIKE_COMMENT": 1,
    "DO_NOTHING": 0,
    "SEARCH_POSTS": 0,
    "SEARCH_USER": 0,
}

def classify(agent_name: str) -> str:
    if agent_name in CLAIM_AGENTS:
        return "claim"
    if agent_name in AMPLIFIER_AGENTS:
        return "amplifier"
    if agent_name in VERIFICATION_AGENTS:
        return "verification"
    return "observer"


def find_run_dir(project_root: Path) -> Path:
    preferred = (
        project_root
        / "backend/uploads/full_runs/run_20260414_101546_lk-99-hype-and-disillusion-demo/02_simulation_artifacts"
    )
    if (preferred / "twitter_actions.jsonl").exists() and (
        preferred / "reddit_actions.jsonl"
    ).exists():
        return preferred

    run_roots = sorted(
        project_root.glob("backend/uploads/full_runs/*lk-99-hype-and-disillusion-demo")
    )
    for run_root in reversed(run_roots):
        artifact_dir = run_root / "02_simulation_artifacts"
        if (artifact_dir / "twitter_actions.jsonl").exists() and (
            artifact_dir / "reddit_actions.jsonl"
        ).exists():
            return artifact_dir
    raise FileNotFoundError("No LK-99 full run with action logs was found.")


def process(jsonl_path: Path):
    hour_map = {}
    data = defaultdict(lambda: defaultdict(int))
    max_hour = 23

    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("event_type") == "round_start":
                round_id = record["round"]
                simulated_hour = int(record.get("simulated_hour", round_id))
                hour_map[round_id] = simulated_hour
                max_hour = max(max_hour, simulated_hour)
                continue

            agent_name = record.get("agent_name")
            if not agent_name:
                continue

            round_id = int(record.get("round", 0))
            hour = int(hour_map.get(round_id, round_id))
            max_hour = max(max_hour, hour)
            role = classify(agent_name)
            weight = ACTION_WEIGHT.get(record.get("action_type", ""), 0)
            data[hour][role] += weight

    return [
        {
            "hour": hour,
            "claim": data[hour].get("claim", 0),
            "amplifier": data[hour].get("amplifier", 0),
            "verification": data[hour].get("verification", 0),
            "observer": data[hour].get("observer", 0),
        }
        for hour in range(max_hour + 1)
    ]



def main():
    docs_dir = Path(__file__).resolve().parent.parent
    project_root = docs_dir.parent
    artifact_dir = find_run_dir(project_root)

    result = {
        "source_run": artifact_dir.parent.name,
        "twitter": process(artifact_dir / "twitter_actions.jsonl"),
        "reddit": process(artifact_dir / "reddit_actions.jsonl"),
    }

    out_path = docs_dir / "assets" / "opinion_trend_data.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written {out_path}")


if __name__ == "__main__":
    main()
