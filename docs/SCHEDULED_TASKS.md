# 定时任务功能使用指南

## 概述

Seelenmaschine 内置了强大的定时任务功能，支持：
- ⏰ 一次性提醒（在特定时间执行）
- 🔄 周期性任务（按固定间隔重复执行）
- 📝 任务管理（列表、暂停、恢复、取消）
- 💬 通过 Telegram 自动发送消息

## 通过对话使用

最简单的方式是直接告诉 AI 你的需求，它会调用 `scheduled_task` skill：

### 添加一次性提醒

```
你: 提醒我明天下午 3 点开会
AI: [调用 scheduled_task skill]
    ✓ Task created (ID: abc123...)
    Name: Meeting Reminder
    Type: One-time
    Trigger at: 2026-01-29 15:00:00
    Message: 别忘了下午 3 点的会议！
```

### 添加周期性任务

```
你: 每天早上 8 点提醒我喝水
AI: [调用 scheduled_task skill]
    ✓ Task created (ID: def456...)
    Name: Daily Water Reminder
    Type: Recurring
    Interval: 1d
    Message: 记得喝水哦！💧
```

### 查看所有任务

```
你: 列出我的所有定时任务
AI: [调用 scheduled_task skill]
    Active tasks (2):
    
    • Meeting Reminder (ID: abc123...)
      Type: once
      Trigger at: 2026-01-29 15:00:00
      Message: 别忘了下午 3 点的会议！
    
    • Daily Water Reminder (ID: def456...)
      Type: interval
      Interval: 1d
      Next run: 2026-01-29 08:00:00
      Message: 记得喝水哦！💧
```

### 管理任务

```
你: 暂停任务 def456
AI: [调用 scheduled_task skill]
    ✓ Task paused: Daily Water Reminder

你: 恢复任务 def456
AI: [调用 scheduled_task skill]
    ✓ Task resumed: Daily Water Reminder

你: 取消任务 abc123
AI: [调用 scheduled_task skill]
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

## 预设任务配置

在 `data/{profile}/scheduled_tasks.json` 中配置启动时自动加载的任务：

```json
[
  {
    "name": "Morning Greeting",
    "trigger_type": "interval",
    "trigger_config": {
      "interval": 86400
    },
    "message": "Good morning! 🌅 Ready to start a new day?"
  },
  {
    "name": "Important Event",
    "trigger_type": "once",
    "trigger_config": {
      "timestamp": 1738051200
    },
    "message": "Don't forget about the event!"
  }
]
```

配置文件路径在 `.env` 中设置：
```ini
SCHEDULED_TASKS_CONFIG_PATH=scheduled_tasks.json
```

## 程序化使用

如果需要在代码中直接使用调度器：

```python
from core.database import DatabaseManager
from core.scheduler import TaskScheduler

# 初始化
db = DatabaseManager()
scheduler = TaskScheduler(db)

# 设置消息回调（Telegram bot 会自动设置）
def my_callback(message: str):
    print(f"Task triggered: {message}")

scheduler.set_message_callback(my_callback)

# 启动调度器
scheduler.start()

# 添加一次性任务
task_id = scheduler.add_task(
    name="Test Reminder",
    trigger_type="once",
    trigger_config={"timestamp": 1738051200},
    message="This is a test!"
)

# 添加周期性任务
task_id = scheduler.add_task(
    name="Hourly Task",
    trigger_type="interval",
    trigger_config={"interval": 3600},  # 每小时
    message="Hourly check-in"
)

# 加载配置文件中的任务
scheduler.load_default_tasks()

# 停止调度器（程序退出时）
scheduler.stop()
```

## 技术细节

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
    status TEXT CHECK(status IN ('active', 'paused', 'completed')) DEFAULT 'active'
);
```

### 任务状态

- `active`: 活动状态，会被调度器执行
- `paused`: 暂停状态，不会被执行
- `completed`: 已完成（一次性任务执行后，或被取消）

### 执行机制

1. 调度器在独立线程中运行
2. 每 10 秒检查一次是否有到期任务
3. 执行到期任务的消息回调
4. 更新任务状态：
   - 一次性任务：设置 `status='completed'`
   - 周期性任务：更新 `next_run_at` 为下次执行时间

### 时区处理

所有时间戳以 UTC 存储，显示时转换为配置的时区（`TIMEZONE`）。

## 测试

运行单元测试：

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -v
```

测试覆盖：
- 任务创建和查询
- 一次性和周期性任务执行
- 任务状态管理
- JSON 配置加载
- 消息回调机制

## 限制和注意事项

1. **单用户模式**: 目前仅支持单用户（`TELEGRAM_USER_ID`）
2. **精度**: 调度器每 10 秒检查一次，精度为 ±10 秒
3. **持久化**: 任务存储在数据库中，重启后自动恢复
4. **时区**: 确保 `.env` 中的 `TIMEZONE` 设置正确

## 未来增强

- [ ] 支持 cron 表达式
- [ ] 支持任务优先级
- [ ] 支持任务依赖关系
- [ ] 支持任务执行历史查询
- [ ] 支持任务失败重试机制
