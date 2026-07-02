from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.paths import ensure_runtime_dirs


@dataclass(frozen=True)
class LogRecord:
    time: datetime
    level: str
    message: str

    def format(self) -> str:
        return f"{self.time.strftime('%H:%M:%S')} [{self.level}] {self.message}"


class LogBus:
    def __init__(self) -> None:
        self._queue: queue.Queue[LogRecord] = queue.Queue()
        self._records: list[LogRecord] = []
        self._lock = threading.Lock()

    def emit(self, level: str, message: str) -> None:
        record = LogRecord(datetime.now(), level.upper(), message)
        with self._lock:
            self._records.append(record)
            if len(self._records) > 5000:
                self._records = self._records[-5000:]
        self._queue.put(record)

    def info(self, message: str) -> None:
        self.emit("INFO", message)

    def ok(self, message: str) -> None:
        self.emit("OK", message)

    def success(self, message: str) -> None:
        self.emit("SUCCESS", message)

    def warning(self, message: str) -> None:
        self.emit("WARNING", message)

    def error(self, message: str) -> None:
        self.emit("ERROR", message)

    def debug(self, message: str) -> None:
        self.emit("DEBUG", message)

    def drain(self) -> list[LogRecord]:
        records: list[LogRecord] = []
        while True:
            try:
                records.append(self._queue.get_nowait())
            except queue.Empty:
                return records

    def records(self) -> list[LogRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def export(self, records: Iterable[LogRecord] | None = None) -> Path:
        paths = ensure_runtime_dirs()
        target = paths.exports_dir / f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        source = list(records) if records is not None else self.records()
        with target.open("w", encoding="utf-8") as file:
            for record in source:
                file.write(record.format() + "\n")
        return target
