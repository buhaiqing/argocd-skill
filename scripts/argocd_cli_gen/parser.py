"""YAML 加载与应用层级判定。

层级决策树（来自 SKILL.md）：

    spec.sources?
    ├─ 是 → 每个 source 均满足 (chart | ref) 且至少含一个 chart 源
    │       ├─ 是 → MULTI_SOURCE_HELM（Helm + $values 模式；可用 `argocd app create -f` 处理）
    │       └─ 否 → MULTI_SOURCE（CLI 无法表达，回退 kubectl apply）
    │
    └─ 否 → 单源
           │
           ├─ destination.namespace == "argo-root"
           │   │   └ 含 metadata.finalizers → ROOT_APP（聚合入口）
           │   │   └ 否则                    → INFRA_ROOT（管理 root 的 root）
           │
           ├─ path/revision 命中运维特征  → OPS_APP
           │
           └─ 其他                          → BUSINESS_APP
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml


class Tier(str, enum.Enum):
    INFRA_ROOT = "infra_root"                # 自启动 root（projects/repos/initns）
    ROOT_APP = "root_app"                    # 聚合 Root
    BUSINESS_APP = "business_app"            # 业务应用
    OPS_APP = "ops_app"                      # 运维组件
    MULTI_SOURCE_HELM = "multi_source_helm"  # 多源 Helm + $values（用 `argocd app create -f` 处理）
    MULTI_SOURCE = "multi_source"            # 多源（CLI 完全不支持，回退 kubectl apply）
    UNKNOWN = "unknown"                      # 非 Application 或无法判定


# 运维特征：path 或 revision 中包含这些子串视为运维组件
OPS_REVISION_KEYWORDS = ("k8s_ops", "k8s-ops")
OPS_NAMESPACE_KEYWORDS = ("ops", "loki", "kube-system", "rabbitmq-system",
                          "argo-rollouts", "argocd")


@dataclass
class LoadedManifest:
    path: Path
    manifest: dict
    tier: Tier
    reason: str = ""        # 判定依据，可用于报告

    @property
    def name(self) -> str:
        return str((self.manifest.get("metadata") or {}).get("name", ""))


def is_application(manifest: dict) -> bool:
    return (manifest.get("apiVersion", "").startswith("argoproj.io/")
            and manifest.get("kind") == "Application")


def _is_helm_multisource(sources: list) -> bool:
    """判定多源结构是否落在"Helm chart + values ref"模式。

    规则（取自 argocd 官方多源用法）：
      1. 每个 source 必须是 dict
      2. 每个 source 要么是 helm chart 源（含 ``chart`` 字段，通常配 ``helm.valueFiles``）
         要么是 values ref 源（含 ``ref`` 字段，用作 ``$values`` 跨源引用）
      3. 至少要有一个 chart 源（仅 ref 源没意义；纯多 chart 则需走传统 kubectl）

    满足上述三点的可用 ``argocd app create -f <yaml>`` 创建；
    其余多源场景（如多个 Git path、自定义 plugin）仍归 MULTI_SOURCE 兜底。
    """
    if not sources or not isinstance(sources, list):
        return False

    has_chart = False
    for s in sources:
        if not isinstance(s, dict):
            return False
        is_chart = bool(s.get("chart"))
        is_ref = bool(s.get("ref"))
        if not (is_chart or is_ref):
            return False
        if is_chart:
            has_chart = True
    return has_chart


def detect_tier(manifest: dict) -> tuple[Tier, str]:
    if not is_application(manifest):
        return Tier.UNKNOWN, "not_argocd_application"

    spec = manifest.get("spec") or {}
    sources = spec.get("sources")
    if sources:
        if _is_helm_multisource(sources):
            return Tier.MULTI_SOURCE_HELM, "helm_chart_with_values_ref"
        return Tier.MULTI_SOURCE, "has_spec_sources"

    dest = spec.get("destination") or {}
    dest_ns = str(dest.get("namespace", ""))

    if dest_ns == "argo-root":
        meta = manifest.get("metadata") or {}
        if meta.get("finalizers"):
            return Tier.ROOT_APP, "namespace=argo-root + finalizers"
        return Tier.INFRA_ROOT, "namespace=argo-root + no finalizers"

    src = spec.get("source") or {}
    revision = str(src.get("targetRevision", ""))
    path = str(src.get("path", ""))

    if any(kw in revision for kw in OPS_REVISION_KEYWORDS):
        return Tier.OPS_APP, f"revision contains ops keyword ({revision})"

    if dest_ns in OPS_NAMESPACE_KEYWORDS and dest_ns != "argocd":
        return Tier.OPS_APP, f"dest_namespace={dest_ns} is ops"

    return Tier.BUSINESS_APP, "default"


def load_manifest(path: Path) -> LoadedManifest | None:
    """加载单个 YAML 文件，兼容多文档结构。

    多文档场景下（如 `initns/*.yaml` 含 Namespace + ResourceQuota）取第一个 Application 文档；
    若全部为非 Application 资源则返回 None。
    """
    try:
        with path.open("r", encoding="utf-8") as fp:
            docs = list(yaml.safe_load_all(fp))
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse failure at {path}: {exc}") from exc

    for data in docs:
        if not isinstance(data, dict):
            continue
        if not is_application(data):
            continue
        tier, reason = detect_tier(data)
        return LoadedManifest(path=path, manifest=data, tier=tier, reason=reason)

    return None


def iter_yaml_files(root: Path, include: str = "**/*.yaml") -> Iterator[Path]:
    yield from sorted(root.glob(include))


def load_directory(root: Path, include: str = "**/*.yaml") -> list[LoadedManifest]:
    """递归扫描目录，加载所有 Application YAML。

    非 Application 的 YAML（如 Project / Repository CR）会被跳过且不计入返回。
    """
    out: list[LoadedManifest] = []
    for p in iter_yaml_files(root, include):
        lm = load_manifest(p)
        if lm is None or lm.tier == Tier.UNKNOWN:
            continue
        out.append(lm)
    return out
