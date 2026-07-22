"""Rollout 状态诊断。

读取单个 Rollout 的 JSON 状态（来自 `kubectl get rollout -o json`），
识别 paused / aborted / Progressing 卡点，输出根因 + 严重级别 + action 列表。

脱敏原则：
  - 所有 action 都是读操作（GET），不执行写操作。
  - revision / 镜像 tag 仅显示短哈希或最后路径段；不回显任何 token。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Action:
    """一条可执行的建议动作（读操作优先）。"""

    description: str
    command: str  # 预填的 kubectl / kubectl argo rollouts 命令（只读）
    priority: int  # 越小越优先


@dataclass
class RolloutDiagnosis:
    name: str
    namespace: str
    strategy: str  # canary / bluegreen / basic

    # 状态快照
    status: str  # Healthy / Progressing / Degraded / Paused / Aborted
    paused: bool
    aborted: bool
    message: str  # 来自 status.message / message 字段

    # 诊断结论
    severity: str  # critical / high / medium / low / info
    root_cause: str
    category: str  # 归因大类
    symptoms: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [asdict(a) for a in self.actions]
        return d


def _short(ref: str) -> str:
    """把 revision / 镜像引用缩短为可展示的片段。"""
    if not ref:
        return ""
    ref = ref.strip()
    if len(ref) > 12 and any(c in ref for c in "/:"):
        # 取最后路径段或 tag
        return ref.rsplit("/", 1)[-1]
    return ref


def diagnose_status(rollout: dict[str, Any]) -> RolloutDiagnosis:
    """从单个 Rollout 的 JSON dict 推断诊断结论。"""
    meta = rollout.get("metadata", {})
    name = meta.get("name", "unknown")
    namespace = meta.get("namespace", "default")
    spec = rollout.get("spec", {})
    status = rollout.get("status", {})

    strategy = "basic"
    if "canary" in spec:
        strategy = "canary"
    elif "blueGreen" in spec:
        strategy = "bluegreen"

    paused = bool(status.get("pauseConditions")) or status.get("paused", False)
    aborted = bool(status.get("aborted", False))
    # status.phase 是 Rollouts 的状态机主相位
    phase = status.get("phase", "Unknown")
    # 统一脱敏：message 仅在内部用于推断，对外输出一律走 _short() 缩短
    raw_message = status.get("message", "") or _aggregate_message(status)
    message = _short(raw_message)

    symptoms: list[str] = []
    actions: list[Action] = []
    category = "healthy"
    root_cause = "Rollout 处于健康状态"
    severity = "info"

    if aborted:
        # 优先级最高：aborted 与 paused 互斥判定时，aborted 优先（已终止的发布不再处于等待）
        category = "aborted"
        severity = "high"
        root_cause = "Rollout 已被中止（aborted）"
        symptoms.append(f"status.aborted=true，原因：{message or '用户或分析失败触发 abort'}")
        actions.append(Action(
            "查看 abort 原因与历史",
            f"kubectl argo rollouts get rollout {name} -n {namespace}",
            1,
        ))
        actions.append(Action(
            "确认后从 aborted 状态恢复推进（resume 不是重新部署新版本，"
            "而是把已中止的发布拉回继续）",
            f"kubectl argo rollouts resume {name} -n {namespace}",
            2,
        ))
    elif paused:
        category = "paused"
        severity = "medium"
        pause_conds = status.get("pauseConditions", []) or []
        reasons = [c.get("reason", "unknown") for c in pause_conds]
        root_cause = f"Rollout 处于暂停（paused），原因：{', '.join(reasons) or '未声明'}"
        symptoms.append(f"pauseConditions={reasons}")
        if "analysis" in str(reasons).lower():
            symptoms.append("分析（Analysis）卡点未通过或未完成")
            actions.append(Action(
                "检查关联 AnalysisRun 结果",
                f"kubectl get analysisrun -n {namespace} -l argo-rollouts=resource",
                1,
            ))
        actions.append(Action(
            "查看当前推进进度",
            f"kubectl argo rollouts get rollout {name} -n {namespace}",
            2,
        ))
        actions.append(Action(
            "人工确认后继续推进",
            f"kubectl argo rollouts promote {name} -n {namespace}",
            3,
        ))
    elif phase == "Degraded":
        category = "degraded"
        severity = "critical"
        root_cause = f"Rollout 处于 Degraded：{message or '新版本不可用'}"
        symptoms.append(f"phase=Degraded，message={message}")
        actions.append(Action(
            "查看 Pod / 事件定位不可用原因",
            f"kubectl argo rollouts get rollout {name} -n {namespace}",
            1,
        ))
        actions.append(Action(
            "回滚到稳定 Revision",
            f"kubectl argo rollouts undo {name} -n {namespace}",
            2,
        ))
    elif phase == "Progressing":
        # 区分"正常推进中"与"卡住"
        step_msgs = _progressing_symptoms(status)
        if step_msgs:
            category = "stuck_progressing"
            severity = "medium"
            root_cause = "Rollout 推进中但疑似卡在某一阶段"
            symptoms.extend(step_msgs)
            actions.append(Action(
                "查看卡点步骤与等待计时",
                f"kubectl argo rollouts get rollout {name} -n {namespace}",
                1,
            ))
        else:
            category = "progressing"
            severity = "info"
            root_cause = "Rollout 正常推进中"
            symptoms.append("phase=Progressing，无异常症状")
    elif phase == "Healthy":
        category = "healthy"
        severity = "info"
        root_cause = "Rollout 健康"
    else:
        category = "unknown"
        severity = "low"
        root_cause = f"未知相位：{phase}"
        symptoms.append(f"phase={phase}")

    return RolloutDiagnosis(
        name=name,
        namespace=namespace,
        strategy=strategy,
        status=phase,
        paused=paused,
        aborted=aborted,
        message=_short(message),
        severity=severity,
        root_cause=root_cause,
        category=category,
        symptoms=symptoms,
        actions=actions,
    )


def _aggregate_message(status: dict[str, Any]) -> str:
    """从 canary/bluegreen 子状态聚合一条可读 message。"""
    parts: list[str] = []
    for key in ("canary", "blueGreen"):
        sub = status.get(key)
        if isinstance(sub, dict) and sub.get("message"):
            parts.append(str(sub["message"]))
    if status.get("message"):
        parts.append(str(status["message"]))
    return " | ".join(parts)


def _progressing_symptoms(status: dict[str, Any]) -> list[str]:
    """识别 Progressing 状态下是否卡在某步骤（如 wait / setWeight 未动）。"""
    symptoms: list[str] = []
    canary = status.get("canary", {})
    if isinstance(canary, dict):
        steps = canary.get("steps", []) or []
        current = canary.get("currentStepIndex")
        if current is not None and steps:
            if current >= len(steps):
                symptoms.append(f"currentStepIndex={current} 已超过步骤总数 {len(steps)}")
            else:
                symptoms.append(f"卡在步骤 #{current + 1}/{len(steps)}: {steps[current]}")
    return symptoms


def fetch_rollout(kubectl: str, name: str, namespace: str) -> dict[str, Any]:
    """通过 kubectl 拉取 Rollout JSON（只读）。失败时抛具体异常。"""
    cmd = [kubectl, "get", "rollout", name, "-n", namespace, "-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到 kubectl 可执行文件: {kubectl}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"拉取 Rollout 超时（>30s）: {name}/{namespace}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"kubectl get rollout 失败 (rc={proc.returncode}): "
            f"{proc.stderr.strip() or '未知错误'}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Rollout JSON 解析失败: {exc}") from exc
