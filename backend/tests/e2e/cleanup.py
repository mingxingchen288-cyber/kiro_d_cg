"""浏览器端到端用例（frontend/tests/e2e/）结束时调用：删掉这次运行产生的平台记录（dcg.Cleanup）。

用法（在 backend 目录）：`uv run python -m tests.e2e.cleanup --keys <请求键,…> --approvals <审批编号,…>`。
请求键为浏览器提交的命令（保存、通过、驳回）的 requestKey，删掉它们的命令记录、投递和站内通知；审批编号为浏览器中
发起的审批，删掉审批实例、处理记录、受影响行和冻结记录。业务数据由用例自己改回。输出删掉前找到的条数。
"""

from __future__ import annotations

import argparse

from .dcg import Cleanup, oracle_engine, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", default="")
    parser.add_argument("--approvals", default="")
    args = parser.parse_args()
    engine = oracle_engine()
    cleanup = Cleanup(engine)
    cleanup.request_keys = [k for k in args.keys.split(",") if k]
    cleanup.approvals = [a for a in args.approvals.split(",") if a]
    commands = sum(len(rows(engine, "SELECT 1 FROM pf_command WHERE request_key = :k", k=k)) for k in cleanup.request_keys)
    approvals = sum(len(rows(engine, "SELECT 1 FROM pf_approval WHERE approval_id = :a", a=int(a))) for a in cleanup.approvals)
    cleanup.run()
    print(f"删掉命令记录 {commands} 条、审批 {approvals} 个（及其投递、站内通知、处理记录、冻结记录）")


if __name__ == "__main__":
    main()
