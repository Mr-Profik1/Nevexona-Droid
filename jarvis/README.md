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
### Режим полного разрешения
Чтобы ИИ сам выполнял команды без вопросов, запустите так:
```
sudo -v
JARVIS_AUTO=1 python3 jarvis_ai.py
```
`sudo -v` один раз спросит пароль, после этого ИИ сможет вызывать sudo (например, `apt install`) в течение нескольких минут. Все команды записываются в `~/.jarvis_log`. Опасные команды (удаление, форматирование, перезагрузка и т.п.) даже в этом режиме спрашивают подтверждение. Без `JARVIS_AUTO=1` подтверждения нужны на каждую команду.

### Приватность
Хостинг не нужен, всё выполняется на вашем компьютере. Но при работе через облачный сервис ваши запросы и вывод команд отправляются этому сервису. Не просите ИИ выводить пароли и личные файлы.
Полностью локальный вариант: поставить Ollama (https://ollama.com) и указать `JARVIS_BASE_URL=http://localhost:11434/v1`, `JARVIS_API_KEY=ollama`, `JARVIS_MODEL=имя-локальной-модели`. На 2 ГБ оперативки потянет только совсем маленькие модели, и они плохо справляются с такими задачами.

## jarvis.py: простой помощник без ИИ (заданные команды, работает без интернета)
```
curl -fsSL https://raw.githubusercontent.com/Mr-Profik1/Nevexona-Droid/main/jarvis/jarvis.py -o jarvis.py
python3 jarvis.py
```
Напишите `помощь`, чтобы увидеть список команд.
