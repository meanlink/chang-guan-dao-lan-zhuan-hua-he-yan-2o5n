import {datasets,jobs,zoneRules} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const versionChip=v=>'<span class="version-chip">v'+(v||0)+' '+(v?'规则版本':'基础口径')+'</span>';
const statusChip=(status,label)=>'<span class="status '+esc(status)+'">'+esc(label||status)+'</span>';

export async function zoneRulesPage(){
 const [current,versions,list,allJobs]=await Promise.all([zoneRules.current(),zoneRules.versions(),datasets.list(),jobs.list()]);
 workspace.zoneCurrent=current;workspace.datasets=list;
 const admin=session.user.role==='admin';
 const live=versions.filter(v=>v.status==='building');
 const history=versions.filter(v=>v.id!==null);
 const blocked=versions.filter(v=>v.id!==null&&(v.status==='blocked'||v.status==='failed'));
 // Workbench-oriented helper: map a batch to the raw zones its rules must cover.
 const batchZones=Object.fromEntries(list.map(d=>[d.id,(current.datasets.find(x=>x.dataset_id===d.id)||{}).raw_zones||[]]));

 return heading('05 / ZONE RULES','展区归并规则版本','展区改名或合并后，按规则版本重算所选批次。一条原始计数只归入一个展区；存在歧义或未归属时整组不生效。',
  '<a class="button" href="#/zones" id="refresh-zones">刷新进度 ↻</a>')+
  '<section class="zone-current panel"><div class="section-title"><h2>各批次当前口径</h2><span>同一批次的分析、简报与归档只读同一版本</span></div>'+
  '<div class="table-wrap"><table><thead><tr><th>数据批次</th><th>原始展区</th><th>当前版本</th><th>归并后展区</th><th>进行中重算</th></tr></thead><tbody>'+
  (current.datasets.length?current.datasets.map(d=>'<tr><td>'+esc(d.dataset_name)+'</td><td>'+esc(d.raw_zones.join('、'))+'</td><td>'+versionChip(d.version)+' '+esc(d.version_name)+'</td><td>'+esc(d.zone_options.filter(z=>z!=='全部').join('、')||'—')+'</td><td>'+(d.rebuild_version?('v'+d.rebuild_version.version+' '+esc(d.rebuild_version.name)):'—')+'</td></tr>').join(''):'<tr><td colspan="5">尚无数据批次。</td></tr>')+
  '</tbody></table></div></section>'+
  (live.length?'<section class="panel"><div class="section-title"><h2>正在重算</h2><span>沿用旧版结果，全部成功后一次性切换</span></div>'+live.map(v=>'<div class="zone-live"><div><strong>v'+v.version+' · '+esc(v.name)+'</strong><small>开始 '+date(v.started_at)+'</small></div><div class="progress-list">'+v.batches.map(b=>'<div class="progress-row"><span>'+esc(b.dataset_name)+'</span>'+statusChip(b.status,b.status_label)+'<small>'+b.done_jobs+' / '+b.total_jobs+' 个任务 · 重算前 v'+(b.previous_version||0)+'</small>'+(b.reason||b.error?'<p class="warning">'+esc(b.reason||b.error)+'</p>':'')+'</div>').join('')+'</div></div>').join('')+'</section>':'')+
  (blocked.length?'<section class="panel"><div class="section-title"><h2>被阻断的版本</h2><span>旧版继续生效，可修正后重新建立</span></div><ul class="blocked-list">'+blocked.map(v=>'<li><button class="text-button" data-detail="'+v.id+'">v'+v.version+' · '+esc(v.name)+'</button> '+statusChip(v.status,v.status_label)+'<p>'+esc(v.error)+'</p></li>').join('')+'</ul></section>':'')+
  '<div class="zone-grid"><section class="panel"><div class="section-title"><h2>新建规则版本</h2><span>仅负责人可建立并执行</span></div>'+
  (admin?'<form id="zone-form"><label>版本名称<input name="name" required minlength="2" maxlength="160" placeholder="例如：11 月展区合并 v2"></label><label>说明（可选）<input name="note" maxlength="500" placeholder="记录改名依据或评审结论"></label>'+
   '<div class="rule-editor"><div class="section-title"><h3>归并规则</h3><button type="button" class="small" id="add-rule">+ 添加一行</button></div><div id="rule-rows">'+ruleRow('','')+'</div><p class="hint">每行一条：左为原始展区，右为归并后展区。同一原始展区只能出现一次；链式改名（A→B 且 B→C）视为歧义。批次中所有原始展区都必须被覆盖，否则整组不生效。</p></div>'+
   '<fieldset class="checks"><legend>需要重算的批次</legend>'+(list.length?list.map(d=>'<label class="check"><input type="checkbox" name="dataset" value="'+d.id+'" data-raw="'+esc((batchZones[d.id]||[]).join('、'))+'" checked> '+esc(d.name)+' · '+d.rows+' 条</label>').join(''):'<p class="hint">尚无批次。</p>')+'</fieldset>'+
   '<button type="submit" class="primary">保存为待执行版本</button></form>':'<p class="empty">观察员与分析员可查看版本与进度；建立和执行需业务负责人。</p>')+
  '</section><section><div class="section-title"><h2>版本历史</h2><span>'+versions.length+' 个版本</span></div><div class="version-list">'+
  versions.map(v=>'<article class="version-card '+(v.is_current?'current':'')+'"><header><div><strong>v'+v.version+' · '+esc(v.name)+'</strong><small>'+(v.created_at?date(v.created_at):'系统基础口径')+(v.note?' · '+esc(v.note):'')+'</small></div>'+statusChip(v.status,v.status_label)+'</header>'+
   (v.error?'<p class="warning">'+esc(v.error)+'</p>':'')+
   (v.batches.length?'<div class="version-batches">'+v.batches.map(b=>'<div class="version-batch"><span>'+esc(b.dataset_name)+'</span>'+statusChip(b.status,b.status_label)+'<small>'+b.done_jobs+'/'+b.total_jobs+' 个任务 · 重算前 v'+(b.previous_version||0)+'</small>'+(b.reason||b.error?'<p class="hint">'+esc(b.reason||b.error)+'</p>':'')+'</div>').join('')+'</div>':'')+
   (v.rules?.length?'<details><summary>规则 '+v.rules.length+' 条</summary><p class="rule-map">'+v.rules.map(r=>'<span>'+esc(r.source)+' → '+esc(r.target)+'</span>').join('')+'</p></details>':'')+
   (admin&&v.id?'<footer>'+(v.can_start?'<button class="small primary" data-start="'+v.id+'">开始重算</button>':'')+(v.can_rollback?'<button class="small" data-rollback="'+v.id+'">回滚到上一版</button>':'')+'</footer>':'')+
   '</article>').join('')+'</div></section></div>';
}

function ruleRow(source='',target=''){
 return '<div class="rule-row"><input name="rule-source" placeholder="原始展区" value="'+esc(source)+'" maxlength="80"><span>→</span><input name="rule-target" placeholder="归并后展区" value="'+esc(target)+'" maxlength="80"><button type="button" class="small rule-remove" title="删除此行">×</button></div>';
}

export function bindZoneRules(refresh){
 const form=document.querySelector('#zone-form');
 const rowsBox=document.querySelector('#rule-rows');
 document.querySelector('#refresh-zones')?.addEventListener('click',e=>{e.preventDefault();refresh();});
 if(!form)return;
 document.querySelector('#add-rule').onclick=()=>{rowsBox.insertAdjacentHTML('beforeend',ruleRow());bindRemove();};
 function bindRemove(){rowsBox.querySelectorAll('.rule-remove').forEach(b=>b.onclick=()=>{if(rowsBox.querySelectorAll('.rule-row').length>1)b.closest('.rule-row').remove();});}
 bindRemove();
 submit(form,async f=>{
  const rules=[...rowsBox.querySelectorAll('.rule-row')].map(row=>({source:row.querySelector('[name=rule-source]').value.trim(),target:row.querySelector('[name=rule-target]').value.trim()})).filter(r=>r.source||r.target);
  const dataset_ids=[...form.querySelectorAll('[name=dataset]:checked')].map(c=>Number(c.value));
  if(!rules.length){notify('请至少填写一条归并规则',true);throw new Error('请至少填写一条归并规则');}
  if(!dataset_ids.length){notify('请选择至少一个批次',true);throw new Error('请选择至少一个批次');}
  await zoneRules.create({name:f.get('name'),note:f.get('note')||'',rules,dataset_ids});
  notify('规则版本已保存为待执行，可在版本历史中开始重算');
  await refresh();
 });
 document.querySelectorAll('[data-start]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await zoneRules.start(b.dataset.start);notify('已开始重算，完成前沿用旧版结果');await refresh();}catch(e){notify(e.message,true);b.disabled=false;}});
 document.querySelectorAll('[data-rollback]').forEach(b=>b.onclick=async()=>{if(!confirm('回滚会把该版本涉及的批次恢复到切换前的当前结果；历史归档保持不变。继续？'))return;b.disabled=true;try{await zoneRules.rollback(b.dataset.rollback);notify('已回滚到切换前结果，需重新批准');await refresh();}catch(e){notify(e.message,true);b.disabled=false;}});
 document.querySelectorAll('[data-detail]').forEach(b=>b.onclick=()=>{location.hash='#/zones';notify('版本 v'+b.dataset.detail+' 的阻断原因已显示在上方历史中');});
 // Live refresh while a version is building.
 if(document.querySelector('.zone-live'))setTimeout(()=>{if(location.hash==='#/zones')refresh();},4000);
}
