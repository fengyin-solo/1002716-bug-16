"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

箱单导入走 commit_tables 事务式提交：先在临时副本里把整批数据装配好，
任何一步校验失败都不触碰正式表，保证“中途断开不留半份箱单”。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS

# 箱单相关的两张内部表，不计入业务模块看板
TABLE_MANIFESTS = "manifests"
TABLE_MANIFEST_ROWS = "manifest_rows"
INTERNAL_TABLES = frozenset({TABLE_MANIFESTS, TABLE_MANIFEST_ROWS})


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._tables[TABLE_MANIFESTS] = []
        self._tables[TABLE_MANIFEST_ROWS] = []
        self._lock = threading.RLock()

    @property
    def lock(self) -> threading.RLock:
        """写操作串行化，避免并发导入同一批次时写出两份。"""
        return self._lock

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in INTERNAL_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    def commit_tables(self, changes: dict[str, list[dict[str, Any]]]) -> None:
        """整批追加多张表的数据：要么全部追加成功，要么一张表都不动。

        changes 里的行应已在调用方完成全部业务校验，这里只负责原子落库。
        """
        with self._lock:
            staged = {name: [dict(row) for row in rows] for name, rows in changes.items()}
            for name, rows in staged.items():
                self._tables.setdefault(name, []).extend(rows)

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
