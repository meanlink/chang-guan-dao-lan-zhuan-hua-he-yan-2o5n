import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, ZoneRuleVersion
from src.config.settings import ARTIFACT_DIR


def job_version(job, db=None):
    """(zone_version_id, zone_version, name) captured on the job row itself."""
    version_id = getattr(job, 'zone_version_id', None)
    number = getattr(job, 'zone_version', None)
    if number is None:
        number = 0
    name = '基础展区口径' if not number else ''
    if version_id and db is not None and not name:
        version = db.get(ZoneRuleVersion, version_id)
        name = version.name if version else ''
    return version_id, number, name


def create(db, data):
    j=db.scalar(select(Job).where(Job.id==data.job_id).with_for_update())
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    version_id, version, _ = job_version(j, db)
    r=Report(name=data.name, job_id=j.id, destination=data.destination,
             interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds,
             enabled=True, zone_version_id=version_id, zone_version=version)
    db.add(r); db.flush()
    return r


def _advance(report):
    report.next_run=time.time()+report.interval_seconds


def deliver(db, report):
    # Row lock keeps a concurrently activated rule version from swapping the
    # job result between the approval check and the file write.
    j=db.scalar(select(Job).where(Job.id==report.job_id).with_for_update())
    report=db.scalar(select(Report).where(Report.id==report.id).with_for_update()) or report
    if not j or j.status!='completed' or not j.approved:
        report.blocked_reason='分析结果已失效或尚未批准，等待负责人重新批准'
        _advance(report)
        return None
    version_id, version, version_name = job_version(j, db)
    if version_id != report.zone_version_id:
        # The plan was approved against another rule version; never mix versions.
        report.blocked_reason=f'结果已切换到规则版本 {version or "基础口径"}，计划仍固定在 v{report.zone_version or 0}；请按新版结果新建计划'
        _advance(report)
        return None
    report.blocked_reason=''
    out=io.StringIO()
    out.write('﻿')
    table=j.result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    data=out.getvalue().encode('utf-8')
    params_hash=hashlib.sha256(json.dumps(j.params or {},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    delivery=Delivery(report_id=report.id, created_at=time.time(),
                      checksum=hashlib.sha256(data).hexdigest(), filename='',
                      destination=report.destination, job_id=j.id,
                      zone_version_id=version_id, zone_version=version,
                      params_checksum=params_hash)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    snapshot={'job':j.name,'job_id':j.id,'params':j.params,
              'zone_rule_version':version,'zone_rule_version_id':version_id,
              'zone_rule_name':version_name,'approved':True,
              'result':j.result,'checksum':delivery.checksum}
    with open(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),'w') as f:
        json.dump(snapshot,f,ensure_ascii=False,allow_nan=False)
    _advance(report)
    return delivery
