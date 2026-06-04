"""fallback.py + report.py 联合测试。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from argocd_cli_gen import fallback, parser, report, renderer
from argocd_cli_gen.parser import LoadedManifest, Tier
from argocd_cli_gen.renderer import RenderOptions


MULTI_SOURCE_HELM_YAML = """
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
  syncPolicy:
    syncOptions:
      - PruneLast=true
"""

MULTI_SOURCE_NON_HELM_YAML = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: composite-app
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

BUSINESS_YAML = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: foo
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: production
    server: https://kubernetes.default.svc
  source:
    repoURL: r
    targetRevision: main
    path: p
  project: default
"""


def _lm(text: str, fname: str = "x.yaml") -> LoadedManifest:
    m = yaml.safe_load(text)
    tier, reason = parser.detect_tier(m)
    return LoadedManifest(path=Path(fname), manifest=m, tier=tier, reason=reason)


def test_fallback_does_not_collect_helm_multisource():
    """多源 Helm 由 renderer 走 `argocd app create -f` 处理，不进 fallback。"""
    lms = [_lm(BUSINESS_YAML, "biz.yaml"), _lm(MULTI_SOURCE_HELM_YAML, "loki.yaml")]
    bundle = fallback.collect(lms)
    assert bundle.entries == []
    assert bundle.yaml_body == ""


def test_fallback_collects_non_helm_multi_source():
    """非 Helm 多源（多 git path）仍走 kubectl apply 兜底。"""
    lms = [
        _lm(BUSINESS_YAML, "biz.yaml"),
        _lm(MULTI_SOURCE_NON_HELM_YAML, "composite.yaml"),
    ]
    bundle = fallback.collect(lms)
    assert len(bundle.entries) == 1
    assert bundle.entries[0].name == "composite-app"
    assert bundle.entries[0].reason == "multi_source"
    assert "kind: Application" in bundle.yaml_body
    assert "composite-app" in bundle.yaml_body


def test_fallback_empty_when_no_multi_source():
    lms = [_lm(BUSINESS_YAML, "biz.yaml")]
    bundle = fallback.collect(lms)
    assert bundle.entries == []
    assert bundle.yaml_body == ""


def test_fallback_collects_patches():
    yaml_text = """
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-svc
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
      patches:
        - target:
            kind: Deployment
          patch: |-
            - op: replace
"""
    lms = [_lm(yaml_text, "payment.yaml")]
    bundle = fallback.collect(lms)
    assert len(bundle.entries) == 1
    assert "kustomize.patches" in bundle.entries[0].fields


def test_write_fallback_creates_file(tmp_path):
    lms = [_lm(MULTI_SOURCE_NON_HELM_YAML, "composite.yaml")]
    bundle = fallback.collect(lms)
    out = fallback.write_fallback(bundle, tmp_path)
    assert out is not None
    assert out.exists()
    assert "kubectl" in out.read_text()


def test_report_includes_warnings(tmp_path):
    lms = [
        _lm(BUSINESS_YAML, "biz.yaml"),
        _lm(MULTI_SOURCE_NON_HELM_YAML, "composite.yaml"),
    ]
    result = renderer.render_all(lms, source_dir=tmp_path, opts=RenderOptions())
    bundle = fallback.collect(lms)

    rep = report.build(lms, result.mapped_by_tier, bundle,
                       input_dir=tmp_path, output_dir=tmp_path)

    assert rep.total == 2
    assert rep.fallback_to_yaml == 1
    assert rep.converted == 1
    assert any(w.reason == "multi_source" for w in rep.warnings)


def test_report_helm_multisource_counted_as_converted(tmp_path):
    """多源 Helm 走 argocd app create -f，应算入 converted 且不进 fallback。"""
    lms = [_lm(BUSINESS_YAML, "biz.yaml"), _lm(MULTI_SOURCE_HELM_YAML, "loki.yaml")]
    result = renderer.render_all(lms, source_dir=tmp_path, opts=RenderOptions())
    bundle = fallback.collect(lms)

    rep = report.build(lms, result.mapped_by_tier, bundle,
                       input_dir=tmp_path, output_dir=tmp_path)

    assert rep.total == 2
    assert rep.fallback_to_yaml == 0
    assert rep.converted == 2
    assert rep.helm_multisource == 1
    assert rep.by_tier.get("multi_source_helm") == 1
    assert all(w.reason != "multi_source" for w in rep.warnings)


def test_report_writes_json_and_md(tmp_path):
    lms = [_lm(BUSINESS_YAML, "biz.yaml")]
    result = renderer.render_all(lms, source_dir=tmp_path, opts=RenderOptions())
    bundle = fallback.collect(lms)
    rep = report.build(lms, result.mapped_by_tier, bundle,
                       input_dir=tmp_path, output_dir=tmp_path)

    json_path, md_path = report.write_report(rep, tmp_path)

    data = json.loads(json_path.read_text())
    assert data["total"] == 1
    assert data["converted"] == 1

    md = md_path.read_text()
    assert "转换报告" in md
    assert "## 按层级分布" in md
