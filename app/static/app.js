const storageKey = 'naviar.student.profile.v1';
const choices = {
  citizenship: [['tm', 'Туркменистан', 'Turkmenistan'], ['uz', 'Узбекистан', 'Uzbekistan'], ['tj', 'Таджикистан', 'Tajikistan'], ['kg', 'Кыргызстан', 'Kyrgyzstan'], ['kz', 'Казахстан', 'Kazakhstan'], ['other', 'Другое', 'Other']],
  university: [['rudn', 'РУДН', 'RUDN University'], ['msu', 'МГУ', 'Moscow State University'], ['hse', 'ВШЭ', 'HSE University'], ['spbu', 'СПбГУ', 'Saint Petersburg State University'], ['other', 'Другой университет', 'Other university']],
  degree: [['bachelor', 'Бакалавриат', 'Bachelor’s degree'], ['master', 'Магистратура', 'Master’s degree'], ['phd', 'Аспирантура', 'Postgraduate studies'], ['preparatory', 'Подготовительный факультет', 'Preparatory faculty']],
};
const english = {
  intro: 'A new country. A clear next step.', studentSpace: 'Your space for studying and living in Russia', setupLabel: 'PROFILE SETUP', welcome: 'Welcome!', welcomeText: 'Let’s set up your profile in a couple of minutes.', citizenship: 'Citizenship', university: 'University', degree: 'Level of study', language: 'App language', continue: 'Continue', localNote: 'Demo version. Your profile is stored on this computer.', space: 'YOUR STUDENT SPACE', greeting: 'Good afternoon!', documents: 'Your documents', nextStep: 'NEXT STEP', whatNow: 'What should I do now?', nextText: 'Add your documents so NAVIAR can identify important deadlines and next steps.', nearby: 'Help is always nearby', assistantText: 'Your future assistant in a new country.', ask: 'Ask NAVIAR', demoNote: 'Demo version · Use test documents only', home: 'Home', documentsNav: 'Documents', assistantNav: 'Assistant', profile: 'Profile', understood: 'Got it',
};
const russian = Object.fromEntries([...document.querySelectorAll('[data-i18n]')].map(element => [element.dataset.i18n, element.textContent]));
const form = document.querySelector('#profile-form');
let language = 'ru';
let profile = null;

function greetingForHour(hour, locale = language) {
  if (hour >= 5 && hour < 12) return locale === 'en' ? 'Good morning!' : 'Доброе утро!';
  if (hour >= 12 && hour < 18) return locale === 'en' ? 'Good afternoon!' : 'Добрый день!';
  if (hour >= 18 && hour < 23) return locale === 'en' ? 'Good evening!' : 'Добрый вечер!';
  return locale === 'en' ? 'Good night!' : 'Доброй ночи!';
}

function updateGreeting() {
  document.querySelector('[data-i18n="greeting"]').textContent = language === 'en' ? 'Hi, Resul!' : 'Привет, Ресул!';
}

// Keep an open dashboard current, including when returning to a background tab.
setInterval(updateGreeting, 60_000);
window.addEventListener('focus', updateGreeting);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) updateGreeting();
});

function showMessage(title, message) {
  document.querySelector('#message-title').textContent = title;
  document.querySelector('#message-text').textContent = message;
  document.querySelector('#message-dialog').showModal();
}

function showAssistant() {
  showMessage('NAVIAR AI', language === 'ru' ? 'AI-помощник появится на следующем этапе разработки.' : 'The AI assistant will arrive in the next development stage.');
}

function applyLanguage() {
  document.documentElement.lang = language;
  document.querySelector('.bottom-nav').setAttribute('aria-label', language === 'ru' ? 'Основная навигация' : 'Main navigation');
  document.querySelectorAll('[data-i18n]').forEach(element => {
    element.textContent = (language === 'en' ? english : russian)[element.dataset.i18n];
  });
  Object.entries(choices).forEach(([field, options]) => {
    const select = form.elements[field];
    const selectedValue = select.value;
    select.replaceChildren(new Option(language === 'ru' ? 'Выберите вариант' : 'Select an option', ''));
    select.options[0].disabled = true;
    options.forEach(option => select.add(new Option(option[language === 'ru' ? 1 : 2], option[0])));
    select.value = selectedValue;
  });
  updateGreeting();
  documentUI.render();
}

function validProfile(value) {
  return value && ['ru', 'en'].includes(value.language) && Object.entries(choices).every(([field, options]) => options.some(option => option[0] === value[field]));
}

function showDashboard() {
  language = profile.language;
  applyLanguage();
  document.querySelector('#onboarding').hidden = true;
  document.querySelector('#dashboard').hidden = false;
  const label = field => choices[field].find(option => option[0] === profile[field])[language === 'ru' ? 1 : 2];
  document.querySelector('#profile-summary').textContent = `${label('university')} · ${label('degree')}`;
  window.scrollTo(0, 0);
  deadlineUI.open(profile);
  studentUI.open(profile);
}

form.elements.language.addEventListener('change', () => {
  language = form.elements.language.value;
  applyLanguage();
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  const candidate = Object.fromEntries(new FormData(form));
  if (!validProfile(candidate)) return;
  try {
    await documentUI.request('/api/student/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(candidate)});
    document.querySelector('#storage-error').hidden = true;
  } catch {
    const error = document.querySelector('#storage-error');
    error.textContent = language === 'ru' ? 'Не удалось сохранить профиль. Проверьте соединение с локальным сервером.' : 'Could not save the profile. Check the local server connection.';
    error.hidden = false;
    return;
  }
  profile = candidate;
  showDashboard();
});
document.querySelector('#ask-assistant').addEventListener('click', showAssistant);
document.querySelector('#close-dialog').addEventListener('click', () => document.querySelector('#message-dialog').close());
document.querySelectorAll('[data-nav]').forEach(button => button.addEventListener('click', () => {
  switch (button.dataset.nav) {
    case 'home': window.scrollTo(0, 0); break;
    case 'documents': document.querySelector('#documents').scrollIntoView({block: 'start'}); break;
    case 'assistant': showAssistant(); break;
    case 'profile':
      document.querySelector('#dashboard').hidden = true;
      document.querySelector('#onboarding').hidden = false;
      Object.entries(profile).forEach(([key, value]) => { form.elements[key].value = value; });
      window.scrollTo(0, 0);
      form.elements.citizenship.focus({preventScroll: true});
      break;
  }
}));
function profileFields(value) {
  return Object.fromEntries(['citizenship','university','degree','language'].map(key=>[key,value[key]]));
}

async function restoreProfile() {
  try {
    const saved=await documentUI.request('/api/student/profile');
    if(validProfile(saved.profile)) profile=profileFields(saved.profile);
    if(!profile) {
      // One-time migration of the previous browser-only onboarding profile.
      let legacy=null;
      try {legacy=JSON.parse(localStorage.getItem(storageKey));} catch {}
      if(validProfile(legacy)) {
        profile=profileFields(legacy);
        await documentUI.request('/api/student/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
      }
    }
    if(profile) {
      try {localStorage.removeItem(storageKey);} catch {}
      showDashboard();
    } else applyLanguage();
  } catch {
    profile=null; applyLanguage();
    const error=document.querySelector('#storage-error'); error.hidden=false;
    error.textContent='Не удалось получить профиль. Проверьте соединение с локальным сервером.';
  }
}
restoreProfile();
