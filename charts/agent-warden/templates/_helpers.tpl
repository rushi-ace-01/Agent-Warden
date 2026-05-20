{{/* Generate a fully qualified image reference for a component. */}}
{{- define "agent-warden.image" -}}
{{- $reg := .root.Values.image.registry | default "" -}}
{{- $tag := .root.Values.image.tag | default .component.image.tag -}}
{{- if $reg -}}
{{ $reg }}/{{ .component.image.repository }}:{{ $tag }}
{{- else -}}
{{ .component.image.repository }}:{{ $tag }}
{{- end -}}
{{- end -}}

{{/* Standard labels applied to every resource. */}}
{{- define "agent-warden.labels" -}}
app.kubernetes.io/name: agent-warden
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* Strict pod security context applied to every Deployment's pod. */}}
{{- define "agent-warden.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "agent-warden.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}
