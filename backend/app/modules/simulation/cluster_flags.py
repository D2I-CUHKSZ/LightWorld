"""Shared topology cluster feature flag helpers."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def resolve_cluster_feature_flags(topo_cfg: Dict[str, Any]) -> Tuple[bool, bool]:
    """Resolve cluster toggles with backward compatibility to `cluster_mode`."""
    cfg = topo_cfg if isinstance(topo_cfg, dict) else {}
    explicit_flags = (
        "threshold_cluster_enabled" in cfg or
        "llm_keyword_cluster_enabled" in cfg
    )

    if explicit_flags:
        threshold_enabled = _to_bool(cfg.get("threshold_cluster_enabled", False))
        llm_enabled = _to_bool(cfg.get("llm_keyword_cluster_enabled", False))
    else:
        cluster_mode = str(cfg.get("cluster_mode", "") or "").strip().lower()
        if cluster_mode == "threshold_only":
            threshold_enabled, llm_enabled = True, False
        elif cluster_mode == "llm_keyword_consistency":
            threshold_enabled, llm_enabled = False, True
        else:
            threshold_enabled, llm_enabled = False, False

    if threshold_enabled and llm_enabled:
        raise ValueError(
            "topology_aware.threshold_cluster_enabled and "
            "topology_aware.llm_keyword_cluster_enabled cannot both be true."
        )
    return threshold_enabled, llm_enabled


def normalize_topology_cluster_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize cluster feature toggles onto config['topology_aware'].

    Returns the normalized topology_aware dict and mutates `config`.
    """
    topo_cfg = config.get("topology_aware", {}) or {}
    if not isinstance(topo_cfg, dict):
        topo_cfg = {}

    threshold_enabled, llm_enabled = resolve_cluster_feature_flags(topo_cfg)
    topo_cfg["threshold_cluster_enabled"] = threshold_enabled
    topo_cfg["llm_keyword_cluster_enabled"] = llm_enabled
    if llm_enabled:
        topo_cfg["cluster_mode"] = "llm_keyword_consistency"
    elif threshold_enabled:
        topo_cfg["cluster_mode"] = "threshold_only"
    else:
        topo_cfg["cluster_mode"] = "disabled"

    config["topology_aware"] = topo_cfg
    return topo_cfg
