"""
Контракт тест-сценария между агентом-продактом и агентом-тестировщиком.

Агент-продакт генерирует сценарии в этом JSON-формате, агент-тестировщик их исполняет.

Формат файла сценариев (.json):
{
  "site_url": "https://bitrix.carrotquest.ru",
  "scenarios": [
    {
      "id": "linger-landing",
      "title": "Долгое залипание на лендинге",
      "description": "Пользователь медленно изучает главную и уводит мышь к закрытию вкладки",
      "steps": [
        {"action": "navigate", "url": "https://bitrix.carrotquest.ru"},
        {"action": "wait", "seconds": 15},
        {"action": "scroll", "to": "bottom"},
        {"action": "wait", "seconds": 20},
        {"action": "exit_intent"},
        {"action": "wait", "seconds": 10}
      ]
    }
  ]
}

Поддерживаемые действия (action):
  navigate    — перейти на URL          поля: url
  wait        — подождать N секунд        поля: seconds
  scroll      — прокрутить страницу       поля: to ("bottom"|"top"|"0..1")
  exit_intent — увести мышь за край окна   поля: —
  click       — кликнуть по селектору      поля: selector
  open_chat   — открыть виджет чата CQ     поля: —
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional


VALID_ACTIONS = {"navigate", "wait", "scroll", "exit_intent", "click", "open_chat"}


@dataclass
class Step:
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        action = d.get("action")
        if action not in VALID_ACTIONS:
            raise ValueError(f"Неизвестное действие сценария: {action!r}. Допустимы: {sorted(VALID_ACTIONS)}")
        params = {k: v for k, v in d.items() if k != "action"}
        return cls(action=action, params=params)


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    steps: list[Step]

    @property
    def estimated_duration(self) -> int:
        """Грубая оценка длительности по сумме wait + накладные расходы на навигацию."""
        total = sum(int(s.params.get("seconds", 0)) for s in self.steps if s.action == "wait")
        nav = sum(3 for s in self.steps if s.action in ("navigate", "scroll", "exit_intent", "click", "open_chat"))
        return total + nav

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        steps = [Step.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id=d.get("id", "scenario"),
            title=d.get("title", d.get("id", "Сценарий")),
            description=d.get("description", ""),
            steps=steps,
        )


def load_scenarios(path: str) -> tuple[Optional[str], list[Scenario]]:
    """Загружает файл сценариев. Возвращает (site_url, [Scenario]).

    Принимает либо {site_url, scenarios:[...]}, либо одиночный объект-сценарий.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "scenarios" in data:
        site_url = data.get("site_url")
        scenarios = [Scenario.from_dict(s) for s in data["scenarios"]]
    elif isinstance(data, dict) and "steps" in data:
        site_url = None
        scenarios = [Scenario.from_dict(data)]
    else:
        raise ValueError("Файл сценариев должен содержать ключ 'scenarios' или быть одиночным сценарием со 'steps'.")

    return site_url, scenarios


async def execute_scenario(session, scenario: Scenario):
    """Исполняет шаги сценария в открытой BrowserSession. Детектор работает параллельно."""
    for step in scenario.steps:
        if step.action == "navigate":
            await session.navigate_to(step.params["url"])
        elif step.action == "wait":
            await session.wait(float(step.params.get("seconds", 5)))
        elif step.action == "scroll":
            await session.scroll_to(str(step.params.get("to", "bottom")))
        elif step.action == "exit_intent":
            await session.exit_intent()
        elif step.action == "click":
            await session.click(step.params["selector"])
        elif step.action == "open_chat":
            await session.open_chat()
