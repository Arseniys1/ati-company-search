'use strict';

const PAGE = 50;
const nf = new Intl.NumberFormat('ru-RU');

const state = {
  tab: 'companies',
  q: '',
  companies: [],
  companyHay: [],
  companyName: [],
  companyLoads: [],
  matches: [],
  companyOffset: 0,
  loadOffset: 0,
  loadTotal: 0,
  loadsReady: false,
  companyFilter: -1,
  selected: null,
  worker: null,
  reqId: 0,
  meta: null,
};

const el = {
  q: document.getElementById('q'),
  clear: document.getElementById('clear'),
  stats: document.getElementById('stats'),
  results: document.getElementById('results'),
  count: document.getElementById('result-count'),
  hint: document.getElementById('result-hint'),
  more: document.getElementById('more'),
  moreBtn: document.getElementById('more-btn'),
  detail: document.getElementById('detail'),
  note: document.getElementById('tab-note'),
  period: document.getElementById('period'),
};

/* ---------- helpers ---------- */

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);
}

function norm(value) {
  return String(value == null ? '' : value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();
}

function digits(value) {
  return String(value == null ? '' : value).replace(/\D+/g, '');
}

function tokensOf(query) {
  return norm(query).split(' ').filter(Boolean).map(token => {
    const num = digits(token);
    return num && num !== token ? [token, num] : [token];
  });
}

function matches(hay, forms) {
  for (const form of forms) {
    if (hay.includes(form)) return true;
  }
  return false;
}

function money(value) {
  return value ? nf.format(Math.round(value)) : '';
}

function num(value) {
  if (value == null || value === 0) return '';
  return nf.format(Math.round(value * 100) / 100);
}

function date(value) {
  if (!value) return '';
  const [y, m, d] = value.split('-');
  return `${d}.${m}.${y}`;
}

/* ---------- companies ---------- */

function prepareCompanies(list) {
  state.companies = list;
  state.companyHay = new Array(list.length);
  state.companyName = new Array(list.length);
  state.companyLoads = new Array(list.length);
  for (let i = 0; i < list.length; i++) {
    const c = list[i];
    const parts = [c.name, c.short, c.city, c.region, c.country, c.kind, c.id];
    for (const contact of c.contacts || []) {
      parts.push(contact.name, contact.email, contact.skype);
      for (const phone of contact.phones || []) parts.push(phone, digits(phone));
    }
    state.companyHay[i] = norm(parts.filter(Boolean).join(' '));
    state.companyName[i] = norm(c.name || c.short || '');
    state.companyLoads[i] = c.loads || 0;
  }
}

function searchCompanies(tokens) {
  const out = [];
  for (let i = 0; i < state.companyHay.length; i++) {
    const hay = state.companyHay[i];
    let ok = true;
    for (const forms of tokens) {
      if (!matches(hay, forms)) { ok = false; break; }
    }
    if (ok) out.push(i);
  }
  if (!tokens.length) {
    out.sort((a, b) => state.companyLoads[b] - state.companyLoads[a] || state.companyName[a].localeCompare(state.companyName[b]));
    return out;
  }
  const prefix = norm(state.q);
  const rank = index => {
    const name = state.companyName[index];
    if (name.startsWith(prefix)) return 0;
    if (name.includes(prefix)) return 1;
    return 2;
  };
  out.sort((a, b) => rank(a) - rank(b) || state.companyLoads[b] - state.companyLoads[a] ||
    state.companyName[a].localeCompare(state.companyName[b]));
  return out;
}

/* ---------- worker (loads) ---------- */

function startWorker() {
  const worker = new Worker('assets/worker.js');
  worker.onmessage = event => {
    const msg = event.data;
    if (msg.type === 'progress') {
      el.note.textContent = `Грузы: загрузка ${Math.round(msg.loaded / msg.total * 100)}%`;
    } else if (msg.type === 'ready') {
      state.loadsReady = true;
      el.note.textContent = '';
      if (state.tab === 'loads') runSearch();
    } else if (msg.type === 'error') {
      el.note.textContent = 'Грузы не загрузились';
    } else if (msg.type === 'results' && msg.reqId === state.reqId) {
      state.loadTotal = msg.total;
      if (msg.offset === 0) state.loadItems = msg.items;
      else state.loadItems = state.loadItems.concat(msg.items);
      renderLoads();
    }
  };
  worker.postMessage({
    type: 'init',
    url: new URL('data/loads.json', location.href).href,
    names: state.companies.map(c => c.name || c.short || ''),
  });
  state.worker = worker;
}

function askLoads(offset) {
  state.reqId += 1;
  state.loadOffset = offset;
  state.worker.postMessage({
    type: 'search',
    reqId: state.reqId,
    tokens: tokensOf(state.q),
    company: state.companyFilter,
    limit: PAGE,
    offset,
  });
}

/* ---------- rendering ---------- */

function renderStats() {
  const meta = state.meta || {};
  el.stats.textContent = `${nf.format(meta.companies || 0)} компаний · ${nf.format(meta.loads || 0)} грузов`;
  el.period.textContent = meta.from ? `Период логов: ${date(meta.from)} — ${date(meta.to)}` : '';
  document.getElementById('intro-stats').textContent =
    `Поиск работает по ${nf.format(meta.companies || 0)} компаниям и ${nf.format(meta.loads || 0)} грузам из логов запросов ATI.`;
}

function renderCompanyItem(index) {
  const c = state.companies[index];
  const rating = c.rating ? `<span class="badge ${c.rating >= 4 ? 'good' : ''}">рейтинг ${num(c.rating)}</span>` : '';
  const vip = c.vip ? '<span class="badge good">VIP</span>' : '';
  const phone = (c.contacts || []).flatMap(x => x.phones || [])[0] || '';
  const email = (c.contacts || []).map(x => x.email).filter(Boolean)[0] || '';
  const contact = phone || email || 'контакты не указаны';
  const place = [c.city, c.kind].filter(Boolean).join(' · ');
  const meta = [c.recs ? `рекомендаций: ${nf.format(c.recs)}` : '', c.loads ? `грузов: ${nf.format(c.loads)}` : '']
    .filter(Boolean).join(' · ');
  return `<button class="item${state.selected && state.selected.type === 'company' && state.selected.index === index ? ' active' : ''}" data-company="${index}">
    <div class="line1"><span class="name">${esc(c.name || c.short || 'Без названия')}</span>${rating}${vip}</div>
    <div class="line2">${esc(place)}</div>
    <div class="line3">${esc(contact)}${meta ? ' · ' + esc(meta) : ''}</div>
  </button>`;
}

function renderLoadItem(load, position) {
  const route = load.f || load.t ? `${load.f || '?'} → ${load.t || '?'}` : 'маршрут не указан';
  const company = state.companies[load.c];
  const companyName = company ? (company.name || company.short) : '';
  const details = [
    load.g,
    load.w ? `${num(load.w)} т` : '',
    load.v ? `${num(load.v)} м³` : '',
    load.p ? `ставка ${money(load.p)}` : '',
    load.d ? `${nf.format(load.d)} км` : '',
  ].filter(Boolean).join(' · ');
  return `<button class="item" data-load="${position}">
    <div class="line1"><span class="name">${esc(route)}</span><span class="date">${esc(date(load.a))}</span></div>
    <div class="line2">${esc(companyName)}</div>
    <div class="line3">${esc(details)}</div>
  </button>`;
}

function renderCompanies() {
  const total = state.matches.length;
  const shown = Math.min(state.companyOffset + PAGE, total);
  el.count.textContent = total ? `Найдено: ${nf.format(total)}` : '';
  el.hint.textContent = state.q ? '' : 'показаны компании с наибольшим числом грузов';
  el.results.innerHTML = state.matches.slice(state.companyOffset, shown).map(renderCompanyItem).join('') ||
    '<div class="loading">Ничего не найдено</div>';
  el.more.hidden = shown >= total;
}

function renderLoadsState(message, progress) {
  el.results.innerHTML = `<div class="loading">${esc(message)}${progress != null
    ? `<div class="bar"><span style="width:${Math.round(progress * 100)}%"></span></div>` : ''}</div>`;
  el.more.hidden = true;
  el.count.textContent = '';
}

function renderLoads() {
  const total = state.loadTotal;
  el.count.textContent = total ? `Найдено: ${nf.format(total)}` : '';
  el.hint.textContent = '';
  const shown = Math.min(state.loadOffset + PAGE, total);
  el.results.innerHTML = state.loadItems.map(renderLoadItem).join('') ||
    '<div class="loading">Ничего не найдено</div>';  el.more.hidden = shown >= total;
}

function renderDetailCompany(index) {
  const c = state.companies[index];
  const rows = [];
  const add = (label, value) => { if (value) rows.push(`<dt>${label}</dt><dd>${value}</dd>`); };
  add('ID', esc(c.id));
  add('Город', esc([c.city, c.region, c.country].filter(Boolean).join(', ')));
  add('Тип', esc(c.kind));
  add('Рейтинг', c.rating ? `${num(c.rating)}${c.ratingPct ? ` (${c.ratingPct}%)` : ''}` : '');
  add('Рекомендаций', c.recs ? nf.format(c.recs) : '');
  add('Претензий', c.claims ? nf.format(c.claims) : '');
  add('Документы', esc(c.docs));
  add('Грузов в логах', c.loads ? nf.format(c.loads) : '');
  add('Период', c.first ? `${date(c.first)} — ${date(c.last || c.first)}` : '');

  const contacts = (c.contacts || []).map(contact => {
    const phones = (contact.phones || []).map(phone =>
      `<a class="phone" href="tel:${esc(digits(phone))}">${esc(phone)}</a>`).join('');
    const email = contact.email ? `<a href="mailto:${esc(contact.email)}">${esc(contact.email)}</a>` : '';
    const skype = contact.skype ? `skype: ${esc(contact.skype)}` : '';
    return `<tr><td>${esc(contact.name)}${contact.confirmed ? ' <span class="badge good">подтв.</span>' : ''}</td>
      <td>${phones}${email}${skype}</td></tr>`;
  }).join('');

  el.detail.innerHTML = `
    <h2>${esc(c.name || c.short)}</h2>
    ${c.short && c.short !== c.name ? `<div class="muted">${esc(c.short)}</div>` : ''}
    <dl class="kv">${rows.join('')}</dl>
    <h3>Контакты</h3>
    ${contacts ? `<table class="contacts">${contacts}</table>` : '<p class="muted">Контакты не указаны.</p>'}
    ${c.loads ? `<button class="btn" data-company-loads="${index}">Грузы компании (${nf.format(c.loads)})</button>` : ''}
  `;
}

function renderDetailLoad(load) {
  const company = state.companies[load.c];
  const rows = [];
  const add = (label, value) => { if (value) rows.push(`<dt>${label}</dt><dd>${value}</dd>`); };
  add('Откуда', esc(load.f));
  add('Куда', esc(load.t));
  add('Груз', esc(load.g));
  add('Вес', load.w ? `${num(load.w)} т` : '');
  add('Объём', load.v ? `${num(load.v)} м³` : '');
  add('Ставка', load.p ? money(load.p) : '');
  add('Оплата через', load.pay ? `${load.pay} дн.` : '');
  add('Расстояние', load.d ? `${nf.format(load.d)} км` : '');
  add('Добавлен', date(load.a));
  add('Погрузка', date(load.f1));
  add('Статус', load.ar ? 'архив' : 'активен');
  el.detail.innerHTML = `
    <h2>Груз${load.n ? ' ' + esc(load.n) : ''}</h2>
    <dl class="kv">${rows.join('')}</dl>
    ${company ? `<h3>Компания</h3><p>${esc(company.name || company.short)}</p>
      <button class="btn secondary" data-company-open="${load.c}">Открыть компанию</button>` : ''}
  `;
}

/* ---------- flow ---------- */

function runSearch() {
  if (state.tab === 'companies') {
    state.matches = searchCompanies(tokensOf(state.q));
    state.companyOffset = 0;
    renderCompanies();
  } else if (!state.loadsReady) {
    renderLoadsState('Грузы загружаются…');
  } else {
    askLoads(0);
  }
  syncHash();
}

function setTab(tab) {
  state.tab = tab;
  for (const button of document.querySelectorAll('.tab')) {
    button.classList.toggle('active', button.dataset.tab === tab);
  }
  if (tab === 'companies') state.companyFilter = -1;
  runSearch();
}

function syncHash() {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.tab !== 'companies') params.set('tab', state.tab);
  if (state.companyFilter >= 0) params.set('company', state.companies[state.companyFilter].id);
  const hash = params.toString();
  history.replaceState(null, '', hash ? '#' + hash : location.pathname + location.search);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const company = params.get('company');
  if (company) {
    const index = state.companies.findIndex(c => c.id === company);
    if (index >= 0) {
      state.companyFilter = index;
      state.tab = 'loads';
    }
  }
  if (params.get('tab') === 'loads') state.tab = 'loads';
  return params.get('q') || '';
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function bind() {
  const onInput = debounce(value => {
    state.q = value.trim();
    el.clear.hidden = !state.q;
    runSearch();
  }, 130);
  el.q.addEventListener('input', event => onInput(event.target.value));
  el.clear.addEventListener('click', () => {
    el.q.value = '';
    state.q = '';
    el.clear.hidden = true;
    runSearch();
    el.q.focus();
  });
  for (const button of document.querySelectorAll('.tab')) {
    button.addEventListener('click', () => setTab(button.dataset.tab));
  }
  el.moreBtn.addEventListener('click', () => {
    if (state.tab === 'companies') {
      state.companyOffset += PAGE;
      renderCompanies();
    } else {
      askLoads(state.loadOffset + PAGE);
    }
  });
  el.results.addEventListener('click', event => {
    const companyButton = event.target.closest('[data-company]');
    if (companyButton) {
      const index = Number(companyButton.dataset.company);
      state.selected = { type: 'company', index };
      renderDetailCompany(index);
      renderCompanies();
      return;
    }
    const loadButton = event.target.closest('[data-load]');
    if (loadButton) {
      const index = Number(loadButton.dataset.load);
      renderDetailLoad(state.loadItems[index]);
    }
  });
  el.detail.addEventListener('click', event => {
    const loadsButton = event.target.closest('[data-company-loads]');
    if (loadsButton) {
      state.companyFilter = Number(loadsButton.dataset.companyLoads);
      state.q = '';
      el.q.value = '';
      el.clear.hidden = true;
      setTab('loads');
      return;
    }
    const openButton = event.target.closest('[data-company-open]');
    if (openButton) {
      const index = Number(openButton.dataset.companyOpen);
      state.q = '';
      el.q.value = '';
      el.clear.hidden = true;
      state.selected = { type: 'company', index };
      setTab('companies');
      renderDetailCompany(index);
      const match = state.matches.indexOf(index);
      if (match >= 0) {
        state.companyOffset = Math.floor(match / PAGE) * PAGE;
        renderCompanies();
        const node = el.results.querySelector('.item.active');
        if (node) node.scrollIntoView({ block: 'center' });
      }
    }
  });
  el.q.addEventListener('keydown', event => {
    if (event.key === 'Enter' && state.tab === 'companies' && state.matches.length) {
      state.selected = { type: 'company', index: state.matches[0] };
      renderDetailCompany(state.matches[0]);
      renderCompanies();
    }
  });
}

async function boot() {
  bind();
  const [meta, companies] = await Promise.all([
    fetch('data/meta.json').then(r => r.json()),
    fetch('data/companies.json').then(r => r.json()),
  ]);
  state.meta = meta;
  prepareCompanies(companies);
  renderStats();

  const query = readHash();
  if (query) {
    state.q = query;
    el.q.value = query;
    el.clear.hidden = false;
  }
  for (const button of document.querySelectorAll('.tab')) {
    button.classList.toggle('active', button.dataset.tab === state.tab);
  }
  runSearch();
  startWorker();
}

boot();
