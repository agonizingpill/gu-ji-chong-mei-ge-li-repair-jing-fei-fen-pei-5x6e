import os
import redis
from sqlalchemy import select
from .models import Accession,Isolation,RiskAssessment
from .common import get,reject,finish,dump
from .catalog_service import latest_observation
from .evidence_service import archive,verify
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)

def request_risk(db,data,user):
    folio=get(db,Accession,data.accession_id,True);obs=latest_observation(db,folio.id)
    reject(not obs,'先录入病害测量')
    reject(not db.scalar(select(Isolation).where(Isolation.accession_id==folio.id,Isolation.active==True)),'先隔离入柜再评估')
    reject(db.scalar(select(RiskAssessment).where(RiskAssessment.observation_id==obs.id,RiskAssessment.status.in_(['queued','running']))) is not None,'该次观测仍在排队')
    row=RiskAssessment(accession_id=folio.id,observation_id=obs.id,evidence_status='pending');db.add(row);db.flush();result=finish(db,user,'提交风险分级',row)
    queue.rpush('folio:risk',row.id);return result

def review(db,id,data,user):
    row=get(db,RiskAssessment,id,True)
    reject(row.status!='done','仅已完成分级可复核')
    reject(latest_observation(db,row.accession_id).id!=row.observation_id,'病害已复测，请重新运行最新分级')
    # 复核只依据预测与现场判断；留证是否补齐不影响复核办理，原预测始终保留。
    row.status='reviewed';row.approved=data.level;row.review_note=data.note
    return finish(db,user,'风险主管复核',row)

def retry_evidence(db,id,user):
    """留证失败后重试；旧单缺依据时尝试补档。不覆盖已归档依据，不用现模型补旧账。"""
    row=get(db,RiskAssessment,id,True)
    reject(row.status not in ('done','reviewed'),'分级尚未完成，暂无可补的留证')
    reject(row.evidence_status=='archived','留证已归档，不重复覆盖原有依据')
    if row.provenance is None:
        row.evidence_status='missing';row.evidence_note='历史记录仅存预测等级，无当时测量与阈值快照，无法核对补档'
        return finish(db,user,'留证缺证登记',row)
    ok,reason=verify(row.provenance,row.predicted)
    if not ok:
        row.evidence_status='missing';row.evidence_note=reason
        return finish(db,user,'留证核对失败登记',row)
    state,reason,name,digest=archive(row)
    row.evidence_status=state;row.evidence_note=reason;row.evidence_file=name;row.evidence_sha256=digest
    action={'archived':'留证重试归档','failed':'留证重试失败'}.get(state,'留证核对失败登记')
    return finish(db,user,action,row)

def evidence(db,id):
    row=get(db,RiskAssessment,id,True)
    return {'assessment':dump(row),'provenance':row.provenance,'evidence_status':row.evidence_status,'evidence_file':row.evidence_file,'evidence_sha256':row.evidence_sha256,'evidence_note':row.evidence_note}
