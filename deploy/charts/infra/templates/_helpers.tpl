{{/* External URL of a `*.localhost` host; the port is omitted when publicPort is 80 (K16). */}}
{{- define "infra.externalUrl" -}}
{{- $port := int .root.Values.publicPort -}}
http://{{ .host }}.localhost{{ if ne $port 80 }}:{{ $port }}{{ end }}
{{- end }}

{{- define "infra.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/part-of: dap
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{/* Container securityContext shared by every workload. */}}
{{- define "infra.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: {{ .readOnly }}
capabilities:
  drop: [ALL]
{{- end }}

{{- define "infra.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .uid }}
runAsGroup: {{ .uid }}
fsGroup: {{ .uid }}
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "infra.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .root.Values.secretName }}
      key: {{ .key | default .name }}
{{- end }}
