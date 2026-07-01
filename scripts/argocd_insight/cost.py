#!/usr/bin/env python3
"""
cost — 资源成本估算工具

查询 ArgoCD App 的部署资源（CPU/Memory requests），估算运行成本。

Usage:
  python -m argocd_insight cost               # 全量估算
  python -m argocd_insight cost --project prod # 指定项目
  python -m argocd_insight cost --output json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

# ponytail: 一次性脚本，不建完整类。成本模型硬编码，按需切换云厂商。

# 成本模型（USD/小时）
# ponytail: 硬编码 AWS us-east-1 m 系列均价，后续按需加云厂商
COST_PER_VCPU_HOUR = 0.042   # $/vCPU-hour (AWS m5/m6i 均价)
COST_PER_GB_HOUR = 0.0047    # $/GB-hour (内存)


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", "command not found"


def fetch_apps(project: str | None = None) -> list[dict]:
    cmd = ["argocd", "app", "list", "--output", "json"]
    if project:
        cmd += ["--project", project]
    _, out, _ = run(cmd)
    return json.loads(out) if out else []


def get_app_resources(app_name: str) -> list[dict]:
    """获取 App 管理的 Kubernetes 资源列表"""
    _, out, _ = run(["argocd", "app", "resources", app_name, "--output", "json"])
    if not out:
        return []
    try:
        data = json.loads(out)
        # argocd app resources 返回 {"items": [...]}
        return data.get("items", []) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        return []


def parse_cpu(cpu_str: str) -> float:
    """将 K8s CPU 字符串转换为核数（小数）"""
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str).strip()
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    try:
        return float(cpu_str)
    except ValueError:
        return 0.0


def parse_memory(mem_str: str) -> float:
    """将 K8s Memory 字符串转换为 GiB"""
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip()
    # ponytail: 只处理常见单位，不搞完整解析
    multipliers = {
        "Ki": 1 / (1024 ** 2),   # → GiB
        "Mi": 1 / 1024,          # → GiB
        "Gi": 1.0,               # → GiB
        "Ti": 1024.0,            # → GiB
        "K": 1 / (1024 ** 2),    # → GiB (decimal)
        "M": 1 / 1000,           # → GiB (decimal)
        "G": 1.0,                # → GiB (decimal)
        "T": 1000.0,             # → GiB (decimal)
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if mem_str.endswith(suffix):
            try:
                return float(mem_str[: -len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(mem_str) / (1024 ** 3)  # bytes → GiB
    except ValueError:
        return 0.0


def extract_resource_specs(resources: list[dict]) -> dict:
    """从资源列表中提取 CPU/Memory requests 汇总"""
    total_cpu_cores = 0.0
    total_memory_gib = 0.0
    total_replicas = 0
    workload_details = []

    for res in resources:
        kind = res.get("kind", "")
        name = res.get("name", "")
        namespace = res.get("namespace", "")
        status = res.get("status", "")
        # ponytail: 只处理健康资源，跳过缺失/未知
        if status not in ("Synced", "Healthy", ""):
            continue
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue

        # 从 resource 的 live state 提取资源规格
        live = res.get("live", {})
        if not live:
            continue

        spec = live.get("spec", {})
        template = spec.get("template", {}).get("spec", {})
        containers = template.get("containers", [])

        # 计算副本数
        replicas = spec.get("replicas", 1)
        if kind == "DaemonSet":
            # DaemonSet: 每个节点一个，无法精确计算，默认 1（后续按节点数调整）
            replicas = 1

        # 汇总所有 container 的 requests
        cpu_total = 0.0
        mem_total = 0.0
        for c in containers:
            res_req = c.get("resources", {}).get("requests", {})
            cpu_total += parse_cpu(res_req.get("cpu", "0"))
            mem_total += parse_memory(res_req.get("memory", "0"))

        workload_cpu = cpu_total * replicas
        workload_mem = mem_total * replicas

        total_cpu_cores += workload_cpu
        total_memory_gib += workload_mem
        total_replicas += replicas

        workload_details.append({
            "name": name,
            "kind": kind,
            "namespace": namespace,
            "replicas": replicas,
            "cpuCores": round(cpu_total, 3),
            "memoryGiB": round(mem_total, 2),
            "cpuCostHourly": round(workload_cpu * COST_PER_VCPU_HOUR, 4),
            "memCostHourly": round(workload_mem * COST_PER_GB_HOUR, 4),
        })

    return {
        "totalCpuCores": round(total_cpu_cores, 3),
        "totalMemoryGiB": round(total_memory_gib, 2),
        "totalReplicas": total_replicas,
        "workloads": workload_details,
    }


def build_report(apps: list[dict]) -> dict:
    """构建成本估算报告"""
    app_costs = []
    total_cpu = 0.0
    total_mem = 0.0
    total_cost_hourly = 0.0
    total_replicas = 0

    for app in apps:
        name = app.get("metadata", {}).get("name", "")
        project = app.get("spec", {}).get("project", "")
        namespace = app.get("spec", {}).get("destination", {}).get("namespace", "")

        resources = get_app_resources(name)
        specs = extract_resource_specs(resources)

        cpu_cost = specs["totalCpuCores"] * COST_PER_VCPU_HOUR
        mem_cost = specs["totalMemoryGiB"] * COST_PER_GB_HOUR
        app_cost = cpu_cost + mem_cost

        total_cpu += specs["totalCpuCores"]
        total_mem += specs["totalMemoryGiB"]
        total_cost_hourly += app_cost
        total_replicas += specs["totalReplicas"]

        app_costs.append({
            "app": name,
            "project": project,
            "namespace": namespace,
            "cpuCores": specs["totalCpuCores"],
            "memoryGiB": specs["totalMemoryGiB"],
            "replicas": specs["totalReplicas"],
            "cpuCostHourly": round(cpu_cost, 4),
            "memCostHourly": round(mem_cost, 4),
            "totalCostHourly": round(app_cost, 4),
            "workloads": specs["workloads"],
        })

    # 按成本排序，找 Top 10
    app_costs.sort(key=lambda x: -x["totalCostHourly"])

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalApps": len(apps),
        "totalCpuCores": round(total_cpu, 3),
        "totalMemoryGiB": round(total_mem, 2),
        "totalReplicas": total_replicas,
        "totalCostHourly": round(total_cost_hourly, 4),
        "totalCostMonthly": round(total_cost_hourly * 24 * 30, 2),
        "costModel": {
            "cpuPerVcpuHour": COST_PER_VCPU_HOUR,
            "memPerGiBHour": COST_PER_GB_HOUR,
            "currency": "USD",
            "note": "基于 AWS us-east-1 m5/m6i 均价估算",
        },
        "top10": app_costs[:10],
        "apps": app_costs,
    }


def print_markdown(report: dict):
    print("# ArgoCD 资源成本估算报告\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"成本模型：CPU ${report['costModel']['cpuPerVcpuHour']}/vCPU-hr，"
          f"Memory ${report['costModel']['memPerGiBHour']}/GiB-hr\n")

    print("## 总览\n")
    print("| 指标 | 值 |")
    print("|------|-----|")
    print(f"| App 总数 | {report['totalApps']} |")
    print(f"| CPU 总量 | {report['totalCpuCores']} cores |")
    print(f"| Memory 总量 | {report['totalMemoryGiB']} GiB |")
    print(f"| 副本总数 | {report['totalReplicas']} |")
    print(f"| **每小时成本** | **${report['totalCostHourly']}** |")
    print(f"| **预估月成本** | **${report['totalCostMonthly']}** |")

    top10 = report.get("top10", [])
    if top10:
        print("\n## Top 10 高成本 App\n")
        print("| 排名 | App | Project | CPU (cores) | Memory (GiB) | 副本 | 月成本 |")
        print("|------|-----|---------|-------------|--------------|------|--------|")
        for i, app in enumerate(top10, 1):
            monthly = round(app["totalCostHourly"] * 24 * 30, 2)
            print(f"| {i} | {app['app']} | {app['project']} | "
                  f"{app['cpuCores']} | {app['memoryGiB']} | "
                  f"{app['replicas']} | ${monthly} |")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ArgoCD 资源成本估算")
    p.add_argument("--project", help="按项目过滤")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    args = p.parse_args(argv)

    print("Fetching apps...", file=sys.stderr)
    apps = fetch_apps(args.project)
    print(f"Got {len(apps)} apps, estimating costs...", file=sys.stderr)

    report = build_report(apps)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
