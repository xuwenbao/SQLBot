# 问数任务端到端流程（以 `run_task` 为核心牵引）

> 说明：流程核心在 `LLMService.run_task`，入口通过 `run_task_async` 异步执行并流式输出。本文件所有步骤均标注代码位置（文件+行号），便于精确对照源码。

---

## 0) 入口与运行机制（异步 + 流式）

**核心实现**
- `run_task_async` 将任务提交到线程池；`run_task_cache` 将生成的 chunk 放入队列；`await_result` 轮询输出。  
  - 代码：`backend/apps/chat/task/llm.py:L1057-L1067`（run_task_async / run_task_cache）  
  - 代码：`backend/apps/chat/task/llm.py:L1043-L1055`（await_result）

**原理说明**
- 使用 `ThreadPoolExecutor` 在后台执行完整流程，主线程通过 `chunk_list` 实现流式输出，保障实时响应体验。

---

## 1) Session 初始化 + RAG/Prompt 准备

**核心实现**
- `run_task` 中创建 DB session，并在已有数据源时进行术语/训练样本/提示词过滤与消息初始化。  
  - 代码：`backend/apps/chat/task/llm.py:L1073-L1085`

**依赖方法与原理**
- **术语召回**：`filter_terminology_template` 调用语义召回后注入术语模板。  
  - 代码：`backend/apps/chat/task/llm.py:L276-L291`
- **训练样本召回**：`filter_training_template` 注入 SQL 示例模板。  
  - 代码：`backend/apps/chat/task/llm.py:L314-L335`
- **自定义提示词**：`filter_custom_prompts` 根据类型加载提示词。  
  - 代码：`backend/apps/chat/task/llm.py:L293-L312`
- **消息初始化**：`init_messages` 选择表结构 + 拼接系统 prompt 与历史上下文。  
  - 代码：`backend/apps/chat/task/llm.py:L204-L257`
- **表结构选择**：`choose_table_schema` 调用 `get_table_schema` 生成 schema。  
  - 代码：`backend/apps/chat/task/llm.py:L340-L350`  
  - 表结构筛选（含表嵌入 Top-N）：`backend/apps/datasource/crud/datasource.py:L431-L532`

**原理说明**
- 在进入 LLM 生成前，将“术语/训练样本/表结构/自定义提示词”作为上下文增强（RAG），确保模型更贴合业务语义与结构。

---

## 2) 返回记录信息（首屏反馈）

**核心实现**
- 立即向前端输出 `record_id`、`regenerate_record_id` 与问题文本。  
  - 代码：`backend/apps/chat/task/llm.py:L1086-L1099`

**原理说明**
- 通过 SSE 先返回记录信息，前端可立即渲染会话框与日志占位。

---

## 3) 数据源选择（若会话未绑定）

**核心实现**
- 若 `self.ds` 为空，调用 `select_datasource` 让 LLM 选择数据源。  
  - 代码：`backend/apps/chat/task/llm.py:L1101-L1115`
- `select_datasource` 会先用 embedding 缩小候选，再让 LLM 决策。  
  - 代码：`backend/apps/chat/task/llm.py:L510-L646`
- 向量候选缩减逻辑：`get_ds_embedding`  
  - 代码：`backend/apps/datasource/embedding/ds_embedding.py:L18-L88`

**原理说明**
- 先用语义相似度缩小候选数据源，再用 LLM 做最终选择，减少误选概率并提高效率。

---

## 4) 数据源合法性校验（历史会话）

**核心实现**
- 若已有 `self.ds`，调用 `validate_history_ds` 校验数据源是否仍有效。  
  - 代码：`backend/apps/chat/task/llm.py:L1116-L1117`  
  - 方法实现：`backend/apps/chat/task/llm.py:L1538-L1556`

**原理说明**
- 避免会话绑定了已删除或权限变化的数据源导致后续错误。

---

## 5) 连接检查（数据库健康校验）

**核心实现**
- 调用 `check_connection` 做连接验证。  
  - 代码：`backend/apps/chat/task/llm.py:L1119-L1122`  
  - 实现：`backend/apps/db/db.py:L173-L205`

**原理说明**
- SQL 生成前先校验数据源可用性，避免后续执行失败。

---

## 6) SQL 生成（LLM）

**核心实现**
- `generate_sql` 通过 LLM 生成 SQL JSON，并写入日志与记录。  
  - 代码：`backend/apps/chat/task/llm.py:L1124-L1133`  
  - 方法实现：`backend/apps/chat/task/llm.py:L649-L683`

**原理说明**
- LLM 以 `sql_message`（含 System+Human+历史上下文）生成 JSON 结构的 SQL，便于后续解析与校验。

---

## 7) SQL 解析 + 标题生成

**核心实现**
- 解析生成结果，提取图表类型与简短标题。  
  - 代码：`backend/apps/chat/task/llm.py:L1138-L1153`  
  - `get_chart_type_from_sql_answer`：`backend/apps/chat/task/llm.py:L872-L889`  
  - `get_brief_from_sql_answer`：`backend/apps/chat/task/llm.py:L892-L909`

**原理说明**
- LLM 返回的 JSON 同时包含 `chart-type` 与 `brief`，用于决定后续图表类型和会话标题。

---

## 8) SQL 校验 + 权限改写（Row-Level）

**核心实现**
- 解析 SQL：`check_sql`  
  - 代码：`backend/apps/chat/task/llm.py:L1162-L1164`  
  - 方法实现：`backend/apps/chat/task/llm.py:L839-L869`
- 行级权限改写：`generate_filter`  
  - 代码：`backend/apps/chat/task/llm.py:L1173-L1179`  
  - 方法实现：`backend/apps/chat/task/llm.py:L786-L791`
- 行权限规则来源：`get_row_permission_filters`  
  - 代码：`backend/apps/datasource/crud/permission.py:L14-L45`
- 动态数据源 SQL：`generate_assistant_dynamic_sql`  
  - 代码：`backend/apps/chat/task/llm.py:L1168-L1182`  
  - 方法实现：`backend/apps/chat/task/llm.py:L728-L741`
- SQL 保存：`check_save_sql`  
  - 代码：`backend/apps/chat/task/llm.py:L1176-L1186`  
  - 方法实现：`backend/apps/chat/task/llm.py:L911-L917`

**原理说明**
- 对 LLM 输出进行 JSON 解析与合法性校验；若需权限过滤或动态数据源则二次生成 SQL，再保存最终 SQL。

---

## 9) SQL 回传（格式化）

**核心实现**
- SQL 格式化并流式输出。  
  - 代码：`backend/apps/chat/task/llm.py:L1193-L1199`

**原理说明**
- 前端获得格式化 SQL，便于展示与审计。

---

## 10) SQL 执行 + 数据保存

**核心实现**
- 执行 SQL：`execute_sql`  
  - 代码：`backend/apps/chat/task/llm.py:L1216-L1222`  
  - 方法实现：`backend/apps/chat/task/llm.py:L1016-L1029`
- 数据保存：`save_sql_data`  
  - 代码：`backend/apps/chat/task/llm.py:L1228-L1232`  
  - 方法实现：`backend/apps/chat/task/llm.py:L997-L1009`
- 大数安全转换：`convert_large_numbers_in_object_array`  
  - 代码：`backend/apps/chat/task/llm.py:L1225-L1226`

**原理说明**
- SQL 执行后先做数据安全处理，再保存结果，用于图表生成/下载/分析。

---

## 11) 早退机制（仅 SQL / 查询数据）

**核心实现**
- 如果 `finish_step` ≤ `GENERATE_SQL` 或 `QUERY_DATA`，则提前返回。  
  - 代码：`backend/apps/chat/task/llm.py:L1209-L1214`  
  - 代码：`backend/apps/chat/task/llm.py:L1234-L1257`

**原理说明**
- 根据业务场景可只返回 SQL 或数据，不生成图表。

---

## 12) 图表生成（LLM）

**核心实现**
- 构建 used_tables_schema 并生成图表 JSON。  
  - 代码：`backend/apps/chat/task/llm.py:L1259-L1278`
- `generate_chart` 负责图表 Prompt 与 LLM 输出。  
  - 代码：`backend/apps/chat/task/llm.py:L803-L837`

**原理说明**
- 图表生成依赖“SQL + 表结构 + 数据字段”进行二次 LLM 推断。

---

## 13) 图表解析与保存

**核心实现**
- 解析图表 JSON 并保存。  
  - 代码：`backend/apps/chat/task/llm.py:L1280-L1290`  
  - 方法实现：`backend/apps/chat/task/llm.py:L919-L978`

**原理说明**
- 对图表 JSON 做字段标准化（如字段小写），保证可视化组件兼容。

---

## 14) 图表图片生成（非表格）

**核心实现**
- 调用 MCP 图表渲染服务生成图片。  
  - 代码：`backend/apps/chat/task/llm.py:L1309-L1333`  
  - 具体请求：`backend/apps/chat/task/llm.py:L1585-L1639`

**原理说明**
- 图表 JSON + 数据 → MCP 渲染服务 → 返回图片 URL，便于前端展示。

---

## 15) 异常处理与收尾

**异常处理**
- 捕获所有异常并保存错误日志，同时按流式或 JSON 方式返回错误。  
  - 代码：`backend/apps/chat/task/llm.py:L1339-L1363`  
  - `save_error`：`backend/apps/chat/task/llm.py:L994-L995`

**收尾**
- 结束记录并释放 session。  
  - 代码：`backend/apps/chat/task/llm.py:L1365-L1366`  
  - `finish_record` 调用：`backend/apps/chat/task/llm.py:L1013-L1014`

---

# ✅ 总结视图（run_task 核心链路）

```
run_task
 ├─ session & RAG 准备
 ├─ 首屏信息返回
 ├─ 数据源选择/校验
 ├─ 连接检查
 ├─ SQL 生成 → 校验 → 权限改写
 ├─ SQL 执行 & 数据保存
 ├─ 图表生成 & 保存
 ├─ 图片生成（可选）
 └─ 异常处理 & finish
```

