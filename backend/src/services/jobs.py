import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.services import zone_rules


def _zone_allowed(db, dataset_id, zone):
    options = zone_rules.zone_options_for(db, dataset_id)
    return str(zone) in options


def create(db, data, user):
    dataset=db.get(Dataset,data.dataset_id)
    if not dataset: raise HTTPException(404,'数据批次不存在')
    # Lock the visible-version row for this batch so a concurrent rule-version
    # switch and this insert cannot interleave: the job is bound to whatever
    # version is current when creation commits.
    zone_rules.lock_visible_state(db, data.dataset_id)
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif key=='zone':
            # Zone choices come from the batch's currently visible rule version.
            if not _zone_allowed(db, data.dataset_id, v):
                raise HTTPException(422,f'{p["label"]} 不在该批次当前展区口径中')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    version = zone_rules.visible_version(db, data.dataset_id)
    j=Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
          created_at=time.time(), status='queued',
          zone_version_id=version.id if version else None,
          zone_version=version.version if version else zone_rules.BASE_VERSION)
    db.add(j); db.flush()
    return j


def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
