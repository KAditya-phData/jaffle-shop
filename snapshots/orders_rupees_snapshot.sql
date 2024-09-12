{% snapshot orders_snapshot %}

{{
    config(
      unique_key='order_id',
      target_schema='snapshots', 
      strategy='check',
      check_cols=['*'],
    )
}}

select * from {{ ref('orders') }}

{% endsnapshot %}