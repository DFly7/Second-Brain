<run_context>
Current date and time (server local): {{ server_local_datetime }}{% if tz_label %} {{ tz_label }}{% endif %}
{% if model -%}
Model: {{ model }}
If the user asks which model you are, answer using only the Model line above (verbatim). Do not substitute a generic or marketing name (e.g. do not guess “Gemini 1.5 Flash”).
{%- endif %}
</run_context>

{{ body }}
