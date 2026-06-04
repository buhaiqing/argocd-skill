"""parser.py 层级判定单测。"""

from __future__ import annotations

import yaml

from argocd_cli_gen import parser
from argocd_cli_gen.parser import Tier


def _detect(text: str) -> tuple[Tier, str]:
    return parser.detect_tier(yaml.safe_load(text))


def test_non_application_is_unknown():
    tier, _ = _detect("""
apiVersion: v1
kind: ConfigMap
""")
    assert tier == Tier.UNKNOWN


def test_multi_source_helm_detected():
    """多源 Helm + $values：chart 源 + ref 源 → MULTI_SOURCE_HELM。

    走 `argocd app create -f` 通道，不再回退 kubectl apply。
    """
    tier, reason = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
spec:
  destination:
    namespace: loki
  sources:
    - repoURL: https://helm-charts.example.com/grafana
      chart: loki
      targetRevision: 6.5.2
      helm:
        valueFiles:
          - $values/loki/values.yaml
    - repoURL: https://github.example.com/values.git
      targetRevision: main
      ref: values
""")
    assert tier == Tier.MULTI_SOURCE_HELM
    assert "helm" in reason


def test_multi_source_non_helm_falls_back():
    """非 Helm 多源（如多个 git path）保留 MULTI_SOURCE → kubectl apply 兜底。"""
    tier, reason = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: composite-app
spec:
  destination:
    namespace: app
  sources:
    - repoURL: https://github.example.com/repo-a.git
      targetRevision: main
      path: components/a
    - repoURL: https://github.example.com/repo-b.git
      targetRevision: main
      path: components/b
""")
    assert tier == Tier.MULTI_SOURCE
    assert "sources" in reason


def test_multi_source_helm_requires_at_least_one_chart():
    """只有 ref 源、缺 chart 源时不算 Helm 多源，应归到 MULTI_SOURCE。"""
    tier, _ = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: only-refs
spec:
  destination:
    namespace: app
  sources:
    - repoURL: https://github.example.com/values-a.git
      ref: values-a
    - repoURL: https://github.example.com/values-b.git
      ref: values-b
""")
    assert tier == Tier.MULTI_SOURCE


def test_root_app_with_finalizers():
    tier, _ = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dly-production-k8s-ops
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: argo-root
  source:
    repoURL: r
    path: p
""")
    assert tier == Tier.ROOT_APP


def test_infra_root_no_finalizers():
    """projects.yaml/repos.yaml 等基础设施层 root。"""
    tier, reason = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: projects
spec:
  destination:
    namespace: argo-root
  source:
    repoURL: r
    path: p
  syncPolicy:
    automated: {}
""")
    assert tier == Tier.INFRA_ROOT
    assert "no finalizers" in reason


def test_ops_app_by_revision():
    tier, _ = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: ops
  source:
    repoURL: r
    targetRevision: k8s_ops
    path: prometheus/overlays/prd
""")
    assert tier == Tier.OPS_APP


def test_ops_app_by_namespace():
    """没有 k8s_ops revision 但 namespace=kube-system 也应被识别为运维。"""
    tier, _ = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-event-exporter
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: kube-system
  source:
    repoURL: r
    targetRevision: main
    path: p
""")
    assert tier == Tier.OPS_APP


def test_business_app_default():
    tier, _ = _detect("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-mas-user-service
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    project: dly
spec:
  destination:
    namespace: production
  source:
    repoURL: r
    targetRevision: k8s_mas
    path: mas-user-service/overlays/production/production
""")
    assert tier == Tier.BUSINESS_APP


def test_load_directory_against_argoapp(tmp_path):
    """用临时目录验证 load_directory 跳过非 Application YAML。"""
    (tmp_path / "app.yaml").write_text("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: foo
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: prod
  source:
    repoURL: r
    targetRevision: main
    path: p
""")
    (tmp_path / "configmap.yaml").write_text("""
apiVersion: v1
kind: ConfigMap
metadata:
  name: c
""")
    loaded = parser.load_directory(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].tier == Tier.BUSINESS_APP
    assert loaded[0].name == "foo"
