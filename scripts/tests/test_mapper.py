"""mapper.py 单元测试。

每条用例覆盖 mapping.md 中的一个/一组字段。
"""

from __future__ import annotations

import yaml

from argocd_cli_gen import mapper


def _load(text: str) -> dict:
    return yaml.safe_load(text)


def test_safe_app_name_strips_underscore():
    assert mapper.safe_app_name("dly_production_k8s_mas") == "dly-production-k8s-mas"


def test_safe_app_name_keeps_hyphen():
    assert mapper.safe_app_name("prod-mas-user-service") == "prod-mas-user-service"


def test_metadata_flags_full():
    m = _load("""
metadata:
  name: foo_app
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  labels:
    project: dly
    profile: production
    stack: dly3
    app: foo
""")
    flags, warnings, app_name = mapper.map_metadata(m)
    rendered = [f.render() for f in flags]

    assert app_name == "foo-app"
    assert "--app-namespace argocd" in rendered
    assert "--set-finalizer" in rendered
    assert "--label project=dly" in rendered
    assert "--label app=foo" in rendered
    assert warnings == []


def test_metadata_without_finalizer():
    m = _load("""
metadata:
  name: simple
""")
    flags, _, app_name = mapper.map_metadata(m)
    rendered = [f.render() for f in flags]

    assert app_name == "simple"
    assert "--set-finalizer" not in rendered


def test_source_kustomize_basic():
    m = _load("""
spec:
  source:
    repoURL: https://example.com/repo.git
    targetRevision: k8s_mas
    path: foo/overlays/prod
    kustomize:
      version: v4.1.3
""")
    flags, warnings = mapper.map_source(m)
    rendered = [f.render() for f in flags]

    assert "--repo https://example.com/repo.git" in rendered
    assert "--revision k8s_mas" in rendered  # 分支名保留下划线
    assert "--path foo/overlays/prod" in rendered
    assert "--kustomize-version v4.1.3" in rendered
    assert warnings == []


def test_source_kustomize_transformers():
    m = _load("""
spec:
  source:
    repoURL: https://example.com/repo.git
    targetRevision: main
    path: app
    kustomize:
      version: v4.1.3
      namePrefix: stable-
      images:
        - my-app:ghcr.io/myorg/api:v3.0.0
        - second:nginx:1.25
      commonLabels:
        env: stable
      replicas:
        - name: payment-api
          count: 3
      forceCommonLabels: true
""")
    flags, _ = mapper.map_source(m)
    rendered = [f.render() for f in flags]

    assert "--kustomize-nameprefix stable-" in rendered
    assert "--kustomize-image my-app:ghcr.io/myorg/api:v3.0.0" in rendered
    assert "--kustomize-image second:nginx:1.25" in rendered
    assert "--kustomize-common-label env=stable" in rendered
    assert "--kustomize-replicas payment-api=3" in rendered
    assert "--kustomize-force-common-labels" in rendered


def test_source_kustomize_patches_warns():
    m = _load("""
spec:
  source:
    repoURL: r
    path: p
    targetRevision: t
    kustomize:
      patches:
        - target:
            kind: Deployment
          patch: |-
            - op: replace
""")
    _, warnings = mapper.map_source(m)
    assert any(w.path.endswith("patches") for w in warnings)


def test_destination_skips_empty_name():
    m = _load("""
spec:
  destination:
    name: ''
    namespace: prod
    server: https://kubernetes.default.svc
""")
    rendered = [f.render() for f in mapper.map_destination(m)]
    assert "--dest-server https://kubernetes.default.svc" in rendered
    assert "--dest-namespace prod" in rendered
    assert not any(r.startswith("--dest-name ") for r in rendered)


def test_sync_policy_automated_full():
    m = _load("""
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - PruneLast=true
      - CreateNamespace=false
""")
    rendered = [f.render() for f in mapper.map_sync_policy(m)]
    assert "--sync-policy automated" in rendered
    assert "--auto-prune" in rendered
    assert "--self-heal" in rendered
    assert "--sync-option PruneLast=true" in rendered
    assert "--sync-option CreateNamespace=false" in rendered


def test_sync_policy_automated_empty_dict():
    m = _load("""
spec:
  syncPolicy:
    automated: {}
""")
    rendered = [f.render() for f in mapper.map_sync_policy(m)]
    assert "--sync-policy automated" in rendered
    assert "--auto-prune" not in rendered
    assert "--self-heal" not in rendered


def test_sync_policy_retry():
    m = _load("""
spec:
  syncPolicy:
    retry:
      limit: 3
      backoff:
        duration: 10s
        factor: 2
        maxDuration: 2m
""")
    rendered = [f.render() for f in mapper.map_sync_policy(m)]
    assert "--sync-retry-limit 3" in rendered
    assert "--sync-retry-backoff-duration 10s" in rendered
    assert "--sync-retry-backoff-factor 2" in rendered
    assert "--sync-retry-backoff-max-duration 2m" in rendered


def test_e2e_business_app():
    """覆盖 examples.md 示例 1：业务应用最常见模式。"""
    m = _load("""
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
    namespace: 'production'
    server: https://kubernetes.default.svc
  source:
    path: mas-user-service/overlays/production/production
    repoURL: https://github-argocd.hd123.com/qianfanops/toolset_dly.git
    targetRevision: k8s_mas
    kustomize:
      version: v4.1.3
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
""")
    app = mapper.map_single_source(m)
    rendered_cmd = app.render(upsert=True)

    assert app.app_name == "production-mas-user-service"
    assert "argocd app create production-mas-user-service" in rendered_cmd
    assert "--upsert" in rendered_cmd
    assert "--label app=mas-user-service" in rendered_cmd
    assert "--repo https://github-argocd.hd123.com/qianfanops/toolset_dly.git" in rendered_cmd
    assert "--revision k8s_mas" in rendered_cmd
    assert "--path mas-user-service/overlays/production/production" in rendered_cmd
    assert "--kustomize-version v4.1.3" in rendered_cmd
    assert "--dest-server https://kubernetes.default.svc" in rendered_cmd
    assert "--dest-namespace production" in rendered_cmd
    assert "--sync-option PruneLast=true" in rendered_cmd
    assert "--sync-policy automated" not in rendered_cmd  # 业务应用不开 automated
    assert app.warnings == []


def test_e2e_root_app():
    """覆盖 examples.md 示例 3：Root 聚合入口，必含 automated。"""
    m = _load("""
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dly-production-k8s-ops
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    name: ''
    namespace: 'argo-root'
    server: https://kubernetes.default.svc
  source:
    path: argo-apps/dly/production/k8s_ops
    repoURL: https://github-argocd.hd123.com/qianfanops/argoapp.git
    targetRevision: dly_prd
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
    automated:
      prune: true
      selfHeal: true
""")
    app = mapper.map_single_source(m)
    cmd = app.render(upsert=True)
    assert "--sync-policy automated" in cmd
    assert "--auto-prune" in cmd
    assert "--self-heal" in cmd
    assert "--dest-namespace argo-root" in cmd


def test_misc_project():
    m = _load("""
spec:
  project: default
  revisionHistoryLimit: 10
""")
    rendered = [f.render() for f in mapper.map_misc(m)]
    assert "--project default" in rendered
    assert "--revision-history-limit 10" in rendered
