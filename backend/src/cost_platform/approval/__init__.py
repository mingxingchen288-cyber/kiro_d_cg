"""审批、冻结（docs/模块/approval.md）。

assembly 的用法：

```python
deps = ApprovalDeps(catalog=..., schema=..., directory=..., documents=..., rules=..., tables=...)
approval = create_approval(deps)            # FreezeReader 和管道阶段
service = ApprovalService(deps, uow_factory, command_executor)
app.include_router(approval_router(service, context))
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
