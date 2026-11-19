{{/* External URL of a `*.localhost` host; the port is omitted when publicPort is 80 (K16). */}}
{{- define "platform.externalUrl" -}}
{{- $port := int .root.Values.publicPort -}}
http://{{ .host }}.localhost{{ if ne $port 80 }}:{{ $port }}{{ end }}
{{- end }}

{{- define "platform.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/part-of: dap
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{- define "platform.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end }}

{{/* Container securityContext shared by every workload (as in the infra chart). */}}
{{- define "platform.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end }}

{{/* uid 10001 is the `app` user of backend/Dockerfile. */}}
{{- define "platform.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/*
Non-secret settings of every backend process (names owned by backend/dap/settings.py). Shared by
the platform ConfigMap (api, worker) and the bootstrap Job's hook ConfigMap.
*/}}
{{- define "platform.config" -}}
POSTGRES_HOST: postgres
POSTGRES_PORT: "5432"
POSTGRES_USER: postgres
DAP_DB_NAME: dap
DATASETS_DB_NAME: datasets
REDIS_HOST: redis
REDIS_PORT: "6379"
RABBITMQ_HOST: rabbitmq
RABBITMQ_PORT: "5672"
RABBITMQ_USER: dap
# Tokens carry the external issuer; the keys are fetched inside the cluster (design §7).
OIDC_ISSUER: {{ include "platform.externalUrl" (dict "root" . "host" "auth") }}/realms/dap
OIDC_JWKS_URL: http://keycloak.{{ .Release.Namespace }}.svc:8080/realms/dap/protocol/openid-connect/certs
LLM_PROVIDER: {{ .Values.llm.provider | quote }}
LLM_BASE_URL: {{ .Values.litellm.url | quote }}
LLM_MODEL: {{ .Values.llm.model | quote }}
FAKE_STEP_DELAY_S: {{ .Values.llm.fakeStepDelayS | quote }}
LITELLM_TEAM_MAX_BUDGET_USD: {{ .Values.litellm.teamMaxBudgetUsd | quote }}
{{- end }}

{{/* Secret settings, from the Secret that scripts/secrets.sh creates. */}}
{{- define "platform.secretEnv" -}}
{{- range list "POSTGRES_PASSWORD" "DS_SALES_RO_PASSWORD" "DS_HR_RO_PASSWORD" "RABBITMQ_PASSWORD" "DAP_FERNET_KEY" "LITELLM_MASTER_KEY" "LANGFUSE_PUBLIC_KEY" "LANGFUSE_SECRET_KEY" "LANGFUSE_HOST" }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ $.Values.secretName }}
      key: {{ . }}
{{- end }}
{{- end }}
