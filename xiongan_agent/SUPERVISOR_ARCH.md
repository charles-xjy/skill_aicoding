# Supervisor 模式完整重构 - 架构文档

## 📋 目录
1. [核心改进点](#核心改进点)
2. [架构设计](#架构设计)
3. [数据流](#数据流)
4. [关键模块](#关键模块)
5. [与旧版本的对比](#与旧版本的对比)
6. [使用指南](#使用指南)

---

## 核心改进点

### 🔴 旧版本 (try.py) 的问题

| 问题 | 影响 | 严重性 |
|------|------|--------|
| **工具混淆** | `task_tool` 每次都重新创建子图，导致资源浪费 | 🔴 高 |
| **无共享 Checkpointer** | 主图无法保存检查点，子图记忆隔离 | 🔴 高 |
| **State 不足** | 只有 messages 和 todo，无法追踪完整执行链路 | 🟡 中 |
| **Thread ID 混乱** | 主图和子图 thread_id 完全独立，无追踪链路 | 🟡 中 |
| **错误处理简陋** | 异常捕获后无重试逻辑 | 🟡 中 |
| **工具方式不纯** | 把子图包装成工具，不是真正的 Supervisor 模式 | 🔴 高 |

### ✅ 新版本 (supervisor.py) 的改进

```
旧架构：
START → Agent --[工具]--> task_tool --创建子图--> 子图 → END
                   ↑__________________|

新架构：
START → Supervisor --[条件边]--> ImageAgent (共享 Checkpointer)
            ↑                        |
            └────────────────────────┘
            ↓
        SearchAgent (共享 Checkpointer)
            |
            └────→ END
```

**改进清单：**
- ✅ **1. 共享 Checkpointer**：主图和子图使用同一 Redis 连接
- ✅ **2. 子图注册模式**：使用 `add_node()` 注册子图，不是工具
- ✅ **3. 结构化 State**：完整的执行追踪和日志
- ✅ **4. 层级 Thread ID**：`main_001` → `sub_image_agent_of_main_001`
- ✅ **5. 条件路由**：根据任务类型自动分发到不同子图
- ✅ **6. 错误恢复**：内置 3 次重试机制
- ✅ **7. 执行日志**：完整的时间戳和链路追踪

---

## 架构设计

### 整体结构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Supervisor Graph                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐                                          │
│  │   START      │                                          │
│  └──────┬───────┘                                          │
│         │                                                  │
│         ▼                                                  │
│  ┌──────────────────────────────────────┐                │
│  │   Supervisor Node                     │                │
│  │ - 分析用户需求                       │                │
│  │ - 决策分发任务                       │                │
│  │ - 生成任务描述                       │                │
│  └──────┬───────────────────┬───────────┘                │
│         │ decision          │                             │
│         ▼                   ▼                             │
│  ┌─────────────────┐  ┌──────────────────┐              │
│  │  ImageAgent     │  │  SearchAgent     │              │
│  │                 │  │                  │              │
│  │ - 下载卫星影像  │  │ - 搜索资料信息   │              │
│  │ - 地理对比分析  │  │ - 获取最新新闻   │              │
│  │                 │  │                  │              │
│  │ (共享子图)      │  │ (共享子图)       │              │
│  └────────┬────────┘  └────────┬─────────┘              │
│           │                    │                         │
│           └────────┬───────────┘                         │
│                    ▼                                      │
│         (错误重试循环)                                    │
│                    │                                      │
│           ┌────────▼────────┐                            │
│           │ Supervisor 决策  │                            │
│           │ 继续 OR 结束     │                            │
│           └────────┬────────┘                            │
│                    │                                      │
│                    ▼                                      │
│              ┌──────────┐                                │
│              │   END    │                                │
│              └──────────┘                                │
│                                                          │
│  ┌─────────────────────────────────────────┐            │
│  │   共享资源：AsyncRedisSaver (Checkpointer)  │            │
│  │   - 消息历史存储                          │            │
│  │   - 执行状态快照                          │            │
│  │   - 线程安全的记忆管理                    │            │
│  └─────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

### 关键特性对比表

| 特性 | 旧版本 | 新版本 |
|------|--------|--------|
| **Checkpointer 管理** | 每个工具自己管理 | 主图创建，所有子图共享 |
| **子图实例化** | 每次调用创建新实例 | 编译时创建，复用 |
| **State 结构** | `messages` + `todo` | `messages` + `task_history` + `execution_log` |
| **Thread ID** | 独立 | 层级制 |
| **错误处理** | 简单异常捕获 | 3 次重试 + 日志记录 |
| **路由方式** | 工具调用 | 条件边 |
| **执行追踪** | 无 | 完整时间戳日志 |

---

## 数据流

### 流程 1：正常执行流

```
1. 用户输入
   └─> "请分析2020-2025年的卫星影像变化"

2. Supervisor 决策
   ├─> 解析需求 (NLP)
   ├─> 判断类型 → "image_agent"
   └─> 生成任务: "下载北邮沙河校区2020和2025年的影像"

3. 路由到 ImageAgent
   ├─> 创建子图实例
   ├─> 设置 thread_id: "sub_image_agent_of_main_001"
   ├─> 执行任务（调用地图工具、下载影像）
   └─> 返回结果

4. 结果合并
   ├─> 提取最后的 AI 响应
   ├─> 更新 task_history
   └─> 设置 next_step = "supervisor"

5. 回到 Supervisor
   ├─> 分析子图结果
   ├─> 判断是否需要进一步处理
   │  ├─> 需要 → 分派到另一个子图
   │  └─> 完成 → next_step = "end"
   └─> 最终输出给用户

6. 结束
   └─> 所有消息和日志保存到 Redis
```

### 流程 2：错误重试流

```
1. 子图执行异常
   └─> Exception caught in try-except

2. 重试检查
   ├─> retry_count < 2?
   ├─> YES → retry_count++, 重新执行
   └─> NO  → 标记失败，返回错误信息

3. 最多 3 次尝试
   Attempt 1: ❌ Failed
   Attempt 2: ❌ Failed
   Attempt 3: ❌ Failed
   └─> 返回错误消息给用户

4. Supervisor 决策
   └─> next_step = "supervisor" (可选择结束或尝试其他方案)
```

### 流程 3：多步骤任务流

```
用户: "请根据卫星影像介绍北邮近年发展，然后搜索相关新闻"

执行序列：
┌──────────────────────────────────────┐
│ Step 1: Supervisor 分析需求           │
│ Decision: image_agent                 │
│ Task: "下载2020-2025卫星影像"         │
└──────────────────────────────────────┘
                ▼
┌──────────────────────────────────────┐
│ Step 2: ImageAgent 执行               │
│ Output: "附上对比分析..."             │
│ next_step = "supervisor"              │
└──────────────────────────────────────┘
                ▼
┌──────────────────────────────────────┐
│ Step 3: Supervisor 评估                │
│ 分析: "影像分析完成，需要搜索新闻"   │
│ Decision: search_agent                │
│ Task: "搜索北京邮电大学沙河校区新闻" │
└──────────────────────────────────────┘
                ▼
┌──────────────────────────────────────┐
│ Step 4: SearchAgent 执行               │
│ Output: "最新新闻：..."               │
│ next_step = "supervisor"              │
└──────────────────────────────────────┘
                ▼
┌──────────────────────────────────────┐
│ Step 5: Supervisor 总结                │
│ 所有任务完成                          │
│ Decision: end                         │
└──────────────────────────────────────┘
                ▼
              ✅ 完成
```

---

## 关键模块

### 1. State 定义

```python
SupervisorState = {
    "messages": [],              # 对话消息历史（支持累加）
    "current_task": None,        # 当前分配的任务
    "task_history": [],          # 已完成的任务列表
    "next_step": "supervisor",   # 下一步: image_agent|search_agent|supervisor|end
    "execution_log": [],         # 执行日志（时间戳+内容）
    "retry_count": 0             # 当前任务的重试计数
}
```

**设计解释：**
- `messages`：使用 `Annotated[List, operator.add]` 支持自动合并
- `current_task`：纯文本，由 Supervisor 生成
- `task_history`：记录每个已执行的任务及其结果
- `next_step`：控制图的路由，与 `should_continue()` 配合
- `execution_log`：完整的执行追踪，便于调试和可观测性

### 2. Supervisor 节点

**职责：**
1. 分析用户输入
2. 决策分发
3. 生成任务描述

**实现：**
```python
async def supervisor_node(state: Dict) -> Dict:
    # 1. 构建系统提示，包含任务历史
    system_prompt = SystemMessage(content=f"""
你是任务 Supervisor。根据以下任务历史和用户需求决策：
{task_summary}

输出格式：
{{"decision": "image_agent|search_agent|end", 
  "task": "具体任务描述", 
  "reasoning": "决策原因"}}
""")
    
    # 2. 调用模型
    response = await model.ainvoke([system_prompt] + messages)
    
    # 3. 解析 JSON 响应
    decision_data = json.loads(extract_json(response.content))
    
    # 4. 更新状态
    return {
        "messages": [response],
        "current_task": decision_data["task"],
        "next_step": decision_data["decision"],
        "execution_log": [new_log_entry]
    }
```

**优势：**
- 决策完全由 LLM 驱动（可扩展）
- JSON 格式化响应易于解析
- 决策历史保留便于分析

### 3. 子图包装器工厂

**工厂函数 `create_subgraph_node()`**

```python
async def create_subgraph_node(subgraph_name: str, checkpointer):
    factory = subgraph_factories[subgraph_name]
    
    async def subgraph_node(state: Dict, config: Dict) -> Dict:
        # 关键：从主图配置中提取 parent_thread_id
        parent_thread_id = config["configurable"]["thread_id"]
        sub_thread_id = f"sub_{subgraph_name}_of_{parent_thread_id}"
        
        # 创建子图（共享 checkpointer）
        subgraph = await factory(checkpointer=checkpointer)
        
        # 执行并收集结果
        result = await subgraph.ainvoke(
            inputs,
            {"configurable": {"thread_id": sub_thread_id}},
        )
        
        # 返回结构化结果
        return {
            "messages": [formatted_result],
            "task_history": [task_record],
            "next_step": "supervisor"
        }
    
    return subgraph_node
```

**关键特性：**
- **共享 Checkpointer**：传入同一个 checkpointer，确保记忆共享
- **层级 Thread ID**：`sub_image_agent_of_main_001` 便于追踪调用链
- **结构化返回**：返回字典而非字符串，保留元数据
- **错误恢复**：内置 3 次重试逻辑

### 4. 条件路由

```python
def should_continue(state: Dict) -> str:
    """根据 next_step 决定路由"""
    next_step = state.get("next_step", "end")
    
    route_map = {
        "image_agent": "image_agent",
        "search_agent": "search_agent",
        "supervisor": "supervisor",
        "end": END,
    }
    
    return route_map.get(next_step, END)
```

**工作原理：**
```
Supervisor 输出 next_step = "image_agent"
        ▼
should_continue() 返回 "image_agent"
        ▼
图路由到 ImageAgent 节点
        ▼
ImageAgent 返回后，next_step = "supervisor"
        ▼
should_continue() 返回 "supervisor"
        ▼
回到 Supervisor 节点
```

### 5. 图编译

```python
async def create_supervisor_graph(db_uri, thread_id):
    # 1. 创建共享 Checkpointer
    checkpointer = AsyncRedisSaver.from_conn_string(db_uri)
    
    # 2. 创建图
    workflow = StateGraph(dict)
    
    # 3. 添加节点
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("image_agent", await create_subgraph_node("image_agent", checkpointer))
    workflow.add_node("search_agent", await create_subgraph_node("search_agent", checkpointer))
    
    # 4. 添加边
    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", should_continue, {...})
    workflow.add_edge("image_agent", "supervisor")
    workflow.add_edge("search_agent", "supervisor")
    
    # 5. 编译（关键：传入 checkpointer）
    graph = workflow.compile(checkpointer=checkpointer)
    
    return graph, checkpointer
```

---

## 与旧版本的对比

### 代码结构对比

| 方面 | 旧版本 (try.py) | 新版本 (supervisor.py) |
|------|-----------------|----------------------|
| **工具定义** | 40 行（task_tool） | 0 行（改用子图节点） |
| **Checkpointer** | 在 task_tool 中 | 在 create_supervisor_graph 中 |
| **State** | 2 字段 | 6 字段 |
| **节点数** | 2（agent + tools） | 4（supervisor + image + search + 条件边） |
| **重试逻辑** | 无 | 3 次重试 |
| **执行日志** | 无结构化追踪 | 时间戳日志 |
| **Thread ID 管理** | 硬编码 | 动态层级制 |

### 执行流对比

**旧版本（工具方式）：**
```python
# 每次都创建新实例，重复初始化
@tool
async def task_tool(description: str, subagent_type: str) -> str:
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        factory = subgraph_factories[subagent_type]
        agent = await factory(checkpointer=saver)  # ⚠️ 每次新建
        ...
```

**新版本（子图节点方式）：**
```python
# 编译时创建一次，执行时复用
checkpointer = AsyncRedisSaver.from_conn_string(db_uri)
graph = workflow.compile(checkpointer=checkpointer)  # ✅ 一次性

async for chunk in graph.astream(state, config):  # ✅ 复用
    ...
```

### 性能对比

| 指标 | 旧版本 | 新版本 | 改进 |
|------|--------|--------|------|
| **子图创建开销** | 每次调用 O(1) | 编译时 O(1) | ✅ 消除动态创建 |
| **Checkpointer 开销** | 每次新建连接 | 共享连接 | ✅ 降低 IO |
| **内存占用** | 每个工具调用 | 共享实例 | ✅ 更高效 |
| **State 合并** | 手动 | 自动 | ✅ 更清晰 |

---

## 使用指南

### 基本使用

```python
import asyncio
from supervisor import create_supervisor_graph, create_supervisor_state

async def main():
    # 1. 创建图
    graph, checkpointer = await create_supervisor_graph(
        db_uri="redis://localhost:6379",
        thread_id="main_001"
    )
    
    # 2. 初始化状态
    state = create_supervisor_state()
    state["messages"] = [HumanMessage(content="你的问题")]
    
    # 3. 执行
    config = {"configurable": {"thread_id": "main_001"}}
    
    async with checkpointer:
        async for chunk in graph.astream(state, config, stream_mode="updates"):
            if "data" in chunk:
                # 处理输出
                pass

if __name__ == "__main__":
    asyncio.run(main())
```

### 监控执行日志

```python
async for chunk in graph.astream(state, config, stream_mode="updates"):
    if "data" in chunk:
        for node_name, node_data in chunk["data"].items():
            # 查看执行日志
            if "execution_log" in node_data:
                logs = node_data["execution_log"]
                for log in logs:
                    print(log)
                    # 输出示例：
                    # [2026-05-12T10:30:45.123] 📋 Supervisor 决策: image_agent | 任务: 下载2020-2025卫星影像...
                    # [2026-05-12T10:30:46.456] 🚀 启动 image_agent | ThreadID: sub_image_agent_of_main_001
                    # [2026-05-12T10:30:52.789] ✅ image_agent 完成 | 结果长度: 2456
```

### 查询 Redis 中的检查点

```python
from langgraph.checkpoint.redis import RedisSaver

with RedisSaver.from_conn_string("redis://localhost:6379") as saver:
    config = {"configurable": {"thread_id": "main_001"}}
    
    # 列出所有检查点
    for state in saver.list(config):
        checkpoint_id = state.config["configurable"]["checkpoint_id"]
        print(f"Checkpoint: {checkpoint_id}")
        
        # 查看消息历史
        messages = state.checkpoint["channel_values"]["messages"]
        for msg in messages:
            print(f"  - {msg.type}: {msg.content[:100]}...")
```

### 自定义扩展

**添加新的子图：**

```python
# 1. 定义工厂函数
async def create_custom_subgraph(checkpointer=None):
    tools = [...]
    agent = create_agent(model=model, tools=tools, checkpointer=checkpointer)
    return agent

# 2. 在 subgraph_factories 中注册
subgraph_factories = {
    "image_agent": create_image_subgraph,
    "search_agent": create_search_subgraph,
    "custom_agent": create_custom_subgraph,  # ✅ 新增
}

# 3. 在 create_supervisor_graph 中添加节点
custom_node = await create_subgraph_node("custom_agent", checkpointer)
workflow.add_node("custom_agent", custom_node)
```

---

## 故障排除

### 问题 1: Redis 连接失败

```
错误: ConnectionError: Cannot connect to Redis at localhost:6379
解决:
  1. 确保 Redis 已启动: docker run -d -p 6379:6379 redis-stack-server
  2. 检查 db_uri 正确: "redis://localhost:6379"
  3. 查看 Redis 日志: docker logs <container_id>
```

### 问题 2: Checkpointer 被关闭

```
错误: RuntimeError: Cannot use checkpointer after context closed
解决:
  使用 async with checkpointer:
    async for chunk in graph.astream(...):
        ...  # ✅ 正确，上下文保持打开
```

### 问题 3: JSON 解析失败

```
错误: json.JSONDecodeError: Expecting value
解决:
  Supervisor 的 LLM 输出可能不是 JSON。添加更详细的 prompt:
  
  system_prompt = "...输出必须是有效的 JSON..."
  
  或修改解析逻辑以处理非 JSON 输出。
```

---

## 总结

### 核心优势

| 特性 | 收益 |
|------|------|
| **Supervisor 模式** | 符合 LangGraph 最佳实践，易于维护 |
| **共享 Checkpointer** | 完整的执行历史和状态追踪 |
| **错误恢复** | 自动重试机制，提高稳定性 |
| **执行日志** | 完全的可观测性 |
| **可扩展性** | 轻松添加新的子图 |
| **性能** | 减少资源创建开销 |

### 适用场景

- ✅ 复杂的多步骤任务（需要决策分发）
- ✅ 需要完整执行追踪的应用
- ✅ 需要保存和恢复状态的长期对话
- ✅ 多个专家智能体的协作
- ✅ 生产环境的可靠性要求高

---

## 附录：完整架构文件树

```
xiongan_agent/
├── supervisor.py              ← 新：Supervisor 主图
├── try.py                      ← 旧：参考（可删除）
│
├── image_agent/
│   ├── __init__.py
│   ├── image_agent_main.py    (create_image_subgraph)
│   ├── chatbot.py
│   └── tool/
│
├── search_agent/
│   ├── __init__.py
│   ├── search_agent_main.py   (create_search_subgraph)
│   ├── chatbot.py
│   └── tool/
│
└── SUPERVISOR_ARCH.md          ← 本文档
```

---

**文档版本**: 1.0  
**最后更新**: 2026-05-12  
**作者**: Claude Code
