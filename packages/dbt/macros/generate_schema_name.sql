{% macro generate_schema_name(custom_schema_name, node) -%}
    {#
      The application security boundary is hard-coded to staging/marts:
      migrations revoke direct app access to marts and expose tenant-filtered
      copilot views over it. dbt's default would prefix the profile schema
      (analytics_marts), silently leaving those views empty.
    #}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
