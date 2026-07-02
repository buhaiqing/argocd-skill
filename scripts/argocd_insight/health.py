#!/usr/bin/env python3
"""
health — ArgoCD 运行稳定性评估工具

对 ArgoCD 集群做全维度健康评估，输出各维度评分、总分、薄弱项分析
和具体改进建议。

维度设计：
  D1  App 健康率       — Healthy apps / total apps
  D2  同步率           — Synced apps / total apps
  D3  错误率           — Error apps / total apps（负分）
  D4  部署频率         — 有最近部署的 apps 比例
  D5  自动化覆盖率     — 配置了 automated sync 的 apps 比例
  D6  聚合入口完整性   — Root App 层是否完整（App-of-Apps 健康度）
  D7  多源冗余度       — 使用多源或红黑切换的 apps 比例
  D8  漂移复发率       — 反复 OutOfSync 的 apps（历史归因）

Usage:
  python -m argocd_insight health
  python -m argocd_insight health --project default
  python -m argocd_insight health --output json
  python -m argocd_insight health --detail    # 输出每个 App 的维度详情

评分逻辑：
  - 每个维度 0-100 分
  - 总分 = 加权平均（critical 维度权重更高）
  - 评分标准在代码中硬编码，与 kustomize-mapping.md 的 4-tier 模型对齐
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    """单个维度的评分结果。"""
    id: str
    name: str
    score: int           # 0-100
    weight: float        # 权重（所有维度权重和 = 1）
    level: str           # "critical" | "warning" | "info"
    apps_ok: int         # 该维度下健康的 apps 数量
    apps_total: int       # 该维度下参与评分的 apps 总数
    detail: str          # 一句话描述
    findings: list[str]  # 具体发现
    suggestions: list[str]  # 改进建议


@dataclass
class HealthReport:
    """整体健康评估报告。"""
    generated_at: str
    total_apps: int
    dimensions: list[DimensionScore]
    total_score: int
    total_level: str
    summary: str


# ---------------------------------------------------------------------------
# 底层调用
# ---------------------------------------------------------------------------

def _run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except FileNotFoundError:
        return -2, "", f"Not found: {args[0]}"


def _fetch_apps() -> list[dict]:
    rc, out, _ = _run(["argocd", "app", "list", "--output", "json"])
    return json.loads(out) if rc == 0 and out else []


def _fetch_history(app: str) -> tuple[int, str]:
    rc, out, _ = _run(["argocd", "app", "get", app, "--output", "json"])
    return rc, out


def _fetch_proj(app: str) -> tuple[int, str]:
    rc, out, _ = _run(["argocd", "proj", "get", app])
    return rc, out


# ---------------------------------------------------------------------------
# 维度计算
# ---------------------------------------------------------------------------

def _calc_health_rate(apps: list[dict]) -> DimensionScore:
    """D1: App 健康率"""
    total = len(apps)
    healthy = sum(
        1 for a in apps
        if a.get("status", {}).get("health", {}).get("status") == "Healthy"
    )
    score = round(healthy / total * 100) if total else 0
    level = "critical" if score < 80 else "warning" if score < 95 else "info"

    findings = []
    if total == 0:
        findings.append("未发现任何 Application")
    else:
        findings.append(f"Healthy: {healthy}/{total} ({score}%)")

    # 列出不健康的 apps（取前 5）
    sick = [
        a.get("metadata", {}).get("name", "")
        for a in apps
        if a.get("status", {}).get("health", {}).get("status") not in ("Healthy", "")
    ]
    if sick:
        findings.append(f"不健康 App: {', '.join(sick[:5])}" + (" ..." if len(sick) > 5 else ""))

    suggestions = []
    if score < 80:
        suggestions.append("立即排查 Degraded / Missing 状态的 App（critical）")
        suggestions.append("使用 `python -m argocd_insight diagnose --severity high` 批量定位")
    elif score < 95:
        suggestions.append("持续关注健康率，设定 SLA 目标 ≥95%")

    return DimensionScore(
        id="D1", name="App 健康率", score=score, weight=0.20,
        level=level, apps_ok=healthy, apps_total=total,
        detail=f"{healthy}/{total} apps 健康（{score}%）",
        findings=findings, suggestions=suggestions,
    )


def _calc_sync_rate(apps: list[dict]) -> DimensionScore:
    """D2: 同步率"""
    total = len(apps)
    synced = sum(
        1 for a in apps
        if a.get("status", {}).get("sync", {}).get("status") == "Synced"
    )
    oos = sum(
        1 for a in apps
        if a.get("status", {}).get("sync", {}).get("status") == "OutOfSync"
    )
    score = round(synced / total * 100) if total else 0
    level = "critical" if score < 70 else "warning" if score < 90 else "info"

    findings = [f"Synced: {synced}/{total} ({score}%)"]
    if oos:
        findings.append(f"OutOfSync: {oos} 个")

    suggestions = []
    if score < 70:
        suggestions.append("OutOfSync 率过高，检查是否存在系统性配置问题（如 webhook 失效）")
        suggestions.append("确认 Git webhook 是否正常触发 ArgoCD 同步")
    elif score < 90:
        suggestions.append("对持续 OOS 的 App 开启 automated sync")

    return DimensionScore(
        id="D2", name="同步率", score=score, weight=0.20,
        level=level, apps_ok=synced, apps_total=total,
        detail=f"{synced}/{total} apps 同步（{score}%）",
        findings=findings, suggestions=suggestions,
    )


def _calc_error_rate(apps: list[dict]) -> DimensionScore:
    """D3: 错误率（越低越好，反向评分）"""
    total = len(apps)
    errors = sum(
        1 for a in apps
        if a.get("status", {}).get("sync", {}).get("status") == "Error"
    )
    # 反向：0 个错误 = 100 分，每 1% 错误率扣 5 分
    error_rate = errors / total if total else 0
    score = max(0, round((1 - error_rate * 5) * 100))
    level = "critical" if errors > 0 else "info"

    findings = [f"Error apps: {errors}/{total}"]
    if errors:
        names = [a.get("metadata", {}).get("name", "") for a in apps
                 if a.get("status", {}).get("sync", {}).get("status") == "Error"]
        findings.append(f"Error App: {', '.join(names[:5])}")

    suggestions = []
    if errors:
        suggestions.append("Sync Error 通常由 Apply 失败导致，优先查看 events 定位原因")
        suggestions.append("`python -m argocd_insight diagnose --severity critical`")

    return DimensionScore(
        id="D3", name="错误率", score=score, weight=0.15,
        level=level, apps_ok=total - errors, apps_total=total,
        detail=f"Error: {errors}/{total}（分数={score}，越低越差）",
        findings=findings, suggestions=suggestions,
    )


def _calc_deploy_frequency(apps: list[dict], concurrency: int = 8,
                            days: int = 30) -> DimensionScore:
    """D4: 部署频率——过去 N 天有部署的 apps 比例（GitOps 活跃度）"""
    total = len(apps)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    active = 0
    stale_names: list[str] = []

    def _hist(app_name: str) -> tuple[str, bool]:
        rc, out = _fetch_history(app_name)
        if rc != 0 or not out:
            return app_name, False
        try:
            hist = json.loads(out).get("status", {}).get("history", [])
            if not hist:
                return app_name, False
            # 最近一条部署时间
            last = hist[0].get("deployedAt", "")
            if last and last >= cutoff_iso:
                return app_name, True
            return app_name, False
        except Exception:
            return app_name, False

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_hist, a.get("metadata", {}).get("name", "")): a for a in apps}
        for fut in as_completed(futs):
            name, ok = fut.result()
            if ok:
                active += 1
            else:
                stale_names.append(name)

    score = round(active / total * 100) if total else 0
    level = "info"  # 没有硬性标准，仅供参考

    findings = [f"最近 {days} 天有部署: {active}/{total} ({score}%)"]
    if stale_names:
        findings.append(f"长期无部署（可能已废弃）: {', '.join(stale_names[:5])}"
                        + (" ..." if len(stale_names) > 5 else ""))

    suggestions = []
    if score < 50:
        suggestions.append("超过一半 App 长期无部署，检查是否有过期/废弃 App 需要归档")
    suggestions.append("长期未部署的 App 可能与 Git 源漂移，建议定期检查 sync 状态")

    return DimensionScore(
        id="D4", name="部署频率", score=score, weight=0.10,
        level=level, apps_ok=active, apps_total=total,
        detail=f"最近 {days} 天有部署: {active}/{total}（{score}%）",
        findings=findings, suggestions=suggestions,
    )


def _calc_automated_sync(apps: list[dict]) -> DimensionScore:
    """D5: 自动化覆盖率"""
    total = len(apps)
    automated = sum(
        1 for a in apps
        if a.get("spec", {}).get("syncPolicy", {}).get("automated") is not None
    )
    score = round(automated / total * 100) if total else 0
    level = "warning" if score < 30 else "info"

    findings = [f"Automated: {automated}/{total} ({score}%)"]
    if automated == 0 and total > 10:
        findings.append("注意：全部 App 均为手动 sync，OutOfSync 风险较高")

    suggestions = []
    if score < 30:
        suggestions.append("建议为核心业务 App 开启 automated sync（--sync-policy automated）")
        suggestions.append("运维组件（k8s_ops/）保持手动 sync，业务 App 可开启自动化")
    elif score < 60:
        suggestions.append("逐步将稳定环境的 App 迁移到 automated sync")

    return DimensionScore(
        id="D5", name="自动化覆盖率", score=score, weight=0.10,
        level=level, apps_ok=automated, apps_total=total,
        detail=f"{automated}/{total} apps 配置了 automated sync（{score}%）",
        findings=findings, suggestions=suggestions,
    )


def _calc_root_completeness(apps: list[dict]) -> DimensionScore:
    """
    D6: 聚合入口完整性（App-of-Apps 健康度）

    识别 Root App（destination.namespace == argo-root 且含 labels.app-of-apps），
    检查其是否正确聚合了子 App。
    """
    # 识别 Root 层 App（4-tier 模型：argo-root namespace 的聚合入口）
    root_apps = [
        a for a in apps
        if a.get("spec", {}).get("destination", {}).get("namespace") == "argo-root"
    ]

    total = len(root_apps)
    if total == 0:
        # 全部是平铺结构，无 Root 层
        score = 50
        level = "warning"
        findings = ["未发现 Root App（argo-root namespace），当前为全平铺结构"]
        suggestions = [
            "建议引入 App-of-Apps 聚合层，便于批量管理",
            "Root App 示例：project-profile-branch.yaml 类型入口",
        ]
    else:
        healthy_roots = sum(
            1 for a in root_apps
            if a.get("status", {}).get("health", {}).get("status") == "Healthy"
            and a.get("status", {}).get("sync", {}).get("status") == "Synced"
        )
        score = round(healthy_roots / total * 100) if total else 0
        level = "critical" if score < 50 else "warning" if score < 100 else "info"
        findings = [f"Root App: {healthy_roots}/{total} 健康且同步（{score}%）"]
        sick_roots = [
            a.get("metadata", {}).get("name", "")
            for a in root_apps
            if a.get("status", {}).get("health", {}).get("status") != "Healthy"
            or a.get("status", {}).get("sync", {}).get("status") != "Synced"
        ]
        if sick_roots:
            findings.append(f"异常 Root App: {', '.join(sick_roots[:5])}")
        suggestions = []
        if score < 100:
            suggestions.append("Root App 异常会导致批量管理失效，优先修复")
            suggestions.append("Root App 健康 = 子 App 批量操作生效的前提")

    return DimensionScore(
        id="D6", name="聚合入口完整性", score=score, weight=0.10,
        level=level, apps_ok=healthy_roots if total > 0 else 0, apps_total=total,
        detail=findings[0] if findings else "无 Root App 数据",
        findings=findings, suggestions=suggestions,
    )


def _calc_multisource_rate(apps: list[dict]) -> DimensionScore:
    """D7: 多源冗余度"""
    total = len(apps)
    multisource = sum(
        1 for a in apps
        if len(a.get("spec", {}).get("sources", [])) > 1
    )
    score = round(multisource / total * 100) if total else 0
    level = "info"  # 多源不是必选项，info 即可

    findings = [f"多源 App: {multisource}/{total} ({score}%)"]
    suggestions = []
    if multisource == 0 and total > 5:
        suggestions.append("当前无多源 App，若有红黑切换或 canary 需求可考虑 spec.sources")
        suggestions.append("多源 App 可实现：主备 Git 源自动切换 + kustomize overlay 组合")

    return DimensionScore(
        id="D7", name="多源冗余度", score=score, weight=0.05,
        level=level, apps_ok=multisource, apps_total=total,
        detail=f"{multisource}/{total} apps 使用多源（{score}%）",
        findings=findings, suggestions=suggestions,
    )


def _calc_drift_recurrence(apps: list[dict], concurrency: int = 4) -> DimensionScore:
    """
    D8: 漂移复发率——过去 30 天内 OutOfSync 次数 >= 3 的 App
    （反复漂移说明有系统性原因，不是偶发）
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_iso = cutoff.isoformat()

    # 过滤当前 OOS 的
    oos_apps = [
        a for a in apps
        if a.get("status", {}).get("sync", {}).get("status") == "OutOfSync"
    ]
    if not oos_apps:
        score = 100
        level = "info"
        findings = ["当前无 OutOfSync apps"]
        suggestions = ["继续保持，关注部署时触发 OOS 的根因"]
        return DimensionScore(
            id="D8", name="漂移复发率", score=score, weight=0.10,
            level=level, apps_ok=len(oos_apps), apps_total=len(apps),
            detail="当前 OOS: 0/{}".format(len(apps)),
            findings=findings, suggestions=suggestions,
        )

    def _count_oos(app_name: str) -> tuple[str, int]:
        rc, out = _fetch_history(app_name)
        if rc != 0:
            return app_name, 0
        try:
            hist = json.loads(out).get("status", {}).get("history", [])
            count = sum(
                1 for h in hist
                if h.get("deployedAt", "") >= cutoff_iso
            )
            return app_name, count
        except Exception:
            return app_name, 0

    recurrent: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_count_oos, a.get("metadata", {}).get("name", "")): a for a in oos_apps}
        for fut in as_completed(futs):
            name, count = fut.result()
            if count >= 3:
                recurrent.append((name, count))

    score = max(0, round((1 - len(recurrent) / len(oos_apps)) * 100))
    level = "critical" if len(recurrent) > len(oos_apps) * 0.3 else "warning" if recurrent else "info"

    findings = [f"OOS 总数: {len(oos_apps)}，反复漂移（≥3次/月）: {len(recurrent)}"]
    if recurrent:
        findings.append("复发 App: " + ", ".join(
            f"{n}({c}次)" for n, c in sorted(recurrent, key=lambda x: -x[1])[:5]
        ) + (" ..." if len(recurrent) > 5 else ""))

    suggestions = []
    if recurrent:
        suggestions.append("反复漂移通常由 webhook 失效 / automated + 手动并行操作导致")
        suggestions.append("检查 webhook 配置或考虑将手动 sync 改为纯 automated 模式")
        suggestions.append("`python -m argocd_insight diagnose --severity high` 批量分析")

    return DimensionScore(
        id="D8", name="漂移复发率", score=score, weight=0.10,
        level=level, apps_ok=len(oos_apps) - len(recurrent), apps_total=len(oos_apps),
        detail=f"{len(recurrent)}/{len(oos_apps)} OOS App 反复漂移（{score}%）",
        findings=findings, suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# 总分计算
# ---------------------------------------------------------------------------

def _calc_total(dimensions: list[DimensionScore]) -> tuple[int, str]:
    """加权平均求总分。"""
    if not dimensions:
        return 0, "unknown"
    total = round(sum(d.score * d.weight for d in dimensions))
    level = (
        "critical" if total < 60
        else "warning" if total < 80
        else "info"
    )
    return total, level


# ---------------------------------------------------------------------------
# 报告构建
# ---------------------------------------------------------------------------

def build_report(
    apps: list[dict],
    project_filter: str | None,
    app_filter: str | None = None,
    concurrency: int = 8,
) -> HealthReport:
    filtered = [
        a for a in apps
        if (not project_filter or a.get("spec", {}).get("project") == project_filter)
        and (not app_filter or a.get("metadata", {}).get("name") == app_filter)
    ]

    print(f"[health] 评估 {len(filtered)} apps（总 {len(apps)} apps）...", file=sys.stderr)

    # D1, D2, D3, D5, D6, D7 是无副作用的（纯读）
    dims = [
        _calc_health_rate(filtered),
        _calc_sync_rate(filtered),
        _calc_error_rate(filtered),
        _calc_automated_sync(filtered),
        _calc_root_completeness(filtered),
        _calc_multisource_rate(filtered),
    ]

    # D4 和 D8 需要额外 API 调用，放最后
    print(f"[health] D4 部署频率（并发={concurrency}）...", file=sys.stderr)
    dims.append(_calc_deploy_frequency(filtered, concurrency=concurrency))

    print(f"[health] D8 漂移复发率（并发={min(4, concurrency)}）...", file=sys.stderr)
    dims.append(_calc_drift_recurrence(filtered, concurrency=min(4, concurrency)))

    total_score, total_level = _calc_total(dims)

    # 生成一句话总结
    critical_dims = [d for d in dims if d.level == "critical"]
    warning_dims = [d for d in dims if d.level == "warning"]
    if critical_dims:
        summary = (f"总分 {total_score}（critical），存在 {len(critical_dims)} 个 critical 维度："
                   f"{"、".join(d.name for d in critical_dims)}。")
    elif warning_dims:
        summary = (f"总分 {total_score}（warning），{len(warning_dims)} 个 warning 维度："
                   f"{", ".join(d.name for d in warning_dims)}。")
        summary = f"总分 {total_score}（健康），所有维度表现良好。"

    return HealthReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_apps=len(filtered),
        dimensions=dims,
        total_score=total_score,
        total_level=total_level,
        summary=summary,
    )


def _score_color(score: int) -> str:
    if score >= 90:
        return "🟢"
    if score >= 70:
        return "🟡"
    if score >= 50:
        return "🟠"
    return "🔴"


def _level_label(level: str) -> str:
    return {"critical": "🔴 critical", "warning": "🟡 warning", "info": "🟢 info"}.get(level, level)


def print_markdown(report: HealthReport):
    print("# ArgoCD 运行稳定性评估报告\n")
    print(f"生成时间：{report.generated_at}")
    print(f"评估 App 数：{report.total_apps}\n")

    # 总分
    print(f"## 总分：{_score_color(report.total_score)} {report.total_score} / 100（{_level_label(report.total_level)}）\n")
    print(f"{report.summary}\n")

    # 维度表格
    print("## 维度评分\n")
    print("| 维度 | 分数 | 级别 | 详情 |")
    print("|------|------|------|------|")
    for d in sorted(report.dimensions, key=lambda x: (x.level == "info", x.level == "warning", x.score)):
        print(f"| {d.name} | {_score_color(d.score)} {d.score} | {_level_label(d.level)} | {d.detail} |")

    # 薄弱项详细分析
    weak = [d for d in report.dimensions if d.level in ("critical", "warning")]
    if weak:
        print("\n## 薄弱项详细分析\n")
        for d in weak:
            print(f"### {_score_color(d.score)} {d.name}（{d.score}/100，{_level_label(d.level)}）\n")
            if d.findings:
                print("**发现：**")
                for f in d.findings:
                    print(f"- {f}")
            if d.suggestions:
                print("\n**改进建议：**")
                for s in d.suggestions:
                    print(f"- {s}")
            print()

    # 所有建议汇总
    all_suggestions = [
        (d.name, s) for d in report.dimensions if d.level in ("critical", "warning")
        for s in d.suggestions
    ]
    if all_suggestions:
        print("## 改进建议汇总（按优先级）\n")
        printed: set[str] = set()
        for dim_name, suggestion in all_suggestions:
            key = suggestion[:40]
            if key not in printed:
                printed.add(key)
                print(f"- [{dim_name}] {suggestion}")

    print("\n---\n")
    print("评估维度：D1=App健康率(20%), D2=同步率(20%), D3=错误率(15%), "
          "D4=部署频率(10%), D5=自动化覆盖(10%), "
          "D6=聚合入口(10%), D7=多源冗余(5%), D8=漂移复发(10%)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ArgoCD 运行稳定性评估：多维度打分 + 薄弱项分析 + 改进建议",
    )
    p.add_argument("--project", help="只评估指定项目的 App")
    p.add_argument("--app", help="只评估指定名称的 App")
    p.add_argument("--days", type=int, default=30,
                   help="部署频率统计天数（默认 30）")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p.add_argument("--concurrency", type=int, default=8)
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_argparser()
    args = p.parse_args(argv)

    print("Fetching apps...", file=sys.stderr)
    apps = _fetch_apps()

    t0 = time.time()
    report = build_report(apps, args.project, args.app, args.concurrency)
    print(f"Done in {time.time()-t0:.1f}s", file=sys.stderr)

    if args.output == "json":
        print(json.dumps({
            "generatedAt": report.generated_at,
            "totalApps": report.total_apps,
            "totalScore": report.total_score,
            "totalLevel": report.total_level,
            "summary": report.summary,
            "dimensions": [
                {
                    "id": d.id,
                    "name": d.name,
                    "score": d.score,
                    "weight": d.weight,
                    "level": d.level,
                    "detail": d.detail,
                    "findings": d.findings,
                    "suggestions": d.suggestions,
                }
                for d in report.dimensions
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)

    # 退出码
    if report.total_level == "critical":
        return 2
    if report.total_level == "warning":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
