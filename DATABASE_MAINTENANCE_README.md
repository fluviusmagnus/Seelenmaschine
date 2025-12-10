# 数据库维护脚本使用说明

## 概述

`database_maintenance.py` 是为 Seelenmaschine 项目设计的数据库维护工具，用于优化和清理 SQLite 和 LanceDB 数据库。

## 功能特性

### SQLite 数据库维护
- **索引优化**：为关键字段创建索引以提高查询性能
- **VACUUM 操作**：回收未使用的数据库空间
- **ANALYZE 操作**：更新查询优化器统计信息
- **完整性检查**：验证数据库文件的完整性

### LanceDB 数据库维护
- **表优化**：对向量数据库表执行优化操作
- **空间回收**：清理碎片化的数据文件

### 安全特性
- **自动备份**：维护前自动备份数据库文件
- **干运行模式**：预览将要执行的操作而不实际修改数据
- **完整性检查**：确保数据库健康状态
- **详细日志**：记录所有操作和结果

## 使用方法

### 基本语法
```bash
python database_maintenance.py <profile> [选项]
```

或使用便捷脚本（推荐）：
```bash
# Linux/macOS
./maintenance.sh <profile> [选项]

# Windows
maintenance.bat <profile> [选项]
```

### 必需参数

| 参数        | 描述                                     |
| ----------- | ---------------------------------------- |
| `<profile>` | 指定使用的配置文件（如 dev, production） |

### 可选参数

| 选项              | 描述                             |
| ----------------- | -------------------------------- |
| `--all`           | 维护所有数据库（默认选项）       |
| `--sqlite`        | 只维护 SQLite 数据库             |
| `--lancedb`       | 只维护 LanceDB 数据库            |
| `--dry-run`       | 干运行模式，只显示将要执行的操作 |
| `--verbose`, `-v` | 详细输出模式                     |
| `--help`, `-h`    | 显示帮助信息                     |

**注意：** Shell 包装脚本已改进，现在支持组合多个选项，与 Python 脚本完全一致。

### 使用示例

#### 1. 使用便捷脚本（推荐）

**基本用法：**
```bash
# Linux/macOS - 完整维护
./maintenance.sh dev

# Windows - 完整维护
maintenance.bat dev

# 显式指定维护所有数据库
./maintenance.sh dev --all
maintenance.bat dev --all
```

**组合选项（新功能）：**
```bash
# 干运行模式 + 只维护 SQLite
./maintenance.sh dev --sqlite --dry-run
maintenance.bat dev --sqlite --dry-run

# 干运行模式 + 只维护 LanceDB
./maintenance.sh production --lancedb --dry-run
maintenance.bat production --lancedb --dry-run

# 完整维护 + 干运行 + 详细输出
./maintenance.sh dev --all --dry-run --verbose
maintenance.bat dev --all --dry-run --verbose

# 只维护 SQLite + 详细输出
./maintenance.sh production --sqlite --verbose
maintenance.bat production --sqlite --verbose
```

**查看帮助：**
```bash
./maintenance.sh help
maintenance.bat help
```

#### 2. 直接运行 Python 脚本

```bash
# 完整维护（默认）
python database_maintenance.py dev
python database_maintenance.py dev --all

# 只维护 SQLite 数据库
python database_maintenance.py production --sqlite

# 只维护 LanceDB 数据库
python database_maintenance.py dev --lancedb

# 干运行模式（预览操作）
python database_maintenance.py dev --all --dry-run
python database_maintenance.py dev --sqlite --dry-run

# 详细输出模式
python database_maintenance.py production --all --verbose

# 组合多个选项
python database_maintenance.py dev --sqlite --dry-run --verbose
python database_maintenance.py production --lancedb --dry-run --verbose
```

## 维护操作详情

### SQLite 数据库操作

1. **备份数据库**
   - 创建时间戳命名的备份文件
   - 格式：`chat_sessions_backup_YYYYMMDD_HHMMSS.db`

2. **完整性检查**
   - 使用 `PRAGMA integrity_check` 验证数据库
   - 如果检查失败，停止后续操作

3. **创建索引**
   - `idx_conversation_session_id`：conversation 表的 session_id 字段
   - `idx_conversation_timestamp`：conversation 表的 timestamp 字段
   - `idx_conversation_session_timestamp`：conversation 表的复合索引
   - `idx_summary_session_id`：summary 表的 session_id 字段
   - `idx_session_status`：session 表的 status 字段
   - `idx_session_start_timestamp`：session 表的 start_timestamp 字段
   - `idx_session_status_timestamp`：session 表的复合索引

4. **VACUUM 操作**
   - 重建数据库文件，回收未使用空间
   - 整理数据页面，提高访问效率

5. **ANALYZE 操作**
   - 收集表和索引的统计信息
   - 帮助查询优化器选择最佳执行计划

### LanceDB 数据库操作

1. **备份数据库**
   - 复制整个 lancedb 目录
   - 格式：`lancedb_backup_YYYYMMDD_HHMMSS/`

2. **表优化**
   - 对 `conversations` 表执行优化
   - 对 `summaries` 表执行优化
   - 整理向量数据，提高搜索性能

## 输出和日志

### 控制台输出
脚本会在控制台显示：
- 操作进度信息
- 错误和警告消息
- 维护报告摘要

### 日志文件
每次运行都会生成日志文件：
- 文件名格式：`maintenance_YYYYMMDD_HHMMSS.log`
- 包含详细的操作记录和时间戳

### 维护报告
操作完成后会显示：
- 数据库维护前后的大小对比
- 节省的存储空间
- 执行的操作列表

## 最佳实践

### 运行频率建议
- **日常使用**：每周运行一次完整维护
- **重度使用**：每 3-5 天运行一次
- **数据库问题**：立即运行完整维护

### 运行时机
- 在系统负载较低时运行
- 确保没有其他程序正在访问数据库
- 建议在备份系统数据后运行

### 预防措施
1. **首次使用**：先运行 `--dry-run` 模式查看将要执行的操作
   ```bash
   # 预览完整维护操作
   ./maintenance.sh dev --all --dry-run
   
   # 预览只维护 SQLite 的操作
   ./maintenance.sh dev --sqlite --dry-run
   ```

2. **重要数据**：手动备份重要数据文件

3. **磁盘空间**：确保有足够的磁盘空间进行备份和操作

4. **权限检查**：确保脚本有读写数据库文件的权限

### 参数组合建议

推荐的参数组合方式：

```bash
# 生产环境：先预览，再执行
./maintenance.sh production --all --dry-run --verbose    # 步骤1：预览
./maintenance.sh production --all --verbose              # 步骤2：执行

# 开发环境：快速维护
./maintenance.sh dev --all

# 针对性维护：只优化特定数据库
./maintenance.sh dev --sqlite --dry-run     # 预览 SQLite 维护
./maintenance.sh dev --sqlite               # 执行 SQLite 维护
```

## 故障排除

### 常见问题

#### 1. 权限错误
```
错误：Permission denied
解决：确保脚本有读写数据库文件的权限
```

#### 2. 磁盘空间不足
```
错误：No space left on device
解决：清理磁盘空间或移动数据库到其他位置
```

#### 3. 数据库被锁定
```
错误：database is locked
解决：关闭所有访问数据库的程序后重试
```

#### 4. 备份失败
```
错误：备份失败，停止维护操作
解决：检查目标目录权限和磁盘空间
```

### 恢复操作

如果维护过程中出现问题：

1. **从备份恢复 SQLite**：
   ```bash
   cp data/chat_sessions_backup_YYYYMMDD_HHMMSS.db data/chat_sessions.db
   ```

2. **从备份恢复 LanceDB**：
   ```bash
   rm -rf data/lancedb
   cp -r data/lancedb_backup_YYYYMMDD_HHMMSS data/lancedb
   ```

## 技术细节

### 依赖项
- Python 3.7+
- sqlite3（Python 标准库）
- lancedb
- pathlib（Python 标准库）

### 配置
脚本使用项目的 `src/config.py` 文件中的配置：
- `Config.SQLITE_DB_PATH`：SQLite 数据库路径
- `Config.LANCEDB_PATH`：LanceDB 数据库路径

### 性能影响
- **SQLite VACUUM**：可能需要较长时间，取决于数据库大小
- **LanceDB 优化**：通常较快，但取决于向量数据量
- **备份操作**：时间取决于数据库大小和磁盘速度

## 版本历史

- **v1.0**：初始版本，支持基本的 SQLite 和 LanceDB 维护功能

## 支持

如果遇到问题或需要帮助，请：
1. 检查日志文件中的详细错误信息
2. 确认系统环境和依赖项
3. 尝试使用 `--dry-run` 模式诊断问题
