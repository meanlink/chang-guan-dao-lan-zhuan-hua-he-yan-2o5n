# 场馆导览转化核验

分类独立性检验的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览、审计轨迹，以及展区归并规则版本。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery、ZoneRuleVersion（规则版本）。

## 展区归并规则版本
展区改名或合并后，旧批次仍按旧名称统计会无法横向比较。负责人可在「展区规则版本」页建立规则版本、选择批次并重算：

- 规则逐条声明「原始展区 → 归并后展区」。一条原始计数只归入一个展区；原展区重复、形成链式歧义（A→B 且 B→C）或批次中存在未归属展区时，整组规则不生效，版本直接阻断并显示原因。
- 重算写入暂存区，当前结果、简报与归档保持旧版不变；所选批次全部成功后在一个事务中一次性切换，任何批次失败都保留旧版，失败版本可再次启动或回滚。
- 分析结果、分发计划与归档都携带规则版本号。切换与新建分析、定时分发并发时，每份结果与简报只含同一版本：新版本下结果必须重新批准；固定旧版本的计划不会混发并显示阻断原因；历史归档不被改写。
- 切换前已排队/运行中的旧任务晚完成时只记录丢弃审计，不覆盖新版结果；规则重算开始后新建的任务切换时标记为「已作废」。
- 回滚恢复切换前的可见结果与审批状态，并把切换期间尚无结果的任务重新排队；归档保持原样。
- 页面可查版本历史、各批次重算进度、阻断/失败原因与当前生效版本。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18204；后端文档 http://localhost:19204/docs；数据库宿主端口 17704。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、规则版本维护与回滚、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准、安排分发或维护规则版本|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed/superseded；RuleVersionStatus：ready/building/active/blocked/failed/superseded/rolled_back。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。规则版本模型在 models/zone_rule.py、models/zone_state.py，业务逻辑在 services/zone_rules.py，worker 通过 `zone_rules.tick` 推进重算与原子切换。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=guide-chi；FRONTEND_PORT=18204；BACKEND_PORT=19204；DB_PORT=17704；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件，并在同一循环推进规则版本重算。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1005/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
