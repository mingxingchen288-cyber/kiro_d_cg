"""审批、冻结（docs/模块/approval.md）。

接线由 `plugin.py` 的两个插件完成（assembly 只把它们放进插件清单）：

```python
deps = ApprovalDeps(catalog=catalog_of(entity_directory, config_reader), schema=..., directory=..., documents=..., rules=..., tables=...)
approval = create_approval(deps)            # 插件 approval：FreezeReader 和管道阶段
service = ApprovalService(deps, uow_factory, command_executor)
approval_router(service, context_provider.context)   # 插件 approval.service：APIRouter
```
"""

from .catalog import ApprovalCatalog, CatalogOf, ItemsApprovalCatalog, NamedFlow, TableEntity
from .deps import ApprovalDeps
from .module import ApprovalModule, create_approval
from .router import approval_router
from .service import ApprovalService

__all__ = [
    "ApprovalCatalog",
    "ApprovalDeps",
    "ApprovalModule",
    "ApprovalService",
    "CatalogOf",
    "ItemsApprovalCatalog",
    "NamedFlow",
    "TableEntity",
    "approval_router",
    "create_approval",
]
