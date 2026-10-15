// Manual planning stays separate from OCR; the backend resolves rules and citizenship.
const deadlineUI = (() => {
  if(new URLSearchParams(location.search).get('dev')!=='1') return {open:()=>{},editMedical:()=>{}};
  document.querySelector('#deadline-section').hidden=false;
  const form = document.querySelector('#deadline-form');
  const message = document.querySelector('#deadline-message');
  const dialog = document.querySelector('#deadline-dialog');
  let profile = null;
  let revision = 0;
  let preserved = {};
  const dateFields = ['visa_expiry','stay_expiry','new_visa_received','entry_date'];
  const formatDate = value => value ? new Intl.DateTimeFormat('ru', {timeZone:'UTC'}).format(new Date(value+'T00:00:00Z')) : 'Не указана';
  const statusLabels = {safe:'Есть время на подготовку',attention:'Обратите внимание на срок',urgent:'Срок близко',due_today:'Крайняя дата сегодня',overdue:'Крайняя дата подачи прошла',unknown:'Требуется уточнение'};
  function node(tag, text, parent) {
    const element=document.createElement(tag); element.textContent=text; parent.append(element); return element;
  }
  async function request(path, options={}) {
    const response=await fetch('/api/deadlines'+path,{cache:'no-store',...options});
    if(!response.ok) throw new Error(response.status===422 ? 'Проверьте даты и выбранные значения.' : 'Не удалось получить сроки. Попробуйте ещё раз.');
    return response.json();
  }
  function remainingText(row) {
    const remaining=row.day_type==='business_days'?row.result.days_remaining_business:row.result.days_remaining_calendar;
    if(remaining===null) return 'Требуется уточнение';
    return (remaining<0?'После крайней даты: ':'До крайней даты подачи: ')+Math.abs(remaining)+(row.day_type==='business_days'?' рабочих дней':' календарных дней');
  }
  function showDetails(row) {
    document.querySelector('#deadline-detail-title').textContent=row.title;
    const body=document.querySelector('#deadline-detail-body'); body.replaceChildren();
    node('h3','Что нужно сделать',body);
    node('p',row.procedure_type==='visa_extension' ? row.notes : row.title,body);
    node('p','До какого числа: '+(row.result.deadline_date?formatDate(row.result.deadline_date):'Требуется уточнение'),body);
    node('p',remainingText(row),body);
    if(row.result.status==='overdue') node('p','Крайняя дата подачи прошла. Обратитесь в МФЦ РУДН, чтобы уточнить дальнейшие действия.',body);
    node('h3','Куда обратиться',body);
    node('p',row.submission_place ? row.submission_place+(row.address ? ': '+row.address : '') : 'Уточните в университете',body);
    node('h3','Какие документы подготовить',body);
    if(row.required_documents.length && !row.requirements_pending) {
      const list=node('ul','',body); row.required_documents.forEach(item=>node('li',item,list));
    } else node('p','Список документов требует уточнения',body);
    node('h3','Официальный источник',body);
    const link=node('a',row.result.rule_source.title,body);
    link.href=row.result.rule_source.url; link.target='_blank'; link.rel='noopener noreferrer';
    node('p','Информация основана на опубликованных правилах университета. Перед подачей проверьте актуальность.',body);
    dialog.showModal();
  }
  function applyRegime(data) {
    const select=form.elements.entry_regime;
    const options=data.entry_regime_determined
      ? [[data.entry_regime,'Визовый']]
      : [['unknown','Требуется уточнение'],['visa_required','Визовый'],['visa_free','Безвизовый']];
    select.replaceChildren(...options.map(([value,label])=>new Option(label,value)));
    select.value=data.entry_regime; select.disabled=data.entry_regime_determined;
    form.elements.stay_expiry.closest('.passport-field').hidden=data.entry_regime==='visa_required';
  }
  function render(data) {
    applyRegime(data);
    const cards=document.querySelector('#deadline-cards'); cards.replaceChildren();
    const medical=document.querySelector('#medical-deadline-cards'); medical.replaceChildren();
    message.textContent=data.message || 'Дата расчёта: '+formatDate(data.today);
    data.procedures.filter(row=>row.document_type!=='medical_examination').forEach(row=>{
      const card=node('article','',cards);
      card.className='deadline-card'; card.dataset.ruleId=row.rule_id; card.dataset.status=row.result.status;
      node('h3',row.title,card);
      if(row.expiry_date) {
        node('p','Действует до: '+formatDate(row.expiry_date),card);
        node('p',row.expiry_days_remaining>=0 ? 'До окончания: '+row.expiry_days_remaining+' календарных дней' : 'Дата окончания прошла: '+Math.abs(row.expiry_days_remaining)+' календарных дней',card);
      }
      node('strong',statusLabels[row.result.status],card);
      if(row.result.deadline_date) {
        node('p','Подать документы до: '+formatDate(row.result.deadline_date),card);
        node('p',remainingText(row),card);
      } else {
        const reason=row.result.reason || '';
        node('p',reason.startsWith('calendar_')?'Календарь нужного года отсутствует или требует обновления.':reason==='trigger_date_missing'?'Укажите дату события.':'Требуется уточнение',card);
      }
      if(row.submission_place) node('p','Место: '+row.submission_place,card);
      if(row.day_type==='business_days') node('p','Рабочие дни считаются без выходных и официальных праздничных дней.',card);
      const button=node('button',row.result.status==='overdue'?'Что делать':'Что подготовить',card);
      button.type='button'; button.className='add-document'; button.addEventListener('click',()=>showDetails(row));
    });
    const info=data.medical_certificates;
    const card=node('article','',medical); card.className='deadline-card'; card.dataset.medical='examination';
    node('h3','Медицинское освидетельствование',card);
    if(info.status==='confirmed' && info.completed_at) {
      node('p','Пройдено: '+formatDate(info.completed_at),card);
      node('p','Обновить до: '+(info.next_required_at?formatDate(info.next_required_at):'Требуется уточнение'),card);
      if(info.next_required_at) node('p','До обновления: '+info.days_remaining+' календарных дней',card);
      if(info.valid_until) {
        node('p','Сертификаты действуют до: '+formatDate(info.valid_until),card);
        if(!info.next_required_at) node('p',info.days_remaining<0?'Срок сертификатов истёк':('Осталось: '+info.days_remaining+' календарных дней'),card);
      }
    } else node('p','Добавьте дату прохождения',card);
    const edit=node('button','Указать даты',card); edit.type='button'; edit.className='add-document'; edit.addEventListener('click',editMedical);
  }
  function contextFromForm() {
    const values=Object.fromEntries(new FormData(form));
    dateFields.forEach(key=>values[key] ||= null);
    const medical_certificates={completed_at:values.medical_completed_at || null,valid_until:values.medical_valid_until || null,status:form.elements.medical_confirmed.checked?'confirmed':'unknown'};
    delete values.medical_completed_at; delete values.medical_valid_until; delete values.medical_confirmed;
    return {...preserved,...values,medical_certificates,entry_regime:form.elements.entry_regime.value,university_id:profile.university,citizenship:profile.citizenship,country_of_study:'RU'};
  }
  function editMedical() {
    document.querySelector('#deadline-inputs').open=true;
    document.querySelector('#medical-inputs').scrollIntoView({block:'center'});
    form.elements.medical_completed_at.focus();
  }
  async function open(nextProfile) {
    profile=nextProfile; preserved={};
    const current=++revision;
    form.reset(); message.textContent='Загружаем сроки…';
    // Hide regime choices until the backend resolves the country.
    form.elements.entry_regime.replaceChildren(new Option('Определяем по гражданству','unknown'));
    form.elements.entry_regime.disabled=true;
    document.querySelector('#deadline-cards').replaceChildren();
    document.querySelector('#medical-deadline-cards').replaceChildren();
    try {
      const saved=await request('/state');
      if(current!==revision) return;
      if(saved.context?.university_id===profile.university && saved.context?.citizenship===profile.citizenship) {
        preserved=saved.context;
        Object.entries(saved.context).forEach(([key,value])=>{if(form.elements[key] && key!=='entry_regime') form.elements[key].value=value || '';});
        const info=saved.context.medical_certificates;
        form.elements.medical_completed_at.value=info.completed_at || '';
        form.elements.medical_valid_until.value=info.valid_until || '';
        form.elements.medical_confirmed.checked=info.status==='confirmed';
        form.elements.entry_regime.replaceChildren(new Option('Режим въезда',saved.context.entry_regime));
      }
      const data=await request('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(contextFromForm())});
      if(current===revision) render(data);
    } catch(error) { if(current===revision) message.textContent=error.message; }
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault(); if(!profile) return;
    const current=revision; const button=document.querySelector('#deadline-save'); button.disabled=true;
    try {
      const data=await request('/state',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(contextFromForm())});
      if(current===revision) {render(data); documentUI.notify('Тестовые даты сохранены');}
    } catch(error) {if(current===revision) message.textContent=error.message;}
    finally {button.disabled=false;}
  });
  document.querySelector('#deadline-close').addEventListener('click',()=>dialog.close());
  return {open,editMedical};
})();
