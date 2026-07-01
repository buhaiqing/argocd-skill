#!/usr/bin/env python3
"""
diagnose — ArgoCD 问题 App 智能诊断工具

一次性拉取全量 App，过滤出有问题的（OutOfSync / Health≠Healthy / Sync Error），
对每个问题 App 做多维度诊断（资源层 / diff 层 / 历史层 / 事件层），
输出根因 + 严重级别 + 具体 action。

Usage:
  python -m argocd_insight diagnose                    # 全量巡检
  python -m argocd_insight diagnose --project default  # 指定项目
  python -m argocd_insight diagnose --severity high    # 只看高危
  python -m argocd_insight diagnose --output json       # 结构化输出（供 LLM 使用）

脱敏原则：
  - 所有 action 都是读操作（GET），不执行写操作
  - revision / repo URL 仅显示最后路径段或前 8 位哈希
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Diagnosis:
    """单个 App 的诊断结果。"""
    app: str
    project: str
    namespace: str

    # 问题快照
    health_status: str
    sync_status: str
    revision: str               # 显示用 short
    revision_raw: str           # 原始值（仅内存，不输出）
    repo: str                   # 最后路径段

    # 诊断结论
    severity: str               # critical / high / medium / low / info
    root_cause: str             # 一句话描述根因
    category: str               # 归因大类
    symptoms: list[str]         # 观察到的具体症状

    # 行动建议
    actions: list["Action"]     # 有序 action 列表（优先级从高到低）
    risk_note: str = ""         # 风险提示（如 prune 风险）


@dataclass
class Action:
    """一条可执行的操作建议。"""
    priority: int               # 1 最高
    command: str               # 建议执行的命令（显示用）
    intent: str                # 意图描述
    risk: str = "low"          # low / medium / high / destructive
    dry_run_suffix: str = ""     # 若有 dry-run 版本命令


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


def _fetch_resources(app: str) -> tuple[int, str, str]:
    return _run(["argocd", "app", "resources", app])


def _fetch_diff(app: str) -> tuple[int, str, str]:
    return _run(["argocd", "app", "diff", app])


def _fetch_events(app: str) -> tuple[int, str, str]:
    return _run(["argocd", "app", "events", app, "--output", "json"])


def _fetch_history(app: str) -> tuple[int, str, str]:
    return _run(["argocd", "app", "get", app, "--output", "json"])


# ---------------------------------------------------------------------------
# 诊断规则（启发式，无外部依赖）
# ---------------------------------------------------------------------------

def _parse_resources(res_out: str) -> tuple[list[str], list[str]]:
    """
    解析 `argocd app resources` 输出。
    Returns: (orphaned_kinds, unhealthy_kinds)
    """
    orphaned = []
    unhealthy = []
    for line in res_out.strip().splitlines():
        if not line or line.startswith("GROUP") or line.startswith("NAMESPACE"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        # ArgoCD resources 输出格式：
        # GROUP  KIND  NAMESPACE  NAME  STATUS  HEALTH  ...
        kind = parts[1] if len(parts) > 1 else "?"
        name = parts[3] if len(parts) > 3 else parts[0]
        health = parts[4] if len(parts) > 4 else ""
        status = parts[5] if len(parts) > 5 else ""

        if status == "Orphaned" or "\tOrphaned" in line or "Orphaned" in status:
            orphaned.append(f"{kind}/{name}")
        elif health and health not in ("Healthy", ""):
            unhealthy.append(f"{kind}/{name}({health})")
    return orphaned, unhealthy


def _parse_diff(diff_out: str) -> dict[str, bool]:
    """解析 diff 输出，检测增减。"""
    has_add = has_del = False
    for line in diff_out.splitlines():
        ls = line.strip()
        if ls.startswith("> ") or (ls.startswith("+") and not ls.startswith("+++")):
            has_add = True
        elif ls.startswith("< ") or (ls.startswith("-") and not ls.startswith("---")):
            has_del = True
    return {"additions": has_add, "deletions": has_del}


def _parse_events(events_out: str) -> list[str]:
    """从 events JSON 中提取关键事件消息。"""
    try:
        events = json.loads(events_out) if events_out else []
    except Exception:
        events = []
    msgs = []
    for ev in events[-10:]:   # 只看最近 10 条
        msg = ev.get("message", "")
        invol = ev.get("involvedObject", {}).get("name", "")
        if msg:
            msgs.append(f"{invol}: {msg}" if invol else msg)
    return msgs


def _parse_history(history_out: str) -> tuple[Optional[str], list[dict]]:
    """从 app get JSON 中提取 revision 和 history 记录。"""
    try:
        d = json.loads(history_out) if history_out else {}
    except Exception:
        return None, []
    rev = d.get("status", {}).get("sync", {}).get("revision", "")
    hist = d.get("status", {}).get("history", [])
    return rev, hist


def _detect_image_error(events: list[str]) -> Optional[str]:
    """检测镜像相关错误。"""
    keywords = [
        ("ErrImagePull", "镜像拉取失败"),
        ("ImagePullBackOff", "镜像拉取重试退避"),
        ("InvalidImageName", "镜像名称无效"),
        ("ErrRegistryUnknown", "镜像仓库未知"),
        ("BackOff", "容器启动失败退避"),
    ]
    for kw, label in keywords:
        for ev in events:
            if kw.lower() in ev.lower():
                return label
    return None


# ---------------------------------------------------------------------------
# 核心诊断逻辑
# ---------------------------------------------------------------------------

@dataclass
class RawData:
    resources_out: str = ""
    diff_out: str = ""
    events_out: str = ""
    history_out: str = ""
    diff_rc: int = 0


def diagnose_app(app_name: str, app_spec: dict) -> Optional[Diagnosis]:
    """
    对单个 App 做完整诊断。
    Returns None if app is healthy (no problems).
    """
    spec = app_spec.get("spec", {})
    status = app_spec.get("status", {})
    sync_status = status.get("sync", {}).get("status", "Unknown")
    health_status = status.get("health", {}).get("status", "Unknown")
    rev_raw = status.get("sync", {}).get("revision", "")
    rev_short = rev_raw[:8] if rev_raw else "(none)"

    # 提取 repo（兼容单源/多源）
    sources = spec.get("sources", [])
    if sources:
        repo_url = sources[0].get("repoURL", "")
    else:
        repo_url = spec.get("source", {}).get("repoURL", "")
    repo_short = repo_url.rsplit("/", 1)[-1] if repo_url else ""

    # 判断是否需要诊断
    needs_diagnosis = (
        sync_status in ("OutOfSync", "Error", "Unknown")
        or health_status not in ("Healthy", "Unknown", "")
    )
    if not needs_diagnosis:
        return None

    # 并发拉取四层数据
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_res = ex.submit(_fetch_resources, app_name)
        f_diff = ex.submit(_fetch_diff, app_name)
        f_evts = ex.submit(_fetch_events, app_name)
        f_hist = ex.submit(_fetch_history, app_name)

        res_rc, res_out = f_res.result()[0], f_res.result()[1]
        diff_rc, diff_out = f_diff.result()[0], f_diff.result()[1]
        evts_rc, evts_out = f_evts.result()[0], f_evts.result()[1]
        hist_rc, hist_out = f_hist.result()[0], f_hist.result()[1]

    orphaned, unhealthy = _parse_resources(res_out)
    diff_info = _parse_diff(diff_out)
    events = _parse_events(evts_out)
    _, history = _parse_history(hist_out)
    image_err = _detect_image_error(events)

    # -------------------- 规则引擎 --------------------
    diagnoses: list[Diagnosis] = []

    # === OutOfSync 诊断 ===
    if sync_status == "OutOfSync":
        if orphaned:
            # 场景：集群有资源，Git 没有（手动创建或从其他途径导入）
            cause = "孤儿资源：集群存在但 Git 清单中已删除的资源"
            severity = "high"
            if len(orphaned) <= 3:
                risk = "medium"
                action_note = "建议先确认这些资源是否仍在使用，避免误删"
            else:
                risk = "high"
                action_note = f"孤儿资源 {len(orphaned)} 个，批量清理风险较高，建议逐个确认"
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app resources {app_name} | grep Orphaned",
                    intent="确认孤儿资源列表及影响范围",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app sync {app_name} --prune --dry-run",
                    intent="预演：sync 会删除不在 Git 中的资源（包含孤儿）",
                    risk=risk,
                ),
                Action(
                    priority=3,
                    command=f"argocd app sync {app_name} --prune",
                    intent="执行 sync 清理孤儿资源",
                    risk="destructive",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="孤儿资源（Orphaned）",
                symptoms=[f"孤儿资源: {', '.join(orphaned[:5])}"],
                actions=actions,
                risk_note=action_note,
            ))

        elif diff_info["additions"] and not diff_info["deletions"]:
            # 场景：Git 有新增，尚未同步到集群
            cause = "Git 新提交/配置变更，尚未部署到集群"
            severity = "medium"
            automated = spec.get("syncPolicy", {}).get("automated")
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app diff {app_name}",
                    intent="查看具体差异内容",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app history {app_name}",
                    intent="查看历史部署记录",
                    risk="low",
                ),
                Action(
                    priority=3,
                    command=f"argocd app sync {app_name}",
                    intent="手动触发同步（推荐）",
                    risk="medium",
                ),
            ]
            if automated:
                actions.insert(2, Action(
                    priority=2,
                    command="# ArgoCD Automated 已配置，等待下一个 sync 周期即可自动同步",
                    intent="当前 App 配置了自动 sync，无需手动干预",
                    risk="low",
                ))
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="Git 新增未同步",
                symptoms=["Git 有新内容，集群尚未应用"],
                actions=actions,
                risk_note="若 diff 内容不符合预期，建议先 `argocd app diff` 确认",
            ))

        elif diff_info["deletions"] and not diff_info["additions"]:
            # 场景：Git 删除了资源，集群中还有
            cause = "Git 已删除资源，集群仍在运行（手动漂移风险）"
            severity = "high"
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app diff {app_name}",
                    intent="查看被删除的具体资源",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app resources {app_name}",
                    intent="确认集群中仍在运行哪些资源",
                    risk="low",
                ),
                Action(
                    priority=3,
                    command=f"argocd app sync {app_name}",
                    intent="同步以清理 Git 中已删除的资源",
                    risk="medium",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="Git 资源删除未同步",
                symptoms=["Git 删除了一些资源，集群仍有残留"],
                actions=actions,
                risk_note="若这些资源仍有业务流量在用，先备份再 sync",
            ))

        elif diff_info["additions"] and diff_info["deletions"]:
            # 场景：既有新增也有删除
            cause = "Git 与集群双向变更，内容漂移"
            severity = "high"
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app diff {app_name} | head -50",
                    intent="查看具体变更内容",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app history {app_name}",
                    intent="确认哪个 revision 是预期状态",
                    risk="low",
                ),
                Action(
                    priority=3,
                    command=f"argocd app sync {app_name}",
                    intent="强制同步到 Git 指定版本",
                    risk="medium",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="双向内容漂移",
                symptoms=["Git 与集群双向变更，具体 diff 需查看"],
                actions=actions,
                risk_note="建议 sync 前确认 diff 内容是否符合预期",
            ))

        elif diff_rc == 1:
            # diff 返回 1 但没有检测到明显的加减（可能格式变化或空白差异）
            cause = "OutOfSync 但 diff 无法明确归因"
            severity = "medium"
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app diff {app_name} | head -30",
                    intent="人工查看 diff 内容",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app history {app_name}",
                    intent="确认当前 revision 和历史 revision",
                    risk="low",
                ),
                Action(
                    priority=3,
                    command=f"argocd app sync {app_name}",
                    intent="同步到 Git 最新状态",
                    risk="medium",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="OutOfSync（未明）",
                symptoms=["OutOfSync 但 diff 归因不明确"],
                actions=actions,
            ))

    # === Health 问题诊断 ===
    if health_status not in ("Healthy", "Unknown", ""):
        if health_status == "Missing":
            cause = "目标命名空间不存在或 RBAC 无权限"
            severity = "critical"
            actions = [
                Action(
                    priority=1,
                    command=f"kubectl get ns {spec.get('destination', {}).get('namespace', '')}",
                    intent="确认 namespace 是否存在",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app resources {app_name}",
                    intent="查看 ArgoCD 对目标命名空间的可见性",
                    risk="low",
                ),
                Action(
                    priority=3,
                    command=f"argocd proj get {spec.get('project', '')}",
                    intent="检查 Project 是否允许该 namespace",
                    risk="low",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="Health: Missing",
                symptoms=["App 报告 Missing：目标 namespace 不存在或无访问权限"],
                actions=actions,
                risk_note="若 namespace 被误删，`argocd app sync` 不会自动创建（需 App 配置 CreateNamespace=true）",
            ))

        elif health_status == "Degraded":
            # 进一步结合 events 和 resources 细化
            cause = "应用组件不健康"
            severity = "high"

            symptoms = []
            if unhealthy:
                symptoms.append(f"不健康资源: {', '.join(unhealthy[:5])}")
            if image_err:
                symptoms.append(f"镜像错误: {image_err}")
            if events:
                symptoms.append(f"最近事件: {events[-1][:80]}")

            actions = [
                Action(
                    priority=1,
                    command=f"argocd app events {app_name} --output json | jq '.[-5:]'",
                    intent="查看最近事件，定位具体报错",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app resources {app_name}",
                    intent="查看各资源健康状态",
                    risk="low",
                ),
            ]
            if image_err:
                actions.append(Action(
                    priority=3,
                    command=f"argocd app sync {app_name} --force",
                    intent=f"强制 sync（尝试拉取新镜像 {image_err}）",
                    risk="medium",
                ))
            actions.append(Action(
                priority=4,
                command=f"argocd app diff {app_name}",
                intent="若配置有变更，先 diff 确认",
                risk="low",
            ))
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category="Health: Degraded",
                symptoms=symptoms or ["应用组件处于 Degraded 状态"],
                actions=actions,
            ))

        else:
            # 其他 health 状态
            cause = f"应用健康状态异常：{health_status}"
            severity = "medium"
            actions = [
                Action(
                    priority=1,
                    command=f"argocd app events {app_name} --output json | jq '.[-5:]'",
                    intent="查看最近事件",
                    risk="low",
                ),
                Action(
                    priority=2,
                    command=f"argocd app resources {app_name}",
                    intent="查看资源健康详情",
                    risk="low",
                ),
            ]
            diagnoses.append(Diagnosis(
                app=app_name,
                project=spec.get("project", ""),
                namespace=spec.get("destination", {}).get("namespace", ""),
                health_status=health_status,
                sync_status=sync_status,
                revision=rev_short,
                revision_raw=rev_raw,
                repo=repo_short,
                severity=severity,
                root_cause=cause,
                category=f"Health: {health_status}",
                symptoms=[f"健康状态: {health_status}"],
                actions=actions,
            ))

    # === Sync Error 诊断 ===
    if sync_status == "Error":
        cause = "Sync 执行出错"
        severity = "critical"
        # 从 events 提取错误消息
        error_msgs = [e for e in events if "error" in e.lower() or "fail" in e.lower()]
        symptoms = error_msgs[:3] if error_msgs else ["Sync Error 状态"]
        actions = [
            Action(
                priority=1,
                command=f"argocd app events {app_name} --output json | jq '[.[] | select(.type==\"Warning\")]'",
                intent="查看 Warning 类型事件，找到报错原因",
                risk="low",
            ),
            Action(
                priority=2,
                command=f"argocd app history {app_name}",
                intent="查看哪个 revision 触发了 Error",
                risk="low",
            ),
            Action(
                priority=3,
                command=f"argocd app sync {app_name} --force",
                intent="尝试强制 sync",
                risk="medium",
            ),
        ]
        diagnoses.append(Diagnosis(
            app=app_name,
            project=spec.get("project", ""),
            namespace=spec.get("destination", {}).get("namespace", ""),
            health_status=health_status,
            sync_status=sync_status,
            revision=rev_short,
            revision_raw=rev_raw,
            repo=repo_short,
            severity=severity,
            root_cause=cause,
            category="Sync Error",
            symptoms=symptoms,
            actions=actions,
            risk_note="Sync Error 通常表示 Apply 失败，先查看 events 定位原因再 sync",
        ))

    # 合并同类诊断，取最严重
    if not diagnoses:
        return None

    primary = max(diagnoses, key=lambda d: _severity_order(d.severity))
    return primary


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _severity_order(s: str) -> int:
    return SEVERITY_ORDER.get(s, 99)


# ---------------------------------------------------------------------------
# 报告构建
# ---------------------------------------------------------------------------

def build_report(
    apps: list[dict],
    project_filter: str | None,
    min_severity: str | None,
    concurrency: int = 8,
) -> dict:
    """对所有 App 执行诊断，生成报告。"""

    # 过滤有问题且符合 project 条件的 App
    target_apps = [
        a for a in apps
        if (not project_filter or a.get("spec", {}).get("project") == project_filter)
        and (
            a.get("status", {}).get("sync", {}).get("status") in ("OutOfSync", "Error")
            or a.get("status", {}).get("health", {}).get("status") not in ("Healthy", "Unknown", "")
        )
    ]

    print(f"[diagnose] 发现 {len(target_apps)} 个问题 App，开始诊断...", file=sys.stderr)

    results: dict[str, dict] = {}
    min_order = _severity_order(min_severity) if min_severity else 99

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {
            ex.submit(diagnose_app, a.get("metadata", {}).get("name", ""), a): a
            for a in target_apps
        }
        done = 0
        for fut in as_completed(futs):
            diag = fut.result()
            if diag and _severity_order(diag.severity) <= min_order:
                # 脱敏：移除 revision_raw
                d = asdict(diag)
                d.pop("revision_raw", None)
                results[diag.app] = d
            done += 1
            if done % 20 == 0:
                print(f"[diagnose] {done}/{len(target_apps)} done", file=sys.stderr)

    # 按严重级别排序
    sorted_results = dict(
        sorted(results.items(), key=lambda x: (_severity_order(x[1]["severity"]), x[0]))
    )

    # 统计
    by_sev = {k: 0 for k in SEVERITY_ORDER if k != "info"}
    by_cat: dict[str, int] = {}
    for d in sorted_results.values():
        by_sev[d["severity"]] = by_sev.get(d["severity"], 0) + 1
        by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalApps": len(apps),
        "problemApps": len(target_apps),
        "diagnosed": len(sorted_results),
        "bySeverity": by_sev,
        "byCategory": by_cat,
        "diagnoses": sorted_results,
    }


def _action_md(a):
    risk = a.get("risk") if isinstance(a, dict) else a.risk
    command = a.get("command") if isinstance(a, dict) else a.command
    intent = a.get("intent") if isinstance(a, dict) else a.intent
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴", "destructive": "🛑"}.get(risk, "⚪")
    return f"{risk_icon} `{command}` — {intent}"



def print_markdown(report: dict):
    print("# ArgoCD 问题 App 智能诊断报告\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"总 App 数：{report['totalApps']}，问题 App：{report['problemApps']}，已诊断：{report['diagnosed']}\n")

    # 严重级别概览
    by_sev = report.get("bySeverity", {})
    print("## 问题概览\n")
    print("| 严重级别 | 数量 |")
    print("|----------|------|")
    for sev in ("critical", "high", "medium", "low"):
        count = by_sev.get(sev, 0)
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
        if count:
            print(f"| {icon} {sev} | {count} |")

    # 归因分布
    by_cat = report.get("byCategory", {})
    if by_cat:
        print("\n## 归因分布\n")
        print("| 类型 | 数量 |")
        print("|------|------|")
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"| {cat} | {count} |")

    # 逐 App 详情
    diagnoses = report.get("diagnoses", {})
    if diagnoses:
        print("\n## 诊断详情\n")
        for name, d in diagnoses.items():
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(d["severity"], "⚪")
            print(f"### {sev_icon} `{name}`\n")
            print(f"- **项目**: {d['project']}")
            print(f"- **命名空间**: {d['namespace']}")
            print(f"- **严重级别**: {sev_icon} {d['severity']}")
            print(f"- **健康**: {d['health_status']}  |  **同步**: {d['sync_status']}  |  **Revision**: `{d['revision']}`")
            print(f"- **根因**: {d['root_cause']}")
            print(f"- **类型**: {d['category']}")
            if d.get("symptoms"):
                print(f"- **症状**: {'; '.join(d['symptoms'])}")
            if d.get("risk_note"):
                print(f"⚠️ {d['risk_note']}")
            print(f"\n**建议操作**（按优先级）:")
            for a in d["actions"]:
                print(f"  {_action_md(a)}")
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ArgoCD 问题 App 智能诊断：识别有问题的 App 并给出根因分析和修复建议",
    )
    p.add_argument("--project", help="只诊断指定项目的 App")
    p.add_argument("--severity", choices=["critical", "high", "medium", "low"],
                   help="只显示该严重级别及以上的 App")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p.add_argument("--concurrency", type=int, default=8)
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_argparser()
    args = p.parse_args(argv)

    print("Fetching all apps...", file=sys.stderr)
    apps = _fetch_apps()
    print(f"Got {len(apps)} apps", file=sys.stderr)

    t0 = time.time()
    report = build_report(apps, args.project, args.severity, args.concurrency)
    print(f"Diagnosed {report['diagnosed']}/{report['problemApps']} apps "
          f"in {time.time()-t0:.1f}s", file=sys.stderr)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)

    # 有 critical/high 问题 → 退出码 2
    by_sev = report.get("bySeverity", {})
    if by_sev.get("critical") or by_sev.get("high"):
        return 2
    if by_sev.get("medium"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
