from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user, admin_only
from src.models import ZoneRuleVersion
from src.schemas.zone_rule import VersionInput
from src.services import zone_rules
from src.services.audit import record
router=APIRouter(prefix='/zone-rules')


def _raise(exc):
    raise HTTPException(exc.status, str(exc))


@router.get('/current')
def current(db=Depends(get_db),u=Depends(current_user)):
    return zone_rules.current_state(db)


@router.get('/versions')
def versions(db=Depends(get_db),u=Depends(current_user)):
    return zone_rules.list_versions(db)


@router.get('/progress')
def progress(db=Depends(get_db),u=Depends(current_user)):
    return zone_rules.building_progress(db)


@router.get('/versions/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    try:
        return zone_rules.detail(db,id)
    except zone_rules.RuleError as exc:
        _raise(exc)


@router.post('/versions',status_code=201)
def create(data:VersionInput,db=Depends(get_db),u=Depends(admin_only)):
    try:
        version=zone_rules.create_version(db,u,data.model_dump())
    except zone_rules.RuleError as exc:
        _raise(exc)
    record(db,u.email,'zone.version.create',{'id':version.id,'version':version.version,
                                             'rules':len(version.rules),'dataset_ids':data.dataset_ids})
    db.commit()
    return zone_rules.detail(db,version.id)


@router.post('/versions/{id}/start',status_code=202)
def start(id:int,db=Depends(get_db),u=Depends(admin_only)):
    version=db.get(ZoneRuleVersion,id)
    if not version:_raise(zone_rules.RuleError('规则版本不存在',404))
    previous_status=version.status
    try:
        started=zone_rules.start_version(db,version,u)
    except zone_rules.RuleError as exc:
        _raise(exc)
    record(db,u.email,'zone.version.start',{'id':version.id,'version':version.version,'started':started})
    db.commit()
    data=zone_rules.detail(db,version.id)
    if previous_status in ('ready','failed','blocked') and data['status']=='blocked':
        raise HTTPException(409,data['error'])
    return data


@router.post('/versions/{id}/rollback')
def rollback(id:int,db=Depends(get_db),u=Depends(admin_only)):
    version=db.get(ZoneRuleVersion,id)
    if not version:_raise(zone_rules.RuleError('规则版本不存在',404))
    try:
        requeue=zone_rules.rollback_version(db,version)
    except zone_rules.RuleError as exc:
        _raise(exc)
    record(db,u.email,'zone.version.rollback',{'id':version.id,'version':version.version,'requeued':len(requeue)})
    db.commit()
    for job_id in requeue:
        from src.services import jobs as jobs_service
        jobs_service.enqueue(job_id)
    return zone_rules.detail(db,version.id)
