"""展区归并规则的版本化：校验、暂存重算、原子切换与回滚。

关键约束：
* 一条原始记录只能映射到一个展区；重复、链式（歧义）或未覆盖的原始展区
  会让整组规则不生效（对应批次被阻断，版本不切换）。
* 重算结果先写入暂存表，当前可见结果保持不变；全部批次成功后在一个事务内
  一次性切换这组批次的当前结果，任何失败都保留旧版。
* 每个分析结果、分发计划与归档都携带规则版本号，跨版本不会混读。
* 切换前已排队/运行中的旧任务完成后只写自己的结果，不会覆盖新版可见结果；
  重算开始后新建的任务在切换时标记为作废（可回滚恢复）。
"""
import json
import time

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from src.models import (Dataset, Job, ZoneRuleVersion, ZoneRuleBatch,
                        ZoneRuleStage, ZoneRuleSnapshot, DatasetZoneState,
                        ZoneRuleDatasetLock)
from src.services.audit import record

BASE_VERSION = 0
BASE_NAME = '基础展区口径'

STATUS_LABELS = {
    'ready': '待执行', 'building': '重算中', 'active': '当前生效',
    'blocked': '已阻断', 'failed': '重算失败', 'superseded': '已被替代',
    'rolled_back': '已回滚',
    'pending': '待重算', 'running': '重算中', 'completed': '已完成',
    'queued': '排队中',
}


class RuleError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _normalise_rules(raw):
    """Validate and canonicalise rules; returns (rules, targets).

    Rejects duplicate sources (one raw count may only enter one zone), chained
    renames (A→B plus B→C would be ambiguous) and empty names. Identity rules
    (A→A) are allowed.
    """
    if not isinstance(raw, list) or not raw:
        raise RuleError('至少需要一条展区归并规则')
    if len(raw) > 500:
        raise RuleError('规则数量超过 500 条上限')
    rules, sources, targets = [], set(), set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuleError(f'第 {index + 1} 条规则格式不正确')
        source = str(item.get('source', '')).strip()
        target = str(item.get('target', '')).strip()
        if not source or not target:
            raise RuleError(f'第 {index + 1} 条规则必须同时填写原展区与归并后展区')
        if len(source) > 80 or len(target) > 80:
            raise RuleError(f'第 {index + 1} 条规则名称超过 80 字符')
        if source in sources:
            raise RuleError(f'原展区“{source}”重复出现，一条原始计数只能归入一个展区')
        sources.add(source)
        rules.append({'source': source, 'target': target})
        targets.add(target)
    # A zone that is the merge target of another rule cannot also be renamed
    # further (A→B plus B→C would make A's destination ambiguous). Identity
    # rules (A→A) are allowed and are the common "keep this zone" case.
    chained = sorted({r['source'] for r in rules
                      if r['target'] != r['source']
                      and any(other['target'] == r['source'] for other in rules)})
    if chained:
        raise RuleError('展区“' + '、'.join(chained) + '”既是归入目标又被继续改名，归并关系存在歧义')
    return rules, sorted(targets)


def mapping_of(version):
    return {str(r['source']): str(r['target']) for r in ((version.rules or []) if version else [])}


def targets_of(version):
    return {str(r['target']) for r in ((version.rules or []) if version else [])}


def zone_options_for(db, dataset_id):
    """Allowed analysis zones for a dataset under its currently visible version."""
    version = visible_version(db, dataset_id)
    if version:
        return ['全部'] + sorted(targets_of(version))
    dataset = db.get(Dataset, dataset_id)
    raw = sorted({str(r.get('zone')) for r in (dataset.records if dataset else [])
                  if isinstance(r, dict) and r.get('zone') is not None})
    return ['全部'] + raw


def visible_version_id(db, dataset_id):
    state = db.scalar(select(DatasetZoneState).where(DatasetZoneState.dataset_id == dataset_id))
    return state.version_id if state else None


def visible_version(db, dataset_id):
    version_id = visible_version_id(db, dataset_id)
    return db.get(ZoneRuleVersion, version_id) if version_id else None


def lock_visible_state(db, dataset_id):
    """Serialise job creation / plan creation against an atomic version switch.

    finalize_version updates the same DatasetZoneState row, so a row lock here
    means a concurrent switch either fully landed before this transaction or
    waits for it. Batches on the base version have no state row, in which case
    the worker's captured-version guard is the safety net.
    """
    db.scalar(select(DatasetZoneState).where(DatasetZoneState.dataset_id == dataset_id)
              .with_for_update())


def visible_versions(db):
    versions = {v.id: v for v in db.scalars(select(ZoneRuleVersion))}
    return {state.dataset_id: versions.get(state.version_id)
            for state in db.scalars(select(DatasetZoneState))}


def active_version_ids(db):
    return {v for v in visible_versions(db).values() if v}


def _version_state(db, version, batches):
    datasets = {d.id: d for d in db.scalars(select(Dataset))}
    active = {v.id for v in active_version_ids(db)}
    data = {
        'id': version.id, 'version': version.version, 'name': version.name,
        'note': version.note, 'rules': version.rules, 'status': version.status,
        'status_label': STATUS_LABELS.get(version.status, version.status),
        'error': version.error, 'created_at': version.created_at,
        'started_at': version.started_at, 'activated_at': version.activated_at,
        'finished_at': version.finished_at,
        'is_current': version.id in active,
        'can_start': version.status in ('ready', 'failed', 'blocked') and bool(batches),
        'can_rollback': version.id in active and version.status == 'active',
        'targets': sorted(targets_of(version)),
        'batches': [_batch_state(b, datasets.get(b.dataset_id)) for b in batches],
    }
    return data


def _base_state(db):
    total = db.scalar(select(func.count()).select_from(Dataset)) or 0
    mapped = len([v for v in active_version_ids(db) if v])
    return {'id': None, 'version': BASE_VERSION, 'name': BASE_NAME,
            'note': '未应用任何归并规则，分析沿用原始展区名称。',
            'rules': [], 'status': 'active', 'status_label': STATUS_LABELS['active'],
            'error': '', 'created_at': None, 'started_at': None, 'activated_at': None,
            'finished_at': None, 'is_current': mapped < total, 'can_start': False,
            'can_rollback': False, 'targets': [], 'datasets_on_base': max(total - mapped, 0),
            'batches': []}


def _batch_state(batch, dataset):
    return {'dataset_id': batch.dataset_id,
            'dataset_name': dataset.name if dataset else '已删除批次',
            'dataset_rows': len(dataset.records) if dataset else 0,
            'status': batch.status, 'status_label': STATUS_LABELS.get(batch.status, batch.status),
            'reason': batch.reason, 'error': batch.error,
            'total_jobs': batch.total_jobs, 'done_jobs': batch.done_jobs,
            'previous_version': batch.previous_version_id,
            'started_at': batch.started_at, 'finished_at': batch.finished_at}


def list_versions(db):
    batches = {}
    for row in db.scalars(select(ZoneRuleBatch).order_by(ZoneRuleBatch.dataset_id)):
        batches.setdefault(row.version_id, []).append(row)
    out = [_version_state(db, v, batches.get(v.id, []))
           for v in db.scalars(select(ZoneRuleVersion).order_by(ZoneRuleVersion.version.desc()))]
    out.append(_base_state(db))
    return out


def detail(db, version_id):
    version = db.get(ZoneRuleVersion, version_id)
    if not version:
        raise RuleError('规则版本不存在', 404)
    rows = list(db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)
                           .order_by(ZoneRuleBatch.dataset_id)))
    data = _version_state(db, version, rows)
    data['stages'] = [{'job_id': s.job_id, 'dataset_id': s.dataset_id, 'status': s.status,
                       'error': s.error, 'zone': (s.params or {}).get('zone')}
                      for s in db.scalars(select(ZoneRuleStage)
                                          .where(ZoneRuleStage.version_id == version.id)
                                          .order_by(ZoneRuleStage.id))][:500]
    return data


def building_progress(db):
    """In-flight versions with per-batch progress and blocking reasons."""
    versions = list(db.scalars(select(ZoneRuleVersion)
                               .where(ZoneRuleVersion.status == 'building')
                               .order_by(ZoneRuleVersion.version.desc())))
    datasets = {d.id: d for d in db.scalars(select(Dataset))}
    out = []
    for version in versions:
        rows = list(db.scalars(select(ZoneRuleBatch)
                               .where(ZoneRuleBatch.version_id == version.id)
                               .order_by(ZoneRuleBatch.dataset_id)))
        out.append({'id': version.id, 'version': version.version, 'name': version.name,
                    'status': version.status,
                    'status_label': STATUS_LABELS.get(version.status, version.status),
                    'error': version.error, 'started_at': version.started_at,
                    'finished_at': version.finished_at,
                    'batches': [_batch_state(b, datasets.get(b.dataset_id)) for b in rows]})
    return out


def _lock_version(db, dataset_id):
    lock = db.get(ZoneRuleDatasetLock, dataset_id)
    if not lock:
        return None
    version = db.get(ZoneRuleVersion, lock.version_id)
    return {'version_id': lock.version_id, 'version': version.version if version else None,
            'name': version.name if version else ''}


def current_state(db):
    """Per-batch visible version, raw zones, analysis zone options and any live rebuild."""
    versions = visible_versions(db)
    out = []
    for dataset in db.scalars(select(Dataset).order_by(Dataset.id)):
        version = versions.get(dataset.id)
        raw_zones = sorted({str(r.get('zone')) for r in dataset.records
                            if isinstance(r, dict) and r.get('zone') is not None})
        out.append({'dataset_id': dataset.id, 'dataset_name': dataset.name,
                    'raw_zones': raw_zones,
                    'zone_options': zone_options_for(db, dataset.id),
                    'version': version.version if version else BASE_VERSION,
                    'version_id': version.id if version else None,
                    'version_name': version.name if version else BASE_NAME,
                    'rule_count': len(version.rules or []) if version else 0,
                    'rebuild_version': _lock_version(db, dataset.id)})
    return {'datasets': out}


def create_version(db, user, data):
    name = str(data.get('name', '')).strip()
    if len(name) < 2:
        raise RuleError('版本名称至少需要两个字符')
    if len(name) > 160:
        raise RuleError('版本名称过长')
    note = str(data.get('note', '')).strip()[:500]
    rules, targets = _normalise_rules(data.get('rules'))
    dataset_ids = data.get('dataset_ids')
    if not isinstance(dataset_ids, list) or not dataset_ids:
        raise RuleError('请选择至少一个需要重算的数据批次')
    try:
        dataset_ids = sorted({int(x) for x in dataset_ids})
    except (TypeError, ValueError):
        raise RuleError('批次编号不合法')
    if len(dataset_ids) > 50:
        raise RuleError('单次最多选择 50 个批次')
    datasets = {d.id: d for d in db.scalars(select(Dataset).where(Dataset.id.in_(dataset_ids)))}
    if set(dataset_ids) - set(datasets):
        raise RuleError('所选批次中有数据不存在', 404)
    for dataset_id in dataset_ids:
        if db.get(ZoneRuleDatasetLock, dataset_id):
            raise RuleError(f'批次“{datasets[dataset_id].name}”已有规则版本正在重算，请等待完成', 409)
        raw = {str(r.get('zone')) for r in datasets[dataset_id].records if isinstance(r, dict)}
        missing = sorted(raw - {r['source'] for r in rules})
        if missing:
            raise RuleError(f'批次“{datasets[dataset_id].name}”中的展区 ' + '、'.join(missing)
                            + ' 未归属，整组规则不生效；请补充归并规则')
    last = db.scalar(select(func.max(ZoneRuleVersion.version))) or BASE_VERSION
    version = ZoneRuleVersion(version=int(last) + 1, name=name, note=note, rules=rules,
                              status='ready', created_by=user.id, created_at=time.time())
    db.add(version)
    db.flush()
    for dataset_id in dataset_ids:
        total_jobs = db.scalar(select(func.count()).select_from(Job)
                               .where(Job.dataset_id == dataset_id,
                                      Job.status.in_(('queued', 'running', 'completed')))) or 0
        db.add(ZoneRuleBatch(version_id=version.id, dataset_id=dataset_id, status='pending',
                             total_jobs=int(total_jobs or 0), done_jobs=0,
                             reason='等待负责人开始重算'))
    db.flush()
    return version


def can_start(db, version):
    # A blocked version may be retried once the conflicting job has been
    # superseded or a lock released; every start revalidates the whole group.
    if version.status not in ('ready', 'failed', 'blocked'):
        raise RuleError('仅待执行、已阻断或重算失败的版本可以启动重算', 409)
    rows = list(db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)))
    if not rows:
        raise RuleError('该版本没有需要重算的批次', 409)
    for row in rows:
        lock = db.get(ZoneRuleDatasetLock, row.dataset_id)
        if lock and lock.version_id != version.id:
            raise RuleError('至少一个批次已有其他版本正在重算，请等待完成', 409)
    return rows


def _remap_job_params(params, mapping, targets):
    """Map the job's own zone filter into the new version; None when impossible."""
    params = dict(params or {})
    zone = str(params.get('zone', '全部'))
    if zone == '全部':
        return params
    if zone in mapping:
        params['zone'] = mapping[zone]
        return params
    if zone in targets:
        return params
    return None


def start_version(db, version, user):
    """Validate every selected batch, then queue staged recomputes.

    The switch stays invisible until all batches finish; a group with any
    ambiguous / unmapped batch does not start at all ("整组不生效").
    """
    rows = can_start(db, version)
    mapping = mapping_of(version)
    targets = targets_of(version)
    now = time.time()

    # Phase 1: validate the whole group before touching any visible state.
    problems, plans = [], []
    for row in rows:
        dataset = db.get(Dataset, row.dataset_id)
        if not dataset:
            problems.append((row, '数据批次已被删除'))
            continue
        raw = {str(r.get('zone')) for r in dataset.records if isinstance(r, dict)}
        missing = sorted(raw - set(mapping))
        if missing:
            problems.append((row, '展区 ' + '、'.join(missing) + ' 未归属，整组规则不生效'))
            continue
        jobs = list(db.scalars(select(Job).where(Job.dataset_id == row.dataset_id,
                                                  Job.status.in_(('queued', 'running', 'completed')))))
        if not jobs:
            problems.append((row, '该批次尚无分析任务，缺少可重算的基线'))
            continue
        bad = next((j for j in jobs if _remap_job_params(j.params, mapping, targets) is None), None)
        if bad:
            problems.append((row, f'任务“{bad.name}”的分析展区 {(bad.params or {}).get("zone")} 无法映射到新版本'))
            continue
        plans.append((row, dataset, jobs))
    if problems:
        for row, reason in problems:
            row.status = 'blocked'
            row.reason = reason
            row.error = ''
            row.finished_at = now
        for row, _, _ in plans:
            row.status = 'blocked'
            row.reason = '同一组其他批次被阻断，整组不生效'
            row.finished_at = now
        version.status = 'blocked'
        version.error = '；'.join(f'批次 {row.dataset_id}：{reason}' for row, reason in problems)[:1900]
        version.finished_at = now
        db.flush()
        return False

    # Phase 2: lock each batch and stage its jobs. Nothing visible changes yet.
    # A retried version discards its previous (partial or failed) staging first.
    for old in db.scalars(select(ZoneRuleStage).where(ZoneRuleStage.version_id == version.id)):
        db.delete(old)
    db.flush()
    for row, dataset, jobs in plans:
        try:
            db.add(ZoneRuleDatasetLock(dataset_id=row.dataset_id, version_id=version.id, created_at=now))
            db.flush()
        except IntegrityError:
            db.rollback()
            raise RuleError('该批次已有其他版本正在重算，请等待完成', 409)
        row.status = 'running'
        row.reason = ''
        row.error = ''
        row.started_at = now
        row.previous_version_id = visible_version_id(db, row.dataset_id)
        row.total_jobs = len(jobs)
        row.done_jobs = 0
        for job in jobs:
            db.add(ZoneRuleStage(version_id=version.id, job_id=job.id, dataset_id=job.dataset_id,
                                 status='pending',
                                 params=_remap_job_params(job.params, mapping, targets),
                                 result={}, updated_at=now))
        db.flush()
    version.status = 'building'
    version.started_at = now
    version.error = ''
    version.finished_at = None
    db.flush()
    return True


def _fail_version(db, version, message):
    version.status = 'failed'
    version.error = message[:1900]
    version.finished_at = time.time()
    for row in db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)):
        if row.status not in ('blocked', 'failed'):
            row.status = 'failed'
            row.error = message[:1900]
            row.finished_at = time.time()
        db.delete(db.get(ZoneRuleDatasetLock, row.dataset_id))
    db.flush()


def pending_stages(db):
    version_ids = list(db.scalars(select(ZoneRuleVersion.id).where(ZoneRuleVersion.status == 'building')))
    if not version_ids:
        return []
    return list(db.scalars(select(ZoneRuleStage.id)
                           .where(ZoneRuleStage.version_id.in_(version_ids),
                                  ZoneRuleStage.status == 'pending')
                           .order_by(ZoneRuleStage.id)))


def compute_stage(db, stage_id):
    """Compute one staged analysis under its version. Never touches visible job state."""
    stage = db.get(ZoneRuleStage, stage_id)
    if not stage or stage.status != 'pending':
        return False
    version = db.get(ZoneRuleVersion, stage.version_id)
    dataset = db.get(Dataset, stage.dataset_id)
    if not version or not dataset or version.status != 'building':
        return False
    from src.services.business import analyze_mapped
    try:
        result = analyze_mapped(dataset.records, stage.params or {}, mapping_of(version),
                                targets_of(version), version=version.version,
                                version_name=version.name)
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        stage.result = result
        stage.status = 'completed'
        stage.error = ''
    except Exception as exc:  # noqa: BLE001 - staged failure recorded per job
        stage.status = 'failed'
        stage.error = str(exc)[:990]
    stage.updated_at = time.time()
    db.flush()
    settle_batch(db, stage.version_id, stage.dataset_id)
    return True


def settle_batch(db, version_id, dataset_id):
    batch = db.scalar(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version_id,
                                                  ZoneRuleBatch.dataset_id == dataset_id))
    if not batch or batch.status in ('completed', 'blocked', 'failed'):
        return batch
    stages = list(db.scalars(select(ZoneRuleStage).where(ZoneRuleStage.version_id == version_id,
                                                         ZoneRuleStage.dataset_id == dataset_id)))
    batch.done_jobs = sum(1 for s in stages if s.status in ('completed', 'failed'))
    if not stages or batch.done_jobs < batch.total_jobs:
        return batch
    failed = next((s for s in stages if s.status == 'failed'), None)
    if failed:
        batch.status = 'failed'
        batch.error = f'任务 {failed.job_id} 重算失败：{failed.error}'
    else:
        batch.status = 'completed'
        batch.error = ''
    batch.finished_at = time.time()
    return batch


def finalize_version(db, version):
    """All-or-nothing switch; returns True when the version became active."""
    if version.status != 'building':
        return False
    rows = list(db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)))
    for row in rows:
        settle_batch(db, version.id, row.dataset_id)
    problems = [r for r in rows if r.status != 'completed']
    if problems:
        reasons = '；'.join(f'{r.dataset_id}：{r.error or r.reason or "重算未完成"}' for r in problems)
        _fail_version(db, version, '重算未全部成功，保留旧版：' + reasons)
        return False
    now = time.time()
    for row in rows:
        stages = {s.job_id: s for s in db.scalars(
            select(ZoneRuleStage).where(ZoneRuleStage.version_id == version.id,
                                        ZoneRuleStage.dataset_id == row.dataset_id))}
        for job in db.scalars(select(Job).where(Job.dataset_id == row.dataset_id).with_for_update()):
            stage = stages.get(job.id)
            if not stage or stage.status != 'completed':
                # Created after the recompute began (or otherwise not staged):
                # never let it shadow the newly activated version. Keep a
                # snapshot so a rollback can restore what users saw before.
                if job.status in ('queued', 'running', 'completed'):
                    db.add(ZoneRuleSnapshot(version_id=version.id, job_id=job.id,
                                            previous_zone_version_id=getattr(job, 'zone_version_id', None),
                                            previous_params=job.params or {},
                                            previous_result=job.result or {},
                                            previous_approved=bool(job.approved),
                                            previous_status=job.status,
                                            previous_error=job.error or ''))
                    job.status = 'superseded'
                    job.error = '该任务创建于规则重算开始之后，未被纳入新版本；请在新版口径下重新发起分析'
                    job.finished_at = now
                    record(db, 'worker', 'job.superseded', {'id': job.id, 'version': version.version})
                continue
            db.add(ZoneRuleSnapshot(version_id=version.id, job_id=job.id,
                                    previous_zone_version_id=getattr(job, 'zone_version_id', None),
                                    previous_params=job.params or {},
                                    previous_result=job.result or {},
                                    previous_approved=bool(job.approved),
                                    previous_status=job.status,
                                    previous_error=job.error or ''))
            job.params = stage.params
            job.result = stage.result
            job.status = 'completed'
            job.error = ''
            job.approved = False
            job.zone_version_id = version.id
            job.zone_version = version.version
            job.finished_at = now
        state = db.scalar(select(DatasetZoneState).where(DatasetZoneState.dataset_id == row.dataset_id))
        if state:
            state.version_id = version.id
            state.updated_at = now
        else:
            db.add(DatasetZoneState(dataset_id=row.dataset_id, version_id=version.id, updated_at=now))
        row.reason = ''
        row.finished_at = now
        db.delete(db.get(ZoneRuleDatasetLock, row.dataset_id))
    _mark_stale_plans(db, version, [r.dataset_id for r in rows])
    version.status = 'active'
    version.activated_at = now
    version.finished_at = now
    version.error = ''
    _supersede_older(db, version, [r.dataset_id for r in rows])
    db.flush()
    return True


def _mark_stale_plans(db, version, dataset_ids):
    """Surface why a plan pinned to an older version will not deliver anymore."""
    from src.models import Report
    for plan in db.scalars(select(Report)):
        if plan.zone_version_id == version.id:
            continue
        job = db.get(Job, plan.job_id)
        if job and job.dataset_id in dataset_ids:
            plan.blocked_reason = (f'分析结果已切换到规则版本 v{version.version}，计划固定在 '
                                   f'v{plan.zone_version or 0}；请按新版结果重新批准并新建计划')


def _supersede_older(db, version, dataset_ids):
    """Retire an older version only when it is no longer current for any batch."""
    still_current = {v.id for v in active_version_ids(db) if v}
    for older in db.scalars(select(ZoneRuleVersion).where(ZoneRuleVersion.status == 'active',
                                                          ZoneRuleVersion.id != version.id)):
        older_batches = list(db.scalars(select(ZoneRuleBatch)
                                        .where(ZoneRuleBatch.version_id == older.id)))
        if older.id in still_current:
            continue  # the older version still governs batches outside this group
        if any(b.dataset_id in dataset_ids for b in older_batches):
            older.status = 'superseded'
            older.superseded_at = time.time()


def rollback_version(db, version):
    """Restore the exact visible state captured at activation; archives are untouched."""
    if version.status != 'active' or version.id not in {v.id for v in active_version_ids(db)}:
        raise RuleError('仅当前生效的版本可以回滚', 409)
    datasets_in_version = {r.dataset_id for r in db.scalars(
        select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id))}
    for lock in db.scalars(select(ZoneRuleDatasetLock)):
        if lock.dataset_id in datasets_in_version and lock.version_id != version.id:
            raise RuleError('该批次正在执行新的规则重算，完成或失败后才能回滚', 409)
    snapshots = list(db.scalars(select(ZoneRuleSnapshot)
                                .where(ZoneRuleSnapshot.version_id == version.id)))
    if not snapshots:
        raise RuleError('该版本没有可回滚的快照', 409)
    now = time.time()
    requeue = []
    for snap in snapshots:
        job = db.get(Job, snap.job_id)
        if not job:
            continue
        job.zone_version_id = snap.previous_zone_version_id
        previous = db.get(ZoneRuleVersion, snap.previous_zone_version_id) if snap.previous_zone_version_id else None
        job.zone_version = previous.version if previous else None
        job.params = snap.previous_params
        job.result = snap.previous_result
        job.approved = snap.previous_approved
        job.status = snap.previous_status
        job.error = snap.previous_error
        if snap.previous_status in ('queued', 'running'):
            # The job had no visible result before the switch; put it back in
            # the queue under the restored version instead of leaving it stuck.
            job.status = 'queued'
            job.error = ''
            job.result = {}
            requeue.append(job.id)
    for row in db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)):
        state = db.scalar(select(DatasetZoneState)
                          .where(DatasetZoneState.dataset_id == row.dataset_id))
        if row.previous_version_id:
            if state:
                state.version_id = row.previous_version_id
                state.updated_at = now
            else:
                db.add(DatasetZoneState(dataset_id=row.dataset_id,
                                        version_id=row.previous_version_id, updated_at=now))
        elif state:
            db.delete(state)
    version.status = 'rolled_back'
    version.superseded_at = now
    previous_ids = [r.previous_version_id for r in db.scalars(
        select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)) if r.previous_version_id]
    for previous in db.scalars(select(ZoneRuleVersion).where(ZoneRuleVersion.id.in_(previous_ids))):
        if previous.status == 'superseded':
            previous.status = 'active'
    # Plans pinned to the restored version can deliver again; clear the stale
    # marker that the switch had attached to them.
    from src.models import Report
    for plan in db.scalars(select(Report)):
        job = db.get(Job, plan.job_id)
        if job and job.zone_version_id == plan.zone_version_id:
            plan.blocked_reason = ''
    db.flush()
    return requeue


def tick(db):
    """Worker entry: compute pending stages, then finalize any fully settled version."""
    processed = 0
    for stage_id in pending_stages(db)[:3]:
        if compute_stage(db, stage_id):
            processed += 1
    db.commit()
    for version in db.scalars(select(ZoneRuleVersion).where(ZoneRuleVersion.status == 'building')):
        rows = list(db.scalars(select(ZoneRuleBatch).where(ZoneRuleBatch.version_id == version.id)))
        for row in rows:
            settle_batch(db, version.id, row.dataset_id)
        if all(r.status in ('completed', 'failed', 'blocked') for r in rows):
            activated = finalize_version(db, version)
            record(db, 'worker', 'zone.version.activated' if activated else 'zone.version.failed',
                   {'version': version.version, 'id': version.id, 'error': version.error})
        db.commit()
    return processed
