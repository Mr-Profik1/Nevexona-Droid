# Помощники для Linux

## jarvis_ai.py: ИИ-помощник (пишете задачу, ИИ сам выполняет команды, отвечает голосом)
Нужен ключ от сервиса с OpenAI-совместимым API (ИИ работает в интернете, на слабом ноутбуке локально он не запустится).
Адреса сервисов, например:
- OpenRouter: `https://openrouter.ai/api/v1`
- Groq: `https://api.groq.com/openai/v1`
- Gemini: `https://generativelanguage.googleapis.com/v1beta/openai`

Названия моделей у сервисов меняются, возьмите актуальное на сайте сервиса. Доступность зависит от страны.

Запуск (подставьте свой адрес, ключ и модель):
```
sudo apt install -y espeak-ng
curl -fsSL https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/jarvis/jarvis_ai.py -o jarvis_ai.py
export JARVIS_BASE_URL="https://адрес-сервиса/v1"
export JARVIS_API_KEY="ваш-ключ"
export JARVIS_MODEL="название-модели"
python3 jarvis_ai.py
```
Каждая команда, которую захочет выполнить ИИ, сначала показывается, и вы подтверждаете её `y`. Ключ никому не показывайте.

## jarvis.py: простой помощник без ИИ (заданные команды, работает без интернета)
```
curl -fsSL https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/jarvis/jarvis.py -o jarvis.py
python3 jarvis.py
```
Напишите `помощь`, чтобы увидеть список команд.
