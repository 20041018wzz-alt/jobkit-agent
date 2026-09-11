# 项目档案（示例知识库 · Sample Projects）

## [PROJECT-01] 多智能体客服系统

- 时间与角色：2026.07–08，独立完成
- 技术栈：LangGraph、FastAPI、DeepSeek API、MySQL、Redis、SSE、pytest
- 定位：基于 LangGraph 的多智能体客服，Supervisor 意图分类 + 专家 Agent 条件路由
- 要点：
  1. LLM 意图分类 + 标签归一化三层兜底；`out_of_scope` 固定话术护栏，不调用业务 LLM
  2. 5 个专家 Agent（产品/技术/账单等）按意图条件路由
  3. 同步 Flask 改 FastAPI + httpx 异步：单轮响应从 4 秒级降到 2 秒内
  4. SSE 双流式：节点级状态 + token 级输出
  5. 会话记忆：MySQL 全量 + Redis 最近 5 轮（TTL 24h），未命中回源；存储故障降级到内存
  6. 16 位 trace_id 贯穿全链路日志
  7. 34 个 pytest，MockLLM 只断言结构与路由，不断言文本，避免 LLM 非确定性导致 flaky
- 面试考点：Supervisor vs Handoff vs 路由式；意图识别错误的兜底；多智能体防无限循环；SSE vs WebSocket；Redis 故障降级链路；LLM 输出的可测试性

## [PROJECT-02] RAG 企业知识库问答 Agent

- 时间：2026.08；已开源
- 仓库：github.com/example/rag-knowledge-agent
- 技术栈：FastAPI、RAG、Embedding、Chroma、DeepSeek、Docker、GitHub Actions
- 要点：
  1. 标题感知 + 重叠窗口的文档切分（约 500 字/块、重叠 50 字）；切分粒度 = 检索粒度
  2. Embedding 三后端（API / 本地 BGE / Mock）+ 工厂模式 + 失败自动降级
  3. Chroma 不可用时降级纯 Python 内存向量库，保证 demo 可跑
  4. Query Rewrite → top-k（默认 4）→ 相关性阈值兜底，低于阈值直接回"知识库中没有相关信息"
  5. 强制 `[n]` 引用标注并校验编号边界，防编造引用
  6. golden set 评测：Recall@4 = 5/5 = 100%
  7. 26 个离线 pytest；Dockerfile 非 root + HEALTHCHECK + compose 数据卷
  8. 优化方向（尚未实现）：Rerank 重排、BM25 + 向量混合检索、Parent-child chunk、Token 级流式
- 面试考点：切分粒度取舍；top-k 与阈值怎么定；RAG vs 微调；如何证明 RAG 靠谱；引用溯源防幻觉；向量库替换成本

## [PROJECT-03] 智能作业调度 Agent 系统

- 时间：2026.07
- 技术栈：Python、Pydantic v2、DAG 拓扑排序、LangChain（可选）
- 要点：自然语言 → DAG 自动调度；依赖感知、优先级、环检测、失败重试；LLM / 规则引擎双模式；插件化 10 个工具；10 个单元测试；5 个演示场景（无人机巡检、设备报告、调度、作业流水线、自定义工具）
- 面试考点：DAG 环检测；任务重试与幂等；LLM 输出结构不合法的兜底

## [PROJECT-04] 外卖商城系统

- 时间：2025.10–2026.01
- 技术栈：Spring Boot 3.0 / Java 17 / MyBatis-Plus / MySQL 8 / uni-app / Vue Admin
- 要点：11–12 个模块、11 张表与索引、统一 ResultVo + 全局异常；微信 code2session 换 openid；订单流转；同事务 `UPDATE stock = stock - n WHERE stock >= n` 乐观锁防超卖，失败整体回滚；小程序 6 页 + 后台共用一套接口

## [PROJECT-05] 软件成本测算系统

- 时间：2026.05
- 技术栈：Spring Boot 2.7 / JPA / H2 / PDFBox / Commons Math / Chart.js
- 要点：中位数、IQR、CV、Kendall W 统计引擎；CV < 5% 且 W ≥ 0.7 双收敛判定；专家注册/模块配置/多轮问卷/统计报表全流程 API；PDF 报告导出

## [PROJECT-06] 其他课程与全栈项目

- 学生选课管理系统（2025.12–2026.01）：JSP / Servlet / JDBC / MySQL / Tomcat / Session；管理员与学生角色权限、JavaBean 分层
- 备忘录管理系统（2026.01）：Spring Boot 2.7 + MyBatis-Plus + uni-app(Vue3)；组合筛选、统一请求层、三端适配、20 余组用例
- 博客系统（2025.11–2026.01）：Spring Boot + MyBatis-Plus + Swagger + uni-app；注册登录、信息流、点赞收藏、登录态持久化与路由拦截
- WhichAnimal 性格测试 App（2026.05–06）：HarmonyOS 5.0 ArkTS / ArkUI；一周上手；4 种题型 10 题；四维评分 + 分级阈值 + 兜底
- 课程实践：人人开源 renren-security 前后端分离项目部署（JDK 17、Maven 3.9.11、MySQL 8、renren-ui 的 npm 构建与登录接口调试）

## [PROJECT-10] 数字口径冲突表

不同简历版本之间存在数字不一致，对外材料以讲解文档的"数字口径速查"为准：

| 项目 | 冲突口径 | 采用 |
| --- | --- | --- |
| 多智能体客服系统 pytest 数 | 27 / 34 | 34 |
| RAG 知识库 Agent pytest 数 | 16 / 25 / 26 | 26 |
| RAG GitHub 链接 | 仅部分版本写了 | 写 |
| 期望工作地 | 杭州 / 上海 | 按岗位版本决定 |

规则：发现版本间数字打架时明确指出并让本人拍板，不自行抹平；改完统一回填所有版本。
