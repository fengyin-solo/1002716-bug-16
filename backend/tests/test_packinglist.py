"""箱单对单口径验证：用 TestClient 跑通全部约定场景。运行：python3 -m tests.test_packinglist"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.packinglist import TEMPLATE_COLUMNS, service

client = TestClient(app)

fails: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" -> {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def reset() -> None:
    # 重新构造一份干净台账（保留 seed 逻辑外的可控数据）
    service._batches.clear()
    service._seq = 0


def import_body(batch_no: str, rows, columns=None):
    return client.post(
        "/api/packinglist/batches/import",
        json={"batch_no": batch_no, "columns": columns or list(TEMPLATE_COLUMNS), "rows": rows},
    )


# 0. 健康 & 模板
r = client.get("/api/packinglist/template")
check("模板列序含危品等级与铅封号", r.json()["columns"] == TEMPLATE_COLUMNS
      and "铅封号" in r.json()["columns"] and "危品等级" in r.json()["columns"], r.json())

reset()

# 1. 空行跳过 + 行号；批内重复只认第一次；空毛重不灌 0
rows = [
    ["CBHU1234567", "20GP", "COSU", "18500", "3000", "SL1", "", "在场"],
    ["", "", "", "", "", "", "", ""],          # line 3 空行
    ["CBHU1234567", "20GP", "COSU", "18500", "3000", "SL1", "", "在场"],  # 重复
    ["TRLU7654321", "40HC", "MAEU", "", "4200", "SL2", "3", "已装船"],     # 空毛重
]
r = import_body("B1", rows)
body = r.json()
check("导入成功", r.status_code == 200 and body["ok"] is True, r.status_code)
check("空行跳过且记录行号=3", body["skipped_lines"] == [3], body["skipped_lines"])
check("批内重复箱号只认第一次", body["accepted_count"] == 2, body)
check("批内重复记录箱号与行号", body["duplicate_in_batch"] == {"CBHU1234567": [4]}, body["duplicate_in_batch"])
gross_null_row = [x for x in body["rows"] if x["箱号"] == "TRLU7654321"][0]
check("空毛重保留 null 而不是 0", gross_null_row["毛重"] is None, gross_null_row["毛重"])
check("合计毛重不含空值(18500)", body["gross_total"] == 18500, body["gross_total"])
check("危品等级/铅封号已带上", gross_null_row["危品等级"] == "3" and gross_null_row["铅封号"] == "SL2")

# 2. 同批次号重复提交只认第一次
r2 = import_body("B1", [["XXXX9999999", "20GP", "ZZZ", "1", "1", "S", "", "在场"]])
check("重复批次号返回首份且 reused", r2.json()["reused"] is True and r2.json()["accepted_count"] == 2, r2.json())

# 3. 跨批次同一箱号只认第一次
r3 = import_body("B2", [["CBHU1234567", "20GP", "COSU", "999", "1", "S9", "", "在场"],
                        ["NEW1111111", "40GP", "MSKU", "5000", "1", "S8", "", "在场"]])
b3 = r3.json()
check("跨批重复箱号被忽略", "CBHU1234567" in b3["duplicate_prior"] and b3["accepted_count"] == 1, b3)

# 4. 列序不符整批打回，且不留批次
bad_cols = ["箱号", "箱主代码", "箱型尺寸", "毛重", "净重", "铅封号", "危品等级", "箱状态"]  # 2/3 调换
before = client.get("/api/packinglist/batches").json()["total"]
r4 = import_body("B3", [["A", "20GP", "COSU", "1", "1", "S", "", "在场"]], columns=bad_cols)
after = client.get("/api/packinglist/batches").json()["total"]
check("列序不符 400 整批打回", r4.status_code == 400 and r4.json()["detail"]["code"] == "COLUMN_MISMATCH", r4.json())
check("打回不留批次(原子)", before == after, (before, after))

# 4b. 缺列/非数值/箱号空行 也整批打回
r4b = import_body("B4", [["A", "20GP", "COSU", "abc", "1", "S", "", "在场"]])
check("非数值毛重整批打回", r4b.status_code == 400 and r4b.json()["detail"]["code"] == "INVALID_NUMBER")
r4c = import_body("B5", [["", "20GP", "COSU", "1", "1", "S", "", "在场"]])
check("箱号空(整行非空)整批打回", r4c.status_code == 400 and r4c.json()["detail"]["code"] == "MISSING_KEY")

# 5. 出单按勾选箱状态；详情/列表同一出口；逐条一致 + checksum
bid = [b for b in client.get("/api/packinglist/batches").json()["items"] if b["batch_no"] == "B1"][0]["id"]
e_all = client.get(f"/api/packinglist/batches/{bid}/export").json()
e_zaizhuang = client.get(f"/api/packinglist/batches/{bid}/export?status=已装船").json()
check("出单列固定含危品+铅封", e_all["columns"] == TEMPLATE_COLUMNS, e_all["columns"])
check("按勾选状态过滤只出已装船1条", e_zaizhuang["total"] == 1
      and all(it["箱状态"] == "已装船" for it in e_zaizhuang["items"]), e_zaizhuang)
e_all2 = client.get(f"/api/packinglist/batches/{bid}/export").json()
check("同一批再导逐条一样", e_all["items"] == e_all2["items"] and e_all["checksum"] == e_all2["checksum"])
check("不同筛选指纹不同", e_all["checksum"] != e_zaizhuang["checksum"])
check("按箱号排序确定", [it["箱号"] for it in e_all["items"]] == sorted(it["箱号"] for it in e_all["items"]))

# 6. 不存在批次
check("导出不存在批次 400", client.get("/api/packinglist/batches/9999/export").status_code == 400)

# 7. 对账合计随箱单重算
rec = client.get("/api/packinglist/reconciliation").json()
check("对账合计箱数=3(B1 2 + B2 1)", rec["box_count"] == 3, rec)
check("对账毛重合计=18500+5000=23500(空不计)", rec["gross_total"] == 23500, rec["gross_total"])
check("对账危品箱=1", rec["dangerous_boxes"] == 1, rec["dangerous_boxes"])
check("对账缺铅封=0(SL1/S2/S8)", rec["missing_seal_boxes"] == 0, rec["missing_seal_boxes"])
check("按状态合计", rec["by_status"].get("在场") == 2 and rec["by_status"].get("已装船") == 1, rec["by_status"])

# 8. 批次详情含原始行号信息
det = client.get(f"/api/packinglist/batches/{bid}").json()
check("详情保留跳过行号与重复信息", det["skipped_lines"] == [3] and "CBHU1234567" in det["duplicate_in_batch"])

print()
if fails:
    print(f"{len(fails)} 项未通过：{fails}")
    raise SystemExit(1)
print("全部口径验证通过 ✔")
