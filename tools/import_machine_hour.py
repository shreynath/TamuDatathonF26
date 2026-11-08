"""Opt-in Tiger Data ingest from a REAL, authorized machine-hour CSV.

Expected columns: observed_at,machine_id,coin_in_cents,house_win_cents,downtime_minutes
Never invent hourly values from monthly aggregates. Never touch Databricks.
"""
import argparse,csv
from datetime import datetime
from pathlib import Path
from sponsor_hub.storage import TigerData
from sponsor_hub.core import IntegrationError

def load(path:Path):
    if path.stat().st_size > 30_000_000: raise IntegrationError('CSV exceeds import size limit')
    with path.open(newline='',encoding='utf8-sig') as handle:
        reader=csv.DictReader(handle)
        cols=['observed_at','machine_id','coin_in_cents','house_win_cents','downtime_minutes']
        if not reader.fieldnames or any(c not in reader.fieldnames for c in cols):
            raise IntegrationError('Machine-hour CSV missing required columns')
        rows=[]
        for item in reader:
            rows.append({'observed_at':datetime.fromisoformat(item['observed_at']),
              'machine_id':item['machine_id'], 'coin_in_cents':int(item['coin_in_cents']),
              'house_win_cents':int(item['house_win_cents']), 'downtime_minutes':int(item['downtime_minutes'])})
            if len(rows)>50000: raise IntegrationError('Import exceeds 50,000 rows')
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument('csv_path',type=Path)
    p.add_argument('--commit',action='store_true',help='Explicitly create schema and write to Tiger Data')
    a=p.parse_args()
    rows=load(a.csv_path)
    print(f'Validated {len(rows)} actual rows; no inferred or synthetic records')
    if a.commit:
        database=TigerData()
        database.initialize(confirm_write=True)
        for i in range(0,len(rows),10000):database.upsert(rows[i:i+10000],confirm_write=True)
        print(f'Inserted/updated {len(rows)} rows in actual Tiger Data database')
    else:print('Dry-run. Add --commit to write after reviewing data and account permissions.')
if __name__=='__main__':main()
