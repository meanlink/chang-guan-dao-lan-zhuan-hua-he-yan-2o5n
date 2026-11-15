from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from src.config.database import get_db
from src.middlewares.auth import current_user
from src.models import Dataset, Job, Report, Audit
from src.services.business import metadata
from src.services import zone_rules
router=APIRouter()
@router.get('/meta')
def meta(db=Depends(get_db)):
    data=metadata()
    # Zone choices accept a batch's own visible version; the global list is
    # the union of current targets so the picker never shows stale raw names.
    zones=set()
    for state in zone_rules.current_state(db)['datasets']:
        zones|=set(state['zone_options'])
    data['parameters'][0]['options']=[{'value':x,'label':x} for x in ['全部']+sorted(zones-{'全部'})]
    return data
@router.get('/overview')
def overview(db=Depends(get_db),user=Depends(current_user)):
    return {'datasets':db.scalar(select(func.count()).select_from(Dataset)), 'records':sum(len(d.records) for d in db.scalars(select(Dataset))), 'jobs':db.scalar(select(func.count()).select_from(Job)), 'approved':db.scalar(select(func.count()).select_from(Job).where(Job.approved==True)), 'reports':db.scalar(select(func.count()).select_from(Report))}
@router.get('/audits')
def audits(db=Depends(get_db),user=Depends(current_user)):
    return [{'id':a.id,'actor':a.actor,'action':a.action,'detail':a.detail,'at':a.at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))]
