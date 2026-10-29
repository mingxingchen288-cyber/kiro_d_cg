"""在另一个操作系统进程中经 Redis 频道发布一条事件（test_redis.py 的两进程验证用，不是测试文件）。

用法：`python publish_event.py '<C10 第 1 节的频道事件 JSON>'`。
连接取环境变量 `PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`，由调用方从根目录 `.env` 读出后传入，不出现在命令行。
"""

from __future__ import annotations

import json
import os
import sys

from cost_platform.contracts.types import ChannelEvent, parse_wire
from cost_platform.realtime import ChannelPublisher, RedisChannel


def main() -> None:
    channel = RedisChannel.from_url(os.environ["PLATFORM_REDIS_URL"], os.environ["PLATFORM_REDIS_NAMESPACE"])
    ChannelPublisher(channel).publish(parse_wire(ChannelEvent, json.loads(sys.argv[1])))


if __name__ == "__main__":
    main()
