// The normal dashboard consumes the backend read-model, never the debug form.
const studentUI=(()=>{
  const dev=new URLSearchParams(location.search).get('dev')==='1';
  const section=document.querySelector('#student-guidance');
  const dialog=document.querySelector('#fallback-dialog');
  const input=document.querySelector('#fallback-value');
  let ready=false, snapshot=null, sequence=0, active=null;
  const names={visa:'Виза',migration_card:'Миграционная карта',registration:'Регистрация'};
  const keys={visa:'expiry_date',migration_card:'entry_date',registration:'expiry_date'};
  const labels={visa:'Дата окончания визы',migration_card:'Дата въезда',registration:'Дата окончания регистрации'};
  const format=value=>value ? new Intl.DateTimeFormat('ru',{timeZone:'UTC'}).format(new Date(value+'T00:00:00Z')) : 'Не указана';
  const node=(tag,text,parent)=>{const item=document.createElement(tag);item.textContent=text;parent.append(item);return item;};
  async function request(path,options={}) {
    const response=await fetch('/api/student'+path,{cache:'no-store',...options});
    if(!response.ok) throw new Error(response.status===422?'Проверьте указанное значение.':response.status===409?'Документ изменился. Откройте его заново.':'Не удалось получить данные. Попробуйте ещё раз.');
    return response.json();
  }
  function button(parent,title,callback) {
    const item=node('button',title,parent); item.type='button';item.className='add-document';item.addEventListener('click',callback);return item;
  }
  function showRule(row) {
    const target=document.querySelector('#deadline-detail-body'); target.replaceChildren();
    document.querySelector('#deadline-detail-title').textContent=row.title;
    node('p',row.notes,target);
    node('p','Документы подать до: '+format(row.result.deadline_date),target);
    node('p',row.submission_place || 'Уточните место в университете',target);
    if(row.required_documents.length && !row.requirements_pending) {
      const list=node('ul','',target);row.required_documents.forEach(text=>node('li',text,list));
    } else node('p','Список документов требует уточнения',target);
    const link=node('a',row.result.rule_source.title,target);link.href=row.result.rule_source.url;link.target='_blank';link.rel='noopener noreferrer';
    node('p','Информация основана на опубликованных правилах университета. Перед подачей проверьте актуальность.',target);
    document.querySelector('#deadline-dialog').showModal();
  }
  function render(data) {
    snapshot=data;
    if(dev || !data.context) return;
    section.hidden=false;
    document.querySelector('#student-status').textContent='';
    const cards=document.querySelector('#student-deadlines');cards.replaceChildren();
    const context=data.context;
    for(const kind of ['visa','migration_card','registration']) {
      if(kind==='visa' && context.entry_regime.value!=='visa_required') continue;
      const group=context[kind], value=group[keys[kind]];
      const card=node('article','',cards);card.className='deadline-card';card.dataset.studentDocument=kind;
      node('h3',names[kind],card);
      if(value.confirmed) {
        node('p',labels[kind]+': '+format(value.value),card);
        const row=data.rules.procedures.find(row=>row.document_type===kind && row.result.deadline_date);
        if(row) {
          if(row.expiry_days_remaining!==null) node('p','До окончания: '+row.expiry_days_remaining+' календарных дней',card);
          node('p','Документы подать до: '+format(row.result.deadline_date),card);
          const remaining=row.day_type==='business_days'?row.result.days_remaining_business:row.result.days_remaining_calendar;
          node('p',remaining===null?'Календарь требует уточнения':(remaining<0?'Крайняя дата подачи прошла. ':'Осталось: ')+Math.abs(remaining)+(row.day_type==='business_days'?' рабочих дней':' календарных дней'),card);
          node('p',row.submission_place || '',card);
          button(card,'Что подготовить',()=>showRule(row));
        } else if(kind==='visa') node('p','Срок подачи требует уточнения в университете.',card);
        button(card,'Исправить дату',()=>openField(kind));
      } else {
        node('p',kind==='visa'?'Нужна дата окончания визы':kind==='migration_card'?'Проверьте дату въезда':'Нужна дата окончания регистрации',card);
        button(card,kind==='visa'?'Проверить визу':group.document_id.value?'Указать вручную':'Добавить документ',()=>openField(kind));
      }
    }
    document.querySelector('#next-action-title').textContent='Что сделать дальше?';
    document.querySelector('#next-action-text').textContent=data.next_actions.length?'':'Добавьте документы, чтобы увидеть следующие действия.';
    document.querySelector('#next-action-button').hidden=true;document.querySelector('#next-action-note').hidden=true;
    const list=document.querySelector('#student-next-actions');list.replaceChildren();
    data.next_actions.forEach(action=>{
      const item=node('article','',list);item.className='student-action';item.dataset.priority=action.priority;
      node('h3',action.title,item);node('p',action.reason,item);
      if(action.deadline) node('p','До '+format(action.deadline)+(action.destination?' · '+action.destination:''),item);
      const rule=data.rules.procedures.find(row=>row.rule_id===action.source_rule?.rule_id);
      button(item,rule?'Что подготовить':'Проверить документ',()=>rule?showRule(rule):openField(action.document_type));
    });
    dashboardUI.presentContext(data);
  }
  async function refresh() {
    if(!ready) return;
    const current=++sequence;
    try { const data=await request('/context');if(current===sequence) {render(data);return data;} }
    catch(error) { if(!dev && current===sequence) {section.hidden=false;document.querySelector('#student-status').textContent=error.message;} }
  }
  async function open() {
    ++sequence; ready=true; await refresh();
  }
  async function openField(kind) {
    if(!ready) {documentUI.notify('Профиль ещё загружается. Попробуйте через секунду.');return;}
    const fresh=await refresh(); if(!fresh?.context) return;
    const record=snapshot?.documents.find(record=>record.type===kind);
    if(!record) {documentUI.openUpload(kind);return;}
    if(kind==='passport') {passportVerification.open(record);return;}
    if(kind==='visa') {visaVerification.open(record);return;}
    if(!keys[kind]) return;
    active={kind,document_id:record.document_id,field:keys[kind]};
    document.querySelector('#fallback-title').textContent=names[kind];
    document.querySelector('#fallback-label').textContent=labels[kind];
    input.value=snapshot.context?.[kind]?.[keys[kind]]?.value || '';
    document.querySelector('#fallback-error').textContent='';dialog.showModal();input.focus();
  }
  document.querySelector('#fallback-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!active) return;
    const target={...active};const save=document.querySelector('#fallback-save');save.disabled=true;
    try {
      const data=await request('/documents/'+target.kind+'/'+target.document_id+'/field',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({field:target.field,value:input.value,confirmed:true})});
      render(data);dialog.close();documentUI.notify('Значение подтверждено');
    } catch(error) {document.querySelector('#fallback-error').textContent=error.message;}
    finally {save.disabled=false;}
  });
  document.querySelector('#fallback-cancel').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(!dialog.open) {active=null;input.value='';}});
  if(!dev) document.querySelector('#deadline-close').addEventListener('click',()=>document.querySelector('#deadline-dialog').close());
  window.addEventListener('naviar:documents-changed',refresh);
  return {open,refresh,openField};
})();
