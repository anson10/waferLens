select
    recipe_id,
    route_step_id,
    name as recipe_name,
    version as recipe_version,
    effective_from as effective_from_at
from {{ source('waferlens', 'recipes') }}
