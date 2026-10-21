-- One row per policy, typed. TRY_ casts return NULL instead of failing, and
-- the not_null tests in _staging.yml catch any value that didn't cast.

with source as (
    select * from {{ source('raw', 'policies') }}
    qualify row_number() over (
        partition by policy_id order by _loaded_at desc, _file_row_number desc
    ) = 1
)

select
    policy_id,
    customer_id,
    product_type,
    try_to_date(effective_date)                  as effective_date,
    try_to_date(expiry_date)                     as expiry_date,
    try_to_decimal(annual_premium, 18, 2)        as annual_premium,
    try_to_decimal(coverage_limit, 18, 2)        as coverage_limit,
    status,
    try_to_timestamp_ntz(created_at)             as created_at,
    try_to_timestamp_ntz(updated_at)             as updated_at,
    _loaded_at
from source
