import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, ZoneRuleVersion
from src.services.business import analyze_mapped
from src.services.reports import deliver
from src.services.audit import record
from src.services import zone_rules
logging.basicConfig(level=logging.INFO)


def _compute(job, dataset, db):
    """Compute under the rule version captured when the job was created."""
    version = db.get(ZoneRuleVersion, job.zone_version_id) if job.zone_version_id else None
    if version:
        return analyze_mapped(dataset.records, job.params or {}, zone_rules.mapping_of(version),
                              zone_rules.targets_of(version), version=version.version,
                              version_name=version.name)
    return analyze_mapped(dataset.records, job.params or {})


def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        captured=j.zone_version_id
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=_compute(j,d,db)
            json.dumps(result,allow_nan=False)
            error=''
        except Exception as e:
            logging.exception('Analysis failed')
            result=None
            error=str(e)[:990]
        # Re-lock the job row: a rule-version switch may have replaced the
        # visible result while this job was computing. A late finish must never
        # overwrite the newly activated version.
        j=db.scalar(select(Job).where(Job.id==job_id).with_for_update())
        visible=zone_rules.visible_version_id(db,j.dataset_id)
        if j.status!='running' or j.zone_version_id!=captured:
            # Another writer owns the row now (rule-version switch, supersede,
            # or recovery). Never overwrite a newer visible result.
            record(db,'worker','job.late_discarded',{'id':j.id,'captured_version':captured,
                                                     'status':j.status,'visible_version':j.zone_version})
        elif visible!=captured:
            # This job was created against an older rule version that has since
            # been switched out; its result belongs to the old version only.
            j.status='superseded'
            j.error='任务完成时展区口径已切换，其旧版结果不覆盖当前结果；请按当前版本重新发起分析'
            j.finished_at=time.time()
            record(db,'worker','job.superseded',{'id':j.id,'captured_version':captured})
        elif result is None:
            j.status='failed';j.error=error;j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        else:
            j.result=result;j.status='completed';j.error='';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id,'zone_version':j.zone_version})
        db.commit()


def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        try:
            zone_rules.tick(db)
        except Exception:
            logging.exception('Zone rule tick failed');db.rollback()
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id,'zone_version':d.zone_version})
        db.commit()


def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
