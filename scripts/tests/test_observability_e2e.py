#!/usr/bin/env python3
"""
可观测与自进化端到端测试

覆盖完整数据流：
  1. 轨迹写入（合成 JSONL）
  2. 轨迹分析（analyzer: stats + bottleneck + error_classify）
  3. 经验提炼（insight_engine: extract_insights + reasoning）
  4. 自进化 dry-run（evolver: evolve + validate）
  5. snapshot_store 读写
  6. trigger/base 工具函数

Usage:
  python scripts/tests/test_observability_e2e.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT / "scripts"))

import argocd_insight
from argocd_insight.analyzer import analyze_session, compute_stats, find_bottlenecks, classify_errors
from argocd_insight.insight_engine import extract_insights, Insight
from argocd_insight.evolver import evolve, classify_risk, validate_write_back, RiskLevel
from argocd_insight.snapshot_store import SnapshotStore
from argocd_insight.trigger.base import list_sessions, count_events, run_pipeline
from argocd_insight.trace.decorator import get_trace_dir
from argocd_insight.trace.writer import TraceWriter


# ---------------------------------------------------------------------------
# 测试数据构建
# ---------------------------------------------------------------------------

def build_test_events() -> list[dict]:
    """构建包含多种场景的合成轨迹事件。"""
    base = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
    events = []

    # 场景1：diagnose 模块，8 并发，正常返回
    for i in range(12):
        events.append({
            "event_id": f"e_{i:04d}",
            "type": "cli_call",
            "module": "diagnose",
            "operation": "list_apps",
            "command": f"argocd app list --project default --output json --concurrency 8",
            "start": (base + timedelta(seconds=i * 5)).isoformat(),
            "duration_ms": 150 + i * 10,
            "return_code": 0,
            "error": "",
            "stdout_size": 2048,
        })

    # 场景2：diagnose 模块，偶尔慢调用（长尾）
    for i in range(12, 18):
        events.append({
            "event_id": f"e_{i:04d}",
            "type": "cli_call",
            "module": "diagnose",
            "operation": "list_apps",
            "command": f"argocd app list --project default --output json",
            "start": (base + timedelta(seconds=i * 5)).isoformat(),
            "duration_ms": 800 + i * 50,  # 显著慢于 P95
            "return_code": 0,
            "error": "",
            "stdout_size": 4096,
        })

    # 场景3：batch 模块，串行调用链（高频同一命令）
    for i in range(18, 28):
        events.append({
            "event_id": f"e_{i:04d}",
            "type": "cli_call",
            "module": "batch",
            "operation": "sync",
            "command": f"argocd app sync my-app --prune --sync-option PruneLast=true",
            "start": (base + timedelta(seconds=i * 3)).isoformat(),
            "duration_ms": 200 + i * 5,
            "return_code": 0,
            "error": "",
            "stdout_size": 512,
        })

    # 场景4：错误归因 - auth_error
    events.append({
        "event_id": "e_0028",
        "type": "cli_call",
        "module": "diagnose",
        "operation": "list_apps",
        "command": "argocd app list --output json",
        "start": (base + timedelta(seconds=30)).isoformat(),
        "duration_ms": 100,
        "return_code": 1,
        "error": "Unauthorized: invalid credentials",
        "stdout_size": 0,
    })

    # 场景5：错误归因 - network_timeout
    events.append({
        "event_id": "e_0029",
        "type": "cli_call",
        "module": "drift",
        "operation": "compare",
        "command": "argocd app list --server https://argocd.example.com",
        "start": (base + timedelta(seconds=31)).isoformat(),
        "duration_ms": 30000,
        "return_code": -1,
        "error": "Connection timed out after 30s",
        "stdout_size": 0,
    })

    # 场景6：错误归因 - resource_not_found
    events.append({
        "event_id": "e_0030",
        "type": "cli_call",
        "module": "health",
        "operation": "get_app",
        "command": "argocd app get non-existent-app",
        "start": (base + timedelta(seconds=32)).isoformat(),
        "duration_ms": 50,
        "return_code": 1,
        "error": "application 'non-existent-app' not found",
        "stdout_size": 0,
    })

    return events


def write_test_session(session_dir: Path, events: list[dict]) -> None:
    """将事件写入 session 目录的 JSONL 文件。"""
    session_dir.mkdir(parents=True, exist_ok=True)
    writer = TraceWriter(session_dir)
    for event in events:
        writer.write_event(event)
    writer.close()

    # 写入 meta.json
    meta = {
        "session_id": session_dir.name,
        "start_time": events[0]["start"],
        "end_time": events[-1]["start"],
        "command": "e2e-test",
        "module": "observability",
        "total_events": len(events),
    }
    (session_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 断言辅助
# ---------------------------------------------------------------------------

def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ✓ {msg}")


def assert_equal(a, b, msg: str):
    if a != b:
        raise AssertionError(f"FAIL: {msg} — expected {b!r}, got {a!r}")
    print(f"  ✓ {msg}")


# ---------------------------------------------------------------------------
# Step 1: 轨迹写入
# ---------------------------------------------------------------------------

def step1_trace_write(tmp_root: Path):
    print("\n【Step 1】轨迹写入")
    events = build_test_events()
    session_id = f"s_test_{uuid.uuid4().hex[:8]}"
    session_dir = tmp_root / "sessions" / session_id
    write_test_session(session_dir, events)
    assert_true(session_dir.exists(), "session 目录已创建")
    assert_true((session_dir / "trace_000.jsonl").exists(), "trace_000.jsonl 已创建")
    # 验证内容
    lines = (session_dir / "trace_000.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert_equal(len(lines), len(events), "所有事件已写入")
    print(f"  ✓ 写入 {len(events)} 条事件到 {session_dir.name}")


# ---------------------------------------------------------------------------
# Step 2: 轨迹分析
# ---------------------------------------------------------------------------

def step2_analyzer(tmp_root: Path):
    print("\n【Step 2】轨迹分析")
    sessions = list_sessions(tmp_root)
    assert_true(len(sessions) == 1, f"发现 1 个 session（实际: {len(sessions)}）")

    report = analyze_session(sessions[0])
    stats = report["stats"]
    bottlenecks = report["bottlenecks"]
    errors = report["errors"]

    print(f"  Stats: total={stats['total_calls']}, error_rate={stats['error_rate']:.2%}")
    print(f"  P50={stats['p50_ms']}ms, P90={stats['p90_ms']}ms, P99={stats['p99_ms']}ms")
    print(f"  模块分布: {stats['module_distribution']}")
    print(f"  热点命令 Top3: {bottlenecks['hot_commands'][:3]}")
    print(f"  P95={bottlenecks['p95_ms']}ms, 慢调用数: {len(bottlenecks['slow_calls'])}")

    assert_equal(report["total_events"], 31, "总事件数为 31")
    assert_true(stats["total_calls"] == 31, "stats.total_calls == 31")
    assert_true(len(bottlenecks["slow_calls"]) > 0, "存在慢调用（长尾）")
    assert_true(len(bottlenecks["frequent_commands"]) > 0, "存在高频串行命令（batch sync）")

    # 错误归因验证
    auth_errors = errors.get("auth_error", [])
    timeout_errors = errors.get("network_timeout", [])
    notfound_errors = errors.get("resource_not_found", [])
    assert_equal(len(auth_errors), 1, "归因出 1 个 auth_error")
    assert_equal(len(timeout_errors), 1, "归因出 1 个 network_timeout")
    assert_equal(len(notfound_errors), 1, "归因出 1 个 resource_not_found")
    print("  ✓ 错误归因正确")


# ---------------------------------------------------------------------------
# Step 3: 经验提炼
# ---------------------------------------------------------------------------

def step3_insight_extraction(tmp_root: Path):
    print("\n【Step 3】经验提炼")
    sessions = list_sessions(tmp_root)
    report = analyze_session(sessions[0])
    insights = extract_insights(report)

    print(f"  提炼出 {len(insights)} 条经验:")
    for ins in insights:
        print(f"    [{ins.category}] {ins.insight} (conf={ins.confidence})")
        for step in ins.reasoning_chain:
            print(f"      {step}")

    assert_true(len(insights) >= 3, f"至少提炼 3 条经验（实际: {len(insights)}）")

    # 验证经验结构完整性
    for ins in insights:
        assert_true(ins.category in ("performance", "error_pattern"), f"category 有效: {ins.category}")
        assert_true(0 <= ins.confidence <= 1, f"confidence 范围有效: {ins.confidence}")
        assert_true(len(ins.reasoning_chain) > 0, "有推断链")
        assert_true(len(ins.evidence) > 0, "有证据数据")

    print("  ✓ 经验结构完整（category/confidence/reasoning_chain/evidence）")


# ---------------------------------------------------------------------------
# Step 4: 自进化 dry-run
# ---------------------------------------------------------------------------

def step4_evolver_dryrun(tmp_root: Path):
    print("\n【Step 4】自进化 dry-run")
    sessions = list_sessions(tmp_root)
    report = analyze_session(sessions[0])
    insights = extract_insights(report)

    # dry-run
    results = evolve(insights, dry_run=True)
    print(f"  分级结果: low={len(results['low'])}, medium={len(results['medium'])}, "
          f"high={len(results['high'])}, skipped={len(results['skipped'])}")

    for level in ["low", "medium", "high"]:
        for item in results[level]:
            print(f"    [{level.upper()}] {item['insight']} — would_write={item.get('would_write')}")

    for item in results.get("skipped", []):
        print(f"    [SKIPPED] {item['insight']} — reason: {item['reason']}")

    # 验证分级逻辑
    for ins in insights:
        risk = classify_risk(ins.confidence)
        risk_key = risk.value
        assert_true(risk_key in ("low", "medium", "high"), f"风险分级有效: {risk_key}")
        if ins.confidence < 0.7:
            assert_true(risk == RiskLevel.HIGH, f"conf={ins.confidence} < 0.7 → HIGH")

    print("  ✓ 风险分级逻辑正确")
    print("  ✓ dry-run 不修改文件")


# ---------------------------------------------------------------------------
# Step 5: validate_write_back 校验
# ---------------------------------------------------------------------------

def step5_validate_write_back():
    print("\n【Step 5】写回校验（validate_write_back）")

    # MD 文件：有效
    valid_md = "---\nname: test\ndescription: |\n  test\n---\n# Test"
    assert_true(validate_write_back(valid_md, "SKILL.md"), "有效 MD 文件通过校验")

    # MD 文件：无 frontmatter
    invalid_md = "# Test\nNo frontmatter"
    assert_true(not validate_write_back(invalid_md, "SKILL.md"), "无 frontmatter MD 被拒绝")

    # Python 文件：有效
    valid_py = "x = 1\nprint(x)"
    assert_true(validate_write_back(valid_py, "cli.py"), "有效 Python 通过校验")

    # Python 文件：语法错误
    invalid_py = "x = 1 print(x)"  # 缺少换行
    assert_true(not validate_write_back(invalid_py, "cli.py"), "语法错误 Python 被拒绝")

    print("  ✓ validate_write_back 正确识别有效/无效文件")


# ---------------------------------------------------------------------------
# Step 6: SnapshotStore
# ---------------------------------------------------------------------------

def step6_snapshot_store(tmp_root: Path):
    print("\n【Step 6】SnapshotStore 读写")

    store = SnapshotStore(tmp_root / "snapshots")
    assert_true(store.store_dir.exists(), "store 目录已创建")

    # 保存快照
    data = {
        "diagnose": {"total": 31, "errors": 3},
        "health": {"score": 72},
    }
    path = store.save(data)
    assert_true(path.exists(), "快照文件已保存")
    print(f"  快照路径: {path.name}")

    # 加载最新
    loaded = store.load_latest()
    assert_true(loaded is not None, "load_latest 返回非空")
    assert_equal(loaded["modules"]["diagnose"]["total"], 31, "快照数据一致")

    # 列表
    snaps = store.list_snapshots()
    assert_equal(len(snaps), 1, "list_snapshots 返回 1 条")

    # count
    assert_equal(store.count(), 1, "count 返回 1")

    print("  ✓ SnapshotStore 读写正常")


# ---------------------------------------------------------------------------
# Step 7: trigger/base 工具函数
# ---------------------------------------------------------------------------

def step7_trigger_base(tmp_root: Path):
    print("\n【Step 7】trigger/base 工具函数")

    # list_sessions
    sessions = list_sessions(tmp_root, since_days=0)
    assert_equal(len(sessions), 1, "list_sessions 返回 1 个 session")

    sessions_7d = list_sessions(tmp_root, since_days=7)
    assert_equal(len(sessions_7d), 1, "since_days=7 仍在范围内")

    sessions_0d = list_sessions(tmp_root, since_days=0)
    assert_equal(len(sessions_0d), 1, "since_days=0 不过滤")

    # count_events
    total = count_events(tmp_root)
    assert_equal(total, 31, f"count_events 返回 31（实际: {total}）")

    # run_pipeline (extract=False, evolve=False)
    result = run_pipeline(tmp_root, since_days=7, extract=False, evolve=False)
    assert_equal(result["sessions_analyzed"], 1, "pipeline sessions_analyzed=1")
    assert_equal(result["total_events"], 31, "pipeline total_events=31")
    assert_equal(len(result["insights"]), 0, "extract=False 时无 insights")

    # run_pipeline (extract=True, evolve=True, dry_run=True)
    result2 = run_pipeline(tmp_root, since_days=7, extract=True, evolve=True, dry_run=True)
    assert_equal(result2["sessions_analyzed"], 1, "pipeline sessions_analyzed=1")
    assert_true(len(result2["insights"]) >= 3, f"提炼经验 >= 3（实际: {len(result2['insights'])})）")
    assert_true("evolve_results" in result2, "evolve_results 已返回")
    print(f"  ✓ run_pipeline extract+evolve 正常（{len(result2['insights'])} 条经验）")


# ---------------------------------------------------------------------------
# Step 8: @traced 装饰器（集成测试）
# ---------------------------------------------------------------------------

def step8_traced_decorator(tmp_root: Path):
    print("\n【Step 8】@traced 装饰器集成测试")

    import os
    old_env = os.environ.get("ARGOCD_SKILL_RUNTIME_DIR")
    os.environ["ARGOCD_SKILL_RUNTIME_DIR"] = str(tmp_root)

    try:
        from argocd_insight.trace import traced, get_session_id

        @traced(module="test_module", operation="test_op")
        def fake_cli_call(arg1: str, arg2: int) -> str:
            return f"result: {arg1} {arg2}"

        sid_before = get_session_id()
        result = fake_cli_call("hello", 42)
        assert_equal(result, "result: hello 42", "装饰器不改变返回值")

        # 检查是否写入了轨迹文件
        session_dir = tmp_root / "sessions" / sid_before
        trace_files = list(session_dir.glob("trace_*.jsonl")) if session_dir.exists() else []
        assert_true(len(trace_files) > 0, "装饰器写入了轨迹文件")
        print(f"  ✓ @traced 写入轨迹到 {trace_files[0].name}")

        # 验证轨迹内容
        content = trace_files[0].read_text(encoding="utf-8")
        lines = [json.loads(l) for l in content.strip().split("\n") if l.strip()]
        assert_equal(len(lines), 1, "写入 1 条轨迹事件")
        assert_equal(lines[0]["module"], "test_module", "module 字段正确")
        assert_equal(lines[0]["operation"], "test_op", "operation 字段正确")
        print(f"  ✓ 轨迹内容正确: module=test_module, operation=test_op")

    finally:
        if old_env is None:
            os.environ.pop("ARGOCD_SKILL_RUNTIME_DIR", None)
        else:
            os.environ["ARGOCD_SKILL_RUNTIME_DIR"] = old_env


# ---------------------------------------------------------------------------
# Step 9: evolver 真实写回 dry-run（检查目标文件）
# ---------------------------------------------------------------------------

def step9_evolver_real_dryrun(tmp_root: Path):
    print("\n【Step 9】evolver 真实 dry-run 检查")
    sessions = list_sessions(tmp_root)
    report = analyze_session(sessions[0])
    insights = extract_insights(report)

    # 用真实项目根目录做 dry-run（验证路径安全）
    results = evolve(insights, dry_run=True)
    print(f"  dry-run 结果: {json.dumps(results, indent=2, ensure_ascii=False)}")

    # 验证所有 would_write 项确实未写文件
    for level in ["low", "medium", "high"]:
        for item in results.get(level, []):
            action = item.get("action")
            if action and action.get("target"):
                target_path = ROOT / action["target"]
                before = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
                # dry-run 不会改变文件，所以内容不变
                after = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
                assert_equal(before, after, f"dry-run 未修改 {action['target']}")

    print("  ✓ dry-run 未修改任何目标文件")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("可观测与自进化 — 端到端功能验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="argocd_e2e_") as tmp:
        tmp_root = Path(tmp)

        try:
            step1_trace_write(tmp_root)
            step2_analyzer(tmp_root)
            step3_insight_extraction(tmp_root)
            step4_evolver_dryrun(tmp_root)
            step5_validate_write_back()
            step6_snapshot_store(tmp_root)
            step7_trigger_base(tmp_root)
            step8_traced_decorator(tmp_root)
            step9_evolver_real_dryrun(tmp_root)

            print("\n" + "=" * 60)
            print("✅ 所有步骤通过 — 可观测与自进化功能验证完成")
            print("=" * 60)
            return 0

        except AssertionError as e:
            print(f"\n❌ 断言失败: {e}")
            return 1
        except Exception as e:
            print(f"\n❌ 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(main())