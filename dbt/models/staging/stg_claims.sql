-- One row per claim, typed.
-- Money is DECIMAL(18,2), never FLOAT: a float can't hold 0.10 exactly, and
-- finance totals have to match to the cent.

with source as (
    select * from {{ source('raw', 'claims') }}
    qualify row_number() over (
        partition by claim_id order by _loaded_at desc, _file_row_number desc
    ) = 1
)

select
    claim_id,
    claim_number,
    policy_id,
    customer_id,
    product_type,
    claim_type,
    try_to_date(loss_date)                       as loss_date,
    try_to_date(report_date)                     as report_date,
    try_to_decimal(claim_amount, 18, 2)          as claim_amount,
    status,
    try_to_boolean(is_fraud)                     as is_fraud,      -- 'True' / 'False' in the CSV
    try_to_decimal(fraud_score, 5, 3)            as fraud_score,
    adjuster_id,
    try_to_timestamp_ntz(created_at)             as created_at,
    try_to_timestamp_ntz(updated_at)             as updated_at,
    _loaded_at
from source
