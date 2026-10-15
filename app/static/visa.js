// Visa OCR uses only this dialog's memory and the local backend; never localStorage.
const visaVerification=(()=>{
  const dialog=document.querySelector('#visa-dialog');
  const form=document.querySelector('#visa-form');
  const recognize=document.querySelector('#visa-recognize');
  const confirm=document.querySelector('#visa-confirm');
  const message=document.querySelector('#visa-error');
  const note=document.querySelector('#visa-ocr-note');
  const names=['visa_number','visa_type','entries','issue_date','valid_from','valid_until','citizenship','passport_number_if_present','purpose_or_category_if_reliable','issuing_authority_if_reliable'];
  let active=null,version=0,busy=false;
  const empty=input=>!input.value || input.value==='unknown';
  function setBusy(value) {busy=value;confirm.disabled=value;recognize.disabled=value || active?.status==='verified';}
  function fill(data,onlyEmpty=false) {
    names.forEach(name=>{const input=form.elements[name];if(!onlyEmpty || empty(input)) input.value=data?.[name] || (input.tagName==='SELECT'?'unknown':'');});
  }
  function missingFields() {
    document.querySelectorAll('[data-visa-missing]').forEach(item=>{
      const name=item.dataset.visaMissing;item.replaceChildren();item.hidden=!empty(form.elements[name]);
      if(item.hidden) return;
      const text=document.createElement('span');text.textContent=name==='valid_until'?'Не удалось определить срок действия визы. ':'Значение не распознано. ';
      const button=document.createElement('button');button.type='button';button.className='add-document';button.textContent='Указать вручную';
      button.addEventListener('click',()=>form.elements[name].focus());item.append(text,button);
    });
  }
  function showExtraction(extraction) {
    if(!extraction) {note.textContent='Распознайте JPG/PNG локально или заполните поля вручную.';return;}
    const messages={supported_partial:'Виза распознана частично. Проверьте найденные поля, остальные можно заполнить вручную.',success:'Данные распознаны. Проверьте каждое поле перед подтверждением.',partial:'Часть данных распознана. Заполните или исправьте недостающие поля.',failed:'Не удалось распознать документ. Попробуйте ещё раз или заполните данные вручную.',unsupported_or_not_visa:'Похоже, загруженный файл не является поддерживаемой визой. Загрузите фото или скан визы либо заполните данные вручную.'};
    note.textContent=extraction.errors?.includes('ocr_images_only')?'Для локального распознавания загрузите JPG или PNG. Данные PDF можно заполнить вручную.':messages[extraction.processing_status] || messages.failed;
    missingFields();
  }
  async function request(suffix,options={}) {
    const response=await fetch('/api/documents/visa/'+suffix,{cache:'no-store',...options});
    if(!response.ok) {
      const data=await response.json().catch(()=>({}));
      throw new Error(response.status===409?'Документ или его состояние изменились. Откройте форму заново.':response.status===422?'Проверьте поля: даты должны быть корректными, а срок окончания — не раньше выдачи и начала действия. Заполните хотя бы одно поле.':'Не удалось выполнить действие. Попробуйте ещё раз.');
    }
    return response.json();
  }
  async function open(record) {
    const token=++version;active=record;fill({});names.forEach(name=>form.elements[name].disabled=true);message.textContent='';note.textContent='Загрузка данных…';
    document.querySelectorAll('[data-visa-missing]').forEach(item=>item.hidden=true);
    document.querySelector('#visa-additional').open=false;
    if(!dialog.open) dialog.showModal();setBusy(true);
    try {
      const result=await request('data');if(token!==version || !dialog.open) return;
      if(result.document.document_id!==record.document_id) throw new Error('Документ изменился. Откройте форму заново.');
      active=result.document;fill(result.data);showExtraction(result.extraction);
      if(active.status==='verified') note.textContent='Данные подтверждены вами. Здесь можно исправить значения и подтвердить их снова.';
      document.querySelector('#visa-additional').open=names.slice(6).some(name=>!!result.data?.[name]);
    } catch(error) {if(token===version) {active=null;message.textContent=error.message;}}
    finally {if(token===version) {names.forEach(name=>form.elements[name].disabled=false);setBusy(false);if(!active) {confirm.disabled=true;recognize.disabled=true;}}}
  }
  recognize.addEventListener('click',async()=>{
    if(busy || !active) return;const token=version;const id=active.document_id;setBusy(true);message.textContent='';note.textContent='Распознаём на этом компьютере…';
    try {
      const result=await request('process',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document_id:id})});
      if(token!==version || !dialog.open) return;
      active=result.document;fill(result.data,true);showExtraction(result.extraction);documentUI.update(result.document);
      if(names.slice(6).some(name=>!!form.elements[name].value)) document.querySelector('#visa-additional').open=true;
    } catch(error) {if(token===version) {message.textContent=error.message;note.textContent='Можно заполнить поля вручную.';}}
    finally {if(token===version) setBusy(false);}
  });
  form.addEventListener('input',()=>{message.textContent='';missingFields();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !active) return;
    const token=version;const data=Object.fromEntries(names.map(name=>[name,form.elements[name].value || null]));
    setBusy(true);message.textContent='';
    try {
      const result=await request('data',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({document_id:active.document_id,data})});
      if(token!==version) return;
      documentUI.update(result.document);dialog.close();documentUI.notify('Данные визы подтверждены');
    } catch(error) {if(token===version) message.textContent=error.message;}
    finally {if(token===version) setBusy(false);}
  });
  document.querySelector('#visa-cancel').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(dialog.open) return;++version;active=null;fill({});setBusy(false);});
  return {open};
})();
