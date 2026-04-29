from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .scraper import AppointmentSlot


class SeenSlotStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "seen_slots.json"
        self.data: dict[str, dict] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.data = {}
            return
        content = self.path.read_text(encoding="utf-8")
        self.data = json.loads(content) if content.strip() else {}

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def new_slots(self, slots: list[AppointmentSlot], force: bool = False) -> list[AppointmentSlot]:
        if force:
            return slots
        return [slot for slot in slots if slot.key not in self.data]

    def mark_alerted(self, slots: list[AppointmentSlot]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for slot in slots:
            self.data[slot.key] = {"alerted_at": now, "slot": asdict(slot)}

    def reset(self) -> None:
        self.data = {}
        self.save()


class DailyStatsStore:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "daily_stats.json"
        self.data: dict = {
            "last_reset_date": None,
            "last_success_at": None,
            "last_watchdog_alert_at": None,
            "days": {},
        }

    def load(self) -> None:
        if not self.path.exists():
            self.data = {
                "last_reset_date": None,
                "last_success_at": None,
                "last_watchdog_alert_at": None,
                "days": {},
            }
            return
        content = self.path.read_text(encoding="utf-8")
        self.data = json.loads(content) if content.strip() else {
            "last_reset_date": None,
            "last_success_at": None,
            "last_watchdog_alert_at": None,
            "days": {},
        }
        self.data.setdefault("last_reset_date", None)
        self.data.setdefault("last_success_at", None)
        self.data.setdefault("last_watchdog_alert_at", None)
        self.data.setdefault("days", {})

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def record_successful_search(self, day: date, appointments_found: int, when: datetime) -> None:
        key = day.isoformat()
        self.data["last_success_at"] = when.astimezone(timezone.utc).isoformat()
        day_stats = self.data["days"].setdefault(
            key,
            {
                "successful_searches": 0,
                "total_appointments_found": 0,
                "max_appointments_found": 0,
            },
        )
        day_stats["successful_searches"] += 1
        day_stats["total_appointments_found"] += appointments_found
        day_stats["max_appointments_found"] = max(
            day_stats["max_appointments_found"],
            appointments_found,
        )

    def stats_for(self, day: date) -> dict:
        return self.data["days"].get(
            day.isoformat(),
            {
                "successful_searches": 0,
                "total_appointments_found": 0,
                "max_appointments_found": 0,
            },
        )

    def has_reset_today(self, day: date) -> bool:
        return self.data.get("last_reset_date") == day.isoformat()

    def mark_reset_today(self, day: date) -> None:
        self.data["last_reset_date"] = day.isoformat()

    def last_success_at(self) -> datetime | None:
        raw = self.data.get("last_success_at")
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def last_watchdog_alert_at(self) -> datetime | None:
        raw = self.data.get("last_watchdog_alert_at")
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def mark_watchdog_alert_sent(self, when: datetime) -> None:
        self.data["last_watchdog_alert_at"] = when.astimezone(timezone.utc).isoformat()
