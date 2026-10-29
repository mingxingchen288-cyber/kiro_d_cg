"""T-CT-3：每个端口都有替代实现和契约测试；替代实现的方法与端口一致；预设错误的方式统一（CT-03、CT-05）。"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from cost_platform.contracts import fakes, ports
from cost_platform.contracts.fakes import PORT_FAKES, Call, FakeClock, FakeDocumentReader, Scripted
from cost_platform.contracts.types import DocumentRef, ErrorCode, PlatformError

REAL_ONLY = {"CommandRecorder", "TableWriter", "ContextProvider"}
"""不写替代实现和契约测试、直接用真实实现验证的端口：第 5a 节的写入能力（2026-10-28，用户："按这个做"，在 d_cg 上验证），
以及 assembly 提供的 `ContextProvider`（2026-10-29，把 HTTP 请求变成执行上下文，由浏览器联调验证）。"""

PORTS = {name: obj for name, obj in vars(ports).items()
         if inspect.isclass(obj) and getattr(obj, "_is_protocol", False) and obj.__module__ == ports.__name__
         and name not in REAL_ONLY}

# 每个端口的契约测试类；UnitOfWork 与工厂、ConfigSnapshot 与读取方在同一套测试中
PORT_CONTRACTS = {
    "UnitOfWork": "test_unit_of_work.UnitOfWorkContract",
    "UnitOfWorkFactory": "test_unit_of_work.UnitOfWorkContract",
    "SchemaInspector": "test_schema_inspector.SchemaInspectorContract",
    "ConnectionFactory": "test_connection_factory.ConnectionFactoryContract",
    "Authenticator": "test_authenticator.AuthenticatorContract",
    "DirectoryReader": "test_directory_reader.DirectoryReaderContract",
    "AccountImporter": "test_account_importer.AccountImporterContract",
    "ConfigSnapshot": "test_config_snapshot_reader.ConfigSnapshotReaderContract",
    "ConfigSnapshotReader": "test_config_snapshot_reader.ConfigSnapshotReaderContract",
    "ConfigImporter": "test_config_importer.ConfigImporterContract",
    "EntityDirectory": "test_entity_directory.EntityDirectoryContract",
    "CommandExecutor": "test_command_executor.CommandExecutorContract",
    "PipelineStage": "test_pipeline_stage.PipelineStageContract",
    "PermissionChecker": "test_permission_checker.PermissionCheckerContract",
    "RulesEngine": "test_rules_engine.RulesEngineContract",
    "RelatedQuery": "test_related_query.RelatedQueryContract",
    "DocumentReader": "test_document_reader.DocumentReaderContract",
    "PersonalConfigImporter": "test_personal_config_importer.PersonalConfigImporterContract",
    "DeliveryDispatcher": "test_delivery_dispatcher.DeliveryDispatcherContract",
    "RealtimePublisher": "test_realtime_publisher.RealtimePublisherContract",
    "Clock": "test_clock.ClockContract",
    "IdGenerator": "test_id_generator.IdGeneratorContract",
    "FreezeReader": "test_freeze_reader.FreezeReaderContract",
}


def _protocol_members(protocol: type) -> tuple[dict[str, inspect.Signature], set[str]]:
    methods = {n: inspect.signature(f) for n, f in vars(protocol).items() if inspect.isfunction(f) and not n.startswith("_")}
    attributes = set(vars(protocol).get("__annotations__", {})) - set(methods)
    return methods, attributes


def test_every_port_has_fake_and_contract() -> None:
    assert len(PORTS) == 23
    assert set(PORT_FAKES) == set(PORTS)
    assert set(PORT_CONTRACTS) == set(PORTS)
    for name, target in PORT_CONTRACTS.items():
        module_name, cls_name = target.split(".")
        module = importlib.import_module(f"{__package__}.{module_name}")
        contract = getattr(module, cls_name)
        assert any(n.startswith("test_") for n in dir(contract)), name
        concrete = [c for c in vars(module).values() if inspect.isclass(c) and issubclass(c, contract) and c is not contract]
        assert any(c.__name__.startswith("TestFake") for c in concrete), f"{name} 的替代实现没有运行 {cls_name}"


@pytest.mark.parametrize("port", sorted(PORTS))
def test_fake_matches_port(port: str) -> None:
    """替代实现有端口的全部方法，参数名和默认值相同；端口的方法都在 `scriptable` 中，可以预设错误。"""
    methods, attributes = _protocol_members(PORTS[port])
    fake = PORT_FAKES[port]
    for name, signature in methods.items():
        impl = getattr(fake, name, None)
        assert callable(impl), f"{fake.__name__} 缺少 {name}"
        expected = [(p.name, p.default) for p in list(signature.parameters.values())[1:]]
        actual = [(p.name, p.default) for p in list(inspect.signature(impl).parameters.values())[1:]]
        assert actual == expected, f"{fake.__name__}.{name}"
    if issubclass(fake, Scripted):
        assert set(fake.scriptable) >= set(methods), fake.__name__
    for attribute in attributes:
        assert hasattr(fake, attribute) or f"self.{attribute} = " in inspect.getsource(fake), f"{fake.__name__} 缺少属性 {attribute}"


def test_fakes_package_lists_every_module() -> None:
    names = {m.name for m in pkgutil.iter_modules([str(Path(fakes.__file__).parent)])}
    assert names == {"_script", "approval", "authz", "config", "db", "delivery", "identity", "pipeline", "queries", "realtime",
                     "rules", "system"}


# ---------------------------------------------------------------- 预设错误

def _error() -> PlatformError:
    return PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库不可用")


def test_fail_once_then_normal() -> None:
    clock = FakeClock()
    clock.fail("now", _error())
    with pytest.raises(PlatformError):
        clock.now()
    assert clock.now() == FakeClock().now()
    assert clock.calls == [Call("now", ()), Call("now", ())]


def test_fail_n_times_and_until_recovered() -> None:
    reader = FakeDocumentReader()
    ref = DocumentRef(entity="E", record_key="1")
    reader.fail("load", _error(), times=2)
    for _ in range(2):
        with pytest.raises(PlatformError):
            reader.load(ref)
    assert reader.load(ref) is None
    reader.fail("load", _error(), times=None)
    for _ in range(3):
        with pytest.raises(PlatformError):
            reader.load(ref)
    reader.recover("load")
    assert reader.load(ref) is None
    assert len(reader.calls_to("load")) == 7


def test_fail_queue_in_order() -> None:
    clock = FakeClock()
    first, second = _error(), PlatformError(ErrorCode.INTERNAL_ERROR, "其他错误")
    clock.fail("now", first)
    clock.fail("now", second)
    with pytest.raises(PlatformError) as caught:
        clock.now()
    assert caught.value is first
    with pytest.raises(PlatformError) as caught:
        clock.now()
    assert caught.value is second


def test_fail_rejects_unknown_method_and_bad_times() -> None:
    clock = FakeClock()
    with pytest.raises(AttributeError):
        clock.fail("advance", _error())
    with pytest.raises(AttributeError):
        clock.fail("nwo", _error())
    with pytest.raises(ValueError):
        clock.fail("now", _error(), times=0)
