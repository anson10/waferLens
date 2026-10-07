select
    wafer_id,
    pattern as predicted_pattern,
    confidence,
    auto_accept,
    prediction_set,
    alpha,
    model as classifier,
    scored_at
from {{ source('waferlens', 'wafer_patterns') }}
