"""renderer.py 集成测试：从 YAML → shell 脚本。"""

from __future__ import annotations

from pathlib import Path

import yaml

from argocd_cli_gen import parser, renderer
from argocd_cli_gen.parser import LoadedManifest, Tier
from argocd_cli_gen.renderer import RenderOptions


BUSINESS_YAML = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-mas-user-service
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    project: dly
    profile: production
    stack: dly3
    app: mas-user-service
spec:
  destination:
    name: ''
    namespace: production
    server: https://kubernetes.default.svc
  source:
    path: mas-user-service/overlays/production/production
    repoURL: https://example.com/toolset_dly.git
    targetRevision: k8s_mas
    kustomize:
      version: v4.1.3
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
"""

ROOT_YAML = """
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
    path: argo-apps/dly/production/k8s_ops
    repoURL: https://example.com/argoapp.git
    targetRevision: dly_prd
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
    automated:
      prune: true
      selfHeal: true
"""

HELM_MULTISOURCE_YAML = """
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
    - repoURL: https://helm-charts.example.com/grafana
      chart: loki
      targetRevision: 6.5.2
      helm:
        valueFiles:
          - $values/loki/overlays/dly-prd/values-scalable-s3.yaml
    - repoURL: https://github.example.com/toolset_dly.git
      targetRevision: k8s_ops
      ref: values
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
      - CreateNamespace=false
"""


def _make_lm(text: str, fname: str = "x.yaml") -> LoadedManifest:
    m = yaml.safe_load(text)
    tier, reason = parser.detect_tier(m)
    return LoadedManifest(path=Path(fname), manifest=m, tier=tier, reason=reason)


def test_render_business_app_emits_create_command():
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    business_scripts = [s for s in result.scripts
                        if s.relative_path == renderer.TIER_FILES[Tier.BUSINESS_APP]]
    assert len(business_scripts) == 1
    body = business_scripts[0].body
    assert "argocd app create production-mas-user-service" in body
    assert "--upsert" in body
    assert "--revision k8s_mas" in body
    assert "set -euo pipefail" in body


def test_render_emits_dry_run_copy():
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=True))
    business_scripts = [s for s in result.scripts
                        if s.relative_path == renderer.TIER_FILES[Tier.BUSINESS_APP]]
    assert business_scripts[0].dry_run_body is not None
    assert "argocd app create --dry-run -o yaml" in business_scripts[0].dry_run_body


def test_render_no_dry_run_when_disabled():
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=False))
    business_scripts = [s for s in result.scripts
                        if s.relative_path == renderer.TIER_FILES[Tier.BUSINESS_APP]]
    assert business_scripts[0].dry_run_body is None


def test_render_root_emits_automated_flags():
    lm = _make_lm(ROOT_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    root_scripts = [s for s in result.scripts
                    if s.relative_path == renderer.TIER_FILES[Tier.ROOT_APP]]
    body = root_scripts[0].body
    assert "--sync-policy automated" in body
    assert "--auto-prune" in body
    assert "--self-heal" in body


def test_render_mixed_buckets_emit_separate_files():
    """业务 + Root 应输出两个不同的 shell 脚本。"""
    lms = [_make_lm(BUSINESS_YAML, "biz.yaml"), _make_lm(ROOT_YAML, "root.yaml")]
    result = renderer.render_all(lms, source_dir=Path("/in"), opts=RenderOptions())

    names = {s.relative_path for s in result.scripts}
    assert renderer.TIER_FILES[Tier.BUSINESS_APP] in names
    assert renderer.TIER_FILES[Tier.ROOT_APP] in names
    assert "00_preflight.sh" in names
    assert "run_all.sh" in names


def test_write_results_creates_files(tmp_path):
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())
    written = renderer.write_results(result, tmp_path)

    assert any(p.name == "00_preflight.sh" for p in written)
    assert any(p.name == "30_workloads_business.sh" for p in written)
    assert any(p.name == "30_workloads_business.dry-run.sh" for p in written)
    assert any(p.name == "run_all.sh" for p in written)

    main = tmp_path / "30_workloads_business.sh"
    assert main.exists()
    assert main.stat().st_mode & 0o100  # 可执行


def test_patches_yaml_skipped_from_main_scripts():
    """P0 回归：含 spec.source.kustomize.patches 的 YAML 不应出现在主脚本中。

    设计 §7.2 要求这类 YAML 整体回退到 99_multisource_fallback.yaml，
    不能既在主脚本（argocd app create）又在 fallback（kubectl apply）。
    """
    patches_yaml = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-svc
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: prod
    server: https://kubernetes.default.svc
  source:
    repoURL: r
    targetRevision: main
    path: p
    kustomize:
      version: v4.1.3
      patches:
        - target:
            kind: Deployment
          patch: |-
            - op: replace
              path: /spec/template/spec/containers/0/resources
              value: {requests: {cpu: 500m}}
  project: default
"""
    lms = [_make_lm(BUSINESS_YAML, "biz.yaml"), _make_lm(patches_yaml, "payment.yaml")]
    result = renderer.render_all(lms, source_dir=Path("/in"), opts=RenderOptions())

    # 主脚本中不应包含 payment-svc
    all_main_bodies = "\n".join(s.body for s in result.scripts if s.relative_path.endswith(".sh"))
    assert "argocd app create payment-svc" not in all_main_bodies, \
        "含 patches 的 YAML 不应出现在主脚本（会与 fallback YAML 重复创建）"
    # 业务应用仍应渲染
    assert "argocd app create production-mas-user-service" in all_main_bodies


def test_non_helm_multi_source_yaml_skipped_from_main_scripts():
    """非 Helm 多源 YAML（如多 git path）不进任何 .sh 主脚本，只进 fallback。"""
    multi_yaml = """
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
    lms = [_make_lm(BUSINESS_YAML, "biz.yaml"), _make_lm(multi_yaml, "composite.yaml")]
    result = renderer.render_all(lms, source_dir=Path("/in"), opts=RenderOptions())

    all_main_bodies = "\n".join(s.body for s in result.scripts if s.relative_path.endswith(".sh"))
    assert "argocd app create composite" not in all_main_bodies


def test_run_all_only_includes_present_tiers():
    """仅业务应用时，run_all.sh 不应引用 infra/ops 脚本。"""
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    run_all = next(s for s in result.scripts if s.relative_path == "run_all.sh")
    assert "30_workloads_business.sh" in run_all.body
    assert "10_app_roots.sh" not in run_all.body
    assert "05_infra_roots.sh" not in run_all.body
    assert "20_workloads_ops.sh" not in run_all.body


def test_main_scripts_do_not_embed_auth_args():
    """P0 回归：主脚本不应嵌入 argocd_args 数组或 --server/--auth-token 命令行。

    认证应在 00_preflight.sh 中通过 `argocd login` 完成；
    重复在每个脚本嵌入会导致死代码（数组未展开使用）或命令噪声。
    """
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    business = next(s for s in result.scripts
                    if s.relative_path == renderer.TIER_FILES[Tier.BUSINESS_APP])
    assert "argocd_args=(" not in business.body, \
        "主脚本不应再嵌入 argocd_args 数组（死代码）"
    assert "--server \"$ARGOCD_SERVER\"" not in business.body, \
        "主脚本中的 argocd app create 不应携带 --server 参数"
    assert "--auth-token \"$ARGOCD_AUTH_TOKEN\"" not in business.body
    # dry-run 副本也应满足同样要求
    assert business.dry_run_body is not None
    assert "argocd_args=(" not in business.dry_run_body


def test_preflight_does_login_with_token():
    """P0 回归：00_preflight.sh 应执行 `argocd login --auth-token`，
    建立全局 session 供后续脚本复用。
    """
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())
    preflight = next(s for s in result.scripts if s.relative_path == "00_preflight.sh")

    assert 'ARGOCD_AUTH_TOKEN:?' in preflight.body, "preflight 仍应强校验 ARGOCD_AUTH_TOKEN"
    assert "argocd login" in preflight.body, "preflight 应执行 argocd login 建立 session"
    assert "--auth-token" in preflight.body
    assert "--grpc-web" in preflight.body
    assert "command -v argocd" in preflight.body
    assert "argocd account get-user-info" in preflight.body


def test_run_all_dry_run_body_uses_dry_run_subscripts():
    """run_all 的 dry_run_body 应仅调用各 tier 的 *.dry-run.sh，不调用真实下发版本。

    preflight 仍走真实 login（dry-run 也需要鉴权连接 argocd 服务器）。
    """
    lms = [_make_lm(BUSINESS_YAML, "biz.yaml"), _make_lm(ROOT_YAML, "root.yaml")]
    result = renderer.render_all(lms, source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=True))

    run_all = next(s for s in result.scripts if s.relative_path == "run_all.sh")
    assert run_all.dry_run_body is not None
    body = run_all.dry_run_body

    # preflight 不变
    assert "bash 00_preflight.sh" in body
    # 应调用 *.dry-run.sh，且不应出现非 dry-run 的 tier 脚本
    assert "bash 30_workloads_business.dry-run.sh" in body
    assert "bash 10_app_roots.dry-run.sh" in body
    # 必须用空格分隔确保只匹配独立的非 dry-run 行
    assert "bash 30_workloads_business.sh\n" not in body
    assert "bash 10_app_roots.sh\n" not in body
    # 提示文案
    assert "dry-run simulated" in body


def test_run_all_no_dry_run_body_when_disabled():
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=False))
    run_all = next(s for s in result.scripts if s.relative_path == "run_all.sh")
    assert run_all.dry_run_body is None


def test_write_run_all_dry_run_lands_on_disk(tmp_path):
    """落盘后应产出 run_all.dry-run.sh 物理文件。"""
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all([lm], source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=True))
    written = renderer.write_results(result, tmp_path)
    names = {p.name for p in written}
    assert "run_all.sh" in names
    assert "run_all.dry-run.sh" in names

    dry = tmp_path / "run_all.dry-run.sh"
    assert dry.exists()
    assert dry.stat().st_mode & 0o100  # 可执行


def test_helm_multisource_emits_create_file_command():
    """多源 Helm 应渲染到 40_workloads_helm.sh，使用 `argocd app create -f`。"""
    lm = _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    helm_scripts = [s for s in result.scripts
                    if s.relative_path == renderer.TIER_FILES[Tier.MULTI_SOURCE_HELM]]
    assert len(helm_scripts) == 1
    body = helm_scripts[0].body
    assert "argocd app create" in body
    assert "-f helm-apps/loki.yaml" in body
    assert "--upsert" in body
    assert 'cd "$(dirname "$0")"' in body, "helm 脚本必须 cd 到自身目录以解析相对 YAML 路径"


def test_helm_multisource_emits_companion_yaml_extra():
    """多源 Helm 应同时输出 helm-apps/<name>.yaml 附属文件，内容含完整 spec.sources。"""
    lm = _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())

    extras = {e.relative_path: e for e in result.extras}
    assert "helm-apps/loki.yaml" in extras
    yaml_body = extras["helm-apps/loki.yaml"].body
    assert "kind: Application" in yaml_body
    assert "sources:" in yaml_body
    assert "$values/loki" in yaml_body
    assert "ref: values" in yaml_body


def test_helm_multisource_dry_run_uses_dry_run_flag():
    lm = _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")
    result = renderer.render_all([lm], source_dir=Path("/in"),
                                 opts=RenderOptions(emit_dry_run=True))
    helm = next(s for s in result.scripts
                if s.relative_path == renderer.TIER_FILES[Tier.MULTI_SOURCE_HELM])
    assert helm.dry_run_body is not None
    assert "--dry-run -o yaml" in helm.dry_run_body
    assert "-f helm-apps/loki.yaml" in helm.dry_run_body


def test_helm_multisource_skipped_from_fallback_path():
    """多源 Helm 不应再被识别为 fallback 项（避免双重创建）。"""
    from argocd_cli_gen import fallback as fb_mod
    lm = _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")
    assert fb_mod.reasons_for(lm) == []


def test_write_results_creates_helm_yaml_files(tmp_path):
    lm = _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())
    written = renderer.write_results(result, tmp_path)

    helm_yaml = tmp_path / "helm-apps" / "loki.yaml"
    assert helm_yaml.exists()
    assert helm_yaml in written
    assert "$values/loki" in helm_yaml.read_text(encoding="utf-8")
    assert (tmp_path / renderer.TIER_FILES[Tier.MULTI_SOURCE_HELM]).exists()


def test_run_all_includes_helm_line_when_helm_apps_present():
    lms = [_make_lm(BUSINESS_YAML, "biz.yaml"), _make_lm(HELM_MULTISOURCE_YAML, "loki.yaml")]
    result = renderer.render_all(lms, source_dir=Path("/in"), opts=RenderOptions())
    run_all = next(s for s in result.scripts if s.relative_path == "run_all.sh")
    assert "bash 40_workloads_helm.sh" in run_all.body
    assert run_all.dry_run_body is not None
    assert "bash 40_workloads_helm.dry-run.sh" in run_all.dry_run_body


def test_run_all_omits_helm_line_when_no_helm_apps():
    lm = _make_lm(BUSINESS_YAML, "biz.yaml")
    result = renderer.render_all([lm], source_dir=Path("/in"), opts=RenderOptions())
    run_all = next(s for s in result.scripts if s.relative_path == "run_all.sh")
    assert "bash 40_workloads_helm.sh" not in run_all.body
    assert "no multi-source helm" in run_all.body


def test_same_run_uses_single_timestamp():
    """P3 回归：同一次 render_all 调用产出的所有脚本应使用同一个时间戳。"""
    import re
    lm = _make_lm(BUSINESS_YAML)
    result = renderer.render_all(
        [lm], source_dir=Path("/in"), opts=RenderOptions(),
        timestamp="2026-05-26T08:00:00Z",
    )
    pattern = re.compile(r"Generated by argocd-cli-gen at (\S+)")
    stamps = set()
    for s in result.scripts:
        m = pattern.search(s.body)
        assert m, f"脚本 {s.relative_path} 缺少 Generated 时间戳"
        stamps.add(m.group(1))
    assert stamps == {"2026-05-26T08:00:00Z"}, \
        f"同一 run 中存在不同时间戳：{stamps}"
