"""转换报告生成（JSON + Markdown）。"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fallback import FallbackBundle, FallbackEntry
from .mapper import MappedApp, UnsupportedField
from .parser import LoadedManifest, Tier


@dataclass
class Warning_:
    file: str
    name: str
    severity: str        # "info" / "warning" / "error"
    reason: str
    field_path: str = ""
    suggestion: str = ""


@dataclass
class Report:
    timestamp: str
    input_dir: str
    output_dir: str
    total: int = 0
    by_tier: dict[str, int] = field(default_factory=dict)
    converted: int = 0
    fallback_to_yaml: int = 0
    helm_multisource: int = 0     # 走 `argocd app create -f` 的多源 Helm 应用数
    failed: int = 0
    warnings: list[Warning_] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# argocd-cli-gen 转换报告")
        lines.append("")
        lines.append(f"- **生成时间：** {self.timestamp}")
        lines.append(f"- **输入目录：** `{self.input_dir}`")
        lines.append(f"- **输出目录：** `{self.output_dir}`")
        lines.append("")
        lines.append("## 总览")
        lines.append("")
        lines.append("| 指标 | 数量 |")
        lines.append("|---|---|")
        lines.append(f"| 输入 Application 总数 | {self.total} |")
        lines.append(f"| 成功转换为 CLI | {self.converted} |")
        lines.append(f"| └ 含多源 Helm（argocd app create -f） | {self.helm_multisource} |")
        lines.append(f"| 回退到 YAML | {self.fallback_to_yaml} |")
        lines.append(f"| 失败 | {self.failed} |")
        lines.append("")
        lines.append("## 按层级分布")
        lines.append("")
        lines.append("| 层级 | 数量 |")
        lines.append("|---|---|")
        for tier_name, count in sorted(self.by_tier.items()):
            lines.append(f"| {tier_name} | {count} |")
        lines.append("")

        if self.warnings:
            lines.append("## 警告与回退明细")
            lines.append("")
            lines.append("| 严重度 | 文件 | 应用名 | 原因 | 涉及字段 | 建议 |")
            lines.append("|---|---|---|---|---|---|")
            for w in self.warnings:
                lines.append(
                    f"| {w.severity} | `{w.file}` | {w.name} | {w.reason} | "
                    f"`{w.field_path}` | {w.suggestion} |"
                )
            lines.append("")
        else:
            lines.append("## 警告")
            lines.append("")
            lines.append("无。")
            lines.append("")

        lines.append("## 后续操作")
        lines.append("")
        lines.append("1. 阅读 `report.json`（机器可读） 和本文档（人读）")
        lines.append("2. 运行 `bash 00_preflight.sh` 验证 argocd 连接")
        lines.append("3. 用 dry-run 副本灰度：`bash 30_workloads_business.dry-run.sh`")
        if self.helm_multisource > 0:
            lines.append("   - 多源 Helm 同样有 dry-run：`bash 40_workloads_helm.dry-run.sh`")
        lines.append("4. 确认无误后执行 `bash run_all.sh`")
        step = 5
        if self.helm_multisource > 0:
            lines.append(
                f"{step}. **多源 Helm 单独跑：** `bash 40_workloads_helm.sh`（依赖同目录 `helm-apps/*.yaml`）"
            )
            step += 1
        if self.fallback_to_yaml > 0:
            lines.append(
                f"{step}. **额外步骤：** `kubectl -n argocd apply -f 99_multisource_fallback.yaml`"
            )
        lines.append("")

        return "\n".join(lines)


def build(
    loaded: list[LoadedManifest],
    mapped_by_tier: dict[Tier, list[MappedApp]],
    fallback: FallbackBundle,
    input_dir: Path,
    output_dir: Path,
    timestamp: str | None = None,
) -> Report:
    ts = timestamp or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = Report(
        timestamp=ts,
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        total=len(loaded),
    )

    # 按层级统计
    for lm in loaded:
        key = lm.tier.value
        report.by_tier[key] = report.by_tier.get(key, 0) + 1

    report.fallback_to_yaml = len(fallback.entries)
    report.converted = report.total - report.fallback_to_yaml
    report.helm_multisource = report.by_tier.get(Tier.MULTI_SOURCE_HELM.value, 0)

    # 汇总多源回退到 warnings
    for entry in fallback.entries:
        report.warnings.append(Warning_(
            file=str(entry.path),
            name=entry.name,
            severity="warning",
            reason=entry.reason,
            field_path=", ".join(entry.fields),
            suggestion="使用 kubectl apply -f 99_multisource_fallback.yaml",
        ))

    # 汇总 mapper 报告的不支持字段
    for tier, apps in mapped_by_tier.items():
        for app in apps:
            for w in app.warnings:
                report.warnings.append(Warning_(
                    file="(see fallback)",
                    name=app.app_name,
                    severity="info",
                    reason=w.reason,
                    field_path=w.path,
                    suggestion=w.suggestion,
                ))

    return report


def write_report(report: Report, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, md_path
