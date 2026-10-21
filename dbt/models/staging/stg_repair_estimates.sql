-- One row per repair estimate from the body-shop vendor, typed.

with source as (
    select * from {{ source('raw', 'repair_estimates') }}
    qualify row_number() over (
        partition by estimate_id order by _loaded_at desc, _file_row_number desc
    ) = 1
)

select
    estimate_id,
    claim_id,
    shop_id,
    try_to_date(estimate_date)                   as estimate_date,
    try_to_decimal(parts_amount, 18, 2)          as parts_amount,
    try_to_decimal(labour_amount, 18, 2)         as labour_amount,
    try_to_decimal(total_amount, 18, 2)          as total_amount,
    currency,
    try_to_date(vendor_ingest_date)              as vendor_ingest_date,
    _loaded_at
from source
