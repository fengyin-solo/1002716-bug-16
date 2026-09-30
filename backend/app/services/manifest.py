"""箱单（对单）业务规则。

口岸对单发现的四类口径问题都在这里收口：

1. 列按“表头名称”取值而不是按下标取值——箱型尺寸/箱主代码串位、铅封号整列丢失，
   本质都是把列顺序写死导致的；表头序列与模板对不上的批次整批打回。
2. 毛重等数值列空着就是空着，保留 None，绝不灌成 0。
3. 同一次导出里相同箱号按箱号归并成一条；空值行整条跳过，并把源文件行号报回去。
4. 同一个批次号重复提交只认第一次，重复请求原样返回首份结果，不再多写一份。

批次落库的是“冻结快照”：出单时按当前勾选的箱状态过滤，但字段值不随后续操作漂移，
配合箱号稳定排序，保证详情页/列表页导出同一批数据逐条一致、重复导出也逐条一致。
"""
from __future__ import annotations

from typing import Any

from app.store import (
    TABLE_MANIFEST_ROWS,
    TABLE_MANIFESTS,
    store,
)

# 模板列序：导入按这套表头识别，导出也按这套列序出单。
TEMPLATE_COLUMNS = ["箱号", "箱型尺寸", "箱主代码", "毛重", "净重", "铅封号", "危品等级", "箱状态"]
REQUIRED_COLUMNS = ["箱号"]
# 箱状态必须落在这个集合里，勾错状态的行会在整批校验时被拦下。
VALID_STATUSES = ["在场", "已装船", "已提箱", "待查验"]


class ManifestValidationError(ValueError):
    """整批打回的校验错误，消息直接回给对单人员。"""


class ManifestService:
    # ---- 导入 ----------------------------------------------------------------

    def import_manifest(
        self,
        *,
        batch_no: str,
        columns: list[str],
        rows: list[list[Any]],
    ) -> dict[str, Any]:
        """接收一次箱单导出结果，校验、归并后整批落库。

        返回批次概览（accepted/skipped/merged 行数与跳过行号）；
        同一 batch_no 再提交时原样返回首份结果，不产生第二份箱单。
        """
        batch_no = str(batch_no or "").strip()
        if not batch_no:
            raise ManifestValidationError("批次号不能为空，无法按“同一次导出”归并")

        with store.lock:
            existing = self._find_batch(batch_no)
            if existing is not None:
                # 重复提交导出只认第一次：回首份结果，标记为重复提交，不再落库。
                result = self._batch_summary(existing)
                result["deduplicated"] = True
                result["message"] = f"批次 {batch_no} 已导入过，只认第一次的结果"
                return result

            normalized_cols = [str(col or "").strip() for col in columns]
            self._validate_columns(normalized_cols)

            accepted, skipped_rows, merged_duplicates = self._parse_rows(
                normalized_cols, rows
            )

            manifest = {
                "id": store.next_id(TABLE_MANIFESTS),
                "batch_no": batch_no,
                "imported_rows": len(accepted),
                "skipped_rows": skipped_rows,
                "merged_duplicates": merged_duplicates,
            }
            stored_rows = [
                {
                    "id": store.next_id(TABLE_MANIFEST_ROWS) + index,
                    "manifest_id": manifest["id"],
                    "batch_no": batch_no,
                    "seq": index + 1,
                    "source_row": item["source_row"],
                    **{col: item[col] for col in TEMPLATE_COLUMNS},
                }
                for index, item in enumerate(accepted)
            ]
            # 装配完毕才一次性提交：任何校验失败都走不到这里，不会留下半份箱单。
            store.commit_tables(
                {TABLE_MANIFESTS: [manifest], TABLE_MANIFEST_ROWS: stored_rows}
            )

            result = self._batch_summary(manifest)
            result["deduplicated"] = False
            result["message"] = self._build_import_message(
                batch_no, accepted, skipped_rows, merged_duplicates
            )
            return result

    def _validate_columns(self, columns: list[str]) -> None:
        """列序与模板对不上整批打回：缺列、多列、换序都不行。"""
        if columns == TEMPLATE_COLUMNS:
            return
        if not columns:
            raise ManifestValidationError("没有读到表头，整批打回：列序与模板对不上")
        if len(columns) != len(TEMPLATE_COLUMNS):
            raise ManifestValidationError(
                "整批打回：表头列数与模板不一致，"
                f"模板要求 {len(TEMPLATE_COLUMNS)} 列（{'、'.join(TEMPLATE_COLUMNS)}），"
                f"实际 {len(columns)} 列"
            )
        mismatches = [
            f"第 {idx + 1} 列应为「{expected}」实际为「{actual}」"
            for idx, (expected, actual) in enumerate(zip(TEMPLATE_COLUMNS, columns))
            if expected != actual
        ]
        raise ManifestValidationError(
            "整批打回：列序与模板对不上——" + "；".join(mismatches)
        )

    def _parse_rows(
        self, columns: list[str], raw_rows: list[list[Any]]
    ) -> tuple[list[dict[str, Any]], list[int], list[int]]:
        """逐行解析：空行跳过并记行号，同箱号按首次出现归并。

        行号从 2 起算（第 1 行是表头），与口岸对单人员看到的 Excel 行号一致。
        """
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        skipped_rows: list[int] = []
        duplicate_rows: list[int] = []

        for offset, raw in enumerate(raw_rows):
            source_row = offset + 2
            cells = list(raw or [])
            # 按表头名称取值，列与列串位/缺列都不会张冠李戴。
            record = {
                col: self._clean(cells[idx] if idx < len(cells) else None)
                for idx, col in enumerate(columns)
            }
            container_no = str(record.get("箱号") or "").strip()
            if not container_no or self._is_blank_row(record):
                # 空值行（连箱号都没有的整行空行）整条跳过。
                skipped_rows.append(source_row)
                continue

            status = record.get("箱状态")
            if status and status not in VALID_STATUSES:
                raise ManifestValidationError(
                    f"第 {source_row} 行箱状态「{status}」不在允许范围"
                    f"（{'、'.join(VALID_STATUSES)}），整批打回"
                )

            if container_no in merged:
                # 同一批箱号导入两次只保留一份：首条为主，后续非空值补缺。
                first = merged[container_no]
                for col in TEMPLATE_COLUMNS:
                    if first.get(col) is None and record.get(col) is not None:
                        first[col] = record[col]
                duplicate_rows.append(source_row)
            else:
                record["箱号"] = container_no
                record["source_row"] = source_row
                merged[container_no] = record
                order.append(container_no)

        accepted = [merged[no] for no in order]
        return accepted, skipped_rows, duplicate_rows

    @staticmethod
    def _clean(value: Any) -> Any:
        """空白清成 None（空值不灌 0），其余去首尾空白。"""
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @staticmethod
    def _is_blank_row(record: dict[str, Any]) -> bool:
        return all(record.get(col) is None for col in TEMPLATE_COLUMNS)

    @staticmethod
    def _build_import_message(
        batch_no: str,
        accepted: list[dict[str, Any]],
        skipped_rows: list[int],
        duplicate_rows: list[int],
    ) -> str:
        parts = [f"批次 {batch_no} 已对单入库，归并后 {len(accepted)} 箱"]
        if skipped_rows:
            parts.append(f"跳过空值行 {len(skipped_rows)} 行（行号 {', '.join(map(str, skipped_rows))}）")
        if duplicate_rows:
            parts.append(
                f"同箱号重复归并 {len(duplicate_rows)} 行（行号 {', '.join(map(str, duplicate_rows))}）"
            )
        return "；".join(parts)

    # ---- 查询与导出 ----------------------------------------------------------

    def list_batches(self, page: int = 1, size: int = 20) -> tuple[list[dict[str, Any]], int]:
        """箱单批次列表：后导入的在前，合计随箱单实时重算。"""
        manifests = sorted(
            self.rows(),
            key=lambda item: int(item["id"]),
            reverse=True,
        )
        total = len(manifests)
        start = max(page - 1, 0) * size
        page_items = [self._batch_summary(item) for item in manifests[start:start + size]]
        return page_items, total

    def get_batch(self, batch_no: str) -> dict[str, Any] | None:
        manifest = self._find_batch(batch_no)
        if manifest is None:
            return None
        return self._batch_summary(manifest)

    def export_batch(
        self, batch_no: str, statuses: list[str] | None = None
    ) -> dict[str, Any] | None:
        """出单：详情页与列表页走的都是这一个口径。

        - 按当前勾选的箱状态过滤（不勾视为全部）；
        - 危品等级、铅封号随单带出；
        - 冻结快照 + 箱号稳定排序，同一批再导一次逐条一样。
        """
        manifest = self._find_batch(batch_no)
        if manifest is None:
            return None
        selected = self._selected_statuses(statuses)
        invalid = [item for item in (statuses or []) if item not in VALID_STATUSES]
        if invalid:
            raise ManifestValidationError(
                f"箱状态「{'、'.join(invalid)}」不在允许范围（{'、'.join(VALID_STATUSES)}）"
            )

        rows = sorted(
            (
                {col: row.get(col) for col in TEMPLATE_COLUMNS}
                for row in self.row_rows()
                if int(row.get("manifest_id", 0)) == int(manifest["id"])
                and (not selected or row.get("箱状态") in selected)
            ),
            key=lambda item: str(item["箱号"]),
        )
        gross_total = self._sum_weight(rows, "毛重")
        net_total = self._sum_weight(rows, "净重")
        return {
            "module": "container_manifest",
            "batch_no": batch_no,
            "columns": TEMPLATE_COLUMNS,
            "statuses": selected,
            "total": len(rows),
            "items": rows,
            # 对账合计跟这批箱单一起重算，空毛重不计入合计，不按 0 混算。
            "summary": {"box_count": len(rows), "gross_total": gross_total, "net_total": net_total},
        }

    def reconciliation_totals(self) -> dict[str, Any]:
        """对账看板合计：跟着当前所有箱单实时重算。"""
        rows = [
            {col: row.get(col) for col in TEMPLATE_COLUMNS}
            for row in self.row_rows()
        ]
        by_status = {status: 0 for status in VALID_STATUSES}
        for row in self.row_rows():
            status = row.get("箱状态")
            if status in by_status:
                by_status[status] += 1
        return {
            "batch_count": len(self.rows()),
            "box_count": len(rows),
            "gross_total": self._sum_weight(rows, "毛重"),
            "net_total": self._sum_weight(rows, "净重"),
            "by_status": by_status,
        }

    # ---- 内部辅助 ------------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        return store.rows(TABLE_MANIFESTS)

    def row_rows(self) -> list[dict[str, Any]]:
        return store.rows(TABLE_MANIFEST_ROWS)

    @staticmethod
    def _selected_statuses(statuses: list[str] | None) -> list[str]:
        selected = [str(item).strip() for item in (statuses or []) if str(item or "").strip()]
        # 去重但保持勾选顺序，列表页与详情页传同样的勾选就能得到同样的结果。
        return list(dict.fromkeys(selected))

    def _find_batch(self, batch_no: str) -> dict[str, Any] | None:
        for manifest in self.rows():
            if manifest.get("batch_no") == batch_no:
                return manifest
        return None

    def _batch_summary(self, manifest: dict[str, Any]) -> dict[str, Any]:
        row_count = sum(
            1
            for row in self.row_rows()
            if int(row.get("manifest_id", 0)) == int(manifest["id"])
        )
        return {
            "id": manifest["id"],
            "batch_no": manifest["batch_no"],
            "imported_rows": manifest.get("imported_rows", row_count),
            "skipped_rows": manifest.get("skipped_rows", []),
            "merged_duplicates": manifest.get("merged_duplicates", []),
            "box_count": row_count,
        }

    @staticmethod
    def _sum_weight(rows: list[dict[str, Any]], field: str) -> float:
        total = 0.0
        for row in rows:
            value = row.get(field)
            if value is None:
                continue
            try:
                total += float(value)
            except (TypeError, ValueError):
                # 非数值毛重不参与合计，也不被当成 0。
                continue
        return round(total, 3)


manifest_service = ManifestService()
