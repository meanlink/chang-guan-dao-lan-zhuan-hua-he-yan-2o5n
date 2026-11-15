import {datasets,jobs,zoneRules} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const zoneSelect=(zones,dataset)=>{const byId=Object.fromEntries(zones.map(z=>[z.dataset_id,z]));
 return '<select name="param-zone">'+((byId[dataset]?.zone_options||['全部']).map(z=>'<option value="'+esc(z)+'" '+(z==='全部'?'selected':'')+'>'+esc(z)+'</option>').join(''))+'</select>';};

export async function workbench(){
 const [list,current]=await Promise.all([datasets.list(),zoneRules.current()]);workspace.datasets=list;workspace.zoneCurrent=current;const m=workspace.meta;
 const byId=Object.fromEntries(current.datasets.map(d=>[d.dataset_id,d]));
 const first=list[0];
 return heading('03 / ANALYSIS LAB',m.workbench_title,'选择业务批次和分析口径。参数、规则版本、输入指纹与计算结论随任务保存，便于复核和复现。')+'<div class="workbench-grid"><section class="panel"><form id="job-form"><label>分析任务名称<input name="name" required minlength="2" value="'+esc(m.name)+' · 复核试算"></label><label>数据批次<select name="dataset_id" required>'+workspace.datasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条 · 规则 v'+((byId[d.id]||{}).version||0)+'</option>').join('')+'</select></label><div class="parameter-grid">'+m.parameters.map(p=>p.key==='zone'
  ?'<label>'+esc(p.label)+zoneSelect(current.datasets,first?.id)+'</label>'
  :(p.type==='select'?'<label>'+esc(p.label)+'<select name="param-'+esc(p.key)+'">'+p.options.map(o=>'<option value="'+esc(o.value)+'" '+(o.value==p.default?'selected':'')+'>'+esc(o.label)+'</option>').join('')+'</select></label>':'<label>'+esc(p.label)+'<input type="number" step="any" name="param-'+esc(p.key)+'" value="'+esc(p.default)+'" min="'+esc(p.min??'')+'" max="'+esc(p.max??'')+'" required></label>')).join('')+'</div><p class="hint" id="zone-hint">展区选项来自该批次当前生效的规则版本（'+(first?(byId[first.id]?.version_name||'基础展区口径'):'无批次')+'）；切换期间新任务绑定提交时可见的版本。规则版本见 <a href="#/zones" class="text-link">展区规则</a>。</p><button type="submit" class="primary" '+(session.user.role==='viewer'||!workspace.datasets.length?'disabled':'')+'>'+esc(m.action_label||'执行分析')+' ↗</button><p class="hint">提交后由后台任务计算。观察员可查看参数和结果，无法提交。</p></form></section><section class="method-sheet"><p class="eyebrow">METHOD / BUSINESS RULE</p><h2>'+esc(m.method)+'</h2><p>'+esc(m.tagline)+'</p><h3>业务判读边界</h3><ul>'+m.limitations.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul><div class="method-trace"><span>输入</span><strong>'+esc(m.dataset_name)+'</strong><span>输出</span><strong>可复核结果 / 规则版本 / 分发归档</strong></div></section></div>';
}

export function bindWorkbench(){
 const form=document.querySelector('#job-form');
 // Zone choices are per-batch: swap them when the selected batch changes.
 form.querySelector('[name=dataset_id]')?.addEventListener('change',e=>{
  const byId=Object.fromEntries((workspace.zoneCurrent?.datasets||[]).map(z=>[z.dataset_id,z]));
  const target=form.querySelector('[name=param-zone]');
  if(!target)return;
  target.innerHTML=(byId[Number(e.target.value)]?.zone_options||['全部']).map(z=>'<option value="'+esc(z)+'">'+esc(z)+'</option>').join('');
  const hint=form.querySelector('#zone-hint');
  if(hint)hint.innerHTML='展区选项来自该批次当前生效的规则版本（'+esc(byId[Number(e.target.value)]?.version_name||'基础展区口径')+'）；切换期间新任务绑定提交时可见的版本。规则版本见 <a href="#/zones" class="text-link">展区规则</a>。';
 });
 submit(form,async f=>{const params={};for(const p of workspace.meta.parameters){const value=f.get('param-'+p.key);params[p.key]=p.type==='number'?Number(value):value;}const j=await jobs.create({name:f.get('name'),dataset_id:Number(f.get('dataset_id')),params});workspace.selectedJob=j.id;notify('分析任务已提交');location.hash='#/results/'+j.id;});
}
