{{- define "zhengheng.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "zhengheng.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "zhengheng.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "zhengheng.labels" -}}
app.kubernetes.io/name: {{ include "zhengheng.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "zhengheng.agentName" -}}
{{- printf "%s-%s" (include "zhengheng.fullname" .root) .agent.id | lower | trunc 63 | trimSuffix "-" }}
{{- end }}
