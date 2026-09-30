"""箱单对单业务规则。

口径（与口岸对单约定对齐，全部收口在这一层，接口层只做转发）：

1. 列序以模板为准：表头必须与 TEMPLATE_COLUMNS 逐列一致，对不上整批打回，不入库。
2. 空值行（整行没有任何内容）跳过，并记录物理行号（表头算第 1 行）。
3. 同一次提交里按箱号归并，同一个箱号只认第一次出现的那一行。
4. 已在更早批次落库的箱号再次提交也只认第一次，后到的行记为重复并忽略。
5. 毛重、净重为空保留为空（None），绝不灌成 0；非空必须是数值，否则整批打回。
6. 出单按勾选的箱状态过滤，列固定且始终带齐危品等级、铅封号（空也保留整列）。
7. 同一批次号重复提交直接返回首份结果，不会多出一份箱单。
8. 先在内存里完成全部校验，再在锁内一次性提交，中途失败不会留下半份箱单。
9. 导出按箱号排序、列序固定并给校验指纹；列表页与详情页走同一出口，逐条一致。
"""
from __future__ import annotations

import hashlib
import json
import threading
from decimal import Decimal, InvalidOperation
from typing import Any

# 箱单模板列序：表头必须逐列等于它，顺序错、缺列、多列都整批打回。
TEMPLATE_COLUMNS: list[str] = ["箱号", "箱型尺寸", "箱主代码", "毛重", "净重", "铅封号", "危品等级", "箱状态"]
KEY_COLUMN = "箱号"
NUMERIC_COLUMNS = ("毛重", "净重")
# 出单固定列序，危品等级与铅封号显式在列，杜绝整列丢失。
EXPORT_COLUMNS: list[str] = list(TEMPLATE_COLUMNS)
BOX_STATUSES = ("在场", "已装船", "已提箱", "待查验")


class BatchRejected(Exception):
    """整批打回：任何一条数据不合规都不允许落库半行。"""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_detail(self) -> dict[str, Any]:
        detail = {"code": self.code, "message": self.message}
        detail.update(self.extra)
        return detail


def _is_blank_row(cells: list[str]) -> bool:
    return all(not str(cell or "").strip() for cell in cells)


def _parse_number(raw: str, *, line: int, column: str) -> int | float | None:
    """空 → None（不是 0）；整数返回 int，其余返回 float；非数值整批打回。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        Decimal(text)  # 先确认是合法数值
    except InvalidOperation:
        raise BatchRejected(
            "INVALID_NUMBER",
            f"第 {line} 行「{column}」不是合法数值：{text}",
            line=line,
            column=column,
            value=text,
        )
    try:
        return int(text)
    except ValueError:
        return float(text)


class PackingListService:
    """箱单批次台账：批次整存整取，箱号全局唯一（只认第一次）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        # batch_no -> batch；批次数组本身也按落库顺序保存
        self._batches: dict[str, dict[str, Any]] = {}

    # ---------- 导入 ----------
    def import_batch(
        self,
        *,
        batch_no: str,
        columns: list[str],
        rows: list[list[Any]],
    ) -> dict[str, Any]:
        batch_no = str(batch_no or "").strip()
        if not batch_no:
            raise BatchRejected("MISSING_BATCH_NO", "缺少批次号（同一次导出的归并键）")
        columns = [str(c or "").strip() for c in columns]

        # 1) 列序与模板逐列比对：对不上整批打回。
        if columns != TEMPLATE_COLUMNS:
            raise BatchRejected(
                "COLUMN_MISMATCH",
                "列序与模板对不上，整批打回；请按模板表头顺序导入",
                expected=TEMPLATE_COLUMNS,
                actual=columns,
            )

        # 2) 逐行在内存里解析、校验；此阶段不写任何状态，失败天然不留半份。
        parsed: list[dict[str, Any]] = []
        skipped_lines: list[int] = []
        for offset, raw_row in enumerate(rows):
            line = offset + 2  # 表头是第 1 行
            cells = [str(c if c is not None else "") for c in raw_row]
            if _is_blank_row(cells):
                skipped_lines.append(line)
                continue
            if len(cells) != len(TEMPLATE_COLUMNS):
                raise BatchRejected(
                    "ROW_ARITY_MISMATCH",
                    f"第 {line} 行列数为 {len(cells)}，模板要求 {len(TEMPLATE_COLUMNS)} 列，整批打回",
                    line=line,
                )
            record: dict[str, Any] = {"source_line": line}
            for idx, column in enumerate(TEMPLATE_COLUMNS):
                value = cells[idx].strip()
                if column == KEY_COLUMN:
                    if not value:
                        raise BatchRejected(
                            "MISSING_KEY",
                            f"第 {line} 行箱号为空，无法归并，整批打回",
                            line=line,
                        )
                    record[column] = value
                elif column in NUMERIC_COLUMNS:
                    record[column] = _parse_number(value, line=line, column=column)
                else:
                    record[column] = value or None
            parsed.append(record)

        # 3) 同一次提交内按箱号归并，只认第一次。
        seen_in_submission: set[str] = set()
        duplicate_in_batch: dict[str, list[int]] = {}
        ordered: list[dict[str, Any]] = []
        for record in parsed:
            key = record[KEY_COLUMN]
            if key in seen_in_submission:
                duplicate_in_batch.setdefault(key, []).append(record["source_line"])
                continue
            seen_in_submission.add(key)
            ordered.append(record)

        # 4) 锁内做幂等与跨批次去重，并一次性提交。
        with self._lock:
            existing = self._batches.get(batch_no)
            if existing is not None:
                # 同一批次号重复提交：原样返回首份结果，不多一份。
                return self._summary(existing, reused=True)

            known = {
                row[KEY_COLUMN]
                for batch in self._batches.values()
                for row in batch["rows"]
            }
            duplicate_prior: dict[str, list[int]] = {}
            accepted: list[dict[str, Any]] = []
            for record in ordered:
                key = record[KEY_COLUMN]
                if key in known:
                    duplicate_prior.setdefault(key, []).append(record["source_line"])
                    continue
                known.add(key)
                accepted.append(record)

            self._seq += 1
            batch = {
                "id": self._seq,
                "batch_no": batch_no,
                # 出单口径要求逐条一致：按箱号排序后固化
                "rows": sorted(accepted, key=lambda r: r[KEY_COLUMN]),
                "skipped_lines": skipped_lines,
                "duplicate_in_batch": duplicate_in_batch,
                "duplicate_prior": duplicate_prior,
            }
            self._batches[batch_no] = batch
            return self._summary(batch, reused=False)

    # ---------- 查询 / 导出 ----------
    def list_batches(self) -> list[dict[str, Any]]:
        with self._lock:
            summaries = [self._summary(b, reused=False, include_rows=False)
                         for b in self._batches.values()]
        return summaries

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        with self._lock:
            for batch in self._batches.values():
                if batch["id"] == batch_id:
                    return batch
        return None

    def export_batch(self, batch_id: int, statuses: list[str] | None) -> dict[str, Any]:
        """列表页与详情页共用的唯一出单口：同批同筛选条件结果逐条一样。"""
        batch = self.get_batch(batch_id)
        if batch is None:
            raise BatchRejected("BATCH_NOT_FOUND", f"批次 {batch_id} 不存在或已归档")

        wanted = {s.strip() for s in (statuses or []) if s and s.strip()}
        filtered = [
            row for row in batch["rows"]
            if not wanted or (row.get("箱状态") or "未标注") in wanted
        ]
        # 已在入库时排序，这里仍显式排序以保证出口确定性
        filtered = sorted(filtered, key=lambda r: r[KEY_COLUMN])
        items = [{col: row.get(col) for col in EXPORT_COLUMNS} for row in filtered]
        return {
            "module": "packinglist",
            "batch_id": batch["id"],
            "batch_no": batch["batch_no"],
            "status_filter": sorted(wanted),
            "columns": list(EXPORT_COLUMNS),
            "total": len(items),
            "checksum": _checksum(batch["batch_no"], wanted, items),
            "items": items,
        }

    # ---------- 对账看板 ----------
    def reconciliation(self) -> dict[str, Any]:
        """合计数不缓存：随当前已落库的箱单实时重算，保证看板跟着这批箱单走。"""
        with self._lock:
            all_rows = [row for batch in self._batches.values() for row in batch["rows"]]

        by_status: dict[str, int] = {status: 0 for status in BOX_STATUSES}
        gross_total = Decimal("0")
        dangerous_boxes = 0
        missing_seal = 0
        for row in all_rows:
            status = row.get("箱状态") or "未标注"
            by_status[status] = by_status.get(status, 0) + 1
            gross = row.get("毛重")
            if gross is not None:
                gross_total += Decimal(str(gross))
            if row.get("危品等级"):
                dangerous_boxes += 1
            if not row.get("铅封号"):
                missing_seal += 1

        return {
            "module": "packinglist",
            "batch_count": len(self._batches),
            "box_count": len(all_rows),
            # 空毛重不计入，绝不按 0 之外的口径灌值，也不把空当 0 之外的虚高
            "gross_total": _decimal_to_number(gross_total),
            "dangerous_boxes": dangerous_boxes,
            "missing_seal_boxes": missing_seal,
            "by_status": by_status,
        }

    # ---------- 内部 ----------
    @staticmethod
    def _summary(batch: dict[str, Any], *, reused: bool, include_rows: bool = True) -> dict[str, Any]:
        gross_total = Decimal("0")
        for row in batch["rows"]:
            if row.get("毛重") is not None:
                gross_total += Decimal(str(row["毛重"]))
        summary: dict[str, Any] = {
            "ok": True,
            "reused": reused,
            "id": batch["id"],
            "batch_no": batch["batch_no"],
            "accepted_count": len(batch["rows"]),
            "gross_total": _decimal_to_number(gross_total),
            "skipped_lines": list(batch["skipped_lines"]),
            "duplicate_in_batch": dict(batch["duplicate_in_batch"]),
            "duplicate_prior": dict(batch["duplicate_prior"]),
        }
        if include_rows:
            summary["rows"] = [dict(row) for row in batch["rows"]]
        return summary


def _decimal_to_number(value: Decimal) -> int | float:
    if value == value.to_integral():
        return int(value)
    return float(value)


def _checksum(batch_no: str, wanted: set[str], items: list[dict[str, Any]]) -> str:
    """对出单内容做指纹：同批同筛选两次导出指纹相同，逐行可对账。"""
    payload = json.dumps(
        {"batch_no": batch_no, "status_filter": sorted(wanted), "items": items},
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 单例：内存台账（真实项目会换成数据库 + 事务，锁内一次性提交的语义保持不变）。
service = PackingListService()


def _seed() -> None:
    """造一份口径正确的示例批次：含空行、批内重复、空毛重，便于立刻看到对单效果。"""
    service.import_batch(
        batch_no="SEED-20260930-01",
        columns=list(TEMPLATE_COLUMNS),
        rows=[
            ["CBHU1234567", "20GP", "COSU", "18500", "3000", "SL-0001", "", "在场"],
            ["", "", "", "", "", "", "", ""],  # 第 3 行空行，跳过
            ["CBHU1234567", "20GP", "COSU", "18500", "3000", "SL-0001", "", "在场"],  # 批内重复
            ["TRLU7654321", "40HC", "MAEU", "", "4200", "SL-0002", "3", "已装船"],     # 空毛重
            ["MSKU1111111", "40GP", "MSKU", "22000", "3900", "", "", "待查验"],        # 空铅封
        ],
    )


_seed()
