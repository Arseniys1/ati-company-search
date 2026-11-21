'use strict';

let names = [];
let ids = [];
let cities = [];
let cargos = [];
let rows = [];
let hay = [];

function norm(value) {
  return String(value == null ? '' : value).toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();
}

function matches(text, forms) {
  for (const form of forms) {
    if (text.includes(form)) return true;
  }
  return false;
}

function buildIndex() {
  hay = new Array(rows.length);
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    hay[i] = norm([
      names[row[0]],
      ids[row[0]],
      cities[row[1]],
      cities[row[2]],
      cargos[row[4]],
      row[13],
      row[9],
    ].filter(Boolean).join(' '));
  }
}

function toItem(row, index) {
  return {
    i: index,
    c: row[0],
    n: row[13] || '',
    f: row[1] >= 0 ? cities[row[1]] : '',
    t: row[2] >= 0 ? cities[row[2]] : '',
    g: row[4] >= 0 ? cargos[row[4]] : '',
    d: row[3],
    w: row[5],
    v: row[6],
    p: row[7],
    pay: row[8],
    a: row[9],
    f1: row[10],
    l: row[11],
    ar: row[12] === 1,
  };
}

function search(msg) {
  const tokens = msg.tokens || [];
  const company = msg.company;
  const exact = msg.exactCompany == null ? -1 : msg.exactCompany;
  const picked = [];
  let total = 0;
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (company >= 0 && row[0] !== company) continue;
    if (exact >= 0 && row[0] !== exact) continue;
    if (tokens.length && exact < 0) {
      const text = hay[i];
      let ok = true;
      for (const forms of tokens) {
        if (!matches(text, forms)) { ok = false; break; }
      }
      if (!ok) continue;
    }
    total += 1;
    if (total > msg.offset && picked.length < msg.limit) {
      picked.push(toItem(row, i));
    }
  }
  return { type: 'results', reqId: msg.reqId, offset: msg.offset, total, items: picked };
}

async function loadData(url) {
  const response = await fetch(url);
  if (!response.ok || !response.body) throw new Error('loads.json');
  const length = Number(response.headers.get('content-length') || 0);
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  let reported = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (loaded - reported > 512 * 1024) {
      reported = loaded;
      self.postMessage({ type: 'progress', loaded, total: length || loaded });
    }
  }
  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const data = JSON.parse(new TextDecoder().decode(bytes));
  cities = data.cities;
  cargos = data.cargos;
  rows = data.rows;
  buildIndex();
  self.postMessage({ type: 'ready', count: rows.length });
}

self.onmessage = async event => {
  const msg = event.data;
  if (msg.type === 'init') {
    names = msg.names;
    ids = msg.ids || [];
    try {
      await loadData(msg.url);
    } catch (error) {
      self.postMessage({ type: 'error', message: String(error) });
    }
  } else if (msg.type === 'search') {
    self.postMessage(search(msg));
  }
};
