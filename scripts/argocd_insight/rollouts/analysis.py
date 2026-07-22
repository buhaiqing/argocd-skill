"""AnalysisRun 失败归因。

读取 AnalysisRun 的 JSON 状态（来自 `kubectl get analysisrun -o json`），
归因失败原因：metric 阈值未达标 / run 未完成（超时或卡住） / 无 progression 超时。

脱敏：只读，不回显 token。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalysisFinding:
    name: str
    namespace: str
    phase: str  # Pending / Running / Successful / Failed / Error / Inconclusive
    root_cause: str
    category: str  # metric_failed / run_incomplete / no_progression / ok
    severity: str  # critical / high / medium / low / info
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_run(run: dict[str, Any]) -> AnalysisFinding:
    """从单个 AnalysisRun 的 JSON dict 推断归因。"""
    meta = run.get("metadata", {})
    name = meta.get("name", "unknown")
    namespace = meta.get("namespace", "default")
    status = run.get("status", {})
    phase = status.get("phase", "Unknown")
    message = status.get("message", "") or ""

    details: list[str] = []

    if phase == "Successful":
        return AnalysisFinding(
            name=name, namespace=namespace, phase=phase,
            root_cause="AnalysisRun 通过", category="ok",
            severity="info", details=["所有 metric 达标"],
        )

    if phase == "Failed":
        # 逐 metric 检查：区分「阈值未达标 (Failed)」与「查询/计算异常 (Error)」
        failed_metrics, errored_metrics = _failed_metrics(status)
        if failed_metrics:
            details.append("未达标 metric: " + ", ".join(failed_metrics))
            root_cause = f"分析失败：metric 阈值未达标（{', '.join(failed_metrics)}）"
            category = "metric_failed"
            severity = "high"
        elif errored_metrics:
            details.append("异常 metric: " + ", ".join(errored_metrics))
            root_cause = f"分析失败：metric 查询/计算异常（{', '.join(errored_metrics)}）"
            category = "metric_error"
            severity = "high"
        elif message:
            root_cause = f"分析失败：{message}"
            category = "metric_failed"
            severity = "high"
        else:
            root_cause = "分析失败（原因未显式声明）"
            category = "metric_failed"
            severity = "high"
        return AnalysisFinding(
            name=name, namespace=namespace, phase=phase,
            root_cause=root_cause, category=category,
            severity=severity, details=details,
        )

    if phase in ("Error", "Inconclusive"):
        return AnalysisFinding(
            name=name, namespace=namespace, phase=phase,
            root_cause=f"分析异常（{phase}）：{message or 'job/prometheus 查询失败'}",
            category="run_incomplete", severity="high",
            details=details or [message or "检查 AnalysisTemplate 的 provider 配置"],
        )

    if phase in ("Pending", "Running"):
        # 区分正常进行中 vs 卡住（长时间无进展）
        if status.get("phase") == "Running" and not status.get("metricResults"):
            details.append("Running 但尚无 metricResults，可能查询未返回")
            root_cause = "分析进行中，尚未产出结果（若长期无变化则卡住）"
            category = "no_progression"
            severity = "medium"
        else:
            details.append(f"phase={phase}，分析中")
            root_cause = "分析进行中"
            category = "ok"
            severity = "info"
        return AnalysisFinding(
            name=name, namespace=namespace, phase=phase,
            root_cause=root_cause, category=category,
            severity=severity, details=details,
        )

    return AnalysisFinding(
        name=name, namespace=namespace, phase=phase,
        root_cause=f"未知相位：{phase}", category="run_incomplete",
        severity="low", details=details,
    )


def _failed_metrics(status: dict[str, Any]) -> tuple[list[str], list[str]]:
    """从 metricResults 中分离两类失败：
    - 阈值未达标 (phase=Failed)：成功条件不满足
    - 查询/计算异常 (phase=Error)：provider 查询失败或无法求值
    二者语义不同，必须分开归因。
    """
    failed: list[str] = []
    errored: list[str] = []
    for m in status.get("metricResults", []) or []:
        if m.get("phase") == "Failed":
            failed.append(m.get("name", "unknown"))
        elif m.get("phase") == "Error":
            errored.append(m.get("name", "unknown"))
    return failed, errored


def fetch_analysis_runs(kubectl: str, namespace: str, label: str) -> list[dict[str, Any]]:
    """拉取命名空间下（按 label 过滤）的 AnalysisRun 列表（只读）。"""
    cmd = [kubectl, "get", "analysisrun", "-n", namespace, "-o", "json"]
    if label:
        cmd += ["-l", label]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到 kubectl 可执行文件: {kubectl}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"拉取 AnalysisRun 超时（>30s）: {namespace}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"kubectl get analysisrun 失败 (rc={proc.returncode}): "
            f"{proc.stderr.strip() or '未知错误'}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AnalysisRun JSON 解析失败: {exc}") from exc
    return payload.get("items", [])
