// Optional browser smoke test. Requires a separate Chrome debugging session on 9223.
// Only run against an empty local demo store. No npm dependencies are needed.
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const base = process.env.NAVIAR_TEST_URL || 'http://127.0.0.1:8000';
const debugPort = process.env.NAVIAR_DEBUG_PORT || '9223';
const existing = await (await fetch(base + '/api/documents')).json();
assert.equal(existing.length, 0, 'Use an empty demo store for this test.');
const output = path.resolve('.browser-check/results');
await mkdir(output, {recursive: true});
let png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=', 'base64');
if (process.env.NAVIAR_TEST_OCR === '1') {
  png = await readFile(path.resolve('.document-lab/fixtures/synthetic-td3-issue.png'));
}
await writeFile(path.join(output, 'naviar-ui-demo.png'), png);
let pdf = '%PDF-1.4\n';
const offsets = [0];
const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R >>', '<< /Length 0 >>\nstream\n\nendstream'];
objects.forEach((item, index) => { offsets.push(pdf.length); pdf += (index + 1) + ' 0 obj\n' + item + '\nendobj\n'; });
const xref = pdf.length;
pdf += 'xref\n0 5\n0000000000 65535 f \n' + offsets.slice(1).map(offset => String(offset).padStart(10, '0') + ' 00000 n \n').join('');
pdf += 'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n' + xref + '\n%%EOF\n';
await writeFile(path.join(output, 'naviar-ui-demo.pdf'), pdf);
const tabs = await (await fetch('http://127.0.0.1:' + debugPort + '/json/list')).json();
const tab = tabs.find(item => item.type === 'page');
const socket = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let sequence = 0;
const pending = new Map();
const browserErrors = [];
socket.onmessage = event => {
  const result = JSON.parse(event.data);
  if (result.method === 'Runtime.exceptionThrown') browserErrors.push(result.params.exceptionDetails);
  if (result.id) {
    const handler = pending.get(result.id);
    pending.delete(result.id);
    result.error ? handler.reject(new Error(JSON.stringify(result.error))) : handler.resolve(result.result);
  }
};
function send(method, params = {}) {
  return new Promise((resolve, reject) => { const id = ++sequence; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params})); });
}
async function evaluate(expression, userGesture = false) {
  const result = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true, userGesture});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function wait(expression, attempts = 100) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out: ' + expression);
}
async function reloadPage() {
  // Page.reload returns before navigation finishes. Ignore the old document,
  // whose counter may already match the expected post-refresh value.
  await evaluate('window.__naviarBeforeReload = true');
  await send('Page.reload');
  await wait("window.__naviarBeforeReload !== true && document.readyState === 'complete' && !!document.querySelector('.count')");
}

async function click(selector) { await evaluate('document.querySelector(' + JSON.stringify(selector) + ').click()', true); }
async function selectFile(name) {
  const {root} = await send('DOM.getDocument');
  const {nodeId} = await send('DOM.querySelector', {nodeId: root.nodeId, selector: '#document-file'});
  await send('DOM.setFileInputFiles', {nodeId, files: [path.join(output, name)]});
}
async function screenshot(name, format = 'png') {
  const capture = await send('Page.captureScreenshot', {format, ...(format === 'jpeg' ? {quality:85} : {}), captureBeyondViewport: false});
  await writeFile(path.join(output, name + (format === 'jpeg' ? '.jpg' : '.png')), Buffer.from(capture.data, 'base64'));
}
const medicalSlots=['medical_hiv_certificate','medical_infectious_diseases_certificate','medical_drug_screening_certificate'];
async function upload(kind, filename, count, subtype=medicalSlots[0]) {
  await click('[data-document-type="' + kind + '"] button');
  if(kind==='medical_certificates') await click('[data-slot="'+subtype+'"] .medical-slot-add');
  await selectFile(filename);
  await wait("!document.querySelector('#upload-submit').disabled");
  await click('#upload-submit');
  await wait("document.querySelector('.count').textContent === '" + count + " / 5' && !document.querySelector('#upload-dialog').open");
}
try {
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', {width:390, height:844, deviceScaleFactor:1, mobile:true});
  await send('Page.navigate', {url: base+'/?dev=1'});
  await wait("!!document.querySelector('#citizenship') && document.querySelector('#citizenship').options.length > 1");
  assert.equal(await evaluate("!!document.querySelector('.intro-symbols')"),false);
  // Welcome/profile styling: use only the isolated test profile, never user storage.
  for (const width of [320,390,440,768,1440]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:956,deviceScaleFactor:1,mobile:width<760});
    assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true,'Welcome screen fits '+width);
  }
  await evaluate("(()=>{const f=document.querySelector('#profile-form');Object.entries({citizenship:'tm',university:'rudn',degree:'bachelor',language:'ru'}).forEach(([key,value])=>f.elements[key].value=value);})()");
  await wait("document.querySelector('#onboarding .brand-symbol').complete && document.querySelector('#onboarding .brand-symbol').naturalWidth>0");
  await screenshot('welcome-desktop-1440');
  const welcomeJpeg=await send('Page.captureScreenshot',{format:'jpeg',quality:85,captureBeyondViewport:false});
  await writeFile(path.join(output,'welcome-desktop-1440.jpg'),Buffer.from(welcomeJpeg.data,'base64'));
  await send('Emulation.setDeviceMetricsOverride',{width:440,height:956,deviceScaleFactor:1,mobile:true});
  await evaluate('window.scrollTo(0,0)');
  await screenshot('welcome-mobile-440');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await evaluate("document.querySelector('#citizenship').focus()");
  assert.equal(await evaluate("document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineStyle==='solid'"),true);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#citizenship')).fontSize"),'16px');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  console.log('PASS: welcome screen 320–1440, desktop/mobile captures, visible keyboard focus and readable mobile fields.');
  await evaluate("(()=>{const form=document.querySelector('#profile-form');form.elements.citizenship.value='tm';form.elements.university.value='rudn';form.elements.degree.value='bachelor';form.elements.language.value='ru';form.requestSubmit();})()");
  await wait("!document.querySelector('#dashboard').hidden");
  assert.equal((await (await fetch(base+'/api/student/profile')).json()).profile.university,'rudn');
  assert.equal(await evaluate("localStorage.getItem('naviar.student.profile.v1')"),null);
  await reloadPage();
  await wait("!!document.querySelector('#dashboard') && !document.querySelector('#dashboard').hidden && document.querySelector('.count').textContent === '0 / 5'");
  for(let attempt=0;attempt<3;attempt++) {
    assert.equal(await evaluate("document.activeElement?.id === 'dashboard-title'"),false);
    assert.equal(await evaluate("document.querySelector('#dashboard-title').hasAttribute('tabindex')"),false);
    assert.equal(await evaluate("getComputedStyle(document.querySelector('#dashboard-title')).outlineStyle"),'none');
    if(attempt<2) { await reloadPage(); await wait("document.querySelector('.count')?.textContent === '0 / 5'"); }
  }
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  await evaluate("document.querySelector('.medical-add').focus()");
  assert.equal(await evaluate("document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineStyle === 'solid'"),true);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.document-grid')).gridTemplateColumns.split(' ').length"),3);
  console.log('PASS: refresh never focuses heading; visible keyboard button focus; compact mobile cards.');
  const greetings = Array.from({length: 24}, (_, hour) => hour < 5 || hour >= 23 ? 'Доброй ночи!' : hour < 12 ? 'Доброе утро!' : hour < 18 ? 'Добрый день!' : 'Добрый вечер!');
  assert.deepEqual(await evaluate("Array.from({length:24},(_,hour)=>greetingForHour(hour,'ru'))"), greetings);
  for (const [hour, minute] of [[0,0],[4,59],[5,0],[11,59],[12,0],[17,59],[18,0],[22,59],[23,0]]) {
    const actual = await evaluate(`(()=>{const OriginalDate=window.Date;try{window.Date=class extends OriginalDate{constructor(...args){super(...(args.length ? args : [2026,8,29,${hour},${minute}]));}};updateGreeting();return document.querySelector('[data-i18n="greeting"]').textContent;}finally{window.Date=OriginalDate;updateGreeting();}})()`);
    assert.equal(actual, 'Привет, Ресул!');
  }
  assert.deepEqual(await evaluate("[6,12,18,23].map(hour=>greetingForHour(hour,'en'))"), ['Good morning!','Good afternoon!','Good evening!','Good night!']);
  console.log('PASS: 24 greeting hours, greeting helper boundaries and reference greeting.');
  await wait("document.querySelectorAll('.deadline-card').length === 3");
  assert.equal(await evaluate("[...document.querySelectorAll('#deadline-cards .deadline-card')].every(card=>card.dataset.status==='unknown')"),true);
  await click('#deadline-inputs summary');
  await evaluate("document.querySelector('#deadline-visa-expiry').focus()");
  assert.equal(await evaluate("document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineStyle === 'solid'"),true);
  await evaluate("(()=>{const f=document.querySelector('#deadline-form');Object.entries({student_category:'foreign_student',entry_regime:'visa_required',residence:'university_dormitory',visa_type:'multiple_entry',age_category:'adult',visa_expiry:'2026-10-30',new_visa_received:'2026-09-29',entry_date:'2026-09-01',medical_completed_at:'2026-09-01',medical_valid_until:'2026-10-30'}).forEach(([key,value])=>f.elements[key].value=value);})()");
  await evaluate("document.querySelector('#medical-confirmed').checked=true");
  await click('#deadline-save');
  await wait("document.querySelector('[data-rule-id=\"rudn.registration_new_visa\"]')?.textContent.includes('02.10.2026') && !document.querySelector('#deadline-save').disabled");
  assert.equal(await evaluate("document.querySelector('[data-rule-id=\"rudn.visa_extension\"]').dataset.status"),'urgent');
  assert.equal(await evaluate("document.querySelector('[data-rule-id=\"rudn.visa_extension\"]').textContent.includes('Источники РУДН расходятся')"),false);
  await click('[data-rule-id="rudn.registration_new_visa"] button');
  assert.equal(await evaluate("document.querySelectorAll('#deadline-detail-body li').length"),6);
  assert.equal(await evaluate("document.querySelector('#deadline-detail-body a').href"),'https://handbook.rudn.ru/help/mfc.html');
  await screenshot('mobile-deadline-source');
  await click('#deadline-close');
  await reloadPage();
  await wait("document.querySelector('[data-rule-id=\"rudn.registration_new_visa\"]')?.textContent.includes('02.10.2026')");
  assert.equal(await evaluate("document.querySelector('#deadline-form').elements.new_visa_received.value"),'2026-09-29');
  await evaluate("document.querySelector('#deadline-section').scrollIntoView()");
  await screenshot('mobile-deadlines');
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"),true);
  await click('#deadline-inputs summary');
  await evaluate("document.querySelector('#deadline-form').elements.new_visa_received.value='2026-09-21'");
  await click('#deadline-save');
  await wait("document.querySelector('[data-rule-id=\"rudn.registration_new_visa\"]').dataset.status==='overdue'");
  assert.equal(await evaluate("document.querySelector('[data-rule-id=\"rudn.registration_new_visa\"] button').textContent"),'Что делать');
  assert.equal(await evaluate("document.querySelector('#deadline-regime').disabled"),true);
  assert.equal(await evaluate("[...document.querySelector('#deadline-regime').options].some(o=>o.value==='visa_free')"),false);
  assert.equal(await evaluate("!!document.querySelector('[data-rule-id=\"rudn.stay_extension\"]')"),false);
  assert.equal(await evaluate("document.querySelector('#medical-completed').value"),'2026-09-01');
  assert.equal(await evaluate("document.querySelector('#medical-valid').value"),'2026-10-30');
  assert.equal(await evaluate("document.querySelector('#medical-deadline-cards').textContent.includes('31 календарных дней')"),true);
  assert.equal(await evaluate("document.querySelectorAll('.document-card').length"),5);
  const savedPlan=await (await fetch(base+'/api/deadlines/state')).json();
  assert.equal(savedPlan.context.entry_regime,'visa_required');
  const overridden=await (await fetch(base+'/api/deadlines/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...savedPlan.context,entry_regime:'visa_free'})})).json();
  assert.equal(overridden.entry_regime,'visa_required');
  assert.equal(overridden.procedures.some(row=>row.procedure_type==='stay_extension'),false);
  const otherUniversity=await (await fetch(base+'/api/deadlines/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...savedPlan.context,university_id:'msu'})})).json();
  assert.equal(otherUniversity.procedures.length,0);
  const invalidPlan=await fetch(base+'/api/deadlines/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...savedPlan.context,visa_expiry:'not-a-date'})});
  assert.equal(invalidPlan.status,422);
  assert.equal((await invalidPlan.text()).includes('not-a-date'),false);
  await click('#deadline-inputs summary');
  await evaluate('window.scrollTo(0,0)');
  console.log('PASS: visa deadline, TKM mapping, medical persistence, official source, category checklist, save/refresh, overdue, entry regimes, university isolation, private validation.');
  assert.equal(await evaluate("!!document.querySelector('#medical-file-type, #medical-type-field')"),false);
  await click('.medical-view');
  assert.equal(await evaluate("document.querySelectorAll('.medical-file').length"),3);
  assert.equal(await evaluate("document.querySelectorAll('.medical-slot-add').length"),3);
  assert.equal(await evaluate("document.querySelector('#medical-files-dialog').textContent.includes('Другой медицинский документ')"),false);
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
  assert.equal(await evaluate("document.querySelector('#medical-files-dialog').classList.contains('naviar-dialog')"),true);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#medical-files-close')).backgroundImage.includes('linear-gradient')"),true);
  await screenshot('medical-0-of-3');
  await screenshot('blue-medical-desktop','jpeg');
  for(const width of [320,440]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:956,deviceScaleFactor:1,mobile:true});
    assert.equal(await evaluate("document.querySelector('#medical-files-dialog').scrollWidth<=document.querySelector('#medical-files-dialog').clientWidth"),true);
  }
  await screenshot('blue-medical-mobile');
  await click('#medical-files-close');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  const medicalJpeg=await evaluate("(()=>{const c=document.createElement('canvas');c.width=16;c.height=16;return c.toDataURL('image/jpeg').split(',')[1];})()");
  await writeFile(path.join(output,'naviar-ui-demo.jpg'),Buffer.from(medicalJpeg,'base64'));
  await upload('medical_certificates','naviar-ui-demo.pdf',0,medicalSlots[0]);
  assert.equal(await evaluate("document.querySelector('.medical-count').textContent"),'1/3');
  await upload('medical_certificates','naviar-ui-demo.png',0,medicalSlots[1]);
  assert.equal(await evaluate("document.querySelector('.medical-count').textContent"),'2/3');
  await upload('medical_certificates','naviar-ui-demo.jpg',1,medicalSlots[2]);
  await reloadPage();
  await wait("document.querySelector('.medical-count')?.textContent === '3/3'");
  assert.equal(await evaluate("document.querySelector('.count').textContent"),'1 / 5');
  await click('.medical-view');
  assert.equal(await evaluate("document.querySelectorAll('.medical-file[data-file-id]').length"),3);
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
  await screenshot('medical-3-of-3');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate("document.querySelector('#medical-files-dialog').scrollWidth <= document.querySelector('#medical-files-dialog').clientWidth"),true);
  await screenshot('medical-3-of-3-mobile');
  const oldMedical=await evaluate("document.querySelector('.medical-file').dataset.fileId");
  const medicalView=await evaluate("document.querySelector('.medical-file a').href");
  assert.equal((await fetch(medicalView)).status,200);
  await click('.medical-file summary');
  await evaluate("(()=>{const f=document.querySelector('.medical-date-form');f.elements.issue_date.value='2026-09-01';f.elements.valid_until.value='2026-10-30';f.requestSubmit();})()");
  await wait("document.querySelector('#document-toast').textContent==='Даты сохранены'");
  await click('#medical-files-close');
  await reloadPage();
  await wait("document.querySelector('.medical-count')?.textContent==='3/3'");
  await click('.medical-view');
  assert.equal(await evaluate("document.querySelector('.medical-date-form').elements.issue_date.value"),'2026-09-01');
  assert.equal(await evaluate("document.querySelector('.medical-date-form').elements.valid_until.value"),'2026-10-30');
  await click('.medical-file-update');
  await selectFile('naviar-ui-demo.png');
  await wait("!document.querySelector('#file-preview').hidden && document.querySelector('#file-preview').naturalWidth>0");
  await click('#upload-submit');
  await wait("!document.querySelector('#upload-dialog').open");
  assert.equal((await fetch(base+'/api/documents/medical_certificates/'+oldMedical+'/file')).status,404);
  await click('.medical-view');
  assert.equal(await evaluate("document.querySelectorAll('.medical-file[data-file-id]').length"),3);
  await click('[data-slot="medical_infectious_diseases_certificate"] .medical-file-delete');
  await wait("document.querySelector('.medical-count').textContent==='2/3'");
  assert.equal(await evaluate("document.querySelector('.count').textContent"),'0 / 5');
  assert.equal(await evaluate("document.querySelectorAll('.medical-file').length"),3);
  await click('.medical-file-delete');
  await wait("document.querySelector('.medical-count').textContent==='1/3'");
  await click('.medical-file-delete');
  await wait("document.querySelector('.medical-count').textContent==='0/3'");
  await click('#medical-files-close');
  console.log('PASS: fixed medical slots, no dropdown, 0/3–3/3, independent files/dates, persistence, preview, view, replacement, deletion.');

  await click('[data-document-type="passport"] button');
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.file-picker')).outlineColor"),'rgb(69, 140, 255)');
  assert.equal(await evaluate("document.querySelector('#upload-submit').disabled"),true);
  await screenshot('mobile-upload-empty');
  await screenshot('blue-upload-mobile');
  await selectFile('naviar-ui-demo.png');
  await wait("!document.querySelector('#file-preview').hidden && document.querySelector('#file-preview').naturalWidth > 0");
  assert.equal(await evaluate("document.querySelector('#selected-file-name').textContent"), 'naviar-ui-demo.png');
  await screenshot('mobile-upload-preview');
  await click('#remove-selection');
  assert.equal(await evaluate("document.querySelector('#selected-file').hidden && document.querySelector('#upload-submit').disabled"), true);
  await selectFile('naviar-ui-demo.png');
  await click('#cancel-upload');
  await wait("!document.querySelector('#upload-dialog').open");
  await upload('passport', 'naviar-ui-demo.png', 1);
  assert.equal(await evaluate("document.querySelector('#document-toast').textContent"), 'Документ добавлен');

  // Manual passport confirmation: required fields, dates, cancel, view and edit.
  assert.equal(await evaluate("document.querySelector('[data-document-type=\"passport\"] .document-verification-note').textContent"), 'Статус: Требуется проверка');
  assert.equal(await evaluate("document.querySelector('#next-action-title').textContent"), 'Проверьте данные документов');
  await click('#next-action-button');
  await wait("!document.querySelector('#passport-form').hidden");
  assert.equal(await evaluate("document.querySelectorAll('#passport-form input').length"), 8);
  await screenshot('mobile-passport-form-empty');
  await click('#passport-confirm');
  assert.equal(await evaluate("document.querySelectorAll('#passport-form [aria-invalid=\"true\"]').length"), 7);
  const fictional = {last_name:'Фиктивная',first_name:'Демо',middle_name:'',citizenship:'Тестовая страна',passport_number:'TEST-0000',birth_date:'2000-01-01',issue_date:'2020-01-01',expiry_date:'2030-01-01'};
  async function fillPassport(data) {
    await evaluate('Object.entries(' + JSON.stringify(data) + ').forEach(([name,value])=>{const input=document.querySelector("#passport-form").elements[name];input.value=value;input.dispatchEvent(new Event("input",{bubbles:true}));})');
  }
  await fillPassport({...fictional,birth_date:'2099-01-01'});
  await click('#passport-confirm');
  assert.equal(await evaluate("document.querySelector('#passport-birth_date').getAttribute('aria-invalid')"), 'true');
  await fillPassport({...fictional,issue_date:'2099-01-01'});
  await click('#passport-confirm');
  assert.equal(await evaluate("document.querySelector('#passport-issue_date').getAttribute('aria-invalid')"), 'true');
  await fillPassport({...fictional,expiry_date:'2020-01-01'});
  await click('#passport-confirm');
  assert.equal(await evaluate("document.querySelector('#passport-expiry_date').getAttribute('aria-invalid')"), 'true');
  assert.equal((await (await fetch(base + '/api/documents/passport/data')).json()).data, null);
  await click('#passport-cancel');
  await wait("!document.querySelector('#passport-dialog').open");
  await click('[data-document-type="passport"] .verify-document');
  await wait("!document.querySelector('#passport-form').hidden");
  assert.equal(await evaluate("document.querySelector('#passport-first_name').value"), '');

  // Exercise the actual dialog renderer with isolated response fixtures.
  // No OCR state or document data is written to the backend by these checks.
  const ocrMessages = {
    success: 'Данные распознаны. Проверьте каждое поле перед подтверждением.',
    partial: 'Часть данных распознана. Заполните или исправьте недостающие поля.',
    unsupported_or_not_passport: 'Похоже, этот файл не является поддерживаемым международным паспортом. Загрузите страницу паспорта с машиночитаемой зоной или заполните данные вручную.',
    failed: 'Не удалось распознать документ. Попробуйте ещё раз или заполните данные вручную.',
  };
  for (const [status, expected] of Object.entries(ocrMessages)) {
    await click('#passport-cancel');
    await wait("!document.querySelector('#passport-dialog').open");
    const actual = await evaluate(`(async()=>{const original=documentUI.request;const response=await original('/api/documents/passport/data');response.document.status=${JSON.stringify(status)}==='failed'?'processing_error':'needs_confirmation';response.extraction={status:${JSON.stringify(status)}};try{documentUI.request=async(url,options)=>url==='/api/documents/passport/data'?response:original(url,options);await passportVerification.open(response.document);return document.querySelector('#passport-ocr-note').textContent;}finally{documentUI.request=original;}})()`);
    assert.equal(actual, expected);
  }
  await click('#passport-cancel');
  await wait("!document.querySelector('#passport-dialog').open");
  await click('[data-document-type="passport"] .verify-document');
  await wait("!document.querySelector('#passport-form').hidden");
  console.log('PASS: exact success/partial/error/unsupported OCR messages in the dialog.');

  if (process.env.NAVIAR_TEST_OCR === '1') {
    await fillPassport({last_name:'MANUAL-KEEP',issue_date:'2019-06-15'});
    await click('#passport-recognize');
    await wait("!document.querySelector('#passport-recognize').disabled && document.querySelector('#passport-passport_number').value === 'TEST00001'", 600);
    assert.equal(await evaluate("document.querySelector('#passport-last_name').value"), 'MANUAL-KEEP');
    assert.equal(await evaluate("document.querySelector('#passport-issue_date').value"), '2019-06-15');
    await click('#passport-recognize');
    await wait("!document.querySelector('#passport-recognize').disabled", 600);
    assert.equal(await evaluate("document.querySelector('#passport-last_name').value"), 'MANUAL-KEEP');
    assert.equal(await evaluate("document.querySelector('#passport-issue_date').value"), '2019-06-15');
    const draft = await (await fetch(base + '/api/documents/passport/data')).json();
    assert.equal(draft.document.status, 'needs_confirmation');
    assert.equal(draft.extraction.status, 'partial');
    assert.equal(draft.extraction.fields.passport_number.source, 'mrz');
    assert.equal(draft.data.issue_date, '2020-01-15');
    assert.equal(draft.extraction.fields.date_of_issue.needs_confirmation, true);
    await screenshot('mobile-ocr-prefill');
    await reloadPage();
    await wait("!!document.querySelector('.count') && document.querySelector('.count').textContent === '1 / 5'");
    await click('[data-document-type="passport"] .verify-document');
    await wait("!document.querySelector('#passport-form').hidden");
    assert.equal(await evaluate("document.querySelector('#passport-passport_number').value"), 'TEST00001');
    assert.equal(await evaluate("document.querySelector('#passport-birth_date').value"), '2000-01-01');
    console.log('PASS: real offline CPU OCR, partial prefill, typed values preserved, draft survives refresh, never auto-verified.');
  }

  await fillPassport(fictional);
  await screenshot('mobile-passport-form-filled');
  await click('#passport-confirm');
  await wait("!document.querySelector('#passport-dialog').open && document.querySelector('[data-document-type=\"passport\"] .document-status').textContent === '● Данные подтверждены'");
  assert.equal(await evaluate("document.querySelector('#document-toast').textContent"), 'Данные паспорта подтверждены');
  assert.equal(await evaluate("document.querySelector('.count').textContent"), '1 / 5');
  assert.equal(await evaluate("document.querySelector('#next-action-title').textContent"), 'Данные паспорта подтверждены');
  await click('[data-document-type="passport"] .verify-document');
  await wait("!document.querySelector('#passport-details').hidden");
  assert.equal(await evaluate("document.querySelector('#passport-details dd').textContent"), fictional.last_name);
  await click('#passport-edit');
  assert.equal(await evaluate("document.querySelector('#passport-first_name').value"), fictional.first_name);
  await fillPassport({...fictional, first_name:'ОтменённоеИзменение'});
  await click('#passport-cancel');
  await wait("!document.querySelector('#passport-dialog').open");
  assert.equal((await (await fetch(base + '/api/documents/passport/data')).json()).data.first_name, fictional.first_name);
  await click('[data-document-type="passport"] .verify-document');
  await wait("!document.querySelector('#passport-details').hidden");
  await click('#passport-edit');
  await fillPassport({...fictional,first_name:'Редактировано'});
  await click('#passport-confirm');
  await wait("!document.querySelector('#passport-dialog').open");
  assert.equal((await (await fetch(base + '/api/documents/passport/data')).json()).data.first_name, 'Редактировано');
  assert.equal(await evaluate("Object.keys(localStorage).some(key => key !== 'naviar.student.profile.v1')"), false);
  assert.equal(await evaluate("JSON.stringify(localStorage).includes('TEST-0000')"), false);

  await upload('visa', 'naviar-ui-demo.pdf', 2);
  await reloadPage();
  await wait("!!document.querySelector('.count') && document.querySelector('.count').textContent === '2 / 5'");
  assert.equal(await evaluate("document.querySelectorAll('.document-status').length"), 2);

  assert.equal(await evaluate("document.querySelector('[data-document-type=\"passport\"] .document-status').textContent"), '● Данные подтверждены');
  assert.equal(await evaluate("document.querySelector('[data-document-type=\"visa\"] .document-verification-note').textContent"), 'Статус: Требуется проверка');
  assert.equal(await evaluate("document.querySelector('#next-action-title').textContent"), 'Проверьте данные документов');
  assert.equal(await evaluate("document.querySelector('#next-action-button').hidden"), true);
  assert.equal(await evaluate("document.querySelector('#next-action-note').textContent.includes('Проверка остальных документов')"), true);
  await click('[data-document-type="passport"] .verify-document');
  await wait("!document.querySelector('#passport-details').hidden");
  assert.equal(await evaluate("document.querySelectorAll('#passport-details dd')[1].textContent"), 'Редактировано');
  await screenshot('mobile-passport-details');
  await send('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await screenshot('desktop-passport-details');
  await click('#passport-edit');
  await screenshot('desktop-passport-form');
  await click('#passport-cancel');
  await wait("!document.querySelector('#passport-dialog').open");
  await send('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});

  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true);
  await screenshot('mobile-dashboard');
  await upload('migration_card', 'naviar-ui-demo.png', 3);
  const jpegData = await evaluate("(()=>{const canvas=document.createElement('canvas');canvas.width=16;canvas.height=16;const ctx=canvas.getContext('2d');ctx.fillStyle='#eaf0e9';ctx.fillRect(0,0,16,16);return canvas.toDataURL('image/jpeg').split(',')[1];})()");
  await writeFile(path.join(output, 'naviar-ui-demo.jpg'), Buffer.from(jpegData, 'base64'));
  await upload('registration', 'naviar-ui-demo.jpg', 4);
  await upload('medical_certificates','naviar-ui-demo.pdf',4,medicalSlots[0]);
  await upload('medical_certificates','naviar-ui-demo.png',4,medicalSlots[1]);
  await upload('medical_certificates','naviar-ui-demo.jpg',5,medicalSlots[2]);
  await click('.medical-view');
  await click('.medical-file-delete');
  await wait("document.querySelector('.count').textContent==='4 / 5'");
  await click('#medical-files-close');
  await upload('medical_certificates','naviar-ui-demo.pdf',5,medicalSlots[0]);
  assert.equal(await evaluate("document.querySelector('.count').textContent"),'5 / 5');
  await screenshot('mobile-five-documents');
  assert.equal(await (await fetch(base + '/api/documents/passport/file')).arrayBuffer().then(buffer => buffer.byteLength), png.length);
  await send('Emulation.setDeviceMetricsOverride', {width:1280, height:900, deviceScaleFactor:1, mobile:false});
  await evaluate('window.scrollTo(0,0)');
  await screenshot('desktop-dashboard');
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.document-grid')).gridTemplateColumns.split(' ').length"),5);
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"),true);
  await click('[data-document-type="passport"] .document-actions a');
  let viewer;
  for (let attempt=0;attempt<40;attempt++) {
    const opened=await (await fetch('http://127.0.0.1:'+debugPort+'/json/list')).json();
    viewer=opened.find(item=>item.url === base+'/api/documents/passport/file');
    if(viewer) break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(viewer, 'View action opens the uploaded file');
  await send('Target.closeTarget',{targetId:viewer.id});
  let count = 5;
  for (const kind of ['passport', 'visa', 'migration_card', 'registration', 'medical_certificates']) {
    if(kind==='medical_certificates') {
      await click('.medical-view');
      for(let remaining=2;remaining>=0;remaining--) {
        await click('.medical-file-delete');
        await wait("document.querySelectorAll('.medical-file[data-file-id]').length==="+remaining);
      }
    } else await click('[data-document-type="' + kind + '"] .document-actions button:not(.verify-document)');
    await wait("document.querySelector('.count').textContent === '" + (--count) + " / 5'");
  }
  await click('#medical-files-close');
  await reloadPage();
  await wait("!!document.querySelector('.count') && document.querySelector('.count').textContent === '0 / 5'");
  await click('[data-document-type="passport"] button');
  await screenshot('desktop-upload-empty');
  await screenshot('blue-upload-desktop','jpeg');
  await click('#cancel-upload');
  assert.deepEqual(browserErrors, []);
  assert.equal(await evaluate("document.querySelector('#next-action-text').textContent"), 'Добавьте документы, чтобы NAVIAR мог определить важные сроки и следующие действия.');
  assert.equal((await fetch(base + '/api/documents/passport/data')).status, 404);
  if (process.env.NAVIAR_TEST_OCR === '1') {
    await upload('passport', 'naviar-ui-demo.jpg', 1);
    await click('[data-document-type="passport"] .verify-document');
    await wait("!document.querySelector('#passport-form').hidden");
    await click('#passport-recognize');
    await wait("!document.querySelector('#passport-recognize').disabled && document.querySelector('#passport-ocr-note').textContent.includes('не является поддерживаемым')", 600);
    assert.equal(await evaluate("document.querySelector('#passport-last_name').value"), '');
    await fillPassport(fictional);
    await click('#passport-confirm');
    await wait("!document.querySelector('#passport-dialog').open");
    assert.equal((await (await fetch(base + '/api/documents/passport/data')).json()).document.status, 'verified');
    await click('[data-document-type="passport"] .document-actions button:not(.verify-document)');
    await wait("document.querySelector('.count').textContent === '0 / 5'");
    console.log('PASS: unsupported image message and manual confirmation fallback; repeated OCR preserves manual issue date.');
  }
  await send('Page.navigate',{url:base});
  await wait("document.querySelector('#student-guidance') && !document.querySelector('#student-guidance').hidden && document.querySelector('.count').textContent==='0 / 5'");
  assert.equal(await evaluate("document.querySelector('#deadline-section').hidden"),true);
  assert.equal(await evaluate("document.querySelector('#deadline-inputs').getClientRects().length"),0);
  assert.equal(await evaluate("document.querySelector('.medical-add').textContent"),'+ Добавить сертификаты');
  assert.equal(await evaluate("document.querySelector('[data-student-document=visa]').textContent.includes('Нужна дата окончания визы')"),true);
  // Visa flow: same synthetic layout through fake provider or installed local OCR.
  if(process.env.NAVIAR_TEST_OCR==='1') await writeFile(path.join(output,'naviar-ui-demo.png'),await readFile(path.resolve('.document-lab/fixtures/synthetic-visa.png')));
  await upload('visa','naviar-ui-demo.png',1);
  await click('[data-student-document=visa] button');
  await wait("document.querySelector('#visa-dialog').open && !document.querySelector('#visa-recognize').disabled");
  await evaluate("document.querySelector('#visa-visa_number').value='MANUAL0001'");
  await click('#visa-recognize');
  await wait("!document.querySelector('#visa-recognize').disabled && document.querySelector('#visa-valid_until').value==='2026-10-30'",900);
  assert.equal(await evaluate("document.querySelector('#visa-visa_number').value"),'MANUAL0001');
  assert.equal(await evaluate("document.querySelector('#visa-issue_date').value"),'2026-09-15');
  assert.equal(await evaluate("document.querySelector('#visa-valid_from').value"),'2026-09-16');
  assert.equal(await evaluate("document.querySelector('#visa-entries').value"),'multiple');
  assert.equal(await evaluate("document.querySelector('#visa-visa_type').value"),'student');
  assert.equal(await evaluate("document.querySelector('[data-student-document=visa]').textContent.includes('02.10.2026')"),false);
  await evaluate("document.querySelector('#visa-issue_date').value='2026-09-14'");
  await click('#visa-recognize');
  await wait("!document.querySelector('#visa-recognize').disabled",900);
  assert.equal(await evaluate("document.querySelector('#visa-issue_date').value"),'2026-09-14');
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
  await screenshot('visa-confirmation-desktop');
  await screenshot('blue-visa-desktop','jpeg');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await evaluate("document.querySelector('#visa-dialog').scrollWidth<=document.querySelector('#visa-dialog').clientWidth"),true);
  await screenshot('visa-confirmation-mobile');
  await screenshot('blue-visa-mobile');
  await click('#visa-confirm');
  await wait("!document.querySelector('#visa-dialog').open && document.querySelector('[data-student-document=visa]').textContent.includes('02.10.2026')");
  assert.equal(await evaluate("document.querySelector('[data-document-type=visa] .document-status').textContent"),'● Данные подтверждены');
  assert.equal(await evaluate("document.querySelector('#student-next-actions').textContent.includes('Подать документы на продление визы')"),true);
  await reloadPage();
  await wait("document.querySelector('[data-student-document=visa]')?.textContent.includes('02.10.2026')");
  const student=await (await fetch(base+'/api/student/context')).json();
  assert.equal(student.context.citizenship.value,'TKM');
  assert.equal(student.context.entry_regime.value,'visa_required');
  assert.equal(student.context.visa.expiry_date.source,'visa_ocr');
  assert.equal(student.context.visa.visa_number.source,'manual_confirmed');
  assert.equal(student.context.visa.issue_date.value,'2026-09-14');
  assert.equal(student.context.visa.confirmed.value,true);
  assert.equal(student.context.visa.expiry_date.confirmed,true);
  // Reference dashboard: isolated demo data, real counters, responsive shell and unchanged actions.
  assert.equal(await evaluate("document.querySelector('#dashboard-percentage').textContent"),'20%');
  assert.equal(await evaluate("(()=>{dashboardUI.updateProgress(false,true);const value=document.querySelector('#dashboard-document-total').textContent;documentUI.render();return value;})()"),'Документы недоступны');
  for (const [kind, count] of [['passport',2],['migration_card',3],['registration',4]]) {
    await upload(kind,'naviar-ui-demo.pdf',count);
  }
  await wait("document.querySelector('#dashboard-percentage').textContent==='80%' && !!document.querySelector('.primary-action')");
  const dashboardContext=await (await fetch(base+'/api/student/context')).json();
  assert.equal(await evaluate("document.querySelector('#dashboard-next-summary').textContent"),dashboardContext.next_actions[0].title);
  assert.equal(await evaluate("document.querySelector('.primary-action h3').textContent"),dashboardContext.next_actions[0].title);
  assert.equal(await evaluate("document.querySelectorAll('#document-cards .document-icon').length"),5);
  assert.equal(await evaluate("new Set([...document.querySelectorAll('#document-cards .document-icon')].map(icon=>icon.innerHTML)).size"),5);
  assert.equal(await evaluate("document.querySelector('#dashboard-document-total').textContent"),'Добавлено 4 из 5 категорий');
  assert.equal(await evaluate("document.querySelector('#dashboard-progress').getAttribute('aria-valuenow')"),'80');
  for (const width of [320,390,440,768,1100,1440]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:956,deviceScaleFactor:1,mobile:width<600});
    assert.equal(await evaluate("document.documentElement.scrollWidth<=window.innerWidth"),true,'No horizontal overflow at '+width);
    if(width<600) assert.equal(await evaluate("getComputedStyle(document.querySelector('.document-grid')).gridTemplateColumns.split(' ').length"),width<=360?2:3);
  }
  await evaluate('window.scrollTo(0,0)');
  await wait("document.querySelector('#document-toast').hidden");
  await wait("[...document.querySelectorAll('#dashboard img')].every(image=>image.complete && image.naturalWidth>0)");
  assert.equal(await evaluate("document.querySelector('.assistant-illustration').getBoundingClientRect().width<=120"),true);
  await screenshot('reference-desktop-1440');
  const desktopJpeg=await send('Page.captureScreenshot',{format:'jpeg',quality:82,captureBeyondViewport:false});
  await writeFile(path.join(output,'reference-desktop-1440.jpg'),Buffer.from(desktopJpeg.data,'base64'));
  const desktopLayout=await send('Page.getLayoutMetrics');
  const desktopCapture=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1440,height:desktopLayout.cssContentSize.height,scale:1}});
  await writeFile(path.join(output,'reference-desktop-full.png'),Buffer.from(desktopCapture.data,'base64'));
  assert.equal(await evaluate("document.querySelector('.bottom-nav').getBoundingClientRect().width"),208);
  assert.equal(await evaluate("document.querySelector('.assistant-card').getBoundingClientRect().left > document.querySelector('.dashboard-overview').getBoundingClientRect().right"),true);
  await send('Emulation.setDeviceMetricsOverride',{width:440,height:956,deviceScaleFactor:1,mobile:true});
  await evaluate('window.scrollTo(0,0)');
  await screenshot('reference-mobile-440');
  await evaluate("document.querySelector('#student-guidance').scrollIntoView({block:'start'})");
  await screenshot('reference-mobile-deadlines-assistant');
  await evaluate('window.scrollTo(0,0)');
  const full=await send('Page.getLayoutMetrics');
  const capture=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:440,height:full.cssContentSize.height,scale:1}});
  await writeFile(path.join(output,'reference-mobile-full.png'),Buffer.from(capture.data,'base64'));
  await click('[data-document-type=passport] .document-menu summary');
  assert.equal(await evaluate("document.querySelector('[data-document-type=passport] .document-menu').open"),true);
  assert.equal(await evaluate("(()=>{const box=document.querySelector('[data-document-type=passport] .document-menu-content').getBoundingClientRect();return box.left>=0 && box.right<=innerWidth;})()"),true);
  await click('[data-document-type=passport] .document-menu summary');
  await reloadPage();
  await wait("document.querySelector('#dashboard-percentage').textContent==='80%'");
  await click('.primary-action button');
  await wait("document.querySelector('#deadline-dialog').open");
  await click('#deadline-close');
  await click('.deadlines-nav');
  assert.equal(await evaluate("(()=>{const box=document.querySelector('#student-guidance').getBoundingClientRect();return box.top>=0 && box.top<innerHeight-document.querySelector('.bottom-nav').offsetHeight;})()"),true);
  await click('#ask-assistant');
  assert.equal(await evaluate("document.querySelector('#message-dialog').open"),true);
  await click('#close-dialog');
  for(const kind of ['passport','migration_card','registration']) {
    await click('[data-document-type="'+kind+'"] .document-actions button:not(.verify-document)');
    await wait("!document.querySelector('[data-document-type=\""+kind+"\"] .document-status')");
  }
  await wait("document.querySelector('#dashboard-percentage').textContent==='20%'");
  console.log('PASS: Reference dashboard responsive shell (320–1440), 5 icons, live percentage, priority, navigation, assistant preview and refresh.');
  await screenshot('student-dashboard');
  await evaluate("document.querySelector('.next-step').scrollIntoView({block:'start'})");
  await screenshot('student-next-actions');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("document.querySelector('#student-guidance').scrollIntoView({block:'start'})");
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"),true);
  await screenshot('student-guidance-mobile');
  await click('[data-document-type="visa"] .document-actions button:not(.verify-document)');
  await wait("document.querySelector('.count').textContent==='0 / 5'");
  if(process.env.NAVIAR_TEST_VISA_SPECIMEN==='1') {
    const provenance=JSON.parse(await readFile(path.resolve('.document-lab/fixtures/russian-public-visa.provenance.json'),'utf8'));
    await writeFile(path.join(output,'naviar-ui-demo.jpg'),await readFile(path.resolve('.document-lab/fixtures/russian-public-visa.jpg')));
    await upload('visa','naviar-ui-demo.jpg',1);
    await click('[data-document-type=visa] .verify-document');
    await wait("document.querySelector('#visa-dialog').open && !document.querySelector('#visa-recognize').disabled");
    await click('#visa-recognize');
    await wait("!document.querySelector('#visa-recognize').disabled && document.querySelector('#visa-ocr-note').textContent.includes('Виза распознана частично')",1200);
    assert.equal(await evaluate("document.querySelector('#visa-visa_number').value"),provenance.expected_fields.visa_number);
    assert.equal(await evaluate("document.querySelector('#visa-valid_until').value"),'');
    const draft=await (await fetch(base+'/api/documents/visa/data')).json();
    assert.equal(draft.extraction.processing_status,'supported_partial');
    assert.equal(draft.document.status,'needs_confirmation');
    assert.equal(draft.extraction.extracted_fields.visa_number.needs_confirmation,true);
    assert.equal('detection' in draft.extraction,false);
    await screenshot('visa-public-partial-mobile');
    await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
    await screenshot('visa-public-partial-desktop');
    await evaluate("document.querySelector('#visa-visa_number').value='DEMO-CORRECTED';document.querySelector('#visa-valid_until').value='2026-10-30'");
    await click('#visa-confirm');
    await wait("!document.querySelector('#visa-dialog').open && document.querySelector('[data-student-document=visa]').textContent.includes('02.10.2026')");
    await reloadPage();
    await wait("document.querySelector('[data-student-document=visa]')?.textContent.includes('02.10.2026')");
    const confirmed=await (await fetch(base+'/api/student/context')).json();
    assert.equal(confirmed.context.visa.visa_number.value,'DEMO-CORRECTED');
    assert.equal(confirmed.context.visa.visa_number.source,'manual_confirmed');
    assert.equal(confirmed.context.visa.valid_until.source,'manual_confirmed');
    assert.equal(confirmed.context.visa.confirmed.value,true);
    await click('[data-document-type=visa] .document-actions button:not(.verify-document)');
    await wait("document.querySelector('.count').textContent==='0 / 5'");
    // Restore the unrelated blank JPG used by the unsupported regression.
    await writeFile(path.join(output,'naviar-ui-demo.jpg'),Buffer.from(jpegData,'base64'));
    console.log('PASS: public visa specimen supported_partial, safe prefill, manual correction, deadline and persistence; diagnostics stay dev-only.');
  }
  await upload('visa','naviar-ui-demo.jpg',1);
  await click('[data-document-type=visa] .verify-document');
  await wait("document.querySelector('#visa-dialog').open && !document.querySelector('#visa-recognize').disabled");
  await click('#visa-recognize');
  await wait("!document.querySelector('#visa-recognize').disabled && document.querySelector('#visa-ocr-note').textContent.includes('не является поддерживаемой визой')",900);
  assert.equal(await evaluate("document.querySelector('#visa-valid_until').value"),'');
  await evaluate("document.querySelector('#visa-valid_until').value='2026-10-30'");
  await click('#visa-confirm');
  await wait("!document.querySelector('#visa-dialog').open");
  await click('[data-document-type=visa] .document-actions button:not(.verify-document)');
  await wait("document.querySelector('.count').textContent==='0 / 5'");
  console.log('PASS: visa OCR prefill, repeated OCR/manual override, confirmation, automatic deadline, refresh, unsupported fallback, mobile/desktop.');
  await upload('medical_certificates','naviar-ui-demo.png',0,medicalSlots[0]);
  assert.equal(await evaluate("document.querySelector('.medical-add').textContent"),'Продолжить загрузку');
  await upload('medical_certificates','naviar-ui-demo.png',0,medicalSlots[1]);
  assert.equal(await evaluate("document.querySelector('.medical-add').textContent"),'Продолжить загрузку');
  await upload('medical_certificates','naviar-ui-demo.png',1,medicalSlots[2]);
  assert.equal(await evaluate("document.querySelector('.medical-add').textContent"),'Управлять');
  await click('.medical-view');
  for(let remaining=2;remaining>=0;remaining--) { await click('.medical-file-delete');await wait("document.querySelectorAll('.medical-file[data-file-id]').length==="+remaining); }
  await click('#medical-files-close');
  assert.deepEqual(browserErrors,[]);
  console.log('PASS: normal dashboard hides debug form, visa confirmation, automatic deadline/NextAction, context sources, refresh and medical button states.');
  console.log('PASS: passport form, required fields, dates, confirm, view, edit, cancel, reload, status, dynamic guidance, no passport localStorage;');
  console.log('PASS: selection, preview, remove, cancel, PNG/PDF uploads, count 0–5, reload persistence, viewing endpoint, deletion, mobile layout, no browser exceptions.');
} catch (failure) {
  console.error(await evaluate("JSON.stringify({visaNote:document.querySelector('#visa-ocr-note').textContent,visaError:document.querySelector('#visa-error').textContent,uploadError:document.querySelector('#upload-error').textContent,uploadOpen:document.querySelector('#upload-dialog').open,submitDisabled:document.querySelector('#upload-submit').disabled,count:document.querySelector('.count').textContent})"));
  await screenshot('browser-failure');
  throw failure;
} finally {
  const current = await (await fetch(base + '/api/documents')).json();
  for (const record of current) {
    if (record.name.startsWith('naviar-ui-demo.')) await fetch(base + '/api/documents/' + record.type + (record.type==='medical_certificates'?'/'+record.document_id:''), {method:'DELETE'});
  }
  await send('Browser.close');
  socket.close();
}
