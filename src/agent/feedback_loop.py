"""反馈收集与奖励计算（SPAR2 重构后保留的轻量实现）。

对应 Web 端收藏/已阅/引用/跳过等隐式反馈事件：
- `FeedbackEvent`：单条事件
- `FeedbackCollector`：内存收集 + JSONL 持久化
- `RewardComputer`：按论文/查询聚合奖励，计算引文采纳率

这是原 15 大创新中反馈闭环模块的最小可运行版本，接口与
web/app.py 保持一致。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional


class FeedbackEvent:
    """一条用户反馈事件。"""

    __slots__ = ("event_type", "query", "paper_id", "star_value",
                 "user_id", "session_id", "timestamp")

    def __init__(self, event_type: str, query: str = "", paper_id: str = "",
                 star_value: Optional[int] = None, user_id: str = "web-anonymous",
                 session_id: str = "web", timestamp: Optional[float] = None):
        self.event_type = event_type
        self.query = query
        self.paper_id = paper_id
        self.star_value = star_value
        self.user_id = user_id
        self.session_id = session_id
        self.timestamp = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "query": self.query,
            "paper_id": self.paper_id,
            "star_value": self.star_value,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeedbackEvent":
        return cls(
            event_type=str(data.get("event_type") or ""),
            query=str(data.get("query") or ""),
            paper_id=str(data.get("paper_id") or ""),
            star_value=data.get("star_value"),
            user_id=str(data.get("user_id") or "web-anonymous"),
            session_id=str(data.get("session_id") or "web"),
            timestamp=float(data.get("timestamp") or time.time()),
        )


class FeedbackCollector:
    """内存收集 + JSONL 落盘。"""

    def __init__(self) -> None:
        self.events: List[FeedbackEvent] = []

    def _add(self, event_type: str, query: str, paper_id: str,
             star: Optional[int] = None, user_id: str = "web-anonymous",
             session_id: str = "web") -> None:
        self.events.append(FeedbackEvent(
            event_type=event_type, query=query, paper_id=paper_id,
            star_value=star, user_id=user_id, session_id=session_id,
        ))

    def record_click(self, query: str, paper_id: str, **kw) -> None:
        self._add("click", query, paper_id, **kw)

    def record_copy(self, query: str, paper_id: str, **kw) -> None:
        self._add("copy", query, paper_id, **kw)

    def record_cite(self, query: str, paper_id: str, **kw) -> None:
        self._add("cite", query, paper_id, **kw)

    def record_skip(self, query: str, paper_id: str, **kw) -> None:
        self._add("skip", query, paper_id, **kw)

    def record_hide(self, query: str, paper_id: str, **kw) -> None:
        self._add("hide", query, paper_id, **kw)

    def record_star(self, query: str, paper_id: str, star: int = 5, **kw) -> None:
        self._add("star", query, paper_id, star=star, **kw)

    def flush_to_file(self, path: str) -> int:
        """把内存事件追加写入 JSONL，并清空内存。返回写入条数。"""
        if not self.events:
            return 0
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with p.open("a", encoding="utf-8") as f:
            for ev in self.events:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
                n += 1
        self.events = []
        return n

    @classmethod
    def load_from_file(cls, path: str) -> List[FeedbackEvent]:
        p = Path(path)
        if not p.exists():
            return []
        events: List[FeedbackEvent] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(FeedbackEvent.from_dict(json.loads(line)))
            except Exception:
                continue
        return events


class RewardComputer:
    """把反馈事件折算为论文/查询奖励分。"""

    WEIGHTS = {
        "click": 1.0,
        "copy": 1.0,
        "cite": 3.0,
        "skip": -0.5,
        "hide": -1.0,
        "star": 2.0,  # 基础分；星级再按 star/5 放大
    }

    def _reward(self, ev: FeedbackEvent) -> float:
        base = self.WEIGHTS.get(ev.event_type, 0.0)
        if ev.event_type == "star":
            star = max(1, min(5, int(ev.star_value or 5)))
            base *= star / 5.0
        return base

    def compute_per_paper(self, events: List[FeedbackEvent]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for ev in events:
            if not ev.paper_id:
                continue
            out[ev.paper_id] = round(out.get(ev.paper_id, 0.0) + self._reward(ev), 4)
        return out

    def compute_per_query(self, events: List[FeedbackEvent]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for ev in events:
            if not ev.query:
                continue
            out[ev.query] = round(out.get(ev.query, 0.0) + self._reward(ev), 4)
        return out

    def citation_adoption_rate(self, events: List[FeedbackEvent]) -> float:
        """引文采纳率 = cite 事件 / 全部反馈事件。"""
        if not events:
            return 0.0
        cites = sum(1 for ev in events if ev.event_type == "cite")
        return cites / len(events)
