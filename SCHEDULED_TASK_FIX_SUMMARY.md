# 定时任务修复总结

## 问题描述

用户报告一次性定时任务（trigger_type="once"）在执行后会重复执行多次，导致消息重复发送。

## 根本原因

在 `src/core/scheduler.py` 的 `_check_and_run_tasks()` 方法中，一次性任务执行后的状态更新存在问题：

1. 对于一次性任务，原本设置 `next_run_at = 0` 来标记不再执行
2. 但 `get_due_tasks()` 方法只检查 `next_run_at <= current_time`，这意味着 `next_run_at = 0` 的任务会一直被认为是"到期"的
3. 因此一次性任务会在每次执行 `_check_and_run_tasks()` 时重复执行

## 解决方案

### 1. 添加任务状态管理

在 `src/core/database.py` 中添加了任务状态管理方法：

- `update_task_status(task_id: str, status: str)`: 更新任务状态
- `get_due_tasks(current_time: int, status: str = "active")`: 只返回指定状态的任务

状态类型：
- `active`: 任务正在运行
- `paused`: 任务暂停
- `completed`: 任务已完成

### 2. 修改 Scheduler 执行逻辑

在 `src/core/scheduler.py` 的 `_check_and_run_tasks()` 方法中：

```python
# 对于一次性任务，将其标记为已完成
if task["trigger_type"] == "once":
    self.db.update_task_status(task_id, "completed")
else:
    # 对于周期性任务，计算下一次执行时间
    next_run = current_time + interval
    self.db.update_task_next_run(task_id, next_run_at=next_run, last_run_at=current_time)
```

这样：
- 一次性任务执行后被标记为 `completed`
- `get_due_tasks()` 只返回状态为 `active` 的任务
- 已完成任务不会被重复执行
- 周期性任务继续按间隔执行

### 3. 更新测试

更新了 `tests/test_scheduler.py` 中的 `test_task_execution_flow` 测试，验证一次性任务执行后状态为 `completed`。

### 4. 添加专门的测试

创建了 `tests/test_one_time_task_no_repeat.py`，包含三个测试：

1. `test_one_time_task_only_executes_once`: 验证一次性任务只执行一次
2. `test_multiple_one_time_tasks_execute_independently`: 验证多个一次性任务独立执行
3. `test_interval_task_continues_executing`: 验证周期性任务继续执行

## 测试结果

所有测试通过：
- 总计 284 个测试通过
- 11 个跳过（与测试环境配置相关）
- 0 个失败

## 影响范围

### 修改的文件
1. `src/core/database.py`: 添加任务状态管理方法
2. `src/core/scheduler.py`: 修改任务执行逻辑
3. `tests/test_scheduler.py`: 更新测试用例
4. `tests/test_one_time_task_no_repeat.py`: 新增测试文件

### 兼容性
- 现有数据库结构保持不变（已有 `status` 字段）
- 周期性任务行为不受影响
- 一次性任务现在正确执行一次后不再重复

## 使用示例

### 添加一次性任务
```
用户: 10分钟后提醒我喝水
```
系统会创建一个一次性任务，10分钟后执行一次，然后标记为完成。

### 添加周期性任务
```
用户: 每小时提醒我喝水
```
系统会创建一个周期性任务，每小时执行一次，持续运行直到暂停或取消。

### 任务管理
- `list_tasks`: 列出所有任务
- `get_task <task_id>`: 查看任务详情
- `cancel_task <task_id>`: 取消任务
- `pause_task <task_id>`: 暂停任务
- `resume_task <task_id>`: 恢复任务

## 技术细节

### 时间处理
- 使用 Unix 时间戳（秒）
- `get_current_timestamp()` 获取当前时间
- 任务执行时间基于 `next_run_at` 字段

### 任务执行流程
1. 调度器定期调用 `_check_and_run_tasks()`
2. 获取所有状态为 `active` 且 `next_run_at <= current_time` 的任务
3. 执行任务消息回调
4. 更新任务状态：
   - 一次性任务：标记为 `completed`
   - 周期性任务：更新 `next_run_at` 为下一次执行时间

### 数据库查询优化
```sql
-- 只获取活跃的到期任务
SELECT * FROM scheduled_tasks 
WHERE next_run_at <= ? AND status = 'active'
```

## 后续改进建议

1. **任务历史记录**: 可以添加任务执行历史表，记录每次执行的时间和结果
2. **重试机制**: 对于执行失败的任务，可以添加重试逻辑
3. **任务依赖**: 支持任务之间的依赖关系
4. **通知方式**: 支持多种通知方式（Telegram、邮件等）
5. **任务统计**: 添加任务执行统计和分析功能

## 总结

此次修复成功解决了一次性任务重复执行的问题，通过引入任务状态管理机制，确保：
- 一次性任务只执行一次
- 周期性任务按预期持续执行
- 系统行为更加清晰和可预测
- 代码质量和测试覆盖率得到提升