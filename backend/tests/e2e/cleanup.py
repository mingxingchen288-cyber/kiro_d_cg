"""浏览器端到端用例（frontend/tests/e2e/）结束时调用：删掉这次运行产生的平台记录（dcg.Cleanup）。

用法（在 backend 目录）：`uv run python -m tests.e2e.cleanup --keys <请求键,…> --approvals <审批编号,…> --users <账号编号,…>`。
请求键为浏览器提交的命令（保存、通过、驳回）的 requestKey，删掉它们的命令记录、投递和站内通知；审批编号为浏览器中
发起的审批，删掉审批实例、处理记录、受影响行和冻结记录；账号编号为用例经平台新建的测试账号（平台没有删除账号的接口），
删掉 PF_USER、PF_USER_ROLE。业务数据由用例自己删。输出删掉前找到的条数。
"""

from __future__ import annotations

import argparse

from .dcg import Cleanup, oracle_engine, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", default="")
    parser.add_argument("--approvals", default="")
    parser.add_argument("--users", default="")
    args = parser.parse_args()
    engine = oracle_engine()
    cleanup = Cleanup(engine)
    cleanup.request_keys = [k for k in args.keys.split(",") if k]
    cleanup.approvals = [a for a in args.approvals.split(",") if a]
    cleanup.users = [u for u in args.users.split(",") if u]
    commands = sum(len(rows(engine, "SELECT 1 FROM pf_command WHERE request_key = :k", k=k)) for k in cleanup.request_keys)
    approvals = sum(len(rows(engine, "SELECT 1 FROM pf_approval WHERE approval_id = :a", a=int(a))) for a in cleanup.approvals)
    users = sum(len(rows(engine, "SELECT 1 FROM pf_user WHERE user_id = :u", u=int(u))) for u in cleanup.users)
    cleanup.run()
    print(f"删掉命令记录 {commands} 条、审批 {approvals} 个（及其投递、站内通知、处理记录、冻结记录）、测试账号 {users} 个")


if __name__ == "__main__":
    main()
