{#
  dbt's default glues the target schema onto the custom one (STAGING becomes
  DBT_X_STAGING), which would need a CREATE SCHEMA the dbt role doesn't have.
  Here +schema: staging means exactly POLARIS.STAGING, the schema Terraform made.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
