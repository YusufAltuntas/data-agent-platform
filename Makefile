SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help lint test frontend-check up down helm-lint smoke

# Every kubectl/helm call names the context explicitly, so nothing can act on another cluster.
CLUSTER := dap
KUBE_CONTEXT := kind-$(CLUSTER)
NAMESPACE := dap
KUBECTL := kubectl --context $(KUBE_CONTEXT)
HELM := helm --kube-context $(KUBE_CONTEXT)
HELM_WAIT := --wait --timeout 10m --rollback-on-failure
# Our charts are the source of truth: server-side apply that takes over fields changed by hand
# (e.g. with kubectl) instead of failing on the field-manager conflict.
HELM_APPLY := --server-side true --force-conflicts

BACKEND_IMAGE := dap-backend:dev
# Content-derived tag (12 hex digits of the image id), as a shell substitution evaluated when the
# recipe line runs: an unchanged image keeps its tag (no restart), a rebuilt one rolls the pods.
BACKEND_TAG = $$(docker image inspect -f '{{.Id}}' $(BACKEND_IMAGE) | cut -c8-19)
FRONTEND_IMAGE := dap-frontend:dev
FRONTEND_TAG = $$(docker image inspect -f '{{.Id}}' $(FRONTEND_IMAGE) | cut -c8-19)
TRAEFIK_CHART := traefik --repo https://traefik.github.io/charts --version 42.4.1
PROMETHEUS_CHART := prometheus --repo https://prometheus-community.github.io/helm-charts --version 29.47.2
GRAFANA_CHART := grafana --repo https://grafana-community.github.io/helm-charts --version 14.5.0

# Not secret: every external address derives from it (K16). Default 80.
PUBLIC_PORT ?= $(or $(shell sed -n 's/^PUBLIC_PORT=//p' .env 2>/dev/null | tr -dc 0-9),80)
# The LiteLLM Langfuse callback is configured only when both keys are set in .env (K5). A value
# may be quoted; scripts/secrets.sh strips the quotes.
LANGFUSE = $(shell grep -qE "^LANGFUSE_PUBLIC_KEY=[\"']?[^[:space:]\"']" .env 2>/dev/null \
	&& grep -qE "^LANGFUSE_SECRET_KEY=[\"']?[^[:space:]\"']" .env && echo true || echo false)
# Not secret. The web UI's link to Langfuse; the default is Langfuse Cloud, as in the SDK.
LANGFUSE_HOST = $(or $(shell sed -n 's/^LANGFUSE_HOST=//p' .env 2>/dev/null | tail -n 1 | tr -d "\r\"'"),https://cloud.langfuse.com)

INFRA_FLAGS = --set publicPort=$(PUBLIC_PORT) --set litellm.langfuse=$(LANGFUSE) \
	--set-file keycloak.realm=deploy/keycloak/realm-export.json

# K22: the fake model unless `make up REAL_LLM=1` is given on the command line; an exported
# REAL_LLM in the environment is ignored, so the real model cannot be switched on by accident.
LLM_PROVIDER = $(if $(and $(filter command line,$(origin REAL_LLM)),$(filter 1,$(REAL_LLM))),openai_compatible,fake)
PLATFORM_FLAGS = --set publicPort=$(PUBLIC_PORT) --set llm.provider=$(LLM_PROVIDER) \
	$(if $(filter true,$(LANGFUSE)),--set frontend.langfuseBaseUrl=$(LANGFUSE_HOST))
# Grafana's own links and redirects need its external address (K16).
GRAFANA_URL = http://grafana.localhost$(if $(filter 80,$(PUBLIC_PORT)),,:$(PUBLIC_PORT))

# $(call lint-chart,<chart>,<flags>): helm lint plus kubeconform on the rendered manifests.
define lint-chart
helm lint --strict deploy/charts/$(1) $(2)
helm template $(1) deploy/charts/$(1) -n $(NAMESPACE) $(2) \
	| kubeconform -strict -summary -ignore-missing-schemas
endef

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

lint: ## Run ruff (lint + format check) and mypy (strict)
	cd backend && uv run ruff check . ../eval
	cd backend && uv run ruff format --check . ../eval
	cd backend && uv run mypy

test: ## Run unit and integration tests
	cd backend && uv run pytest
	cd backend && uv run pytest -q ../eval

frontend-check: ## Lint, type-check, test and build the frontend (after npm ci in frontend/)
	cd frontend && npm run --silent lint
	cd frontend && npm run --silent typecheck
	cd frontend && npm run --silent test
	cd frontend && npm run --silent build

up: ## Create the kind cluster (if missing) and deploy everything; re-runnable
	@# 1. kind cluster, with Traefik's NodePort mapped to PUBLIC_PORT on the host
	if kind get clusters 2>/dev/null | grep -qx $(CLUSTER); then \
		echo "kind cluster $(CLUSTER) exists"; \
	else \
		sed 's/hostPort: 80$$/hostPort: $(PUBLIC_PORT)/' deploy/kind/kind-config.yaml \
			| kind create cluster --name $(CLUSTER) --config=-; \
	fi
	docker build -t $(BACKEND_IMAGE) backend
	docker tag $(BACKEND_IMAGE) dap-backend:$(BACKEND_TAG)
	kind load docker-image dap-backend:$(BACKEND_TAG) --name $(CLUSTER)
	docker build -t $(FRONTEND_IMAGE) frontend
	docker tag $(FRONTEND_IMAGE) dap-frontend:$(FRONTEND_TAG)
	kind load docker-image dap-frontend:$(FRONTEND_TAG) --name $(CLUSTER)
	@# 2. Traefik
	$(HELM) upgrade --install traefik $(TRAEFIK_CHART) -n traefik --create-namespace \
		-f deploy/values/traefik.yaml $(HELM_WAIT)
	@# 3. Secrets from .env
	scripts/secrets.sh
	@# 4. infra chart
	$(HELM) upgrade --install infra deploy/charts/infra -n $(NAMESPACE) $(INFRA_FLAGS) $(HELM_APPLY) $(HELM_WAIT)
	@# 5. platform chart; its bootstrap Job (pre-install/pre-upgrade hook) runs first
	$(HELM) upgrade --install platform deploy/charts/platform -n $(NAMESPACE) $(PLATFORM_FLAGS) \
		--set image.tag=$(BACKEND_TAG) --set frontend.image.tag=$(FRONTEND_TAG) \
		$(HELM_APPLY) $(HELM_WAIT)
	@# 6. Prometheus and Grafana; the dashboard ConfigMap comes with the platform chart
	$(HELM) upgrade --install prometheus $(PROMETHEUS_CHART) -n $(NAMESPACE) \
		-f deploy/values/prometheus.yaml $(HELM_APPLY) $(HELM_WAIT)
	$(HELM) upgrade --install grafana $(GRAFANA_CHART) -n $(NAMESPACE) \
		-f deploy/values/grafana.yaml --set 'grafana\.ini.server.root_url=$(GRAFANA_URL)' \
		$(HELM_APPLY) $(HELM_WAIT)
	$(KUBECTL) get pods -A

down: ## Delete the kind cluster (only the dap cluster)
	kind delete cluster --name $(CLUSTER)

smoke: ## End-to-end checks against the running cluster (always the fake model, K22)
	PUBLIC_PORT=$(PUBLIC_PORT) scripts/smoke.sh

.PHONY: eval
SET ?= gold
eval: ## Evaluation on the running cluster (real model, costs money; after make up REAL_LLM=1); SET=hard for the hard set
	cd backend && PUBLIC_PORT=$(PUBLIC_PORT) uv run python ../eval/run_eval.py $(SET)

helm-lint: ## helm lint + kubeconform for every chart
	$(call lint-chart,infra,$(INFRA_FLAGS))
	$(call lint-chart,platform,$(PLATFORM_FLAGS))

.PHONY: ci
ci: lint test frontend-check helm-lint ## The CI checks that need no cluster (python, frontend, helm jobs)
