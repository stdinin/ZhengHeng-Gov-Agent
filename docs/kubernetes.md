# Minimal Kubernetes / Helm Profile

The V1.1 chart under `deploy/helm/zhengheng` is intentionally minimal. It
creates an Orchestrator Deployment and ClusterIP Service, a Pi Runtime
Deployment and ClusterIP Service, three fixed Department Agent Deployments and
ClusterIP Services, ConfigMap-based non-secret configuration, and CPU HPAs.
It does not claim to provision or emulate MongoDB, Redis, OpenSearch, Milvus,
or a production secret manager.

## Required secret

Create the referenced secret before installing the chart. Never commit real
values.

```powershell
kubectl create secret generic zhengheng-secrets `
  --from-literal=appSecret='<generate-outside-source-control>' `
  --from-literal=internalServiceToken='<generate-outside-source-control>'
```

The chart references only `appSecret` and `internalServiceToken`; it does not
embed secret values in `values.yaml`, ConfigMaps, rendered artifacts, or logs.

## Static validation

On this Windows host Helm is executed through its official container image, so
the host does not need a global Helm install:

```powershell
docker run --rm -v "${PWD}:/work" -w /work alpine/helm:3.16.3 `
  lint deploy/helm/zhengheng
docker run --rm -v "${PWD}:/work" -w /work alpine/helm:3.16.3 `
  template zhengheng deploy/helm/zhengheng -f deploy/helm/zhengheng/values-kind.yaml
```

The template supplies liveness/readiness probes and resource requests required
by `autoscaling/v2` CPU HPAs. `milvusCollection` defaults to an empty value so
the application derives the model/version-bound BGE-M3 collection name rather
than looking for a non-existent fixed `policy_chunks` collection.

## Kind procedure

When `kind`, `kubectl`, a local metrics server, and sufficient Docker resources
are available, use the provided configuration:

```powershell
kind create cluster --config deploy/kind/kind-config.yaml
kind load docker-image zhengheng-backend:v1.1 zhengheng-pi-runtime:v1.1
helm upgrade --install zhengheng deploy/helm/zhengheng -f deploy/helm/zhengheng/values-kind.yaml
kubectl get pods,svc,hpa
```

Then run a multi-agent smoke request from the Orchestrator pod and deliberately
delete one Department Agent pod to validate partial-response isolation and
Deployment recovery. Actual Kind, pod-failure, and runtime HPA checks remain
deferred until that local cluster and its external infrastructure endpoints are
available; static Helm validation is not represented as a passed Kind test.
