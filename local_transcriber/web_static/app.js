const form = document.querySelector('#transcription-form');
const submitButton = form.querySelector('button[type="submit"]');
const statusBadge = document.querySelector('#status-badge');
const progressBar = document.querySelector('#progress-bar');
const progressText = document.querySelector('#progress-text');
const latestSegment = document.querySelector('#latest-segment');
const errorBox = document.querySelector('#error-box');
const resultBox = document.querySelector('#result-box');
const resultList = document.querySelector('#result-list');

let pollTimer = null;
let lastProgressPercentage = 0;

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearState();

  const data = new FormData(form);
  const selectedFormats = [...form.querySelectorAll('input[name="formats"]:checked')]
    .map((input) => input.value)
    .join(',');
  data.delete('formats');
  data.append('formats', selectedFormats);
  data.set('offline', form.elements.offline.checked ? 'true' : 'false');

  if (!data.get('file')?.name && !data.get('input_path')) {
    showError('Выберите файл или укажите путь к локальному файлу.');
    return;
  }

  if (!selectedFormats) {
    showError('Выберите хотя бы один формат результата.');
    return;
  }

  setBusy(true);
  setStatus('Отправка задания', 'Файл и параметры передаются локальному серверу.');

  try {
    const response = await fetch('/api/jobs', {
      method: 'POST',
      body: data,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Не удалось создать задачу.');
    }
    renderJob(payload);
    startPolling(payload.id);
  } catch (error) {
    setBusy(false);
    showError(error.message);
  }
});

function startPolling(jobId) {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
  pollTimer = setInterval(() => pollJob(jobId), 1000);
  pollJob(jobId);
}

async function pollJob(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Не удалось получить статус.');
    }
    renderJob(payload);
    if (payload.status === 'done' || payload.status === 'failed') {
      clearInterval(pollTimer);
      pollTimer = null;
      setBusy(false);
    }
  } catch (error) {
    clearInterval(pollTimer);
    pollTimer = null;
    setBusy(false);
    showError(error.message);
  }
}

function renderJob(job) {
  const labels = {
    queued: 'В очереди',
    running: 'Транскрибация',
    done: 'Готово',
    failed: 'Ошибка',
  };
  statusBadge.textContent = labels[job.status] || job.status;
  errorBox.hidden = true;

  if (job.status === 'running' || job.status === 'queued') {
    progressBar.classList.add('running');
    updateProgress(job);
  }

  if (job.progress.latest) {
    latestSegment.hidden = false;
    latestSegment.textContent = `${job.progress.latest.start_ts} - ${job.progress.latest.end_ts}: ${job.progress.latest.text}`;
  }

  if (job.status === 'done') {
    progressBar.classList.remove('running');
    progressBar.style.width = '100%';
    progressText.textContent = job.output_dir
      ? `Результаты сохранены: ${job.output_dir}`
      : 'Транскрибация завершена.';
    renderFiles(job.files);
  }

  if (job.status === 'failed') {
    progressBar.classList.remove('running');
    progressBar.style.width = '100%';
    showError(job.error || 'Транскрибация завершилась ошибкой.');
  }
}

function updateProgress(job) {
  const percentage = job.progress.percentage;
  if (Number.isFinite(percentage)) {
    const visiblePercentage = Math.max(lastProgressPercentage, percentage);
    lastProgressPercentage = visiblePercentage;
    progressBar.style.width = `${visiblePercentage}%`;
    progressText.textContent = `Обработано примерно ${visiblePercentage}% видео. Сегментов: ${job.progress.segments}.`;
    return;
  }

  if (lastProgressPercentage === 0) {
    progressBar.style.width = '';
  }
  progressText.textContent = `Длительность пока не определена. Сегментов: ${job.progress.segments}.`;
}

function renderFiles(files) {
  resultList.replaceChildren();
  for (const file of files) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = file.url;
    link.textContent = file.name;
    link.download = file.name;
    item.append(link);
    resultList.append(item);
  }
  resultBox.hidden = files.length === 0;
}

function clearState() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  progressBar.classList.remove('running');
  progressBar.style.width = '0%';
  lastProgressPercentage = 0;
  progressText.textContent = 'Подготовка к запуску.';
  latestSegment.hidden = true;
  latestSegment.textContent = '';
  errorBox.hidden = true;
  errorBox.textContent = '';
  resultBox.hidden = true;
  resultList.replaceChildren();
}

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  submitButton.textContent = isBusy ? 'Идет транскрибация' : 'Транскрибировать';
}

function setStatus(label, text) {
  statusBadge.textContent = label;
  progressText.textContent = text;
}

function showError(message) {
  statusBadge.textContent = 'Ошибка';
  errorBox.hidden = false;
  errorBox.textContent = message;
  progressText.textContent = 'Проверьте параметры и попробуйте снова.';
}
