"""契约：模块之间共用的类型（types.py）和端口协议（ports.py），定义见 docs/契约/。

types.py、ports.py 只依赖标准库和 pydantic；替代实现（fakes/）中的事务和只读连接另用 SQLAlchemy 和内存 SQLite。
各模块这样导入：
    from cost_platform.contracts.types import Command, CommandResult
    from cost_platform.contracts.ports import UnitOfWorkFactory
    from cost_platform.contracts.fakes import FakeUnitOfWorkFactory   # 只在测试和 PLATFORM_BACKEND=memory 时使用
"""
