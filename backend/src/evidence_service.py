import hashlib,json,os,uuid
from pathlib import Path
from .algorithm import explain,MODEL_VERSION
# 留证文件默认写入共享 artifacts 卷；可用 ARTIFACT_DIR 覆盖（测试与本地运行）。
ARTIFACT_DIR=Path(os.getenv('ARTIFACT_DIR','/artifacts'))
EVIDENCE_NOTE='依据由分级当时冻结的快照重放核对；不重新训练、不替换模型。'

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def snapshot(humidity,holes,mold,observation=None):
    """分级当时冻结的预测依据：输入、走过的阈值、模型指印与指标。"""
    result=explain(humidity,holes,mold)
    snapshot={'observation':observation or {'humidity':float(humidity),'holes':int(holes),'mold':float(mold)},'input':result['input'],'predicted':result['predicted'],'decision_path':result['decision_path'],'model':result['model'],'metrics':result['metrics']}
    return snapshot

def verify(snapshot,predicted):
    """只有能重放出当时同一次预测的留证才允许补档。返回 (可补档, 原因)。"""
    if not snapshot:return False,'该记录仅存预测等级，无当时预测快照'
    try:
        data=snapshot['input']
        result=explain(data['humidity'],data['holes'],data['mold'])
    except Exception:return False,'当时预测快照无法重放核对'
    frozen=snapshot.get('model') or {}
    if result['model']['version']!=frozen.get('version') or result['model']['fingerprint']!=frozen.get('fingerprint'):
        return False,'当前模型与当时指印不一致，不能用现模型补旧账'
    if result['predicted']!=snapshot.get('predicted') or result['predicted']!=predicted:
        return False,'重放等级与当时预测不一致'
    if result['decision_path']!=snapshot.get('decision_path'):
        return False,'重放阈值路径与当时快照不一致'
    return True,''

def document(row,frozen):
    # 只包含分级当时的事实，保证同一份快照每次重放得到逐字节相同的留证。
    return {'assessment_id':row.id,'accession_id':row.accession_id,'observation_id':row.observation_id,'predicted':frozen['predicted'],'observation':frozen['observation'],'input':frozen['input'],'decision_path':frozen['decision_path'],'model':frozen['model'],'metrics':frozen['metrics'],'note':EVIDENCE_NOTE}

def path_for(row):return ARTIFACT_DIR/f'risk-{row.id}-evidence.json'

def _write_once(target,payload):
    """先写临时文件再原子挂到目标名；目标已存在则绝不覆盖，也不留下半截文件。"""
    tmp=target.with_name(f'.{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        tmp.write_text(payload,encoding='utf-8')
        try:os.link(tmp,target)
        except FileExistsError:raise
        except OSError:
            # 文件系统不支持硬链接时退回独占创建。
            with open(target,'x',encoding='utf-8') as handle:handle.write(payload)
    finally:
        try:tmp.unlink()
        except FileNotFoundError:pass

def archive(row):
    """核对快照后归档；绝不覆盖已有文件，返回 (状态, 原因, 文件名, sha256)。"""
    frozen=row.provenance
    ok,reason=verify(frozen,row.predicted)
    if not ok:return 'missing',reason,'',''
    payload=canonical(document(row,frozen))
    digest=hashlib.sha256(payload.encode()).hexdigest()
    target=path_for(row)
    try:
        ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
        _write_once(target,payload)
    except FileExistsError:
        existing=target.read_text(encoding='utf-8')
        if hashlib.sha256(existing.encode()).hexdigest()!=digest:
            return 'missing','已有留证文件与本次依据不一致，未覆盖原有依据，请人工核对','',''
    except OSError as exc:
        return 'failed',str(exc)[:200],'',''
    return 'archived','',target.name,digest
