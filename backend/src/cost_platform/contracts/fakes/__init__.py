"""C08 端口和管道阶段的内存替代实现（CT-03）。

各模块开发和验收时用它们代替其他模块的真实实现（结果记为"模拟验证"）。每个替代实现：
- 记录收到的调用（`calls`、`calls_to`）；
- 可以预设错误：`fail(方法名, 错误, times=次数)`，`times=None` 时一直抛出，`recover()` 撤销；
- 返回值由各自的预设方法给出，见各类的说明。

每个替代实现都通过 `backend/tests/contracts/` 中对应端口的契约测试，真实实现运行同一套测试。
"""

from ._script import Call, Scripted
from .approval import FakeFreezeReader
from .authz import FakePermissionChecker
from .config import FakeConfigImporter, FakeConfigSnapshot, FakeConfigSnapshotReader
from .db import FakeConnectionFactory, FakeSchemaInspector, FakeUnitOfWork, FakeUnitOfWorkFactory
from .delivery import FakeDeliveryDispatcher
from .identity import FakeAuthenticator, FakeDirectory
from .pipeline import FakeCommandExecutor, FakeStage, unchanged
from .queries import FakeDocumentReader, FakePersonalConfigImporter, FakeRelatedQuery
from .realtime import FakeRealtimePublisher
from .rules import FakePack, FakeRulesEngine
from .system import FakeClock, FakeIdGenerator

PORT_FAKES = {
    "UnitOfWork": FakeUnitOfWork,
    "UnitOfWorkFactory": FakeUnitOfWorkFactory,
    "SchemaInspector": FakeSchemaInspector,
    "ConnectionFactory": FakeConnectionFactory,
    "Authenticator": FakeAuthenticator,
    "DirectoryReader": FakeDirectory,
    "AccountImporter": FakeDirectory,
    "ConfigSnapshot": FakeConfigSnapshot,
    "ConfigSnapshotReader": FakeConfigSnapshotReader,
    "ConfigImporter": FakeConfigImporter,
    "CommandExecutor": FakeCommandExecutor,
    "PipelineStage": FakeStage,
    "PermissionChecker": FakePermissionChecker,
    "RulesEngine": FakeRulesEngine,
    "RelatedQuery": FakeRelatedQuery,
    "DocumentReader": FakeDocumentReader,
    "PersonalConfigImporter": FakePersonalConfigImporter,
    "DeliveryDispatcher": FakeDeliveryDispatcher,
    "RealtimePublisher": FakeRealtimePublisher,
    "Clock": FakeClock,
    "IdGenerator": FakeIdGenerator,
    "FreezeReader": FakeFreezeReader,
}
"""C08 每个端口（ports.py 中的 Protocol）对应的替代实现。"""

__all__ = [
    "PORT_FAKES",
    "Call",
    "FakeAuthenticator",
    "FakeClock",
    "FakeCommandExecutor",
    "FakeConfigImporter",
    "FakeConfigSnapshot",
    "FakeConfigSnapshotReader",
    "FakeConnectionFactory",
    "FakeDeliveryDispatcher",
    "FakeDirectory",
    "FakeDocumentReader",
    "FakeFreezeReader",
    "FakeIdGenerator",
    "FakePack",
    "FakePermissionChecker",
    "FakePersonalConfigImporter",
    "FakeRealtimePublisher",
    "FakeRelatedQuery",
    "FakeRulesEngine",
    "FakeSchemaInspector",
    "FakeStage",
    "FakeUnitOfWork",
    "FakeUnitOfWorkFactory",
    "Scripted",
    "unchanged",
]
