/* cv_db — form wiring. No framework, no build step.
   Every DOM write goes through render*(); state lives in `db`. Swap the markup
   for a UI kit and the only thing you need to keep is the fetch layer. */

'use strict';

const db = { meta: null, skills: [], entries: [] };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ------------------------------------------------------------------ fetch -- */

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : null,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

let flashTimer;
function flash(message, kind = 'ok') {
  const el = $('#flash');
  el.textContent = message;
  el.className = `flash ${kind}`;
  el.hidden = false;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { el.hidden = true; }, 5000);
}

/* ----------------------------------------------------------------- render -- */

function option(value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label;
  return o;
}

function renderMeta() {
  fillDatalist('#orgs', db.meta.orgs);
  fillDatalist('#categories', db.meta.categories);

  const variant = $('#e-variant');
  variant.replaceChildren(option('', '— not placed —'));
  db.meta.variants.forEach(v => variant.append(option(v.id, v.title)));

  variant.onchange = () => {
    const section = $('#e-section');
    const matches = db.meta.sections.filter(s => String(s.variant_id) === variant.value);
    section.replaceChildren(...matches.map(s => option(s.id, s.heading)));
    section.disabled = matches.length === 0;
  };
  variant.onchange();
}

function fillDatalist(sel, values) {
  $(sel).replaceChildren(...values.map(v => option(v, v)));
}

function renderSkills() {
  // Checkbox pool on the entry form, grouped by category.
  const pool = $('#e-skills');
  pool.replaceChildren();
  for (const [category, items] of groupBy(db.skills, s => s.category)) {
    const group = document.createElement('div');
    group.className = 'check-group';
    group.innerHTML = `<h3>${esc(category)}</h3>`;
    for (const s of items) {
      const id = `skill-${s.id}`;
      const label = document.createElement('label');
      label.className = 'check';
      label.htmlFor = id;
      label.innerHTML =
        `<input type="checkbox" id="${id}" name="skill_ids" value="${s.id}">` +
        `<span>${esc(s.name)}${s.detail ? ` <i>${esc(s.detail)}</i>` : ''}</span>`;
      group.append(label);
    }
    pool.append(group);
  }

  // The management list on the skill tab.
  const list = $('#skill-list');
  list.replaceChildren();
  for (const [category, items] of groupBy(db.skills, s => s.category)) {
    const card = document.createElement('article');
    card.className = 'card';
    card.innerHTML = `<h3>${esc(category)}</h3>`;
    const ul = document.createElement('ul');
    ul.className = 'chips';
    for (const s of items) {
      const li = document.createElement('li');
      li.innerHTML =
        `<span>${esc(s.name)}${s.detail ? ` <i>${esc(s.detail)}</i>` : ''}` +
        `<small> · ${s.uses} ${s.uses === 1 ? 'entry' : 'entries'}</small></span>`;
      li.append(deleteButton(`Delete the skill “${s.name}”?`, `/api/skills/${s.id}`));
      ul.append(li);
    }
    card.append(ul);
    list.append(card);
  }
}

function renderEntries() {
  const needle = $('#search').value.trim().toLowerCase();
  const kind = $('#filter-kind').value;
  const list = $('#entry-list');
  list.replaceChildren();

  const shown = db.entries.filter(e => {
    if (kind && e.kind !== kind) return false;
    if (!needle) return true;
    const hay = [e.org, e.title, e.note, e.summary, ...e.bullets.map(b => b.text)]
      .filter(Boolean).join(' ').toLowerCase();
    return hay.includes(needle);
  });

  if (!shown.length) {
    list.innerHTML = '<p class="empty">Nothing matches.</p>';
    return;
  }

  for (const e of shown) list.append(entryCard(e));
}

function entryCard(e) {
  const card = document.createElement('article');
  card.className = 'card';

  const head = document.createElement('header');
  head.innerHTML =
    `<h3>${esc(e.org || '')}${e.org && e.title ? ' — ' : ''}${esc(e.title || '')}</h3>` +
    `<p class="meta"><span class="tag">${esc(e.kind)}</span> ` +
    `${esc(e.date_display || '')}${e.date_display && e.location ? ' · ' : ''}${esc(e.location || '')}</p>` +
    (e.note ? `<p class="note">${esc(e.note)}</p>` : '');
  head.append(deleteButton(
    `Delete “${e.title || e.org}” and its bullets? This cannot be undone.`,
    `/api/entries/${e.id}`));
  card.append(head);

  if (e.summary) {
    const p = document.createElement('p');
    p.textContent = e.summary;
    card.append(p);
  }

  const ul = document.createElement('ul');
  ul.className = 'bullets';
  for (const b of e.bullets) {
    const li = document.createElement('li');
    li.innerHTML = `<span>${esc(b.text)}</span>`;
    li.append(deleteButton('Delete this bullet?', `/api/bullets/${b.id}`));
    ul.append(li);
  }
  card.append(ul);

  // Inline add-a-bullet, so you can top up an entry without reopening the form.
  const add = document.createElement('form');
  add.className = 'inline-add';
  add.innerHTML = `<input name="text" placeholder="Add a bullet…" aria-label="New bullet">
                   <button type="submit">Add</button>`;
  add.onsubmit = async event => {
    event.preventDefault();
    const text = add.text.value.trim();
    if (!text) return;
    try {
      await api('POST', `/api/entries/${e.id}/bullets`, { text });
      add.reset();
      await refresh();
      flash('Bullet added.');
    } catch (err) { flash(err.message, 'error'); }
  };
  card.append(add);

  if (e.skills.length) {
    const tags = document.createElement('p');
    tags.className = 'skill-tags';
    tags.innerHTML = e.skills.map(s => `<span class="tag">${esc(s.name)}</span>`).join(' ');
    card.append(tags);
  }

  const where = document.createElement('p');
  where.className = 'placement';
  where.innerHTML = e.variants.length
    ? e.variants.map(v => `<span>${esc(v.slug)} → ${esc(v.heading)}</span>`).join(' ')
    : '<span class="unplaced">in no variant — renders nowhere</span>';
  card.append(where);

  return card;
}

function deleteButton(confirmText, path) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'delete';
  b.textContent = '×';
  b.title = 'Delete';
  b.onclick = async () => {
    if (!confirm(confirmText)) return;
    try {
      await api('DELETE', path);
      await refresh();
      flash('Deleted.');
    } catch (err) { flash(err.message, 'error'); }
  };
  return b;
}

/* ------------------------------------------------------------------ forms -- */

$('#entry-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const body = Object.fromEntries(new FormData(form));
  body.is_current = form.is_current.checked;
  // FormData collapses same-named checkboxes to the last one; collect them properly.
  body.skill_ids = $$('input[name="skill_ids"]:checked', form).map(i => Number(i.value));
  if (!body.section_id) delete body.variant_id;   // placement needs both or neither

  try {
    await api('POST', '/api/entries', body);
    form.reset();
    $('#e-variant').onchange();
    await refresh();
    flash(`Saved “${body.title || body.org}”.`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) { flash(err.message, 'error'); }
};

$('#skill-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const body = Object.fromEntries(new FormData(form));
  try {
    await api('POST', '/api/skills', body);
    form.reset();
    await refresh();
    flash(`Saved “${body.name}”.`);
  } catch (err) { flash(err.message, 'error'); }
};

$('#search').oninput = renderEntries;
$('#filter-kind').onchange = renderEntries;

$$('.tab').forEach(tab => {
  tab.onclick = () => {
    $$('.tab').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
    $$('.panel').forEach(p => { p.hidden = p.id !== tab.dataset.panel; });
  };
});

/* ------------------------------------------------------------------ utils -- */

/** Reload every table and repaint. Cheap at this scale, and it keeps the page
 *  and the database from drifting apart. */
async function refresh() {
  const keptVariant = $('#e-variant').value;
  [db.meta, db.skills, db.entries] = await Promise.all([
    api('GET', '/api/meta'),
    api('GET', '/api/skills'),
    api('GET', '/api/entries'),
  ]);
  renderMeta();
  $('#e-variant').value = keptVariant;
  $('#e-variant').onchange();
  renderSkills();
  renderEntries();
}

function groupBy(items, key) {
  const map = new Map();
  for (const item of items) {
    const k = key(item);
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(item);
  }
  return map;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

refresh().catch(err => flash(`Could not reach the server: ${err.message}`, 'error'));
