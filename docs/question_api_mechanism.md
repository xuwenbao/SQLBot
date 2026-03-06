# `POST /chat/question` 接口实现机制梳理（SQLBot）

> 目的：把 SQLBot 的问数入口（`question` 接口）从「路由注册 → 请求模型 → 快速命令分流 → 异步流式执行 → 落库」完整串起来，并标注关键代码位置（文件+行号），方便日后快速定位。
>
> 深挖参考：更完整的 `LLMService.run_task` 端到端执行细节见 `projects/sqlbot/docs/run_task_flow.md`。

---

## 1) 路由与完整 URL 的拼装方式

### 1.1 `question` 接口所在 router

- 路由文件：`projects/sqlbot/backend/apps/chat/api/chat.py`
- router 前缀：`/chat`
  - 代码：`backend/apps/chat/api/chat.py:L29`

### 1.2 router 被挂载到 API v1

- `api_router.include_router(chat.router)` 将 chat router 注册到总路由
  - 代码：`backend/apps/api.py:L14-L26`
- `app.include_router(api_router, prefix=settings.API_V1_STR)` 将总路由挂到 v1 前缀
  - 代码：`backend/main.py:L206`

### 1.3 API v1 前缀由配置计算得到

- `API_V1_STR = CONTEXT_PATH + "/api/v1"`
  - 代码：`backend/common/core/config.py:L52-L53`

### 1.4 最终接口路径

最终路径由三段组成：

- `{CONTEXT_PATH}`（配置项）
- `/api/v1`（`API_V1_STR` 固定片段）
- `/chat/question`（chat router prefix + endpoint path）

因此完整 URL 为：

`{CONTEXT_PATH}/api/v1/chat/question`

---

## 2) 接口入口与权限机制

### 2.1 入口函数

- `POST /chat/question`：`question_answer()`
  - 代码：`backend/apps/chat/api/chat.py:L261-L265`

### 2.2 权限校验

该接口使用 `require_permissions` 做权限检查，权限 key 表达式绑定在 `request_question.chat_id`：

- 代码：`backend/apps/chat/api/chat.py:L262-L263`

---

## 3) 请求模型（Request Body）

接口请求体类型为 `ChatQuestion`：

- `ChatQuestion`：至少包含 `chat_id`，可选 `datasource_id`
  - 代码：`backend/apps/chat/models/chat_model.py:L312-L315`
- `question` 等字段来自其父类 `AiModelQuestion`
  - 代码：`backend/apps/chat/models/chat_model.py:L212-L230`

---

## 4) 快速命令（Quick Command）分流

入口 `question_answer()` 会进入 `question_answer_inner()`，其第一步是解析快速命令：

- 解析：`parse_quick_command(request_question.question)`
  - 代码：`backend/apps/chat/api/chat.py:L268-L275`

### 4.1 支持的命令

`QuickCommand` 枚举定义了当前支持的命令：

- `/regenerate`：重新生成（基于上一条或指定 record）
- `/analysis`：分析（当前注释提示 in_chat 暂不支持）
- `/predict`：预测（当前注释提示 in_chat 暂不支持）

代码：

- `backend/apps/chat/models/chat_model.py:L57-L61`

### 4.2 命令解析规则（必须位于末尾，可带 record_id）

`parse_quick_command` 要求命令出现在字符串末尾，并支持 `"/regenerate 123"` 这种带数字参数的形式：

- 代码：`backend/common/utils/command_utils.py:L7-L97`

### 4.3 `/regenerate` 的基问题拼接逻辑

当走 regenerate 分支时，接口会：

- 读取目标 record（或取最近一次 record）
  - 代码：`backend/apps/chat/api/chat.py:L279-L318`
- 递归追溯原始提问（避免多次 regenerate 造成“基问题丢失”）
  - `find_base_question()`：`backend/apps/chat/api/chat.py:L248-L258`
  - 拼接 `text_before_command + base_question_text`：`backend/apps/chat/api/chat.py:L319-L322`
- 将 `request_question.regenerate_record_id` 设置为目标 record，并复用正常问数流程 `stream_sql()`
  - 代码：`backend/apps/chat/api/chat.py:L323-L327`

---

## 5) 正常问数主流程：`stream_sql`（异步 + SSE 流式）

当没有快速命令（或 regenerate 进入复用路径），会进入 `stream_sql()`。

其关键机制是：

1. 创建 `LLMService`
2. 初始化并落库创建 `ChatRecord`
3. 异步启动后台任务（线程池）
4. 通过 `await_result()` 不断从队列取 chunk，作为 SSE 输出

代码位置：

- 创建服务、建记录、启动后台任务：`backend/apps/chat/api/chat.py:L360-L367`
- 返回 SSE：`backend/apps/chat/api/chat.py:L381-L383`

---

## 6) 记录创建与落库（ChatRecord）

### 6.1 `LLMService.init_record` 触发保存提问

- `LLMService.init_record()` 调用 `save_question(...)`
  - 代码：`backend/apps/chat/task/llm.py:L259-L260`

### 6.2 `save_question` 写入 `chat_record`

`save_question()` 会创建一条 `ChatRecord`，写入：

- `question`
- `chat_id`
- `datasource / engine_type`（来自当前 Chat 会话）
- `ai_modal_id`
- `regenerate_record_id`（若有）

代码：

- `backend/apps/chat/curd/chat.py:L747-L776`

### 6.3 `ChatRecord` 表结构（存储分阶段结果）

`ChatRecord` 上保存了 SQL 生成、SQL 执行、图表生成、分析/预测等多个阶段产物字段：

- 代码：`backend/apps/chat/models/chat_model.py:L102-L131`

---

## 7) 后台执行器：`LLMService.run_task`（问数的“发动机”）

`question` 接口最终会通过 `LLMService.run_task_async()` 把任务丢到线程池执行，并把产出的 chunk 写入 `chunk_list`：

- `run_task_async / run_task_cache / await_result`：详见 `projects/sqlbot/docs/run_task_flow.md`

本接口关注的核心点是：**`question` 入口本身不是“生成 SQL/执行 SQL”的地方，它只是任务启动器与 SSE 输出层；真正的智能问数链路在 `LLMService.run_task()`。**

在 `run_task()` 内部，关键步骤包括（只列高层入口，细节见 `run_task_flow.md`）：

- 数据源选择（会话未绑定时）：`select_datasource`（`backend/apps/chat/task/llm.py:L510-L646`）
- 表结构选择（RAG）：`choose_table_schema`（`backend/apps/chat/task/llm.py:L340-L350`）
- 生成 SQL：`generate_sql`（`backend/apps/chat/task/llm.py:L649-L683`）
- 校验并保存 SQL：`check_sql / check_save_sql`（`backend/apps/chat/task/llm.py:L839-L869`、`L911-L917`）
- 执行 SQL：`execute_sql`（`backend/apps/chat/task/llm.py:L1016-L1029`）
- 保存数据：`save_sql_data`（`backend/apps/chat/task/llm.py:L997-L1009`）
- 生成图表：`generate_chart`（`backend/apps/chat/task/llm.py:L803-L837`）
- 解析/保存图表：`check_save_chart`（`backend/apps/chat/task/llm.py:L919-L978`）

---

## 8) SSE 输出（前端看到的“事件流”）

`question` 接口的响应类型是 `text/event-stream`，典型输出由 `LLMService.run_task()` 内部 yield 多段 `data:{json}\n\n` 组成。

常见事件类型在 `LLMService.run_task()` 内部可见（举例）：

- `id`：返回 record_id（`backend/apps/chat/task/llm.py:L1088`）
- `regenerate_record_id`：若是 regenerate（`backend/apps/chat/task/llm.py:L1089-L1091`）
- `question`：回显问题（`backend/apps/chat/task/llm.py:L1092-L1093`）
- `sql-result`：LLM 生成 SQL 的流式片段（`backend/apps/chat/task/llm.py:L1129-L1132`）
- `sql`：格式化 SQL（`backend/apps/chat/task/llm.py:L1193-L1196`）
- `sql-data`：执行成功标记（`backend/apps/chat/task/llm.py:L1230`）
- `chart-result`：LLM 生成 chart 的流式片段（`backend/apps/chat/task/llm.py:L1274-L1276`）
- `chart`：最终 chart JSON（`backend/apps/chat/task/llm.py:L1288-L1290`）
- `finish`：结束标记（例如 `backend/apps/chat/task/llm.py:L1211`、`L1237`、`L1306`）
- `error`：错误（例如 `backend/apps/chat/task/llm.py:L1355`；入口层也会返回 `error`：`backend/apps/chat/api/chat.py:L344-L352`）

---

## 9) 接口职责总结（一句话）

`POST /chat/question` 的职责是：**解析（可选）快速命令 → 创建 chat_record → 异步启动 `LLMService` 任务 → 用 SSE 把任务过程与结果流式返回**；

而“选数据源/选表/RAG/生成 SQL/执行 SQL/生成图表/落库”全部发生在 `LLMService.run_task()` 链路中。

