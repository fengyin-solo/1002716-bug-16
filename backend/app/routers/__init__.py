"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import berth as router_berth
from app.routers import vessel as router_vessel
from app.routers import quaycrane as router_quaycrane
from app.routers import yardplan as router_yardplan
from app.routers import rtg as router_rtg
from app.routers import truck as router_truck
from app.routers import container as router_container
from app.routers import manifest as router_manifest
from app.routers import gate as router_gate
from app.routers import dangerous as router_dangerous
from app.routers import coldchain as router_coldchain
from app.routers import lashing as router_lashing
from app.routers import shift as router_shift
from app.routers import repair as router_repair
from app.routers import tally as router_tally
from app.routers import customs as router_customs
from app.routers import feeder as router_feeder
from app.routers import oog as router_oog
from app.routers import emptystack as router_emptystack
from app.routers import energy as router_energy
from app.routers import safetycheck as router_safetycheck

ROUTERS = [router_berth, router_vessel, router_quaycrane, router_yardplan, router_rtg, router_truck, router_container, router_manifest, router_gate, router_dangerous, router_coldchain, router_lashing, router_shift, router_repair, router_tally, router_customs, router_feeder, router_oog, router_emptystack, router_energy, router_safetycheck]
