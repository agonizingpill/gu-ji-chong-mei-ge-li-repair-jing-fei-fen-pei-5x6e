import time,logging
from pathlib import Path
from .database import Session
from .models import RiskAssessment,Observation
from .risk_service import queue
from .evidence_service import snapshot,archive
logging.basicConfig(level=logging.INFO)

def process(db,assessment_id):
    """处理一次排队分级：先冻结依据并提交等级，再独立留证。返回是否处理。"""
    row=db.get(RiskAssessment,assessment_id)
    if not row or row.status!='queued':return False
    row.status='running';db.commit()
    try:
        obs=db.get(Observation,row.observation_id)
        frozen=snapshot(obs.humidity,obs.holes,obs.mold,{'humidity':obs.humidity,'holes':obs.holes,'mold':obs.mold,'at':obs.at.isoformat() if obs.at else None,'note':obs.note})
        row.provenance=frozen;row.predicted=frozen['predicted'];row.metrics=frozen['metrics']
        row.status='done';row.error=''
    except Exception as exc:
        # 只有预测本身失败才标记 failed；修复输入后可重新提交分级。
        row.status='failed';row.error=str(exc)[:200];db.commit();return True
    # 等级先落库，复核不必等待留证。
    db.commit()
    try:
        # 留证失败不得回滚等级，记录状态供重试；不覆盖已归档依据。
        state,reason,name,digest=archive(row)
    except Exception as exc:
        state,reason,name,digest='failed',str(exc)[:200],'',''
    row.evidence_status=state;row.evidence_note=reason;row.evidence_file=name;row.evidence_sha256=digest
    db.commit()
    return True

if __name__=='__main__':
    while True:
        Path('/tmp/worker-heartbeat').touch()
        try:
            item=queue.blpop('folio:risk',timeout=2)
            if not item:continue
            with Session() as db:process(db,int(item[1]))
        except Exception:logging.exception('worker iteration');time.sleep(1)
