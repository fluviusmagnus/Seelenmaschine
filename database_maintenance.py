#!/usr/bin/env python3
"""
数据库维护脚本
用于维护Seelenmaschine项目的SQLite和LanceDB数据库
"""

import os
import sys
import sqlite3
import shutil
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import lancedb

# 添加src目录到Python路径
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from config import Config


class DatabaseMaintenance:
    """数据库维护类"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.setup_logging()
        self.stats = {
            "sqlite_before_size": 0,
            "sqlite_after_size": 0,
            "lancedb_before_size": 0,
            "lancedb_after_size": 0,
            "operations_performed": [],
        }

    def setup_logging(self):
        """设置日志"""
        log_format = "%(asctime)s - %(levelname)s - %(message)s"
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(
                    f'maintenance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
                ),
            ],
        )
        self.logger = logging.getLogger(__name__)

    def get_directory_size(self, path: Path) -> int:
        """获取目录大小（字节）"""
        if not path.exists():
            return 0

        if path.is_file():
            return path.stat().st_size

        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
        return total_size

    def format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    def backup_sqlite_db(self) -> Optional[Path]:
        """备份SQLite数据库"""
        if not Config.SQLITE_DB_PATH.exists():
            self.logger.warning("SQLite数据库文件不存在，跳过备份")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = (
            Config.SQLITE_DB_PATH.parent / f"chat_sessions_backup_{timestamp}.db"
        )

        if self.dry_run:
            self.logger.info(f"[DRY RUN] 将备份SQLite数据库到: {backup_path}")
            return backup_path

        try:
            shutil.copy2(Config.SQLITE_DB_PATH, backup_path)
            self.logger.info(f"SQLite数据库已备份到: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"备份SQLite数据库失败: {e}")
            return None

    def backup_lancedb(self) -> Optional[Path]:
        """备份LanceDB数据库"""
        if not Config.LANCEDB_PATH.exists():
            self.logger.warning("LanceDB目录不存在，跳过备份")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Config.LANCEDB_PATH.parent / f"lancedb_backup_{timestamp}"

        if self.dry_run:
            self.logger.info(f"[DRY RUN] 将备份LanceDB到: {backup_path}")
            return backup_path

        try:
            shutil.copytree(Config.LANCEDB_PATH, backup_path)
            self.logger.info(f"LanceDB已备份到: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"备份LanceDB失败: {e}")
            return None

    def create_sqlite_indexes(self) -> bool:
        """为SQLite数据库创建索引"""
        if not Config.SQLITE_DB_PATH.exists():
            self.logger.warning("SQLite数据库文件不存在")
            return False

        indexes = [
            ("idx_conversation_session_id", "conversation", "session_id"),
            ("idx_conversation_timestamp", "conversation", "timestamp"),
            (
                "idx_conversation_session_timestamp",
                "conversation",
                "session_id, timestamp",
            ),
            ("idx_summary_session_id", "summary", "session_id"),
            ("idx_session_status", "session", "status"),
            ("idx_session_start_timestamp", "session", "start_timestamp"),
            ("idx_session_status_timestamp", "session", "status, start_timestamp"),
        ]

        if self.dry_run:
            self.logger.info("[DRY RUN] 将创建以下索引:")
            for idx_name, table, columns in indexes:
                self.logger.info(f"  - {idx_name} ON {table}({columns})")
            return True

        try:
            conn = sqlite3.connect(Config.SQLITE_DB_PATH)
            cursor = conn.cursor()

            created_count = 0
            for idx_name, table, columns in indexes:
                try:
                    cursor.execute(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({columns})"
                    )
                    self.logger.info(f"创建索引: {idx_name}")
                    created_count += 1
                except sqlite3.Error as e:
                    self.logger.warning(f"创建索引 {idx_name} 失败: {e}")

            conn.commit()
            conn.close()

            self.stats["operations_performed"].append(f"创建了 {created_count} 个索引")
            self.logger.info(f"成功创建 {created_count} 个索引")
            return True

        except Exception as e:
            self.logger.error(f"创建索引失败: {e}")
            return False

    def vacuum_sqlite_db(self) -> bool:
        """对SQLite数据库执行VACUUM操作"""
        if not Config.SQLITE_DB_PATH.exists():
            self.logger.warning("SQLite数据库文件不存在")
            return False

        if self.dry_run:
            self.logger.info("[DRY RUN] 将执行VACUUM操作")
            return True

        try:
            self.logger.info("开始执行VACUUM操作...")
            conn = sqlite3.connect(Config.SQLITE_DB_PATH)
            conn.execute("VACUUM")
            conn.close()

            self.stats["operations_performed"].append("执行了VACUUM操作")
            self.logger.info("VACUUM操作完成")
            return True

        except Exception as e:
            self.logger.error(f"VACUUM操作失败: {e}")
            return False

    def analyze_sqlite_db(self) -> bool:
        """对SQLite数据库执行ANALYZE操作"""
        if not Config.SQLITE_DB_PATH.exists():
            self.logger.warning("SQLite数据库文件不存在")
            return False

        if self.dry_run:
            self.logger.info("[DRY RUN] 将执行ANALYZE操作")
            return True

        try:
            self.logger.info("开始执行ANALYZE操作...")
            conn = sqlite3.connect(Config.SQLITE_DB_PATH)
            conn.execute("ANALYZE")
            conn.close()

            self.stats["operations_performed"].append("执行了ANALYZE操作")
            self.logger.info("ANALYZE操作完成")
            return True

        except Exception as e:
            self.logger.error(f"ANALYZE操作失败: {e}")
            return False

    def check_sqlite_integrity(self) -> bool:
        """检查SQLite数据库完整性"""
        if not Config.SQLITE_DB_PATH.exists():
            self.logger.warning("SQLite数据库文件不存在")
            return False

        if self.dry_run:
            self.logger.info("[DRY RUN] 将检查数据库完整性")
            return True

        try:
            self.logger.info("检查数据库完整性...")
            conn = sqlite3.connect(Config.SQLITE_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()

            if result and result[0] == "ok":
                self.logger.info("数据库完整性检查通过")
                self.stats["operations_performed"].append("完整性检查通过")
                return True
            else:
                self.logger.error(f"数据库完整性检查失败: {result}")
                return False

        except Exception as e:
            self.logger.error(f"完整性检查失败: {e}")
            return False

    def optimize_lancedb(self) -> bool:
        """优化LanceDB数据库"""
        if not Config.LANCEDB_PATH.exists():
            self.logger.warning("LanceDB目录不存在")
            return False

        if self.dry_run:
            self.logger.info("[DRY RUN] 将优化LanceDB表")
            return True

        try:
            db = lancedb.connect(Config.LANCEDB_PATH)
            table_names = db.table_names()

            optimized_count = 0
            for table_name in table_names:
                try:
                    self.logger.info(f"优化表: {table_name}")
                    table = db.open_table(table_name)
                    table.optimize()
                    optimized_count += 1
                    self.logger.info(f"表 {table_name} 优化完成")
                except Exception as e:
                    self.logger.warning(f"优化表 {table_name} 失败: {e}")

            self.stats["operations_performed"].append(
                f"优化了 {optimized_count} 个LanceDB表"
            )
            self.logger.info(f"成功优化 {optimized_count} 个LanceDB表")
            return True

        except Exception as e:
            self.logger.error(f"LanceDB优化失败: {e}")
            return False

    def get_sqlite_stats(self) -> Dict[str, Any]:
        """获取SQLite数据库统计信息"""
        if not Config.SQLITE_DB_PATH.exists():
            return {}

        try:
            conn = sqlite3.connect(Config.SQLITE_DB_PATH)
            cursor = conn.cursor()

            stats = {}

            # 获取表记录数
            tables = ["session", "conversation", "summary"]
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"{table}_count"] = cursor.fetchone()[0]

            # 获取数据库页面信息
            cursor.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]

            stats["total_pages"] = page_count
            stats["page_size"] = page_size
            stats["db_size_pages"] = page_count * page_size

            conn.close()
            return stats

        except Exception as e:
            self.logger.error(f"获取SQLite统计信息失败: {e}")
            return {}

    def maintain_sqlite(self) -> bool:
        """维护SQLite数据库"""
        self.logger.info("开始SQLite数据库维护...")

        # 记录维护前大小
        self.stats["sqlite_before_size"] = self.get_directory_size(
            Config.SQLITE_DB_PATH
        )

        # 备份数据库
        backup_path = self.backup_sqlite_db()
        if not backup_path and not self.dry_run:
            self.logger.error("备份失败，停止维护操作")
            return False

        # 检查完整性
        if not self.check_sqlite_integrity():
            self.logger.error("数据库完整性检查失败，停止维护操作")
            return False

        # 创建索引
        if not self.create_sqlite_indexes():
            self.logger.warning("创建索引失败")

        # 执行VACUUM
        if not self.vacuum_sqlite_db():
            self.logger.warning("VACUUM操作失败")

        # 执行ANALYZE
        if not self.analyze_sqlite_db():
            self.logger.warning("ANALYZE操作失败")

        # 记录维护后大小
        self.stats["sqlite_after_size"] = self.get_directory_size(Config.SQLITE_DB_PATH)

        self.logger.info("SQLite数据库维护完成")
        return True

    def maintain_lancedb(self) -> bool:
        """维护LanceDB数据库"""
        self.logger.info("开始LanceDB数据库维护...")

        # 记录维护前大小
        self.stats["lancedb_before_size"] = self.get_directory_size(Config.LANCEDB_PATH)

        # 备份数据库
        backup_path = self.backup_lancedb()
        if not backup_path and not self.dry_run:
            self.logger.error("备份失败，停止维护操作")
            return False

        # 优化数据库
        if not self.optimize_lancedb():
            self.logger.warning("LanceDB优化失败")

        # 记录维护后大小
        self.stats["lancedb_after_size"] = self.get_directory_size(Config.LANCEDB_PATH)

        self.logger.info("LanceDB数据库维护完成")
        return True

    def print_maintenance_report(self):
        """打印维护报告"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("数据库维护报告")
        self.logger.info("=" * 60)

        # SQLite统计
        if self.stats["sqlite_before_size"] > 0:
            sqlite_before = self.format_size(self.stats["sqlite_before_size"])
            sqlite_after = self.format_size(self.stats["sqlite_after_size"])
            sqlite_saved = (
                self.stats["sqlite_before_size"] - self.stats["sqlite_after_size"]
            )
            sqlite_saved_str = (
                self.format_size(sqlite_saved) if sqlite_saved > 0 else "0 B"
            )

            self.logger.info(f"SQLite数据库:")
            self.logger.info(f"  维护前大小: {sqlite_before}")
            self.logger.info(f"  维护后大小: {sqlite_after}")
            self.logger.info(f"  节省空间: {sqlite_saved_str}")

        # LanceDB统计
        if self.stats["lancedb_before_size"] > 0:
            lancedb_before = self.format_size(self.stats["lancedb_before_size"])
            lancedb_after = self.format_size(self.stats["lancedb_after_size"])
            lancedb_saved = (
                self.stats["lancedb_before_size"] - self.stats["lancedb_after_size"]
            )
            lancedb_saved_str = (
                self.format_size(lancedb_saved) if lancedb_saved > 0 else "0 B"
            )

            self.logger.info(f"LanceDB数据库:")
            self.logger.info(f"  维护前大小: {lancedb_before}")
            self.logger.info(f"  维护后大小: {lancedb_after}")
            self.logger.info(f"  节省空间: {lancedb_saved_str}")

        # 执行的操作
        if self.stats["operations_performed"]:
            self.logger.info(f"执行的操作:")
            for operation in self.stats["operations_performed"]:
                self.logger.info(f"  - {operation}")

        self.logger.info("=" * 60)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Seelenmaschine数据库维护工具")
    parser.add_argument("--sqlite", action="store_true", help="只维护SQLite数据库")
    parser.add_argument("--lancedb", action="store_true", help="只维护LanceDB数据库")
    parser.add_argument("--all", action="store_true", help="维护所有数据库")
    parser.add_argument(
        "--dry-run", action="store_true", help="干运行模式（只显示将要执行的操作）"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 如果没有指定任何选项，默认维护所有数据库
    if not any([args.sqlite, args.lancedb, args.all]):
        args.all = True

    maintenance = DatabaseMaintenance(dry_run=args.dry_run)

    if args.dry_run:
        maintenance.logger.info("运行在干运行模式，不会实际修改数据库")

    success = True

    try:
        if args.sqlite or args.all:
            if not maintenance.maintain_sqlite():
                success = False

        if args.lancedb or args.all:
            if not maintenance.maintain_lancedb():
                success = False

        maintenance.print_maintenance_report()

        if success:
            maintenance.logger.info("数据库维护成功完成")
            return 0
        else:
            maintenance.logger.error("数据库维护过程中出现错误")
            return 1

    except KeyboardInterrupt:
        maintenance.logger.info("维护操作被用户中断")
        return 1
    except Exception as e:
        maintenance.logger.error(f"维护过程中发生未预期的错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
