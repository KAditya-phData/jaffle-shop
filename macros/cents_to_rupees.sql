{% macro cents_to_rupees(column_name) -%}
    {{ return(adapter.dispatch('cents_to_rupees')(column_name)) }}
{%- endmacro %}

{% macro default__cents_to_rupees(column_name) -%}
    ({{ column_name }} / 100 * 83.96)::numeric(16, 2)
{%- endmacro %}

{% macro postgres__cents_to_rupees(column_name) -%}
    ({{ column_name }}::numeric(16, 2) / 100 * 83.96)
{%- endmacro %}

{% macro bigquery__cents_to_rupees(column_name) %}
    round(cast(({{ column_name }} / 100 * 83.96) as numeric), 2)
{% endmacro %}
