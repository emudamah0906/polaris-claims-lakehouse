-- One row per customer, no direct PII, with how many policies they hold.

with policy_counts as (
    select
        customer_id,
        count(*)                                  as policy_count,
        count_if(status = 'ACTIVE')               as active_policy_count
    from {{ ref('stg_policies') }}
    group by customer_id
)

select
    c.customer_id,
    c.birth_year,
    c.city,
    c.province,
    c.postal_fsa,
    c.customer_since,
    coalesce(p.policy_count, 0)                   as policy_count,
    coalesce(p.active_policy_count, 0)            as active_policy_count
from {{ ref('stg_customers') }} c
left join policy_counts p using (customer_id)
