/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,zone_version_id:number|null,zone_version:number|null}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,zone_version_id:number|null,zone_version:number|null,blocked_reason:string}} ReportSchedule */
/** @typedef {{source:string,target:string}} ZoneRule */
/** @typedef {{dataset_id:number,dataset_name:string,status:string,status_label:string,reason:string,error:string,total_jobs:number,done_jobs:number,previous_version:number|null}} ZoneRuleBatchProgress */
/** @typedef {{id:number|null,version:number,name:string,note:string,rules:ZoneRule[],status:string,status_label:string,error:string,is_current:boolean,can_start:boolean,can_rollback:boolean,batches:ZoneRuleBatchProgress[]}} ZoneRuleVersion */
export {};
