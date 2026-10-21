-- One row per payment, typed.

with source as (
    select * from {{ source('raw', 'claim_payments') }}
    qualify row_number() over (
        partition by payment_id order by _loaded_at desc, _file_row_number desc
    ) = 1
)

select
    payment_id,
    claim_id,
    try_to_date(payment_date)                    as payment_date,
    try_to_decimal(payment_amount, 18, 2)        as payment_amount,
    payment_type,
    try_to_timestamp_ntz(created_at)             as created_at,
    _loaded_at
from source
