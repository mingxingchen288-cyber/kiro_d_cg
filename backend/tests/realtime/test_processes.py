"""两个后端进程（模拟验证）：一个进程发布的事件，推到连在另一个进程上的连接（RT-02、RT-03）。

两套 `Realtime` 各有自己的应用、事件循环、连接表和订阅任务，共用一个 `MemoryChannel`（代替 Redis 频道）。
真实的两个进程经 Redis 的验证见 test_redis.py。
"""

from __future__ import annotations

from .support import ADMIN, CHENG, COST_PINGGU, Env, config_changed, connect, event_id, recv_json, subscribe


def test_event_published_in_one_process_reaches_connection_in_another() -> None:
    """E18：config 在进程甲发布成本核算页的配置变更；连在进程乙、开着成本核算页的浏览器收到，连在进程甲的也收到。"""
    env = Env()
    admin, cheng = env.login(ADMIN), env.login(CHENG)
    with env.process() as (first, client_a), env.process() as (_second, client_b), \
            connect(client_a, admin.session_id) as on_a, connect(client_b, cheng.session_id) as on_b:
        subscribe(on_a, COST_PINGGU)
        subscribe(on_b, COST_PINGGU)

        first.publisher.publish(config_changed(1, [COST_PINGGU], 13))

        expected = {"topic": "config.changed", "eventId": event_id(1),
                    "payload": {"pages": [COST_PINGGU], "version": 13}}
        assert recv_json(on_b) == expected
        assert recv_json(on_a) == expected
