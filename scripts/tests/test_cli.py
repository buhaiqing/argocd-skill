"""cli.py 端到端集成测试：临时目录 → 输出目录全套产物。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argocd_cli_gen import cli


BUSINESS_YAML = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-mas-user-service
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    project: dly
    app: mas-user-service
spec:
  destination:
    namespace: production
    server: https://kubernetes.default.svc
  source:
    repoURL: https://example.com/toolset_dly.git
    targetRevision: k8s_mas
    path: mas-user-service/overlays/production/production
    kustomize:
      version: v4.1.3
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
"""

ROOT_YAML = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dly-production-k8s-ops
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: argo-root
    server: https://kubernetes.default.svc
  source:
    repoURL: https://example.com/argoapp.git
    targetRevision: dly_prd
    path: argo-apps/dly/production/k8s_ops
  project: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""

HELM_MULTISOURCE_YAML = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: loki
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://example.com/helm
      chart: loki
      targetRevision: 6.5.2
      helm:
        valueFiles:
          - $values/loki/values.yaml
    - repoURL: https://example.com/values.git
      targetRevision: main
      ref: values
  project: default
"""

MULTI_SOURCE_NON_HELM_YAML = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: composite
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: app
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://example.com/repo-a.git
      targetRevision: main
      path: components/a
    - repoURL: https://example.com/repo-b.git
      targetRevision: main
      path: components/b
  project: default
"""


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """搭建一个包含 business / root / multi-source helm 三种典型 YAML 的输入目录。"""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "business.yaml").write_text(BUSINESS_YAML, encoding="utf-8")
    (in_dir / "root.yaml").write_text(ROOT_YAML, encoding="utf-8")
    (in_dir / "loki.yaml").write_text(HELM_MULTISOURCE_YAML, encoding="utf-8")
    # 干扰文件：ConfigMap 应当被跳过
    (in_dir / "configmap.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: c\n",
        encoding="utf-8",
    )
    return in_dir


def test_cli_full_pipeline_writes_all_artifacts(tmp_path, manifest_dir, capsys):
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
    ])
    assert rc == cli.EXIT_OK, "默认 --fail-on=error 下应当退出 0（无 fallback 时无 warning）"

    # 1. 各层级脚本与 dry-run 副本都存在
    expected = [
        "00_preflight.sh",
        "10_app_roots.sh",
        "10_app_roots.dry-run.sh",
        "30_workloads_business.sh",
        "30_workloads_business.dry-run.sh",
        "40_workloads_helm.sh",
        "40_workloads_helm.dry-run.sh",
        "helm-apps/loki.yaml",
        "run_all.sh",
        "report.json",
        "report.md",
    ]
    for name in expected:
        assert (out_dir / name).exists(), f"缺少产物文件：{name}"

    # 2. shell 脚本是可执行的
    assert (out_dir / "30_workloads_business.sh").stat().st_mode & 0o100
    assert (out_dir / "40_workloads_helm.sh").stat().st_mode & 0o100

    # 3. 多源 Helm 产物：argocd app create -f 指向 helm-apps/loki.yaml
    helm_body = (out_dir / "40_workloads_helm.sh").read_text(encoding="utf-8")
    assert "argocd app create" in helm_body
    assert "-f helm-apps/loki.yaml" in helm_body
    # 单独的 YAML 文件保留多源 spec
    loki_yaml = (out_dir / "helm-apps" / "loki.yaml").read_text(encoding="utf-8")
    assert "sources:" in loki_yaml
    assert "ref: values" in loki_yaml

    # 4. 无非 Helm 多源 → 不应出现 99_multisource_fallback.yaml
    assert not (out_dir / "99_multisource_fallback.yaml").exists()

    # 5. report.json 数据正确：3 个应用全部 converted，其中 1 个是 helm 多源
    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert rep["total"] == 3            # business + root + helm multisource
    assert rep["fallback_to_yaml"] == 0
    assert rep["converted"] == 3
    assert rep["helm_multisource"] == 1

    # 6. stderr 输出了总结
    captured = capsys.readouterr()
    assert "处理 Application 总数：3" in captured.err
    assert "输出脚本" in captured.err
    assert "多源 Helm" in captured.err


def test_cli_pipeline_with_non_helm_multi_source_falls_back(tmp_path):
    """非 Helm 多源仍走 99_multisource_fallback.yaml，不会被误归到 helm tier。"""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "business.yaml").write_text(BUSINESS_YAML, encoding="utf-8")
    (in_dir / "composite.yaml").write_text(MULTI_SOURCE_NON_HELM_YAML, encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = cli.main(["--input", str(in_dir), "--output", str(out_dir)])
    assert rc == cli.EXIT_OK

    fb_path = out_dir / "99_multisource_fallback.yaml"
    assert fb_path.exists()
    assert "name: composite" in fb_path.read_text(encoding="utf-8")
    # 没有 helm 多源 → 不生成 helm tier 产物
    assert not (out_dir / "40_workloads_helm.sh").exists()
    assert not (out_dir / "helm-apps").exists()

    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert rep["fallback_to_yaml"] == 1
    assert rep["helm_multisource"] == 0


def test_cli_no_dry_run_when_disabled(tmp_path, manifest_dir):
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
        "--no-emit-dry-run",
    ])
    assert rc == cli.EXIT_OK
    assert (out_dir / "30_workloads_business.sh").exists()
    assert not (out_dir / "30_workloads_business.dry-run.sh").exists()


def test_cli_no_upsert(tmp_path, manifest_dir):
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
        "--no-upsert",
    ])
    assert rc == cli.EXIT_OK
    body = (out_dir / "30_workloads_business.sh").read_text(encoding="utf-8")
    assert "--upsert" not in body


def test_cli_sleep_inserted(tmp_path, manifest_dir):
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
        "--sleep", "1.5",
    ])
    assert rc == cli.EXIT_OK
    body = (out_dir / "30_workloads_business.sh").read_text(encoding="utf-8")
    assert "sleep 1.5" in body


def test_cli_fail_on_warning_returns_1_when_non_helm_fallback_present(tmp_path):
    """非 Helm 多源进 fallback，--fail-on=warning 应触发 1 退出码。"""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "business.yaml").write_text(BUSINESS_YAML, encoding="utf-8")
    (in_dir / "composite.yaml").write_text(MULTI_SOURCE_NON_HELM_YAML, encoding="utf-8")
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(in_dir),
        "--output", str(out_dir),
        "--fail-on", "warning",
    ])
    assert rc == cli.EXIT_WARNING


def test_cli_fail_on_warning_returns_0_for_helm_multisource(tmp_path, manifest_dir):
    """多源 Helm 已转 CLI 命令，不应再触发 warning 级别退出。"""
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
        "--fail-on", "warning",
    ])
    assert rc == cli.EXIT_OK, "多源 Helm 已是 converted，不应产生 fallback warning"


def test_cli_fail_on_warning_returns_0_when_no_fallback(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "biz.yaml").write_text(BUSINESS_YAML, encoding="utf-8")
    out_dir = tmp_path / "out"

    rc = cli.main([
        "--input", str(in_dir),
        "--output", str(out_dir),
        "--fail-on", "warning",
    ])
    assert rc == cli.EXIT_OK
    assert not (out_dir / "99_multisource_fallback.yaml").exists()


def test_cli_missing_input_returns_3(tmp_path, capsys):
    rc = cli.main([
        "--input", str(tmp_path / "nonexistent"),
        "--output", str(tmp_path / "out"),
    ])
    assert rc == cli.EXIT_CLI_ARG_ERROR
    assert "不存在" in capsys.readouterr().err


def test_cli_empty_input_returns_2(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = cli.main([
        "--input", str(empty),
        "--output", str(tmp_path / "out"),
    ])
    assert rc == cli.EXIT_PARSE_ERROR
    assert "未发现" in capsys.readouterr().err


def test_cli_include_filter(tmp_path, manifest_dir):
    """--include 过滤生效后只匹配业务 YAML。"""
    out_dir = tmp_path / "out"
    rc = cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
        "--include", "business.yaml",
    ])
    assert rc == cli.EXIT_OK
    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert rep["total"] == 1
    assert rep["converted"] == 1
    assert rep["fallback_to_yaml"] == 0


def test_cli_run_all_lists_present_tiers(tmp_path, manifest_dir):
    out_dir = tmp_path / "out"
    cli.main([
        "--input", str(manifest_dir),
        "--output", str(out_dir),
    ])
    run_all = (out_dir / "run_all.sh").read_text(encoding="utf-8")
    assert "10_app_roots.sh" in run_all
    assert "30_workloads_business.sh" in run_all
    assert "40_workloads_helm.sh" in run_all   # loki 落在 helm tier
    # 没有 ops/infra 应用，应当以注释代替
    assert "no infra roots" in run_all
    assert "no workloads" not in run_all  # 业务存在
