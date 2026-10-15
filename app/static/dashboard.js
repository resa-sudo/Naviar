// Presentation only: consume existing counters/read-model; no requests or storage.
const dashboardUI = (() => {
  const paths = {
    passport: '<rect x="5" y="3" width="22" height="27" rx="4"/><circle cx="16" cy="14" r="6"/><path d="M10 14h12M16 8c-4 4-4 8 0 12 4-4 4-8 0-12M11 25h10"/>',
    visa: '<rect x="3" y="6" width="26" height="21" rx="4"/><path d="m9 17 4 4 10-10M8 3v5M24 3v5"/>',
    migration_card: '<rect x="3" y="6" width="26" height="21" rx="4"/><path d="M8 12h8M8 17h5m5 1 7 0m-3-3 3 3-3 3M8 22h5"/>',
    registration: '<path d="m4 14 12-10 12 10M7 12v16h18V12M13 28V18h6v10"/>',
    medical_certificates: '<rect x="4" y="7" width="24" height="22" rx="4"/><path d="M11 7V3h10v4M16 12v12M10 18h12"/>',
  };
  function documentIcon(kind) {
    return '<svg class="document-icon" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[kind]+'</svg>';
  }
  function updateProgress(available, failed = false) {
    const count = Number(document.querySelector('.count').textContent.split('/')[0]);
    const percent = available ? count * 20 : null;
    const ring = document.querySelector('#dashboard-progress');
    ring.style.setProperty('--progress', (percent ?? 0) + '%');
    if (available) ring.setAttribute('aria-valuenow', percent);
    else ring.removeAttribute('aria-valuenow');
    document.querySelector('#dashboard-percentage').textContent = percent === null ? '—' : percent + '%';
    document.querySelector('#dashboard-progress-count').textContent = available ? count + ' из 5' : '— из 5';
    presentDocuments();
    const english = document.documentElement.lang === 'en';
    document.querySelector('#dashboard-document-total').textContent = available
      ? (english ? 'Added ' + count + ' of 5 categories' : 'Добавлено ' + count + ' из 5 категорий')
      : failed ? (english ? 'Documents unavailable' : 'Документы недоступны') : (english ? 'Loading documents…' : 'Загружаем документы…');
  }
  function node(tag, text, parent, className = '') {
    const item = document.createElement(tag);
    item.textContent = text; item.className = className; parent.append(item); return item;
  }
  function presentContext(data) {
    // Priority and deadline calculations belong to the existing backend.
    const list = document.querySelector('#student-next-actions');
    const first = list.firstElementChild;
    document.querySelector('#dashboard-next-summary').textContent = data.next_actions[0]?.title || 'Посмотрите свои документы';
    if (first) {
      first.classList.add('primary-action');
      const action = data.next_actions[0];
      if (Number.isFinite(action.days_remaining)) {
        const rule = data.rules.procedures.find(row => row.rule_id === action.source_rule?.rule_id);
        const units = rule?.day_type === 'business_days' ? ' рабочих дней' : ' календарных дней';
        const label = action.days_remaining < 0 ? 'Срок подачи прошёл: ' : 'До подачи: ';
        const timing = node('p', label + Math.abs(action.days_remaining) + units, first, 'action-timing');
        first.querySelector('h3').after(timing);
      }
      const actionButton = first.querySelector('button');
      actionButton.textContent = 'Открыть';
      actionButton.setAttribute('aria-label', 'Открыть: ' + data.next_actions[0].title);
      // Keep secondary actions accessible without competing with the first task.
      const rest = [...list.children].slice(1);
      const explanation = [...first.querySelectorAll(':scope > p:not(.action-timing)')];
      const details = node('details', '', list, 'other-actions');
      node('summary', 'Подробнее' + (rest.length ? ' и другие действия' : ''), details);
      details.append(...explanation, ...rest);
    }
    for (const card of document.querySelectorAll('#student-deadlines .deadline-card')) {
      const kind = card.dataset.studentDocument;
      const row = data.rules.procedures.find(row => row.document_type === kind && row.result.deadline_date);
      const days = row?.expiry_days_remaining;
      const confirmed = data.context[kind]?.[kind === 'migration_card' ? 'entry_date' : 'expiry_date']?.confirmed;
      const value = node('div', '', card, 'deadline-value');
      node('strong', confirmed && Number.isFinite(days) ? String(Math.abs(days)) : '—', value);
      node('span', confirmed && Number.isFinite(days) ? (days < 0 ? 'дней после окончания' : 'дней до окончания') : 'уточните дату', value);
      card.querySelector('h3').after(value);
      const details = document.createElement('details'); details.className = 'deadline-details';
      node('summary', 'Подробнее', details);
      details.append(...card.querySelectorAll(':scope > p, :scope > button'));
      card.append(details);
    }
    const medical = node('article', '', document.querySelector('#student-deadlines'), 'deadline-card medical-deadline-summary');
    medical.dataset.studentDocument = 'medical_certificates';
    node('h3', 'Медицинские', medical);
    const slots = ['medical_hiv_certificate', 'medical_infectious_diseases_certificate', 'medical_drug_screening_certificate'];
    const remaining = data.documents.filter(record => record.type === 'medical_certificates' && slots.includes(record.medical_type) && Number.isFinite(record.days_remaining)).map(record => record.days_remaining);
    const days = remaining.length ? Math.min(...remaining) : null;
    const value = node('div', '', medical, 'deadline-value');
    node('strong', days === null ? '—' : String(Math.abs(days)), value);
    node('span', days === null ? 'уточните дату' : days < 0 ? 'дней после окончания' : 'дней до окончания', value);
    node('p', days === null ? 'Укажите срок в сертификате' : 'Ближайший из указанных сроков', medical);
    const open = node('button', 'Сертификаты', medical, 'add-document'); open.type = 'button';
    open.addEventListener('click', () => document.querySelector('.medical-add').click());
    const medicalDetails = node('details', '', medical, 'deadline-details');
    node('summary', 'Сертификаты', medicalDetails);
    medicalDetails.append(...medical.querySelectorAll(':scope > p, :scope > button'));
    for (const card of cardsForDeadlines()) {
      const icon = document.createElement('span'); icon.className = 'deadline-icon';
      icon.innerHTML = documentIcon(card.dataset.studentDocument);
      card.prepend(icon);
    }
  }
  function cardsForDeadlines() {
    return document.querySelectorAll('#student-deadlines .deadline-card');
  }
  function presentDocuments() {
    // Rearrange the existing controls, preserving their listeners and file URLs.
    for (const card of document.querySelectorAll('#document-cards .document-card')) {
      const actions = card.querySelector('.document-actions');
      const filename = card.querySelector('.document-filename');
      if (filename && actions && !actions.querySelector('.document-menu')) {
        const menu = node('details', '', actions, 'document-menu');
        const summary = node('summary', '⋯', menu);
        summary.setAttribute('aria-label', 'Действия: ' + card.querySelector('h3').textContent);
        const content = node('div', '', menu, 'document-menu-content');
        content.append(filename, ...actions.querySelectorAll(':scope > a, :scope > button:not(.verify-document)'));
      }
      if (card.dataset.documentType === 'medical_certificates') {
        const total = Number(card.querySelector('.medical-count').textContent.split('/')[0]);
        const bar = card.querySelector('.medical-progress') || node('span', '', card, 'medical-progress');
        bar.setAttribute('aria-hidden', 'true'); bar.style.setProperty('--medical-progress', total / 3 * 100 + '%');
      }
    }
  }
  document.querySelector('.header-profile').addEventListener('click', () => document.querySelector('[data-nav="profile"]').click());
  // Anchor navigation also works in the existing developer view.
  document.querySelector('.deadlines-nav').addEventListener('click', event => {
    event.preventDefault();
    const target = document.querySelector('#student-guidance').hidden ? '#deadline-section' : '#student-guidance';
    document.querySelector(target).scrollIntoView({block: 'start'});
  });
  return {documentIcon, updateProgress, presentContext};
})();
