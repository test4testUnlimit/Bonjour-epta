# Bonjur-epta

Desktop онлайн-переводчик выделенного текста: любой язык → любой, автодетект, multi-API.

## Запуск (dev)

```powershell
cd C:\Projects\Bonjur-epta
pip install -r requirements.txt
python main.py
```

Если Python нет: лаунчер ставит сам (3.10+). Вручную — любой Python 3.10+.

## Выделение и hotkey

1. **Выдели текст** (drag или double-click) → рядом с курсором чип **«чивобля?»** → клик открывает главное окно с исходником и переводом.
2. **Двойное нажатие** физической клавиши **` / ё** (слева от `1`, EN/RU) → сразу в главное окно с переводом.

> Глобальные хуки (`keyboard` / `mouse`) на Windows иногда требуют запуска от администратора.

## UI

Двухпанельное окно: исходный | ⇄ | перевод.  
Сверху: выбор API, **Перевести**, **Вставить** (из буфера).  
В панелях: автодетект / язык, текст.

## API (v0.1)

| Провайдер | Ключ | Статус |
|---|---|---|
| Google (gtx) | нет | **default**, работает |
| MyMemory | нет (опц.) | работает, лимит ~500 символов |
| LibreTranslate | иногда | публичный инстанс нестабилен |
| DeepL | да | готов, ждёт ключ |
| Yandex | да | готов, ждёт ключ |

Детали: `notes/api-sources.md`

## Стек

- **Python 3.10+** — runtime (winget на первом запуске)
- **customtkinter** — UI
- **httpx** — HTTP к API (скорость P0)
- **keyboard** — global double-tap ` / ё по scan code
- **pyperclip** — буфер / захват выделения (Ctrl+C)

Портатив позже: PyInstaller one-file. Установщик (как MyDash) — не в scope v0.1.

## Память

Только MemPalace: rooms `bonjur-epta` / `-decisions` / `-worklog` / `-questions`.
