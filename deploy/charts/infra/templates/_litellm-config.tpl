{{/*
LiteLLM proxy config (K3, K4, K17). Prices are explicit so that spend and budgets work even if a
model is missing from LiteLLM's price map. Source: https://platform.claude.com/docs/en/about-claude/pricing,
read 2026-11-19.
  claude-haiku-5-5:  $0.10 / MTok input, $0.50 / MTok output (prompts up to 100K tokens)
  claude-sonnet-5-5: $2.00 / MTok input, $10.00 / MTok output
*/}}
{{- define "infra.litellmConfig" -}}
model_list:
  - model_name: default
    litellm_params:
      model: anthropic/claude-haiku-5-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info:
      input_cost_per_token: 0.0000001
      output_cost_per_token: 0.0000005
  - model_name: strong
    litellm_params:
      model: anthropic/claude-sonnet-5-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info:
      input_cost_per_token: 0.000002
      output_cost_per_token: 0.00001
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
litellm_settings:
  drop_params: true
  {{- if .Values.litellm.langfuse }}
  # Only when Langfuse keys are present (K5).
  success_callback: ["langfuse"]
  {{- end }}
{{- end }}
