import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const zoneRules={
 current:()=>api('/zone-rules/current'),
 versions:()=>api('/zone-rules/versions'),
 version:id=>api('/zone-rules/versions/'+id),
 progress:()=>api('/zone-rules/progress'),
 create:data=>api('/zone-rules/versions',{method:'POST',body:JSON.stringify(data)}),
 start:id=>api('/zone-rules/versions/'+id+'/start',{method:'POST'}),
 rollback:id=>api('/zone-rules/versions/'+id+'/rollback',{method:'POST'})
};
