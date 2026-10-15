// Document files live on the server, never in localStorage.
const documentUI = (() => {
  const maxSize = 10 * 1024 * 1024;
  const types = [
    ['passport', 'Паспорт', 'Passport', 'Добавить паспорт'],
    ['visa', 'Виза', 'Visa', 'Добавить визу'],
    ['migration_card', 'Миграционная карта', 'Migration card', 'Добавить миграционную карту'],
    ['registration', 'Регистрация', 'Registration', 'Добавить регистрацию'],
    ['medical_certificates', 'Медицинские сертификаты', 'Медицинские сертификаты', 'Добавить медицинские сертификаты'],
  ];
  const dialog = document.querySelector('#upload-dialog');
  const form = document.querySelector('#upload-form');
  const input = document.querySelector('#document-file');
  const preview = document.querySelector('#file-preview');
  const submit = document.querySelector('#upload-submit');
  const error = document.querySelector('#upload-error');
  const toast = document.querySelector('#document-toast');
  let records = [];
  let loaded = false;
  let loadingFailed = false;
  let activeType = null;
  let replacement = null;
  let activeMedicalType = null;
  const medicalSlots = [
    ['medical_hiv_certificate','Сертификат об отсутствии ВИЧ'],
    ['medical_infectious_diseases_certificate','Заключение об отсутствии опасных инфекционных заболеваний'],
    ['medical_drug_screening_certificate','Заключение об отсутствии употребления наркотических / психотропных веществ'],
  ];
  const medicalDialog = document.querySelector('#medical-files-dialog');
  let selectedFile = null;
  let previewUrl = null;
  let uploading = false;
  let toastTimer;
  const deleting = new Set();
  const text = (ru, en) => document.documentElement.lang === 'en' ? en : ru;

  const errors = {
    medical_slot_occupied: ['В этот слот уже добавлен файл. Используйте замену.', 'This slot already has a file.'],
    medical_slot_mismatch: ['Нельзя переместить файл в другой слот при замене.', 'Slot mismatch.'],
    already_verified: ['Данные уже подтверждены. Для исправлений используйте редактирование.', 'Details are already confirmed. Use editing to make changes.'],
    processing_in_progress: ['Распознавание уже выполняется. Ручной ввод доступен.', 'Recognition is already running. Manual entry is available.'],
    validation_error: ['Проверьте заполнение полей.', 'Please check the form fields.'],
    document_changed: ['Паспорт был заменён. Закройте окно и откройте данные заново.', 'The passport was replaced. Close the dialog and reopen the details.'],
    unsupported_type: ['Разрешены только JPG, JPEG, PNG и PDF.', 'Only JPG, JPEG, PNG and PDF are allowed.'],
    invalid_content: ['Содержимое файла не соответствует его формату.', 'The file contents do not match its format.'],
    file_too_large: ['Файл должен быть не больше 10 МБ.', 'The file must be no larger than 10 MB.'],
    empty_file: ['Выбранный файл пуст.', 'The selected file is empty.'],
    invalid_filename: ['Недопустимое имя файла. Используйте короткое имя без специальных символов.', 'Invalid filename. Use a short name without special characters.'],
    document_exists: ['Этот документ уже добавлен. Обновите список или сначала удалите его.', 'This document already exists. Refresh the list or delete it first.'],
    document_not_found: ['Документ уже удалён. Список обновлён.', 'The document was already deleted. The list has been refreshed.'],
    storage_error: ['Не удалось обратиться к хранилищу. Попробуйте ещё раз.', 'Storage is unavailable. Please try again.'],
    origin_not_allowed: ['Откройте NAVIAR по локальному адресу и попробуйте снова.', 'Open NAVIAR at its local address and try again.'],
  };

  async function request(url, options = {}) {
    const response = await fetch(url, {cache: 'no-store', ...options});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const code = response.status === 413 ? 'file_too_large' : data.detail;
      const message = errors[code] || ['Не удалось выполнить действие. Проверьте соединение с сервером и попробуйте ещё раз.', 'The action failed. Check the server connection and try again.'];
      const failure = new Error(text(...message));
      failure.fields = Array.isArray(data.fields) ? data.fields : [];
      failure.code = code;
      throw failure;
    }
    return response.status === 204 ? null : response.json();
  }

  function notify(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
  }

  function makeButton(label, callback, className = 'add-document') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = label;
    button.addEventListener('click', callback);
    return button;
  }

  function render() {
    const cards = document.querySelector('#document-cards');
    cards.replaceChildren();
    document.querySelector('.count').textContent = loaded ? (new Set(records.filter(record=>record.type!=='medical_certificates').map(record=>record.type)).size + (medicalFiles().length===3 ? 1 : 0)) + ' / 5' : '— / 5';
    const status = document.querySelector('#documents-status');
    status.replaceChildren();
    if (!loaded || loadingFailed) {
      status.append(document.createTextNode(loadingFailed
        ? text('Не удалось загрузить документы. ', 'Could not load documents. ')
        : text('Загружаем документы…', 'Loading documents…')));
      if (loadingFailed) status.append(makeButton(text('Повторить', 'Retry'), refresh));
    }
    types.forEach(([kind, ru, en]) => {
      const name = text(ru, en);
      const record = records.find(item => item.type === kind);
      const card = document.createElement('article');
      card.className = 'document-card';
      card.dataset.documentType = kind;
      // Fixed local SVG; filenames are inserted only with textContent.
      card.innerHTML = dashboardUI.documentIcon(kind);
      card.dataset.state = record?.status || 'empty';
      const heading = document.createElement('h3');
      heading.textContent = name;
      card.append(heading);
      if (kind === 'medical_certificates') {
        renderMedicalCard(card);
        cards.append(card);
        return;
      }
      if (record) {
        const badge = document.createElement('span');
        badge.className = 'document-status';
        const verified = record.status === 'verified';
        badge.textContent = verified ? text('● Данные подтверждены', '● Details confirmed') : text('● Загружен', '● Uploaded');
        const filename = document.createElement('span');
        filename.className = 'document-filename';
        filename.textContent = record.name;
        filename.title = record.name;
        const actions = document.createElement('div');
        actions.className = 'document-actions';
        const view = document.createElement('a');
        view.className = 'add-document';
        view.textContent = text('Посмотреть', 'View');
        view.href = '/api/documents/' + kind + '/file';
        view.target = '_blank';
        view.rel = 'noopener noreferrer';
        view.setAttribute('aria-label', text('Посмотреть: ', 'View: ') + name);
        const remove = makeButton(deleting.has(kind) ? text('Удаляем…', 'Deleting…') : text('Удалить', 'Delete'), () => removeDocument(kind));
        remove.disabled = deleting.has(kind);
        remove.setAttribute('aria-label', text('Удалить: ', 'Delete: ') + name);
        const verification = makeButton(
          verified ? text('Данные', 'Details') : text('Проверить данные', 'Check details'),
          () => kind === 'medical_certificates'
            ? deadlineUI.editMedical()
            : kind === 'passport'
            ? passportVerification.open(record)
            : studentUI.openField(kind)
        );
        verification.classList.add('verify-document');
        verification.disabled = deleting.has(kind);
        verification.setAttribute('aria-label', verification.textContent + ': ' + name);
        if (kind !== 'medical_certificates') actions.append(verification);
        actions.append(view, remove);
        card.append(badge);
        if (!verified) {
          const note = document.createElement('span');
          note.className = 'document-verification-note';
          note.textContent = kind === 'medical_certificates'
            ? 'Медицинские даты указываются отдельно'
            : record.status === 'processing'
            ? text('Статус: Распознавание', 'Status: Processing')
            : record.status === 'processing_error'
              ? text('Не удалось распознать · Заполните вручную', 'Recognition failed · Enter manually')
              : text('Статус: Требуется проверка', 'Status: Confirmation required');
          card.append(note);
        }
        card.append(filename, actions);
      } else {
        const button = makeButton(text('+ Добавить', '+ Add'), () => openUpload(kind));
        button.disabled = !loaded || loadingFailed;
        button.setAttribute('aria-label', text('Добавить: ', 'Add: ') + name);
        card.append(button);
      }
      cards.append(card);
    });
    dashboardUI.updateProgress(loaded && !loadingFailed, loadingFailed);
    renderNextAction();
    window.dispatchEvent(new Event('naviar:documents-changed'));
  }

  function medicalFiles() {
    return records.filter(record => record.type === 'medical_certificates' && medicalSlots.some(([slot])=>slot===record.medical_type));
  }

  function formatSize(bytes) {
    return new Intl.NumberFormat('ru', {maximumFractionDigits:2}).format(bytes / (1024 * 1024)) + ' МБ (' + bytes.toLocaleString('ru') + ' байт)';
  }

  function renderMedicalCard(card) {
    const badge=document.createElement('span'); badge.className='medical-count';
    badge.textContent=medicalFiles().length+'/3'; card.append(badge);
    const actions=document.createElement('div'); actions.className='document-actions';
    const total=medicalFiles().length;
    const open=makeButton(total===0 ? '+ Добавить сертификаты' : total<3 ? 'Продолжить загрузку' : 'Управлять',openMedicalFiles); open.classList.add('medical-add','medical-view');
    open.disabled=!loaded || loadingFailed; actions.append(open); card.append(actions);
  }

  function renderMedicalFiles() {
    const list=document.querySelector('#medical-files-list'); list.replaceChildren();
    document.querySelector('#medical-files-title').textContent='Медицинские сертификаты · '+medicalFiles().length+'/3';
    medicalSlots.forEach(([slot,title])=>{
      const record=medicalFiles().find(file=>file.medical_type===slot);
      const row=document.createElement('section'); row.className='medical-file'; row.dataset.slot=slot;
      const appearance = {
        medical_hiv_certificate: ['hiv', 'ВИЧ'],
        medical_infectious_diseases_certificate: ['infection', 'Инфекции'],
        medical_drug_screening_certificate: ['narcology', 'Наркология'],
      }[slot];
      row.classList.add('medical-slot--'+appearance[0]);
      row.classList.toggle('medical-slot--uploaded', Boolean(record));
      const badge=document.createElement('span'); badge.className='medical-slot-badge';
      badge.textContent=appearance[1]+' · '+(record ? 'Загружен' : 'Не загружен'); row.append(badge);
      if(record) row.dataset.fileId=record.document_id;
      const heading=document.createElement('h3'); heading.textContent=title; row.append(heading);
      const details=document.createElement('small'); details.textContent=record ? record.name+' · '+formatSize(record.size) : 'Не загружен'; row.append(details);
      const actions=document.createElement('div'); actions.className='document-actions';
      if(record) {
        const view=document.createElement('a'); view.className='add-document'; view.textContent='Посмотреть'; view.href=record.url; view.target='_blank'; view.rel='noopener noreferrer';
        const update=makeButton('Заменить',()=>{medicalDialog.close();openUpload('medical_certificates',record,slot);}); update.classList.add('medical-file-update');
        const remove=makeButton('Удалить',()=>removeMedicalFile(record)); remove.classList.add('medical-file-delete');
        update.disabled=remove.disabled=deleting.has(record.document_id);
        actions.append(view,update,remove);
      } else {
        const add=makeButton('Добавить',()=>{medicalDialog.close();openUpload('medical_certificates',null,slot);}); add.classList.add('medical-slot-add'); actions.append(add);
      }
      row.append(actions);
      if(record) renderMedicalDates(row,record);
      list.append(row);
    });
  }

  function renderMedicalDates(row,record) {
    const details=document.createElement('details'); details.className='medical-dates';
    const summary=document.createElement('summary'); summary.textContent='Даты документа'; details.append(summary);
    const dates=document.createElement('form'); dates.className='medical-date-form';
    [['issue_date','Дата выдачи'],['valid_until','Действителен до']].forEach(([key,label])=>{
      const labelNode=document.createElement('label'); labelNode.textContent=label;
      const input=document.createElement('input'); input.type='date'; input.name=key; input.value=record[key] || '';
      labelNode.append(input); dates.append(labelNode);
    });
    const remaining=document.createElement('p'); remaining.textContent=record.days_remaining===null ? 'Срок не указан' : record.days_remaining<0 ? 'Срок истёк' : 'Осталось '+record.days_remaining+' дней'; dates.append(remaining);
    const errorNode=document.createElement('p'); errorNode.setAttribute('role','status'); dates.append(errorNode);
    const save=makeButton('Сохранить даты',()=>{}); save.type='submit'; dates.append(save);
    dates.addEventListener('submit',async event=>{
      event.preventDefault(); save.disabled=true;
      try {
        const values=Object.fromEntries(new FormData(dates)); Object.keys(values).forEach(key=>values[key] ||= null);
        const updated=await request('/api/documents/medical_certificates/'+record.document_id+'/dates',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
        records=records.filter(item=>item.document_id!==record.document_id).concat(updated);
        render(); renderMedicalFiles(); notify('Даты сохранены');
        document.querySelector('[data-slot="'+record.medical_type+'"] summary')?.focus();
      } catch(error) { errorNode.textContent=error.message; }
      finally { save.disabled=false; }
    });
    details.append(dates); row.append(details);
  }

  function openMedicalFiles() {
    renderMedicalFiles(); medicalDialog.showModal();
  }

  async function removeMedicalFile(record) {
    if(deleting.has(record.document_id)) return;
    deleting.add(record.document_id); renderMedicalFiles();
    try {
      await request('/api/documents/medical_certificates/'+record.document_id,{method:'DELETE'});
      records=records.filter(item=>item.document_id!==record.document_id);
      notify('Документ удалён');
    } catch(failure) { notify(failure.message); await refresh(); }
    finally {
      deleting.delete(record.document_id); render(); renderMedicalFiles();
      document.querySelector('#medical-files-list button, #medical-files-close')?.focus();
    }
  }
  document.querySelector('#medical-files-close').addEventListener('click',()=>medicalDialog.close());
  medicalDialog.addEventListener('close',()=>{
    if(!dialog.open) document.querySelector('[data-document-type="medical_certificates"] .medical-view, [data-document-type="medical_certificates"] .medical-add')?.focus();
  });

  function renderNextAction() {
    if(new URLSearchParams(location.search).get('dev')!=='1') return;
    const title = document.querySelector('#next-action-title');
    const description = document.querySelector('#next-action-text');
    const button = document.querySelector('#next-action-button');
    const note = document.querySelector('#next-action-note');
    button.hidden = true;
    note.hidden = true;
    button.onclick = null;
    if (!loaded || loadingFailed) {
      title.textContent = text('Что мне делать сейчас?', 'What should I do now?');
      description.textContent = loadingFailed
        ? text('Не удалось получить состояние документов. Повторите загрузку списка выше.', 'Could not retrieve document status. Retry loading the list above.')
        : text('Проверяем состояние документов…', 'Checking document status…');
    } else if (records.length === 0) {
      title.textContent = text('Что мне делать сейчас?', 'What should I do now?');
      description.textContent = text('Добавьте документы, чтобы NAVIAR мог определить важные сроки и следующие действия.', 'Add your documents so NAVIAR can identify important deadlines and next steps.');
    } else if (records.some(record => record.status !== 'verified')) {
      title.textContent = text('Проверьте данные документов', 'Check your document details');
      description.textContent = text('Документы загружены. Подтвердите данные, чтобы NAVIAR мог использовать их для определения сроков и следующих действий.', 'Documents have been uploaded. Confirm their details so NAVIAR can use them to identify deadlines and next steps.');
      const passport = records.find(record => record.type === 'passport' && record.status !== 'verified');
      if (passport) {
        button.hidden = false;
        button.textContent = text('Проверить документы', 'Check documents');
        button.onclick = () => passportVerification.open(passport);
      } else {
        note.hidden = false;
        note.textContent = records.some(record => record.type === 'passport')
          ? text('Данные паспорта подтверждены. Проверка остальных документов появится на следующем этапе.', 'Passport details are confirmed. Verification of the other documents will arrive in the next stage.')
          : text('Сейчас доступна только проверка паспорта. Добавьте паспорт, чтобы подтвердить его данные.', 'Only passport confirmation is currently available. Add a passport to confirm its details.');
      }
    } else {
      title.textContent = text('Данные паспорта подтверждены', 'Passport details confirmed');
      description.textContent = text('Вы подтвердили данные паспорта. Добавьте остальные документы. Определение сроков и следующих действий появится на следующем этапе.', 'You have confirmed the passport details. Add the remaining documents. Deadline guidance will arrive in the next stage.');
    }
  }

  function update(record) {
    records = records.filter(item => item.type !== record.type).concat(record);
    render();
  }

  async function refresh() {
    try {
      const snapshot = await request('/api/student/context');
      records = snapshot.documents;
      loaded = true;
      loadingFailed = false;
    } catch {
      loadingFailed = true;
    }
    render();
  }

  function clearSelection() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    selectedFile = null;
    input.value = '';
    preview.removeAttribute('src');
    preview.hidden = true;
    document.querySelector('#selected-file').hidden = true;
    submit.disabled = true;
    error.textContent = '';
  }

  function openUpload(kind, existing = null, slot = null) {
    activeType = kind;
    replacement = existing;
    activeMedicalType=slot;
    if(kind==='medical_certificates' && !medicalSlots.some(([type])=>type===slot)) return;
    clearSelection();
    const type = types.find(item => item[0] === kind);
    document.querySelector('#upload-title').textContent = text(type[3], 'Add ' + type[2].toLowerCase());
    const labels = {
      'upload-description': ['Загрузите фотографию или скан документа.', 'Upload a photo or scan of the document.'],
      'choose-file-label': ['Выбрать файл', 'Choose file'],
      'upload-limits': ['JPG, JPEG, PNG, PDF · До 10 МБ', 'JPG, JPEG, PNG, PDF · Up to 10 MB'],
      'upload-warning': ['Для тестирования используйте только демонстрационные документы без реальных персональных данных.', 'For testing, use only demo documents without real personal data.'],
      'remove-selection': ['Удалить выбранный файл', 'Remove selected file'],
      'cancel-upload': ['Отмена', 'Cancel'],
      'upload-submit': ['Добавить документ', 'Add document'],
    };
    Object.entries(labels).forEach(([id, values]) => { document.getElementById(id).textContent = text(...values); });
    if(activeType==='medical_certificates') document.querySelector('#upload-title').textContent=medicalSlots.find(([type])=>type===activeMedicalType)[1];
    if (replacement) submit.textContent='Заменить документ';
    preview.alt = text('Превью выбранного документа', 'Selected document preview');
    dialog.showModal();
  }

  input.addEventListener('change', () => {
    const file = input.files[0];
    clearSelection();
    if (!file) return;
    if (file.size > maxSize) { error.textContent = text(...errors.file_too_large); return; }
    if (file.size === 0) { error.textContent = text(...errors.empty_file); return; }
    const extensions = {jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', pdf: 'application/pdf'};
    const extension = file.name.split('.').pop().toLowerCase();
    if (!extensions[extension] || (file.type && extensions[extension] !== file.type)) {
      error.textContent = text(...errors.unsupported_type); return;
    }
    selectedFile = file;
    document.querySelector('#selected-file-name').textContent = file.name;
    document.querySelector('#selected-file-size').textContent = new Intl.NumberFormat(document.documentElement.lang, {maximumFractionDigits: 2}).format(file.size / (1024 * 1024)) + text(' МБ', ' MB') + ' (' + file.size.toLocaleString(document.documentElement.lang) + text(' байт)', ' bytes)');
    document.querySelector('#selected-file').hidden = false;
    if (extension !== 'pdf') {
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
      preview.hidden = false;
    }
    submit.disabled = false;
  });

  preview.addEventListener('error', () => {
    clearSelection();
    error.textContent = text(...errors.invalid_content);
  });
  document.querySelector('#remove-selection').addEventListener('click', clearSelection);
  document.querySelector('#cancel-upload').addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (uploading) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    if (!dialog.open) clearSelection();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedFile || uploading) return;
    uploading = true;
    error.textContent = '';
    form.querySelectorAll('button, input, select').forEach(element => { element.disabled = true; });
    submit.textContent = text('Добавляем…', 'Uploading…');
    try {
      const body = new FormData();
      body.append('file', selectedFile);
      const suffix=activeType==='medical_certificates' ? (replacement ? '/'+replacement.document_id : '')+'?medical_type='+encodeURIComponent(activeMedicalType) : '';
      const record = await request('/api/documents/' + activeType + suffix, {method: replacement ? 'PUT' : 'POST', body});
      records = records.filter(item => activeType==='medical_certificates' ? item.document_id!==replacement?.document_id : item.type!==activeType).concat(record);
      render();
      dialog.close();
      document.querySelector('[data-document-type="' + activeType + '"] .medical-view, [data-document-type="' + activeType + '"] a')?.focus();
      notify(replacement ? 'Документ обновлён' : text('Документ добавлен', 'Document added'));
    } catch (failure) {
      error.textContent = failure instanceof TypeError ? text('Нет соединения с сервером. Попробуйте ещё раз.', 'Cannot reach the server. Please try again.') : failure.message;
      await refresh();
    } finally {
      uploading = false;
      form.querySelectorAll('button, input, select').forEach(element => { element.disabled = false; });
      submit.disabled = !selectedFile;
      submit.textContent = replacement ? 'Заменить документ' : text('Добавить документ', 'Add document');
    }
  });

  async function removeDocument(kind) {
    if (deleting.has(kind)) return;
    deleting.add(kind);
    render();
    try {
      await request('/api/documents/' + kind, {method: 'DELETE'});
      records = records.filter(item => item.type !== kind);
      notify(text('Документ удалён', 'Document deleted'));
    } catch (failure) {
      notify(failure instanceof TypeError ? text('Нет соединения с сервером.', 'Cannot reach the server.') : failure.message);
      await refresh();
    } finally {
      deleting.delete(kind);
      render();
      document.querySelector('[data-document-type="' + kind + '"] button')?.focus();
    }
  }

  refresh();
  return {render, refresh, request, notify, update, openUpload};
})();
