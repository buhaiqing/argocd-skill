"""字段 → CLI flag 映射表。

数据源：skills/argocd-skill/references/kustomize-mapping.md
任何修改请保持两边同源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


SAFE_NAME_TRANSLATION = str.maketrans({"_": "-"})


def safe_app_name(raw: str) -> str:
    """argocd 应用名不允许下划线，统一替换为连字符。"""
    return raw.translate(SAFE_NAME_TRANSLATION)


def get_path(data: dict, path: str, default: Any = None) -> Any:
    """按点分路径取值，缺失返回 default。"""
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class Flag:
    """一条已渲染好的 CLI flag，按顺序拼接到命令中。"""

    name: str          # 例如 "--repo"
    value: str | None = None   # None 代表布尔 flag（如 --set-finalizer）

    def render(self) -> str:
        if self.value is None:
            return self.name
        return f"{self.name} {self.value}"


@dataclass
class UnsupportedField:
    """识别到但 CLI 无对应 flag 的字段。"""

    path: str
    reason: str        # "no_cli_flag" / "must_use_yaml"
    suggestion: str    # 处置建议


# ---- 已识别字段白名单（用于检测未知字段并告警） -----------------------------
#
# 维护同源：与 references/kustomize-mapping.md 保持一致。
# 任何新增字段都应先加入 mapping.md 再在此登记。
# ---------------------------------------------------------------------------

KNOWN_META_FIELDS = {"name", "namespace", "finalizers", "labels", "annotations",
                     "uid", "resourceVersion", "generation", "creationTimestamp",
                     "managedFields", "ownerReferences"}

KNOWN_SPEC_FIELDS = {"source", "sources", "destination", "project", "syncPolicy",
                     "revisionHistoryLimit", "info", "ignoreDifferences"}

KNOWN_SOURCE_FIELDS = {"repoURL", "targetRevision", "path", "kustomize",
                       "helm", "directory", "plugin", "chart", "ref"}

KNOWN_KUSTOMIZE_FIELDS = {"version", "namePrefix", "nameSuffix", "namespace",
                          "kubeVersion", "images", "commonLabels", "commonAnnotations",
                          "replicas", "apiVersions", "patches", "components",
                          "labelWithoutSelector", "forceCommonLabels",
                          "forceCommonAnnotations", "labelIncludeTemplates",
                          "commonAnnotationsEnvsubst", "ignoreMissingComponents"}

KNOWN_DEST_FIELDS = {"server", "namespace", "name"}

KNOWN_SYNCPOLICY_FIELDS = {"automated", "syncOptions", "retry", "managedNamespaceMetadata"}


def _detect_unknown_fields(manifest: dict) -> list[UnsupportedField]:
    """扫描已识别"层"中的未知 key，返回 info 级别警告列表。

    只检查我们已实现映射的层级；未映射的字段（如 spec.info）整体跳过。
    """
    out: list[UnsupportedField] = []

    meta = manifest.get("metadata") or {}
    for k in meta:
        if k not in KNOWN_META_FIELDS:
            out.append(UnsupportedField(
                path=f"metadata.{k}",
                reason="unknown_field",
                suggestion="字段未在 mapping.md 登记，CLI 映射时已跳过；如需保留请改用 kubectl apply",
            ))

    spec = manifest.get("spec") or {}
    for k in spec:
        if k not in KNOWN_SPEC_FIELDS:
            out.append(UnsupportedField(
                path=f"spec.{k}",
                reason="unknown_field",
                suggestion="同上",
            ))

    src = spec.get("source") or {}
    for k in src:
        if k not in KNOWN_SOURCE_FIELDS:
            out.append(UnsupportedField(
                path=f"spec.source.{k}",
                reason="unknown_field",
                suggestion="同上",
            ))

    kus = src.get("kustomize") or {}
    for k in kus:
        if k not in KNOWN_KUSTOMIZE_FIELDS:
            out.append(UnsupportedField(
                path=f"spec.source.kustomize.{k}",
                reason="unknown_field",
                suggestion="同上",
            ))

    dest = spec.get("destination") or {}
    for k in dest:
        if k not in KNOWN_DEST_FIELDS:
            out.append(UnsupportedField(
                path=f"spec.destination.{k}",
                reason="unknown_field",
                suggestion="同上",
            ))

    sp = spec.get("syncPolicy") or {}
    for k in sp:
        if k not in KNOWN_SYNCPOLICY_FIELDS:
            out.append(UnsupportedField(
                path=f"spec.syncPolicy.{k}",
                reason="unknown_field",
                suggestion="同上",
            ))

    return out


# ---- 元数据 --------------------------------------------------------------

def map_metadata(spec_root: dict) -> tuple[list[Flag], list[UnsupportedField], str]:
    """返回 (flags, warnings, app_name_positional)."""
    flags: list[Flag] = []
    warnings: list[UnsupportedField] = []

    raw_name = get_path(spec_root, "metadata.name", "")
    app_name = safe_app_name(str(raw_name))

    ns = get_path(spec_root, "metadata.namespace")
    if ns:
        flags.append(Flag("--app-namespace", str(ns)))

    finalizers = get_path(spec_root, "metadata.finalizers") or []
    if any("resources-finalizer.argocd.argoproj.io" in f for f in finalizers):
        flags.append(Flag("--set-finalizer"))

    labels = get_path(spec_root, "metadata.labels") or {}
    for k, v in labels.items():
        flags.append(Flag("--label", f"{k}={v}"))

    annotations = get_path(spec_root, "metadata.annotations") or {}
    for k, v in annotations.items():
        flags.append(Flag("--annotations", f"{k}={v}"))

    return flags, warnings, app_name


# ---- 源字段（单源） ------------------------------------------------------

def map_source(spec_root: dict) -> tuple[list[Flag], list[UnsupportedField]]:
    flags: list[Flag] = []
    warnings: list[UnsupportedField] = []

    src = get_path(spec_root, "spec.source") or {}

    if "repoURL" in src:
        flags.append(Flag("--repo", str(src["repoURL"])))
    if "targetRevision" in src:
        flags.append(Flag("--revision", str(src["targetRevision"])))
    if "path" in src:
        flags.append(Flag("--path", str(src["path"])))

    kustomize = src.get("kustomize") or {}
    flags.extend(_map_kustomize(kustomize, warnings))

    return flags, warnings


def _map_kustomize(kus: dict, warnings: list[UnsupportedField]) -> list[Flag]:
    flags: list[Flag] = []

    if "version" in kus:
        flags.append(Flag("--kustomize-version", str(kus["version"])))
    if "namePrefix" in kus:
        flags.append(Flag("--kustomize-nameprefix", str(kus["namePrefix"])))
    if "nameSuffix" in kus:
        flags.append(Flag("--kustomize-namesuffix", str(kus["nameSuffix"])))
    if "namespace" in kus:
        flags.append(Flag("--kustomize-namespace", str(kus["namespace"])))
    if "kubeVersion" in kus:
        flags.append(Flag("--kustomize-kube-version", str(kus["kubeVersion"])))

    for img in kus.get("images") or []:
        flags.append(Flag("--kustomize-image", str(img)))

    for k, v in (kus.get("commonLabels") or {}).items():
        flags.append(Flag("--kustomize-common-label", f"{k}={v}"))
    for k, v in (kus.get("commonAnnotations") or {}).items():
        flags.append(Flag("--kustomize-common-annotation", f"{k}={v}"))

    for rep in kus.get("replicas") or []:
        if isinstance(rep, dict) and "name" in rep and "count" in rep:
            flags.append(Flag("--kustomize-replicas", f"{rep['name']}={rep['count']}"))

    for api in kus.get("apiVersions") or []:
        flags.append(Flag("--kustomize-api-versions", str(api)))

    for bool_field, flag_name in (
        ("labelWithoutSelector", "--kustomize-label-without-selector"),
        ("forceCommonLabels", "--kustomize-force-common-labels"),
        ("forceCommonAnnotations", "--kustomize-force-common-annotations"),
        ("labelIncludeTemplates", "--kustomize-label-include-templates"),
        ("commonAnnotationsEnvsubst", "--kustomize-common-annotation-envsubst"),
        ("ignoreMissingComponents", "--ignore-missing-components"),
    ):
        if kus.get(bool_field):
            flags.append(Flag(flag_name))

    if "patches" in kus:
        warnings.append(UnsupportedField(
            path="spec.source.kustomize.patches",
            reason="no_cli_flag",
            suggestion="将 patches 写入 overlays 的 kustomization.yaml，或保留整 YAML 使用 kubectl apply 管理",
        ))
    if "components" in kus:
        warnings.append(UnsupportedField(
            path="spec.source.kustomize.components",
            reason="no_cli_flag",
            suggestion="保留 YAML 方式管理 components",
        ))

    return flags


# ---- 目标字段 ------------------------------------------------------------

def map_destination(spec_root: dict) -> list[Flag]:
    """映射 destination 字段。所有取值采用 truthy 检查，自动跳过空字符串。"""
    flags: list[Flag] = []
    dest = get_path(spec_root, "spec.destination") or {}

    if dest.get("server"):
        flags.append(Flag("--dest-server", str(dest["server"])))
    if dest.get("namespace"):
        flags.append(Flag("--dest-namespace", str(dest["namespace"])))
    if dest.get("name"):
        flags.append(Flag("--dest-name", str(dest["name"])))

    return flags


# ---- 同步策略 ------------------------------------------------------------

def map_sync_policy(spec_root: dict) -> list[Flag]:
    flags: list[Flag] = []
    sp = get_path(spec_root, "spec.syncPolicy") or {}

    automated = sp.get("automated")
    if automated is not None:
        flags.append(Flag("--sync-policy", "automated"))
        if isinstance(automated, dict):
            if automated.get("prune"):
                flags.append(Flag("--auto-prune"))
            if automated.get("selfHeal"):
                flags.append(Flag("--self-heal"))
            if automated.get("allowEmpty"):
                flags.append(Flag("--allow-empty"))

    for opt in sp.get("syncOptions") or []:
        flags.append(Flag("--sync-option", str(opt)))

    retry = sp.get("retry") or {}
    if "limit" in retry:
        flags.append(Flag("--sync-retry-limit", str(retry["limit"])))
    backoff = retry.get("backoff") or {}
    if "duration" in backoff:
        flags.append(Flag("--sync-retry-backoff-duration", str(backoff["duration"])))
    if "factor" in backoff:
        flags.append(Flag("--sync-retry-backoff-factor", str(backoff["factor"])))
    if "maxDuration" in backoff:
        flags.append(Flag("--sync-retry-backoff-max-duration", str(backoff["maxDuration"])))

    return flags


# ---- 项目与其他 ----------------------------------------------------------

def map_misc(spec_root: dict) -> list[Flag]:
    flags: list[Flag] = []
    project = get_path(spec_root, "spec.project")
    if project:
        flags.append(Flag("--project", str(project)))

    rhl = get_path(spec_root, "spec.revisionHistoryLimit")
    if rhl is not None:
        flags.append(Flag("--revision-history-limit", str(rhl)))

    return flags


# ---- 总入口 --------------------------------------------------------------

@dataclass
class MappedApp:
    app_name: str                        # 位置参数（已做 _→- 转换）
    raw_name: str                        # 原始 metadata.name
    flags: list[Flag] = field(default_factory=list)
    warnings: list[UnsupportedField] = field(default_factory=list)

    def render(self, upsert: bool = True, prefix: str = "argocd app create") -> str:
        lines = [f"{prefix} {self.app_name}"]
        if upsert:
            lines.append("--upsert")
        lines.extend(flag.render() for flag in self.flags)
        return " \\\n  ".join(lines)


def map_single_source(manifest: dict) -> MappedApp:
    """对单源 Application YAML 做完整映射。

    调用方须先确认 manifest 不含 spec.sources（由 parser 做层级判定）。
    """
    meta_flags, meta_warnings, app_name = map_metadata(manifest)
    src_flags, src_warnings = map_source(manifest)

    flags: list[Flag] = []
    flags.extend(meta_flags)
    flags.extend(map_misc(manifest))
    flags.extend(src_flags)
    flags.extend(map_destination(manifest))
    flags.extend(map_sync_policy(manifest))

    return MappedApp(
        app_name=app_name,
        raw_name=str(get_path(manifest, "metadata.name", "")),
        flags=flags,
        warnings=meta_warnings + src_warnings + _detect_unknown_fields(manifest),
    )
