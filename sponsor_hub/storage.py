"""Real optional Tiger Data and MongoDB Atlas integrations. No Databricks references."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from .core import IntegrationError, required_env

TIGER_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    """CREATE TABLE IF NOT EXISTS pitboss_machine_hour (
    observed_at TIMESTAMPTZ NOT NULL,
    machine_id TEXT NOT NULL,
    coin_in_cents BIGINT NOT NULL CHECK (coin_in_cents >= 0),
    house_win_cents BIGINT NOT NULL,
    downtime_minutes INTEGER NOT NULL CHECK (downtime_minutes BETWEEN 0 AND 60),
    PRIMARY KEY (observed_at, machine_id)
)""",
    "SELECT create_hypertable('pitboss_machine_hour', by_range('observed_at'), if_not_exists => TRUE)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS pitboss_machine_day
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', observed_at) AS day,
       machine_id,
       SUM(coin_in_cents) AS coin_in_cents,
       SUM(house_win_cents) AS house_win_cents,
       SUM(downtime_minutes) AS downtime_minutes
FROM pitboss_machine_hour
GROUP BY 1, 2
WITH NO DATA""",
    """SELECT add_continuous_aggregate_policy(
    'pitboss_machine_day',
    start_offset => INTERVAL '30 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE)""",
)
TIGER_SCHEMA = ";\n".join(TIGER_STATEMENTS) + ";"

class TigerData:
    def __init__(self, conn_factory=None):
        self._factory = conn_factory
    def _connection(self):
        if self._factory: return self._factory()
        try: import psycopg
        except ImportError: raise IntegrationError("Install the optional psycopg[binary] dependency") from None
        return psycopg.connect(required_env("TIGER_DATABASE_URL"), connect_timeout=7)
    def initialize(self, *, confirm_write=False):
        if not confirm_write: raise IntegrationError("Schema changes require explicit confirmation")
        with self._connection() as conn:
            with conn.cursor() as cur:
                for statement in TIGER_STATEMENTS:
                    cur.execute(statement)
    def upsert(self, records:list[dict], *, confirm_write=False):
        if not confirm_write: raise IntegrationError("Write operation requires explicit confirmation")
        if len(records)>10000: raise IntegrationError("Batch too large")
        rows=[]
        for r in records:
            if not isinstance(r["observed_at"],datetime) or r["observed_at"].tzinfo is None: raise IntegrationError("Timestamp must include timezone")
            if not isinstance(r["machine_id"],str) or not (1<=len(r["machine_id"])<=64): raise IntegrationError("Invalid machine ID")
            if not isinstance(r["coin_in_cents"],int) or r["coin_in_cents"]<0: raise IntegrationError("Invalid coin in")
            if not isinstance(r["house_win_cents"],int): raise IntegrationError("Invalid house win")
            if not isinstance(r["downtime_minutes"],int) or not 0<=r["downtime_minutes"]<=60: raise IntegrationError("Invalid downtime")
            rows.append((r["observed_at"],r["machine_id"],r["coin_in_cents"],r["house_win_cents"],r["downtime_minutes"]))
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO pitboss_machine_hour (observed_at,machine_id,coin_in_cents,house_win_cents,downtime_minutes)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT (observed_at,machine_id) DO UPDATE SET
                    coin_in_cents=EXCLUDED.coin_in_cents,house_win_cents=EXCLUDED.house_win_cents,downtime_minutes=EXCLUDED.downtime_minutes""",rows)
        return len(rows)
    def daily(self,start:datetime,end:datetime) -> list[dict]:
        if start.tzinfo is None or end.tzinfo is None or start>=end or end-start>timedelta(days=400): raise IntegrationError("Invalid interval")
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT time_bucket('1 day',observed_at) AS day,
                   SUM(coin_in_cents),SUM(house_win_cents),SUM(downtime_minutes)
                   FROM pitboss_machine_hour WHERE observed_at >= %s AND observed_at < %s
                   GROUP BY 1 ORDER BY 1""",(start,end))
                return [{"day":r[0].isoformat(),"coin_in_cents":int(r[1]),
                         "house_win_cents":int(r[2]),"downtime_minutes":int(r[3])} for r in cur.fetchall()]
    def daily_aggregate(self, start:datetime, end:datetime) -> list[dict]:
        """Read the continuous aggregate. Same bounds as daily(), different relation."""
        if start.tzinfo is None or end.tzinfo is None or start>=end or end-start>timedelta(days=400):
            raise IntegrationError("Invalid interval")
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT day, SUM(coin_in_cents), SUM(house_win_cents), SUM(downtime_minutes)
                   FROM pitboss_machine_day WHERE day >= %s AND day < %s
                   GROUP BY 1 ORDER BY 1""", (start, end))
                return [{"day":r[0].isoformat(),"coin_in_cents":int(r[1]),
                         "house_win_cents":int(r[2]),"downtime_minutes":int(r[3]),
                         "source":"pitboss_machine_day"} for r in cur.fetchall()]

class AtlasEvidence:
    def __init__(self, client=None):
        if client is None:
            try: from pymongo import MongoClient
            except ImportError: raise IntegrationError("Install optional pymongo[srv] dependency") from None
            client = MongoClient(required_env("MONGODB_ATLAS_URI"),serverSelectionTimeoutMS=7000)
        self.collection = client["pitboss"]["investigations"]
    def ensure_indexes(self, *, confirm_write=False):
        if not confirm_write: raise IntegrationError("Index change requires explicit confirmation")
        self.collection.create_index("created_at")
        self.collection.create_index("sources")

    def save(self, record:dict, *, confirm_write=False)->str:
        if not confirm_write: raise IntegrationError("Evidence save requires explicit confirmation")
        if not isinstance(record.get("answer"),str) or len(record["answer"])>4000: raise IntegrationError("Invalid answer")
        sources=record.get("sources")
        if not isinstance(sources,list) or not sources or not all(isinstance(x,str) and len(x)<128 for x in sources): raise IntegrationError("Evidence references required")
        doc={"answer":record["answer"],"sources":sources,"period":str(record.get("period", ""))[:64],
             "created_at":datetime.now(timezone.utc),"schema_version":1}
        result=self.collection.insert_one(doc)
        return str(result.inserted_id)
    def latest(self,limit:int=10)->list[dict]:
        if not isinstance(limit,int) or not 1<=limit<=50: raise IntegrationError("Invalid limit")
        cursor=self.collection.find({}, {"_id":0,"answer":1,"sources":1,"period":1,"created_at":1}).sort("created_at",-1).limit(limit)
        return list(cursor)
