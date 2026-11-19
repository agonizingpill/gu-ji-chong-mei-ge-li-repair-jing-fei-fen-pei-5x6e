from sqlalchemy import inspect,text
from .database import engine
COLUMNS={'provenance':'JSON','evidence_status':"VARCHAR(20) DEFAULT 'pending'",'evidence_file':"VARCHAR(80) DEFAULT ''",'evidence_sha256':"VARCHAR(64) DEFAULT ''",'evidence_note':"VARCHAR(200) DEFAULT ''"}

def migrate():
    """create_all 不会给既有表补列；旧库的等级记录需照常可读。"""
    inspector=inspect(engine)
    if 'risk_assessments' not in inspector.get_table_names():return
    existing={c['name'] for c in inspector.get_columns('risk_assessments')}
    missing={k:v for k,v in COLUMNS.items() if k not in existing}
    if not missing:return
    with engine.begin() as conn:
        for name,ddl in missing.items():conn.execute(text(f'ALTER TABLE risk_assessments ADD COLUMN {name} {ddl}'))
        # 旧单只存了等级：登记缺证，不伪造当时测量或阈值。
        conn.execute(text("UPDATE risk_assessments SET evidence_status='missing', evidence_note='历史记录仅存预测等级，无当时测量与阈值快照' WHERE provenance IS NULL AND status IN ('done','reviewed') AND (evidence_note IS NULL OR evidence_note='')"))
