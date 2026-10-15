// Passport fields stay in this dialog's memory and on the local backend only.
const passportVerification = (() => {
  const dialog = document.querySelector('#passport-dialog');
  const form = document.querySelector('#passport-form');
  const details = document.querySelector('#passport-details');
  const message = document.querySelector('#passport-error');
  const confirm = document.querySelector('#passport-confirm');
  const edit = document.querySelector('#passport-edit');
  const cancel = document.querySelector('#passport-cancel');
  const ocrBox = document.querySelector('#passport-ocr');
  const ocrButton = document.querySelector('#passport-recognize');
  const ocrNote = document.querySelector('#passport-ocr-note');
  let currentDocument = null;
  let extractionSummary = null;
  let processing = false;
  const text = (ru, en) => document.documentElement.lang === 'en' ? en : ru;
  const labels = {
    last_name: ['Фамилия', 'Last name'],
    first_name: ['Имя', 'First name'],
    middle_name: ['Отчество — необязательное', 'Middle name — optional'],
    citizenship: ['Гражданство', 'Citizenship'],
    passport_number: ['Номер паспорта', 'Passport number'],
    birth_date: ['Дата рождения', 'Date of birth'],
    issue_date: ['Дата выдачи', 'Date of issue'],
    expiry_date: ['Действителен до', 'Valid until'],
  };
  let documentId = null;
  let savedData = null;
  let saving = false;
  let loadVersion = 0;
  let loadController = null;

  function today() {
    const now = new Date();
    return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-');
  }

  function fieldMessage(code) {
    const messages = {
      date_in_future: ['Дата не должна быть в будущем.', 'The date cannot be in the future.'],
      expiry_must_follow_issue: ['Срок действия должен быть позже даты выдачи.', 'The expiry date must be after the issue date.'],
      invalid_date: ['Укажите корректную дату.', 'Enter a valid date.'],
      invalid_text: ['Уберите недопустимые управляющие символы.', 'Remove invalid control characters.'],
      string_too_long: ['Значение слишком длинное.', 'This value is too long.'],
      missing: ['Заполните обязательное поле.', 'Complete this required field.'],
      string_too_short: ['Заполните обязательное поле.', 'Complete this required field.'],
    };
    return text(...(messages[code] || ['Проверьте значение поля.', 'Check this field.']));
  }

  function clearErrors() {
    message.textContent = '';
    Object.keys(labels).forEach(name => {
      form.elements[name].setCustomValidity('');
      form.elements[name].removeAttribute('aria-invalid');
      document.querySelector('[data-passport-error="' + name + '"]').textContent = '';
    });
  }

  function setFieldError(name, code) {
    if (!Object.hasOwn(labels, name)) return;
    const input = form.elements[name];
    const value = fieldMessage(code);
    input.setCustomValidity(value);
    input.setAttribute('aria-invalid', 'true');
    document.querySelector('[data-passport-error="' + name + '"]').textContent = value;
  }

  function setEditMode() {
    clearErrors();
    details.hidden = true;
    form.hidden = false;
    edit.hidden = true;
    confirm.hidden = false;
    document.querySelector('#passport-description').textContent = text(
      'Заполните данные вручную или попробуйте локальное распознавание. Проверьте каждое поле перед подтверждением.',
      'Enter details manually or try local recognition. Check every field before confirming.'
    );
    document.querySelector('#passport-title').textContent = text('Проверьте данные паспорта', 'Check your passport details');
    Object.keys(labels).forEach(name => { form.elements[name].value = savedData?.[name] || ''; });
    form.elements.birth_date.max = today();
    form.elements.issue_date.max = today();
    renderOCR();
    form.elements.last_name.focus({preventScroll: true});
  }

  function setViewMode() {
    ocrBox.hidden = true;
    form.hidden = true;
    details.hidden = false;
    edit.hidden = false;
    confirm.hidden = true;
    document.querySelector('#passport-title').textContent = text('Данные паспорта', 'Passport details');
    document.querySelector('#passport-description').textContent = text(
      'Данные подтверждены вами. Это не проверка подлинности или юридической действительности паспорта.',
      'You confirmed these details. This is not a check of the passport’s authenticity or legal validity.'
    );
    details.replaceChildren();
    Object.entries(labels).forEach(([name, translations]) => {
      const term = document.createElement('dt');
      term.textContent = text(...translations);
      const value = document.createElement('dd');
      const stored = savedData[name];
      value.textContent = stored && name.endsWith('_date')
        ? new Intl.DateTimeFormat(document.documentElement.lang, {timeZone: 'UTC'}).format(new Date(stored + 'T00:00:00Z'))
        : stored || '—';
      details.append(term, value);
    });
    edit.focus({preventScroll: true});
  }

  async function open(record) {
    loadController?.abort();
    const version = ++loadVersion;
    loadController = new AbortController();
    documentId = record.document_id;
    currentDocument = record;
    extractionSummary = null;
    ocrBox.hidden = true;
    savedData = null;
    clearErrors();
    form.reset();
    details.replaceChildren();
    form.hidden = true;
    details.hidden = true;
    edit.hidden = true;
    confirm.hidden = true;
    document.querySelector('#passport-title').textContent = text('Проверьте данные паспорта', 'Check your passport details');
    document.querySelector('#passport-description').textContent = text('Загружаем данные…', 'Loading details…');
    document.querySelector('#passport-warning').textContent = text('Используйте только вымышленные тестовые данные. Реальные паспортные данные вводить нельзя.', 'Use fictional test data only. Do not enter real passport details.');
    cancel.textContent = text('Отмена', 'Cancel');
    confirm.textContent = text('Подтвердить данные', 'Confirm details');
    edit.textContent = text('Редактировать данные', 'Edit details');
    Object.entries(labels).forEach(([name, translations]) => {
      document.querySelector('label[for="passport-' + name + '"]').textContent = text(...translations);
    });
    dialog.showModal();
    try {
      const response = await documentUI.request('/api/documents/passport/data', {signal: loadController.signal});
      if (!dialog.open || version !== loadVersion) return;
      if (response.document.document_id !== documentId) {
        throw new Error(text('Паспорт был заменён. Закройте окно и откройте данные заново.', 'The passport was replaced. Close this dialog and reopen the details.'));
      }
      savedData = response.data;
      currentDocument = response.document;
      extractionSummary = response.extraction;
      documentUI.update(response.document);
      if (response.document.status === 'verified' && savedData) setViewMode();
      else setEditMode();
    } catch (failure) {
      if (failure.name === 'AbortError' || version !== loadVersion) return;
      document.querySelector('#passport-description').textContent = '';
      message.textContent = failure instanceof TypeError
        ? text('Нет соединения с сервером. Закройте окно и попробуйте снова.', 'Cannot reach the server. Close this dialog and try again.')
        : failure.message;
      await documentUI.refresh();
    }
  }

  form.addEventListener('input', event => {
    const input = event.target;
    if (!Object.hasOwn(labels, input.name)) return;
    input.setCustomValidity('');
    input.removeAttribute('aria-invalid');
    document.querySelector('[data-passport-error="' + input.name + '"]').textContent = '';
    // A changed issue date may also resolve an earlier expiry error.
    if (input.name === 'issue_date') {
      form.elements.expiry_date.setCustomValidity('');
      form.elements.expiry_date.removeAttribute('aria-invalid');
      document.querySelector('[data-passport-error="expiry_date"]').textContent = '';
    }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || processing) return;
    clearErrors();
    for (const name of Object.keys(labels)) {
      const input = form.elements[name];
      input.value = input.value.trim();
      if (input.required && !input.value) setFieldError(name, 'missing');
    }
    for (const name of ['birth_date', 'issue_date']) {
      if (form.elements[name].value > today()) setFieldError(name, 'date_in_future');
    }
    if (form.elements.expiry_date.value && form.elements.issue_date.value && form.elements.expiry_date.value <= form.elements.issue_date.value) {
      setFieldError('expiry_date', 'expiry_must_follow_issue');
    }
    if (!form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form));
    saving = true;
    dialog.querySelectorAll('input, button').forEach(element => { element.disabled = true; });
    confirm.textContent = text('Сохраняем…', 'Saving…');
    try {
      const record = await documentUI.request('/api/documents/passport/data', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({document_id: documentId, data}),
      });
      documentUI.update(record);
      dialog.close();
      documentUI.notify(text('Данные паспорта подтверждены', 'Passport details confirmed'));
    } catch (failure) {
      message.textContent = failure instanceof TypeError
        ? text('Нет соединения с сервером. Проверьте соединение и попробуйте снова.', 'Cannot reach the server. Check the connection and try again.')
        : failure.message;
      (failure.fields || []).forEach(item => setFieldError(item.field, item.code));
      if (failure.code === 'document_changed' || failure.code === 'document_not_found') await documentUI.refresh();
    } finally {
      saving = false;
      dialog.querySelectorAll('input, button').forEach(element => { element.disabled = false; });
      confirm.textContent = text('Подтвердить данные', 'Confirm details');
      renderOCR();
    }
  });
  edit.addEventListener('click', setEditMode);
  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    // A queued close event must not clear a newly reopened dialog.
    if (dialog.open) return;
    ++loadVersion;
    loadController?.abort();
    documentId = null;
    savedData = null;
    currentDocument = null;
    extractionSummary = null;
    ocrBox.hidden = true;
    form.reset();
    details.replaceChildren();
    clearErrors();
    document.querySelector('[data-document-type="passport"] button')?.focus();
  });

  function renderOCR() {
    ocrBox.hidden = currentDocument?.status === 'verified' || !currentDocument || form.hidden;
    ocrButton.textContent = processing ? text('Распознаём…', 'Recognizing…') : text('Распознать локально', 'Recognize locally');
    ocrButton.disabled = processing || saving || currentDocument?.content_type === 'application/pdf' || currentDocument?.status === 'processing';
    if (currentDocument?.content_type === 'application/pdf') {
      ocrNote.textContent = text('В этом эксперименте OCR доступен для JPG и PNG. Данные PDF заполните вручную.', 'This experiment supports OCR for JPG and PNG. Enter PDF details manually.');
    } else if (processing || currentDocument?.status === 'processing') {
      ocrNote.textContent = text('Локальная обработка может занять до двух минут. Изображение никуда не отправляется.', 'Local processing can take up to two minutes. The image stays on this computer.');
    } else if (extractionSummary?.status === 'unsupported_or_not_passport') {
      ocrNote.textContent = text('Похоже, этот файл не является поддерживаемым международным паспортом. Загрузите страницу паспорта с машиночитаемой зоной или заполните данные вручную.', 'This file does not appear to be a supported international passport. Upload the passport page with a machine-readable zone or enter the details manually.');
    } else if (currentDocument?.status === 'processing_error' || extractionSummary?.status === 'failed') {
      ocrNote.textContent = text('Не удалось распознать документ. Попробуйте ещё раз или заполните данные вручную.', 'Could not recognize the document. Try again or enter the details manually.');
    } else if (extractionSummary?.status === 'success') {
      ocrNote.textContent = text('Данные распознаны. Проверьте каждое поле перед подтверждением.', 'Data recognized. Check every field before confirming.');
    } else if (extractionSummary?.status === 'partial') {
      ocrNote.textContent = text('Часть данных распознана. Заполните или исправьте недостающие поля.', 'Some data was recognized. Complete or correct the missing fields.');
    } else {
      ocrNote.textContent = text('Экспериментальный OCR для тестовых JPG/PNG. Ручной ввод остаётся доступен.', 'Experimental OCR for test JPG/PNG images. Manual entry remains available.');
    }
  }

  ocrButton.addEventListener('click', async () => {
    if (processing || !documentId) return;
    const requestedId = documentId;
    processing = true;
    confirm.disabled = true;
    renderOCR();
    try {
      const response = await documentUI.request('/api/documents/passport/process', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({document_id: requestedId}),
      });
      documentUI.update(response.document);
      if (!dialog.open || documentId !== requestedId) return;
      currentDocument = response.document;
      extractionSummary = response.extraction;
      if (currentDocument.status === 'verified') {
        savedData = response.data;
        setViewMode();
        return;
      }
      // Keep anything the user has already entered.
      Object.entries(response.data || {}).forEach(([name, value]) => {
        const input = form.elements[name];
        if (input && !input.value && value) {
          input.value = value;
          input.dispatchEvent(new Event('input', {bubbles: true}));
        }
      });
    } catch (failure) {
      if (dialog.open && documentId === requestedId) {
        message.textContent = failure instanceof TypeError
          ? text('Нет соединения с сервером. Ручной ввод остаётся доступен.', 'Cannot reach the server. Manual entry is still available.')
          : failure.message;
      }
      await documentUI.refresh();
    } finally {
      processing = false;
      confirm.disabled = saving;
      renderOCR();
    }
  });

  return {open};
})();
