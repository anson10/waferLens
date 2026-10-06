# import pandas as pd
# lots = pd.read_csv('data/lots.csv')
# wafers = pd.read_csv('data/wafers.csv')
# print('Lots:')
# print(lots[['lot_id', 'product', 'technology_node', 'status']].head())
# print('\nWafer status distribution:')
# print(wafers['status'].value_counts())
# print('\nWafer numbers per lot:', wafers.groupby('lot_id')['wafer_number'].count().unique())


# drift verification

# import pandas as pd

# df = pd.read_csv('data/measurements.csv')

# etch = df[df['parameter'] == 'etch_rate_nm_s'].reset_index(drop=True)
# n = len(etch)

# early = etch.head(50)['value'].mean()
# late = etch.tail(50)['value'].mean()
# print(f'Etch rate — early wafers: {early:.3f} late wafers: {late:.3f}')
# print(f'Decay: {early - late:.3f} nm/s (should be positive — rate decreases over time)')

# cmp = df[df['parameter'] == 'thickness_post_cmp_nm'].reset_index(drop=True)
# early_c = cmp.head(50)['value'].mean()
# late_c = cmp.tail(50)['value'].mean()
# print(f'CMP thickness — early: {early_c:.2f} late: {late_c:.2f}')
# print(f'Growth: {late_c - early_c:.2f} nm (should be positive — pad wear leaves more material)')


# verify yield model
# import pandas as pd
# yr = pd.read_csv('data/yield_records.csv')
# wafers = pd.read_csv('data/wafers.csv')
# merged = yr.merge(wafers, on='wafer_id')
# print('Yield by status:')
# print(merged.groupby('status')['yield_pct'].describe().round(2))
# print()
# print('Scrap wafers yield == 0:')
# print(merged[merged['status']=='scrap']['yield_pct'].unique())

# db populated verification
from db.session import get_session
from sqlalchemy import text
with get_session() as s: 
    for table in ['lots','wafers','process_steps','measurements','yield_records','spc_flags']: n = s.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar() 
    print(f' {table}: {n} rows')