"""
parse_utils — ArgoCD CLI 文本输出解析工具函数

统一维护 diff / resources 等文本解析逻辑，避免在多个诊断工具中重复。
ArgoCD 版本兼容性变化只需在此文件中调整。

典型用法：
  from argocd_insight.parse_utils import parse_diff, parse_resources
  diff_info = parse_diff(diff_out)
  orphaned, unhealthy = parse_resources(res_out)
"""


def parse_diff(diff_out: str) -> dict[str, bool]:
    """
    解析 `argocd app diff` 输出，检测增减。

    ponytail: 统一 diff 格式用 `+`/`-` 前缀，普通 diff 用 `>`/`<` 前缀。
    同时匹配两种格式以避免 ArgoCD 版本差异。
    若版本升级后格式变化，优先调整此函数而非各调用点。

    Returns: {"additions": bool, "deletions": bool}
    """
    has_add = has_del = False
    for line in diff_out.splitlines():
        ls = line.strip()
        if ls.startswith("> ") or (ls.startswith("+") and not ls.startswith("+++")):
            has_add = True
        elif ls.startswith("< ") or (ls.startswith("-") and not ls.startswith("---")):
            has_del = True
    return {"additions": has_add, "deletions": has_del}


def parse_resources(res_out: str) -> tuple[list[str], list[str]]:
    """
    解析 `argocd app resources` 输出。

    ArgoCD resources 输出格式（文本表格，列数因版本和资源类型而异）：
      GROUP  KIND  NAMESPACE  NAME  STATUS  HEALTH  [ORPHANED|DETAIL]

    Orphaned 检测策略（兼容多版本）：
      1. STATUS 列为 "Orphaned"
      2. 行尾（最后一列）为 "Yes"（旧版本格式）
      3. 行中包含 "\tOrphaned"

    ponytail: 若版本升级后格式变化，改为解析 JSON 输出。

    Returns: (orphaned_kinds: list[str], unhealthy_kinds: list[str])
      - orphaned: ["Kind/Name", ...] 格式
      - unhealthy: ["Kind/Name(HealthStatus)", ...] 格式
    """
    orphaned: list[str] = []
    unhealthy: list[str] = []
    for line in res_out.strip().splitlines():
        if not line or line.startswith("GROUP") or line.startswith("NAMESPACE"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        # 使用负索引兼容 GROUP 列为空的场景
        # 典型格式: [GROUP] KIND NAMESPACE NAME STATUS HEALTH [DETAIL]
        kind = parts[-5] if len(parts) >= 5 else parts[0]
        name = parts[-3] if len(parts) >= 3 else parts[0]

        # 检查 orphaned：状态列为 "Orphaned" 或行尾为 "Yes"
        is_orphaned = False
        for p in parts:
            if p == "Orphaned":
                is_orphaned = True
                break
        if not is_orphaned and len(parts) >= 2 and parts[-1] == "Yes":
            is_orphaned = True

        if is_orphaned:
            orphaned.append(f"{kind}/{name}")
            continue

        # 检查健康状态（倒数第二列或第4列）
        health = parts[-2] if len(parts) >= 3 else ""
        if health and health not in ("Healthy", ""):
            unhealthy.append(f"{kind}/{name}({health})")
    return orphaned, unhealthy


def has_orphaned_entries(res_out: str) -> list[str]:
    """
    轻量版 orphaned 检测——只判断是否有 orphaned 资源并返回名称列表。
    适用于 oos_analyzer 等只需要 orphaned 列的场景（不需要 unhealthy 检测）。

    Returns: ["Kind/Name", ...]
    """
    orphaned, _ = parse_resources(res_out)
    return orphaned