# CQ Popup Testing Agent

Агент автоматически тестирует всплывающие окна (попапы) на сайтах, где установлен Carrot Quest.
Обнаруживает два типа багов: наложение попапов и слишком быстрое повторное появление.

## Структура проекта

```
agent/
  config.py          — CSS-селекторы трёх типов попапов, константы
  popup_detector.py  — мониторинг DOM через Playwright (polling каждые 0.5 сек)
  browser_session.py — управление Playwright: запуск, навигация, скролл
  carrotquest_api.py — REST API клиент Carrot Quest (события, карточка пользователя)
  reporter.py        — генерация Markdown-отчёта
  test_runner.py     — точка входа, оркестрация всего вышеперечисленного
```

## Запуск теста

```bash
# Установить зависимости (один раз)
pip install -r requirements.txt
playwright install chromium

# Запустить тест
python -m agent.test_runner \
  --url https://bitrix.carrotquest.ru \
  --scenario "Ты потенциальный клиент, хочешь купить продукт. Осмотри сайт." \
  --extra-urls https://bitrix.carrotquest.ru/products/ \
  --duration 120 \
  --no-headless
```

## Ключевые параметры

| Параметр | Описание | Дефолт |
|----------|----------|--------|
| `--url` | Стартовый URL | обязателен |
| `--scenario` | Текстовая легенда (для отчёта) | — |
| `--extra-urls` | Дополнительные URL для обхода | [] |
| `--duration` | Длительность сессии (сек) | 120 |
| `--threshold` | Порог быстрого повторения (сек) | 60 |
| `--no-headless` | Показать браузер | выкл |

## Типы попапов и CSS-селекторы

| Тип | Селектор |
|-----|----------|
| CQ Конструктор | `[data-resize-popup]` |
| JS Попап | `.cq-popup__body` |
| Нотификация бота | `[data-resize-notification]` |

## Типы багов

- **overlap** — два попапа одновременно видимы в DOM
- **rapid_succession** — новый попап появился менее чем через 60 сек после закрытия предыдущего

## Конфигурация (.env)

```
CQ_AUTH_TOKEN=app.APPID.token
CQ_APP_ID=2782
```

Файл `.env` в `.gitignore` — не коммитить.

## Как получить CQ user ID

После загрузки страницы Playwright выполняет:
```js
window.carrotquest?.data?.user?.id
```
Этот ID используется для запросов к API (`/users/{id}/events`).

## Добавление новых тест-кейсов (V2+)

1. Создать новый детектор по образцу `popup_detector.py`
2. Подключить в `test_runner.py` рядом с `PopupDetector`
3. Добавить секцию в отчёт в `reporter.py`
