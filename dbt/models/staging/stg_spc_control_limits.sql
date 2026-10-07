select
    limit_id,
    source,
    scope,
    chamber_id,
    tool_id,
    parameter_id,
    route_step_id,
    is_multivariate,
    version as limit_version,
    center,
    sigma,
    t2_dims,
    t2_limit,
    n_baseline,
    baseline_start as baseline_start_at,
    baseline_end as baseline_end_at
from {{ source('waferlens', 'spc_control_limits') }}
