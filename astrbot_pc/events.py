"""极简事件总线：给 SSE 用。

每个订阅者拿一个 ``queue.Queue``，写满就丢最旧的一条，绝不让界面卡住后台。
另外留一段环形历史，SSE 断线重连或走轮询兜底时能补上最近发生的事。
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections import deque
from typing import Any, Iterator


class EventBus:
    def __init__(self, maxsize: int = 256, history: int = 200) -> None:
        self._subs: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._seq = itertools.count(1)
        self._maxsize = maxsize
        self._history: deque[dict[str, Any]] = deque(maxlen=history)

    def subscribe(self) -> tuple[int, queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            sid = next(self._ids)
            self._subs[sid] = q
        return sid, q

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def emit(self, kind: str, payload: Any) -> None:
        msg = {"seq": next(self._seq), "kind": kind, "ts": int(time.time()), "data": payload}
        with self._lock:
            self._history.append(msg)
            subs = list(self._subs.values())
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    def since(self, seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [m for m in self._history if m["seq"] > int(seq or 0)]

    def last_seq(self) -> int:
        with self._lock:
            return self._history[-1]["seq"] if self._history else 0

    def stream(self, sid: int, q: queue.Queue, stop: threading.Event) -> Iterator[str]:
        """产出已经编码好的 SSE 帧。"""
        yield "retry: 3000\n\n"
        while not stop.is_set():
            try:
                msg = q.get(timeout=15)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            yield "id: " + str(msg.get("seq", 0)) + "\n"
            yield "data: " + dumps(msg) + "\n\n"


def dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


bus = EventBus()
