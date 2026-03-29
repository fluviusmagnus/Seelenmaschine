# 定时任务功能使用指南

[English](SCHEDULED_TASKS_EN.md) | 中文

## 概述

Seelenmaschine 内置了强大的定时任务功能，支持：
- ⏰ **智能任务触发**：触发后通过 LLM 生成个性化回复，而非直接发送固定消息
- 🔄 **周期性任务**：按固定间隔重复执行
- 📝 **任务管理**：列表、暂停、恢复、取消
- 💬 **通过 Telegram 自动发送消息**

## 核心设计理念

**与传统定时任务不同**，Seelenmaschine 的定时任务不是直接发送预设消息给用户，而是：

1. 当任务触发时，将 `message` 字段内容发送给 **AI（LLM）**
2. AI 根据任务内容和当前对话上下文，生成个性化、情境化的提醒
3. AI 的回复发送给用户并保存到记忆中

**示例流程**：
```
任务设置: message="提醒用户喝水"
         
触发时 → AI 收到: "[SYSTEM_SCHEDULED_TASK] Task: 提醒用户喝水"
         
AI 生成: "下午好！工作了一会儿了，记得站起来活动一下，
          顺便喝杯水补充能量 💧 需要我帮你调整接下来的安排吗？"
         
用户收到: 上述个性化回复（已保存到记忆）
```

## 通过对话使用

最简单的方式是直接告诉 AI 你的需求，它会调用 `scheduled_task` 工具：

### 添加一次性提醒

```
你: 提醒我明天下午 3 点开会
AI: [调用 scheduled_task 工具]
    ✓ Task created (ID: abc123...)
    Name: Meeting Reminder
    Type: One-time
    Trigger at: 2026-01-29 15:00:00
    Message: Remind user about the 3 PM meeting and ask if they need any preparation
```

### 添加周期性任务

```
你: 每天早上 8 点提醒我喝水
AI: [调用 scheduled_task 工具]
    ✓ Task created (ID: def456...)
    Name: Daily Water Reminder
    Type: Recurring
    Interval: 1d
    Message: Suggest user drink a glass of water to start the day hydrated
```

### 查看所有任务

```
你: 列出我的所有定时任务
AI: [调用 scheduled_task 工具]
    Active tasks (2):
    
    • Meeting Reminder (ID: abc123...)
      Type: once
      Trigger at: 2026-01-29 15:00:00
      Message: Remind user about the 3 PM meeting...
    
    • Daily Water Reminder (ID: def456...)
      Type: interval
      Interval: 1d
      Next run: 2026-01-29 08:00:00
      Message: Suggest user drink a glass of water...
```

### 管理任务

```
你: 暂停任务 def456
AI: [调用 scheduled_task 工具]
    ✓ Task paused: Daily Water Reminder

你: 恢复任务 def456
AI: [调用 scheduled_task 工具]
    ✓ Task resumed: Daily Water Reminder

你: 取消任务 abc123
AI: [调用 scheduled_task 工具]
    ✓ Task cancelled: Meeting Reminder
```

## 时间表达式

### 一次性任务支持

- **Unix 时间戳**: `1738051200`
- **ISO 日期时间**: `2026-01-29T15:00:00`
- **相对时间**:
  - `in 2 hours` - 2 小时后
  - `in 30 minutes` - 30 分钟后
  - `in 3 days` - 3 天后
  - `tomorrow` - 明天
  - `next week` - 下周

### 周期性任务支持

简洁的间隔表达式：
- `30s` - 每 30 秒
- `5m` - 每 5 分钟
- `1h` - 每小时
- `1d` - 每天
- `1w` - 每周

## 任务字段说明

### `name` vs `message`

- **`name`**: 任务的名字，仅用于列出和识别任务。简短即可，如 "Morning Reminder", "Water Break"

- **`message`**: **给 AI 看的任务内容**，不是直接发给用户的！AI 会根据这个内容生成个性化提醒。
  - 应该具体说明要提醒什么、建议什么行动
  - 示例：
    - ✅ "Remind user to call Mom about weekend plans"
    - ✅ "Suggest user take a 5-minute break and stretch"
    - ✅ "Ask user about progress on the quarterly report"
    - ❌ "记得喝水" (太笼统，AI 无法提供上下文)
    - ❌ "Check something" (太模糊)

## 当前实现说明

当前版本的任务由数据库 `scheduled_tasks` 表持久化管理，Telegram 适配器启动后会把调度器作为后台任务运行。

也就是说：

- 已创建的任务会在重启后自动恢复
- 当前代码库**没有**从 `data/{profile}/scheduled_tasks.json` 自动加载预设任务的机制
- 如需预置任务，建议通过对话调用 `scheduled_task` 工具创建，或在代码中显式调用 `scheduler.add_task(...)`

## 技术细节

### 消息格式

当任务触发时，发送给 LLM 的消息格式如下：

```json
{
  "role": "user",
  "content": "⚡ [Current Request]\n[SYSTEM_SCHEDULED_TASK]\nTask Name: Daily Water Reminder\nTrigger Time: 2026-01-29 08:00:00\nTask: Suggest user drink a glass of water to start the day hydrated\n\nPlease respond proactively based on this scheduled task."
}
```

### 数据保存策略

| 数据                 | 保存到数据库 | 计入上下文 | 说明                   |
| -------------------- | ------------ | ---------- | ---------------------- |
| 任务消息 (`message`) | ❌ 否         | ❌ 否       | 仅用于触发 LLM，不保存 |
| 任务名称 (`name`)    | ✅ 是         | ❌ 否       | 用于列出和管理任务     |
| LLM 生成的回复       | ✅ 是         | ✅ 是       | 作为正常对话保存       |

### 数据库表结构

```sql
CREATE TABLE scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('once', 'interval')),
    trigger_config TEXT NOT NULL,  -- JSON
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    next_run_at INTEGER NOT NULL,
    last_run_at INTEGER,
    status TEXT CHECK(status IN ('active', 'paused', 'completed', 'running')) DEFAULT 'active'
);
```

### 任务状态

- `active`: 活动状态，会被调度器执行
- `paused`: 暂停状态，不会被执行
- `completed`: 已完成（一次性任务执行后，或被取消）

### 执行机制

1. 调度器每 10 秒检查一次是否有到期任务
2. 任务触发时，构造 `[SYSTEM_SCHEDULED_TASK]` 消息发送给 LLM
3. LLM 生成个性化回复（可使用记忆搜索等工具，**但不能使用 scheduled_task 工具**）
4. 回复发送给用户，并保存到数据库（计入对话历史）
5. 更新任务状态：
   - 一次性任务：设置 `status='completed'`
   - 周期性任务：更新 `next_run_at` 为下次执行时间

### 时区处理

所有时间戳以 UTC 存储，显示时转换为配置的时区（`TIMEZONE`）。

## 程序化使用

如果需要在代码中直接使用调度器：

```python
import asyncio

from core.database import DatabaseManager
from core.scheduler import TaskScheduler

# 初始化
db = DatabaseManager()
scheduler = TaskScheduler(db)

# 设置消息回调（Telegram bot 会自动设置）
# 注意：回调现在接收两个参数：message 和 task_name
def my_callback(message: str, task_name: str):
    print(f"Task '{task_name}' triggered with message: {message}")

scheduler.set_message_callback(my_callback)

# 启动调度器
# 直接作为后台协程运行
task = asyncio.create_task(scheduler.run_forever())

# 添加一次性任务
task_id = scheduler.add_task(
    name="Test Reminder",
    trigger_type="once",
    trigger_config={"timestamp": 1738051200},
    message="Suggest user take a break and review today's progress"
)

# 添加周期性任务
task_id = scheduler.add_task(
    name="Hourly Check",
    trigger_type="interval",
    trigger_config={"interval": 3600},  # 每小时
    message="Ask user if they need anything or want to chat"
)

# 停止调度器（程序退出时）
scheduler.stop()
await task
```

上面的代码片段需要先导入 `asyncio`，并在异步上下文中运行。

## 测试

运行单元测试：

```bash
python -m pytest tests/test_scheduler.py -v
```

测试覆盖：
- 任务创建和查询
- 一次性和周期性任务执行
- 任务状态管理
- JSON 配置加载
- 消息回调机制（包括 task_name 传递）

## 限制和注意事项

1. **单用户模式**: 目前仅支持单用户（`TELEGRAM_USER_ID`）
2. **精度**: 调度器每 10 秒检查一次，触发精度约为 ±10 秒
3. **持久化**: 任务存储在数据库中，重启后自动恢复
4. **时区**: 确保 `.env` 中的 `TIMEZONE` 设置正确
5. **工具限制**: 处理计划任务时，LLM **不能使用** `scheduled_task` 工具创建新任务（避免循环）
6. **Token 消耗**: 计划任务触发 LLM 调用会增加 API 成本

## 未来增强

- [ ] 支持 cron 表达式
- [ ] 支持任务优先级
- [ ] 支持任务依赖关系
- [ ] 支持任务执行历史查询
- [ ] 支持任务失败重试机制
