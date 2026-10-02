# Local Transcriber

Локальный CLI-инструмент и простой веб-интерфейс для транскрибации видео и аудио через `faster-whisper`.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Если CUDA недоступна, запускайте на CPU:

```powershell
python transcribe.py "E:\Videos\call.mp4" --device cpu --compute-type int8
```

## Запуск

Через скрипт:

```powershell
python transcribe.py "E:\Videos\my_recording.mp4"
```

Через модуль:

```powershell
python -m local_transcriber "E:\Videos\my_recording.mp4"
```

С параметрами:

```powershell
python transcribe.py "E:\Videos\call.mp4" --language ru --device cuda --compute-type int8_float16 --formats md,json,srt
```

## Веб-режим

MVP локального веб-интерфейса запускается как обычный Python-сервер на вашем компьютере:

```powershell
python -m local_transcriber.web
```

По умолчанию сервер слушает только локальный адрес и сам открывает страницу в браузере:

```text
http://127.0.0.1:8765
```

Можно указать другой порт:

```powershell
python -m local_transcriber.web --host 127.0.0.1 --port 8766
```

Если страницу не нужно открывать автоматически:

```powershell
python -m local_transcriber.web --no-open
```

Веб-режим использует то же ядро транскрибации, что и CLI. По умолчанию в интерфейсе выбрано:

```text
device: auto
compute type: auto
```

Для принудительного запуска на компьютере без CUDA можно выбрать CPU-настройки:

```text
device: cpu
compute type: int8
```

По умолчанию используется:

- модель: `large-v3-turbo`;
- язык: `ru`;
- устройство: `auto`;
- форматы: `md,json,srt`;
- папка вывода: `.\output`.

## Результаты

Для файла `E:\Videos\my_recording.mp4` будет создана папка:

```text
output/my_recording/
```

Внутри появятся:

- `transcript.md` - Markdown с таймкодами и текстом сегментов;
- `transcript_segments.json` - источник, длительность, язык, вероятность языка и список сегментов;
- `transcript.srt` - субтитры в SRT.

Если передать `--out`, папка с именем файла создается внутри указанной директории:

```powershell
python transcribe.py "E:\Videos\my_recording.mp4" --out "E:\Transcripts"
```

Результат будет в:

```text
E:\Transcripts\my_recording\
```

## Offline-режим

Флаг `--offline` запрещает скачивание модели и использует только уже доступные локальные файлы:

```powershell
python transcribe.py "E:\Videos\call.mp4" --offline
```

Если модель еще не скачана, сначала выполните один online-запуск или скачайте модель явно:

```powershell
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo')"
```

Также можно передать локальный путь к модели:

```powershell
python transcribe.py "E:\Videos\call.mp4" --model "C:\Models\faster-whisper-large-v3-turbo" --offline
```

## Форматы и ограничения

Инструмент не ограничивает расширения искусственно: если `faster-whisper` и PyAV могут прочитать файл, транскрибация будет запущена. Минимально ожидаемый сценарий - `.mp4`.

Текущая версия делает транскрибацию с таймкодами. Автоматическое разделение по говорящим не входит в базовую версию.

## Проверка проекта

Unit-тесты запускаются без модели Whisper:

```powershell
python -m unittest discover -s tests -v
```
