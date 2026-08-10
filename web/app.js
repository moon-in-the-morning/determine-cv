/* cv_db — form wiring. No framework, no build step.

   Two halves, mirroring the schema. `db.library` is your experience and knows
   nothing about documents. `db.doc` is one arrangement over it: headings,
   placements, cut bullets, chosen skills. Everything on screen is one or the
   other joined at render time. */

'use strict';

const db = {
  meta: null,
  library: { entries: [], skills: [], references: [] },
  doc: null,
  versions: [],
  imports: null,
};

/* The six ways a heading can render, and what each one reads from. Kept in one
   place because the Build tab, the new-heading form, and the tree all need it. */
const STYLES = [
  ['entries', 'entries — full, with bullets'],
  ['itemized', 'itemized — one line each'],
  ['skills', 'skills — comma-separated'],
  ['skill-lines', 'skill-lines — one per line'],
  ['references', 'references'],
  ['profile', 'profile'],
];

const SKILL_STYLES = ['skills', 'skill-lines'];
const ENTRY_STYLES = ['entries', 'itemized'];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ACTIVE_KEY = 'cv_db.active_document';
const activeId = () => Number(localStorage.getItem(ACTIVE_KEY)) || null;
const setActive = id => localStorage.setItem(ACTIVE_KEY, String(id));

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

/** Fire a write, repaint on success, surface the error otherwise. */
async function write(method, path, body) {
  try {
    await api(method, path, body);
    await refresh();
    return true;
  } catch (err) { flash(err.message, 'error'); return false; }
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

/* ----------------------------------------------------------------- helpers */

function option(value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label;
  return o;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
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

const entryLabel = e =>
  [e.org, e.title].filter(Boolean).join(' — ') || `entry ${e.id}`;

/** Text that becomes an input when clicked, and saves on blur. */
function editable(path, field, value, { placeholder = '', multiline = false } = {}) {
  const span = document.createElement('span');
  span.className = 'editable' + (value ? '' : ' empty');
  span.textContent = value || placeholder;
  span.title = 'Click to edit';
  span.onclick = () => {
    const input = document.createElement(multiline ? 'textarea' : 'input');
    input.value = value || '';
    input.className = 'edit-field';
    if (multiline) input.rows = Math.max(2, Math.ceil((value || '').length / 80));
    span.replaceWith(input);
    input.focus();

    let done = false;
    const commit = async () => {
      if (done) return;
      done = true;
      const next = input.value.trim();
      if (next === (value || '')) { input.replaceWith(span); return; }
      if (!await write('PATCH', path, { [field]: next })) input.replaceWith(span);
    };
    input.onblur = commit;
    input.onkeydown = e => {
      if (e.key === 'Escape') { done = true; input.replaceWith(span); }
      if (e.key === 'Enter' && !multiline) { e.preventDefault(); input.blur(); }
    };
  };
  return span;
}

function checkbox(checked, title, onchange) {
  const wrap = document.createElement('label');
  wrap.className = 'check include';
  wrap.title = title;
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = checked;
  box.onchange = () => onchange(box.checked);
  wrap.append(box);
  return wrap;
}

function button(label, className, onclick, title = '') {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = className;
  b.textContent = label;
  if (title) b.title = title;
  b.onclick = onclick;
  return b;
}

function deleteButton(confirmText, path) {
  return button('×', 'delete', async () => {
    if (!confirm(confirmText)) return;
    if (await write('DELETE', path)) flash('Deleted.');
  }, 'Delete');
}

/* ------------------------------------------------------------ the document */

const placementOf = id => db.doc?.placements.find(p => p.entry_id === id) || null;
const entryById = id => db.library.entries.find(e => e.id === id);

function renderTree() {
  const tree = $('#tree');
  tree.replaceChildren();
  if (!db.doc) return;

  $('#build-empty').hidden = db.doc.sections.length > 0;

  for (const sec of db.doc.sections) {
    const block = document.createElement('section');
    block.className = 'section-block' + (sec.include ? '' : ' off');

    const head = document.createElement('header');
    head.append(checkbox(!!sec.include, 'Print this heading',
      on => write('PATCH', `/api/sections/${sec.id}`, { include: on ? 1 : 0 })));

    const h2 = document.createElement('h2');
    h2.append(editable(`/api/sections/${sec.id}`, 'heading', sec.heading));
    head.append(h2);

    const style = document.createElement('select');
    style.className = 'style-select';
    style.title = 'How this block renders';
    STYLES.forEach(([value, label]) => style.append(option(value, label)));
    style.value = sec.style;
    style.onchange = () => write('PATCH', `/api/sections/${sec.id}`, { style: style.value });
    head.append(style);

    // Which slice of the ticked skills this heading prints. Without it, two
    // skills headings in one document would each print all of them.
    if (SKILL_STYLES.includes(sec.style)) {
      const category = document.createElement('select');
      category.className = 'style-select';
      category.title = 'Which category of skills this heading prints';
      category.append(option('', 'every ticked skill'));
      db.meta.categories.forEach(c => category.append(option(c, c)));
      category.value = sec.category || '';
      category.onchange = () => write('PATCH', `/api/sections/${sec.id}`,
                                      { category: category.value });
      head.append(category);
    }

    head.append(deleteButton(
      `Delete the heading “${sec.heading}” from this document? ` +
      `The experience under it stays in your library.`,
      `/api/sections/${sec.id}`));
    block.append(head);

    if (sec.style === 'profile') {
      const p = document.createElement('p');
      p.className = 'prose';
      p.append(editable('/api/profile', 'summary', db.meta.profile.summary,
        { placeholder: 'No profile paragraph yet — click to write one.', multiline: true }));
      block.append(p);
    } else if (SKILL_STYLES.includes(sec.style)) {
      const chosen = db.library.skills.filter(
        s => db.doc.skill_ids.includes(s.id) && (!sec.category || s.category === sec.category));
      const note = document.createElement('p');
      note.className = 'hint';
      note.innerHTML = `Prints ${chosen.length} skill${chosen.length === 1 ? '' : 's'}` +
                       (sec.category ? ` from ${esc(sec.category)}` : ' — every ticked one') +
                       ` · tick them on the <b>Skills</b> tab.`;
      block.append(note);
    } else if (sec.style === 'references') {
      const chosen = db.library.references.filter(r => db.doc.reference_ids.includes(r.id));
      const note = document.createElement('p');
      note.className = 'hint';
      note.innerHTML = chosen.length
        ? `Names ${chosen.map(r => esc(r.name)).join(', ')} · ` +
          `choose them on the <b>References</b> tab.`
        : `No referees ticked for this document — choose them on the ` +
          `<b>References</b> tab. An empty heading is skipped when generating.`;
      block.append(note);
    } else {
      const placed = db.doc.placements
        .filter(p => p.section_id === sec.id)
        .sort((a, b) => a.sort_order - b.sort_order || a.entry_id - b.entry_id);

      if (!placed.length) {
        const empty = document.createElement('p');
        empty.className = 'hint';
        empty.textContent = 'Nothing under this heading yet — add from the Library tab. ' +
                            'An empty heading is skipped when generating.';
        block.append(empty);
      }
      placed.forEach(p => {
        const entry = entryById(p.entry_id);
        if (entry) block.append(placedRow(entry, p, sec));
      });
    }

    tree.append(block);
  }
}

function placedRow(e, placement, sec) {
  const wrap = document.createElement('details');
  wrap.className = 'entry-row' + (placement.include ? '' : ' off');
  wrap.dataset.id = e.id;

  const shown = e.bullets.filter(b => !db.doc.hidden_bullets.includes(b.id));
  const itemized = sec.style === 'itemized';
  const summary = document.createElement('summary');
  summary.innerHTML =
    `<span class="title">${esc(entryLabel(e))}</span> ` +
    `<span class="tag">#${itemized ? 'line-item' : shown.length ? 'entry' : 'item'}</span> ` +
    `<span class="meta">${esc(e.date_display || '')}</span>`;
  wrap.append(summary);

  // Say plainly what an itemized heading drops, so nothing goes missing
  // quietly. It is all still here — switch the style back and it returns.
  if (itemized && (shown.length || e.note)) {
    const trimmed = document.createElement('p');
    trimmed.className = 'hint';
    trimmed.textContent =
      `Prints as one line: date, then title, organisation, location. ` +
      `The note and ${shown.length} bullet${shown.length === 1 ? '' : 's'} ` +
      `stay in the library and print again under the entries style.`;
    wrap.append(trimmed);
  }

  const bar = document.createElement('div');
  bar.className = 'entry-bar';
  bar.append(checkbox(!!placement.include, 'Print this in the document',
    on => write('PATCH', `/api/documents/${db.doc.document.id}/place/${e.id}`,
                { include: on ? 1 : 0 })));

  // Moving between headings is the whole point: same entry, different section.
  const move = document.createElement('select');
  move.className = 'style-select';
  move.title = 'Move to another heading';
  db.doc.sections.filter(s => ENTRY_STYLES.includes(s.style))
                 .forEach(s => move.append(option(s.id, s.heading)));
  move.value = sec.id;
  move.onchange = () => write('PATCH', `/api/documents/${db.doc.document.id}/place/${e.id}`,
                              { section_id: Number(move.value) });
  bar.append(move);

  bar.append(button('Remove', 'small', async () => {
    if (await write('DELETE', `/api/documents/${db.doc.document.id}/place/${e.id}`))
      flash(`Removed from ${db.doc.document.title} — still in your library.`);
  }, 'Take out of this document; keep in the library'));
  wrap.append(bar);

  wrap.append(entryFields(e));
  wrap.append(bulletList(e));
  wrap.append(addBulletForm(e));
  return wrap;
}

function entryFields(e) {
  const fields = document.createElement('dl');
  fields.className = 'fields';
  for (const [label, field] of [['Organisation', 'org'], ['Title', 'title'],
                                ['Dates', 'date_display'], ['Location', 'location'],
                                ['Note', 'note'], ['Summary', 'summary']]) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.append(editable(`/api/entries/${e.id}`, field, e[field], { placeholder: '—' }));
    fields.append(dt, dd);
  }
  return fields;
}

/** In a document, a bullet's checkbox cuts it from THAT document only.
 *  In the library there is no document, so bullets are just listed. */
function bulletList(e, { inDocument = true } = {}) {
  const ul = document.createElement('ul');
  ul.className = 'bullets';
  for (const b of e.bullets) {
    const hidden = inDocument && db.doc?.hidden_bullets.includes(b.id);
    const li = document.createElement('li');
    li.className = hidden ? 'off' : '';
    if (inDocument && db.doc) {
      li.append(checkbox(!hidden, 'Print this bullet in this document',
        on => write('PUT', `/api/documents/${db.doc.document.id}/bullets/${b.id}`,
                    { include: on ? 1 : 0 })));
    }
    li.append(editable(`/api/bullets/${b.id}`, 'text', b.text, { multiline: true }));
    li.append(deleteButton(
      'Delete this bullet from the library? It disappears from every document.',
      `/api/bullets/${b.id}`));
    ul.append(li);
  }
  return ul;
}

function addBulletForm(e) {
  const form = document.createElement('form');
  form.className = 'inline-add';
  form.innerHTML = `<input name="text" placeholder="Add a bullet…" aria-label="New bullet">
                    <button type="submit">Add</button>`;
  form.onsubmit = async event => {
    event.preventDefault();
    const text = form.text.value.trim();
    if (!text) return;
    if (await write('POST', `/api/entries/${e.id}/bullets`, { text })) form.reset();
  };
  return form;
}

/* ----------------------------------------------------------------- library */

function renderLibrary() {
  const needle = $('#search').value.trim().toLowerCase();
  const kind = $('#filter-kind').value;
  const unusedOnly = $('#filter-unused').checked;
  const list = $('#library-list');
  list.replaceChildren();

  const shown = db.library.entries.filter(e => {
    if (kind && e.kind !== kind) return false;
    if (unusedOnly && placementOf(e.id)) return false;
    if (!needle) return true;
    return [e.org, e.title, e.note, e.summary, ...e.bullets.map(b => b.text)]
      .filter(Boolean).join(' ').toLowerCase().includes(needle);
  });

  if (!shown.length) {
    list.innerHTML = '<p class="empty">Nothing matches.</p>';
    return;
  }
  shown.forEach(e => list.append(libraryRow(e)));
}

function libraryRow(e) {
  const wrap = document.createElement('details');
  wrap.className = 'entry-row card';
  wrap.dataset.id = `lib-${e.id}`;

  const here = placementOf(e.id);
  const summary = document.createElement('summary');
  summary.innerHTML =
    `<span class="title">${esc(entryLabel(e))}</span> ` +
    `<span class="tag">${esc(e.kind)}</span> ` +
    `<span class="meta">${esc(e.date_display || '')}</span>` +
    (e.used_in.length
      ? ` <span class="meta">· in ${e.used_in.map(d => esc(d.title)).join(', ')}</span>`
      : ' <span class="meta unused">· in no document</span>');
  wrap.append(summary);

  const bar = document.createElement('div');
  bar.className = 'entry-bar';

  if (db.doc) {
    const sections = db.doc.sections.filter(s => ENTRY_STYLES.includes(s.style));
    if (!sections.length) {
      const hint = document.createElement('span');
      hint.className = 'hint';
      hint.textContent = `“${db.doc.document.title}” has no headings yet — add one on Build.`;
      bar.append(hint);
    } else if (here) {
      const label = document.createElement('span');
      label.className = 'hint';
      const section = db.doc.sections.find(s => s.id === here.section_id);
      label.textContent = `In ${db.doc.document.title} under ${section?.heading ?? '—'}`;
      bar.append(label);
      bar.append(button('Remove', 'small',
        () => write('DELETE', `/api/documents/${db.doc.document.id}/place/${e.id}`),
        'Take out of this document'));
    } else {
      const pick = document.createElement('select');
      pick.className = 'style-select';
      pick.append(option('', `Add to ${db.doc.document.title} under…`));
      sections.forEach(s => pick.append(option(s.id, s.heading)));
      pick.onchange = async () => {
        if (!pick.value) return;
        if (await write('POST', `/api/documents/${db.doc.document.id}/place`,
                        { entry_id: e.id, section_id: Number(pick.value) }))
          flash(`Added “${entryLabel(e)}”.`);
      };
      bar.append(pick);
    }
  }

  bar.append(deleteButton(
    `Delete “${entryLabel(e)}” from the library entirely? ` +
    `It disappears from every document. This cannot be undone.`,
    `/api/entries/${e.id}`));
  wrap.append(bar);

  wrap.append(entryFields(e));
  wrap.append(bulletList(e, { inDocument: false }));
  wrap.append(addBulletForm(e));

  if (e.skills.length) {
    const tags = document.createElement('p');
    tags.className = 'skill-tags';
    tags.innerHTML = e.skills.map(s => `<span class="tag">${esc(s.name)}</span>`).join(' ');
    wrap.append(tags);
  }
  return wrap;
}

/* --------------------------------------------------------------- documents */

function renderDocuments() {
  const list = $('#document-list');
  list.replaceChildren();

  for (const d of db.meta.documents) {
    const card = document.createElement('article');
    card.className = 'card document-card' + (d.id === db.doc?.document.id ? ' active' : '');

    const head = document.createElement('header');
    const h3 = document.createElement('h3');
    h3.append(editable(`/api/documents/${d.id}`, 'title', d.title));
    head.append(h3);
    head.append(deleteButton(
      `Delete the document “${d.title}”? Its headings and selection go; ` +
      `every entry, bullet, and skill stays in your library.`,
      `/api/documents/${d.id}`));
    card.append(head);

    const meta = document.createElement('p');
    meta.className = 'meta';
    meta.textContent = `${d.slug} · ${d.sections} heading${d.sections === 1 ? '' : 's'} · ` +
                       `${d.entries} entr${d.entries === 1 ? 'y' : 'ies'} · ${d.paper}`;
    card.append(meta);

    const notes = document.createElement('p');
    notes.className = 'note';
    notes.append(editable(`/api/documents/${d.id}`, 'notes', d.notes,
                          { placeholder: '+ what this one is for' }));
    card.append(notes);

    if (d.id !== db.doc?.document.id) {
      card.append(button('Build this one', 'small', async () => {
        setActive(d.id);
        await refresh();
        $$('.tab').find(t => t.dataset.panel === 'panel-build').click();
      }));
    } else {
      const badge = document.createElement('span');
      badge.className = 'tag';
      badge.textContent = 'building';
      card.append(badge);
    }
    list.append(card);
  }
}

/* ------------------------------------------------------------------ skills */

function renderSkills() {
  const chosen = new Set(db.doc?.skill_ids ?? []);

  const pool = $('#e-skills');
  pool.replaceChildren();
  for (const [category, items] of groupBy(db.library.skills, s => s.category)) {
    const group = document.createElement('div');
    group.className = 'check-group';
    group.innerHTML = `<h3>${esc(category)}</h3>`;
    for (const s of items) {
      const label = document.createElement('label');
      label.className = 'check';
      label.innerHTML = `<input type="checkbox" name="skill_ids" value="${s.id}">` +
                        `<span>${esc(s.name)}</span>`;
      group.append(label);
    }
    pool.append(group);
  }

  const list = $('#skill-list');
  list.replaceChildren();
  for (const [category, items] of groupBy(db.library.skills, s => s.category)) {
    const card = document.createElement('article');
    card.className = 'card';
    const h3 = document.createElement('h3');
    h3.textContent = category;
    card.append(h3);

    const ul = document.createElement('ul');
    ul.className = 'chips';
    for (const s of items) {
      const on = chosen.has(s.id);
      const li = document.createElement('li');
      li.className = on ? '' : 'off';
      if (db.doc) {
        li.append(checkbox(on, `Print in ${db.doc.document.title}`,
          checked => write('PUT', `/api/documents/${db.doc.document.id}/skills/${s.id}`,
                           { include: checked ? 1 : 0 })));
      }
      li.append(editable(`/api/skills/${s.id}`, 'name', s.name));
      const detail = document.createElement('small');
      detail.append(editable(`/api/skills/${s.id}`, 'detail', s.detail,
                             { placeholder: '+ detail' }));
      detail.append(document.createTextNode(` · ${s.uses} ${s.uses === 1 ? 'entry' : 'entries'}`));
      li.append(detail);
      li.append(deleteButton(
        `Delete the skill “${s.name}” from the library? It goes from every document.`,
        `/api/skills/${s.id}`));
      ul.append(li);
    }
    card.append(ul);
    list.append(card);
  }
}

/* ----------------------------------------------------------------- profile */

function renderProfile() {
  const p = db.meta.profile ?? {};

  // A database straight from starter.sql has the placeholder name and no
  // contacts. Say so once, on the tab you land on, rather than letting someone
  // generate a CV headed "Your Name".
  $('#first-run').hidden =
    !(!p.full_name || p.full_name === 'Your Name' || !db.meta.contacts.length);

  const fields = document.createElement('dl');
  fields.className = 'fields';
  for (const [label, field, opts] of [
    ['Name', 'full_name', { placeholder: 'Your name — click to set it' }],
    ['Legal name', 'legal_name', { placeholder: '— (only if it differs)' }],
    ['Pronouns', 'pronouns', { placeholder: '—' }],
    ['Profile paragraph', 'summary', { placeholder: '—', multiline: true }],
  ]) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.append(editable('/api/profile', field, p[field], opts));
    fields.append(dt, dd);
  }
  $('#profile-fields').replaceChildren(fields);

  const list = $('#contact-list');
  list.replaceChildren();
  if (!db.meta.contacts.length) {
    list.innerHTML = '<p class="empty">No contact details yet — add one below.</p>';
    return;
  }
  const ul = document.createElement('ul');
  ul.className = 'sends';                     // same one-line-each treatment
  for (const c of db.meta.contacts) {
    const li = document.createElement('li');

    const kind = document.createElement('select');
    kind.className = 'style-select';
    kind.title = 'How this one prints';
    db.meta.contact_kinds.forEach(k => kind.append(option(k, k)));
    kind.value = c.kind;
    kind.onchange = () => write('PATCH', `/api/contacts/${c.id}`, { kind: kind.value });
    li.append(kind);

    const value = document.createElement('span');
    value.className = 'title';
    value.append(editable(`/api/contacts/${c.id}`, 'value', c.value));
    li.append(value);

    const display = document.createElement('small');
    display.append(editable(`/api/contacts/${c.id}`, 'display', c.display,
                            { placeholder: '+ display as' }));
    li.append(display);

    li.append(deleteButton(`Remove ${c.value} from your contact line?`,
                           `/api/contacts/${c.id}`));
    ul.append(li);
  }
  list.append(ul);
}

/* -------------------------------------------------------------- references */

function renderReferences() {
  const chosen = new Set(db.doc?.reference_ids ?? []);
  const list = $('#reference-list');
  list.replaceChildren();

  if (!db.library.references.length) {
    list.innerHTML = '<p class="empty">No references yet — add one below.</p>';
    return;
  }

  for (const r of db.library.references) {
    const card = document.createElement('article');
    const on = chosen.has(r.id);
    card.className = 'card' + (on ? '' : ' off');

    const head = document.createElement('header');
    if (db.doc) {
      head.append(checkbox(on, `Name them in ${db.doc.document.title}`,
        checked => write('PUT', `/api/documents/${db.doc.document.id}/references/${r.id}`,
                         { include: checked ? 1 : 0 })));
    }
    const h3 = document.createElement('h3');
    h3.append(editable(`/api/references/${r.id}`, 'name', r.name));
    head.append(h3);
    head.append(deleteButton(
      `Delete ${r.name} from your references? They go from every document.`,
      `/api/references/${r.id}`));
    card.append(head);

    // The printed block, field by field, in the order it prints.
    const fields = document.createElement('dl');
    fields.className = 'fields';
    for (const [label, field, opts] of [
      ['Title', 'title', {}], ['Institution', 'org', {}],
      ['Department', 'department', {}], ['Address', 'address', { multiline: true }],
      ['Email', 'email', {}], ['Phone', 'phone', {}],
      ['How you know them', 'relation', {}],
    ]) {
      const dt = document.createElement('dt');
      dt.textContent = label;
      const dd = document.createElement('dd');
      if (field === 'relation') dd.className = 'unprinted';
      dd.append(editable(`/api/references/${r.id}`, field, r[field],
                         { placeholder: '—', ...opts }));
      fields.append(dt, dd);
    }
    card.append(fields);

    const meta = document.createElement('p');
    meta.className = 'meta';
    meta.textContent = r.used_in
      ? `Named in ${r.used_in} document${r.used_in === 1 ? '' : 's'}`
      : 'Named in no document';
    card.append(meta);

    list.append(card);
  }
}

/* ---------------------------------------------------------------- versions */

/** "2026-08-10T05:39:10Z" → "10 Aug 2026, 05:39 UTC". */
function stamp(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const date = d.toLocaleDateString(undefined,
    { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const time = d.toLocaleTimeString(undefined,
    { hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false });
  return `${date}, ${time} UTC`;
}

function renderVersions() {
  const list = $('#version-list');
  list.replaceChildren();

  if (!db.doc) {
    list.innerHTML = '<p class="empty">No document selected.</p>';
    return;
  }
  if (!db.versions.length) {
    list.innerHTML = '<p class="empty">Nothing generated yet. ' +
                     'Press Generate on the Build tab and this fills in.</p>';
    return;
  }

  for (const v of db.versions) {
    const card = document.createElement('article');
    card.className = 'card version-card';

    const head = document.createElement('header');
    const h3 = document.createElement('h3');
    h3.textContent = `Version ${v.number}`;
    head.append(h3);

    const when = document.createElement('span');
    when.className = 'meta';
    when.textContent = stamp(v.created_at);
    head.append(when);

    const digest = document.createElement('code');
    digest.className = 'digest';
    digest.textContent = v.digest.slice(0, 12);
    digest.title = `sha256 ${v.digest}`;
    head.append(digest);

    const source = document.createElement('a');
    source.className = 'download-link';
    source.href = `/download/version?id=${v.id}`;
    source.textContent = '↓ .typ';
    source.title = 'The exact Typst this version was';
    head.append(source);
    card.append(head);

    const notes = document.createElement('p');
    notes.className = 'note';
    notes.append(editable(`/api/versions/${v.id}`, 'notes', v.notes,
                          { placeholder: '+ what changed, or what this one is for' }));
    card.append(notes);

    const sends = document.createElement('ul');
    sends.className = 'sends';
    if (!v.sends.length) {
      const li = document.createElement('li');
      li.className = 'hint';
      li.textContent = 'Not sent anywhere yet.';
      sends.append(li);
    }
    for (const s of v.sends) {
      const li = document.createElement('li');
      const who = document.createElement('span');
      who.className = 'title';
      who.append(editable(`/api/sends/${s.id}`, 'recipient', s.recipient));
      li.append(who);

      for (const [field, placeholder] of
           [['org', '+ where'], ['sent_on', '+ when'], ['channel', '+ how']]) {
        const bit = document.createElement('span');
        bit.className = 'meta';
        bit.append(editable(`/api/sends/${s.id}`, field, s[field], { placeholder }));
        li.append(bit);
      }

      const note = document.createElement('small');
      note.append(editable(`/api/sends/${s.id}`, 'notes', s.notes, { placeholder: '+ note' }));
      li.append(note);
      li.append(deleteButton(`Delete the record of sending this to ${s.recipient}?`,
                             `/api/sends/${s.id}`));
      sends.append(li);
    }
    card.append(sends);
    card.append(sendForm(v));
    list.append(card);
  }
}

function sendForm(v) {
  const form = document.createElement('form');
  form.className = 'inline-add';
  form.innerHTML =
    `<input name="recipient" placeholder="Sent to…" aria-label="Recipient" required>
     <input name="org" placeholder="Where" aria-label="Organisation">
     <input name="sent_on" type="date" aria-label="Date sent">
     <input name="channel" list="channels" placeholder="How" aria-label="Channel">
     <button type="submit">Record</button>`;
  form.onsubmit = async event => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(form));
    if (!body.recipient.trim()) return;
    if (await write('POST', `/api/versions/${v.id}/sends`, body)) {
      form.reset();
      flash(`Recorded: version ${v.number} → ${body.recipient}.`);
    }
  };
  return form;
}

/* -------------------------------------------------------------- chrome ---- */

function renderChrome() {
  const picker = $('#active-doc');
  picker.replaceChildren();
  db.meta.documents.forEach(d => picker.append(option(d.id, d.title)));
  if (db.doc) picker.value = db.doc.document.id;
  picker.disabled = db.meta.documents.length === 0;

  const copy = $('#d-copy');
  copy.replaceChildren(option('', 'Blank — no headings, nothing selected'));
  db.meta.documents.forEach(d => copy.append(option(d.id, `Copy of ${d.title}`)));

  const file = $('#e-section');
  const kept = file.value;
  file.replaceChildren(option('', 'Library only — place it later'));
  (db.doc?.sections ?? []).filter(s => ENTRY_STYLES.includes(s.style))
    .forEach(s => file.append(option(s.id, s.heading)));
  file.value = kept;

  $('#orgs').replaceChildren(...db.meta.orgs.map(v => option(v, v)));
  $('#categories').replaceChildren(...db.meta.categories.map(v => option(v, v)));
}

/* ------------------------------------------------------------------ forms -- */

$('#entry-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const body = Object.fromEntries(new FormData(form));
  body.is_current = form.is_current.checked;
  // FormData collapses same-named checkboxes to the last one; collect properly.
  body.skill_ids = $$('input[name="skill_ids"]:checked', form).map(i => Number(i.value));
  if (body.section_id) body.document_id = db.doc?.document.id;

  try {
    await api('POST', '/api/entries', body);
    form.reset();
    await refresh();
    flash(`Saved “${body.title || body.org}” to the library.`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) { flash(err.message, 'error'); }
};

$('#skill-form').onsubmit = async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  try {
    await api('POST', '/api/skills', body);
    event.target.reset();
    await refresh();
    flash(`Saved “${body.name}”. Tick it to print it in this document.`);
  } catch (err) { flash(err.message, 'error'); }
};

$('#contact-form').onsubmit = async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  if (!body.value.trim()) return;
  if (await write('POST', '/api/contacts', body)) {
    event.target.reset();
    flash(`Added ${body.value} to your contact line.`);
  }
};

$('#reference-form').onsubmit = async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  try {
    await api('POST', '/api/references', body);
    event.target.reset();
    await refresh();
    flash(`Saved ${body.name}. Tick them to name them in this document.`);
  } catch (err) { flash(err.message, 'error'); }
};

$('#section-form').onsubmit = async event => {
  event.preventDefault();
  if (!db.doc) { flash('Create a document first.', 'error'); return; }
  const body = Object.fromEntries(new FormData(event.target));
  if (!body.heading?.trim()) return;
  if (await write('POST', `/api/documents/${db.doc.document.id}/sections`, body)) {
    event.target.reset();
    flash(`Added the heading “${body.heading}”.`);
  }
};

$('#document-form').onsubmit = async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  try {
    const made = await api('POST', '/api/documents', body);
    event.target.reset();
    setActive(made.id);
    await refresh();
    flash(`Created “${body.title}”. Add headings on the Build tab.`);
    $$('.tab').find(t => t.dataset.panel === 'panel-build').click();
  } catch (err) { flash(err.message, 'error'); }
};

$('#active-doc').onchange = async event => {
  setActive(Number(event.target.value));
  await refresh();
};

$('#search').oninput = renderLibrary;
$('#filter-kind').onchange = renderLibrary;
$('#filter-unused').onchange = renderLibrary;

/* ---------------------------------------------------------------- generate */

/** Fallback for browsers with no save picker: straight to Downloads. */
function saveToDownloads(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
}

function suggestedName(suffix) {
  const person = (db.meta?.profile?.full_name || '').trim();
  const title = db.doc?.document.title || 'CV';
  const safe = [...[person, title].filter(Boolean).join(' - ')]
    .filter(c => /[a-z0-9 \-_]/i.test(c)).join('').trim() || 'cv';
  return `${safe}.${suffix}`;
}

$('#generate').onclick = async () => {
  const status = $('#generate-status');
  const link = $('#download-link');
  if (!db.doc) { flash('Create a document first.', 'error'); return; }

  const wantPdf = $('#do-compile').checked;
  const suffix = wantPdf ? 'pdf' : 'typ';

  // Ask WHERE first, while the click still counts as user activation. Once an
  // await has let that lapse the picker refuses to open.
  let handle = null;
  if (window.showSaveFilePicker) {
    try {
      handle = await window.showSaveFilePicker({
        suggestedName: suggestedName(suffix),
        types: [wantPdf
          ? { description: 'PDF document', accept: { 'application/pdf': ['.pdf'] } }
          : { description: 'Typst source', accept: { 'text/plain': ['.typ'] } }],
      });
    } catch (err) {
      if (err.name === 'AbortError') { status.textContent = 'cancelled'; return; }
      handle = null;                      // unsupported here — fall through
    }
  }

  status.textContent = 'generating…';
  link.hidden = true;
  try {
    const out = await api('POST', '/api/generate',
                          { document_id: db.doc.document.id, compile: wantPdf });
    $('#output').textContent = out.typst;
    $('#output-wrap').hidden = false;

    if (out.error) {
      status.textContent = `wrote ${out.path}`;
      flash(out.error, 'error');
      return;
    }

    const url = `${out.download}?name=${encodeURIComponent(out.filename)}&t=${Date.now()}`;
    if (handle) {
      const blob = await (await fetch(url)).blob();
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      flash(`Saved as ${handle.name}.`);
    } else {
      saveToDownloads(url, out.filename);
      flash(`Saved ${out.filename} to your downloads.`);
    }

    link.href = url;
    link.download = out.filename;
    link.textContent = `↓ ${out.filename}`;
    link.hidden = false;

    const v = out.version;
    const which = v.new
      ? `version ${v.number}`
      : `version ${v.number} — unchanged since ${stamp(v.created_at)}`;
    status.textContent = (out.compiled ? `wrote ${out.path} and ${out.pdf}`
                                       : `wrote ${out.path} — PDF not compiled`) +
                         ` · ${which}`;
    await refresh();          // so the Versions tab shows it without a reload
  } catch (err) {
    status.textContent = '';
    flash(err.message, 'error');
  }
};

$('#reveal').onclick = async () => {
  try {
    const out = await api('POST', '/api/reveal',
                          { kind: $('#do-compile').checked ? 'pdf' : 'typ' });
    flash(`Showing ${out.revealed} in Finder.`);
  } catch (err) { flash(err.message, 'error'); }
};

$$('.tab').forEach(tab => { tab.onclick = () => show(tab.dataset.panel); });


/* ==================================================================== import ==

   Upload, then a confirmation per part of the library. The wizard never writes
   to the library itself: every decision goes to /api/extractions, and the
   server promotes only what was accepted. Edits made here are staged on the
   proposal, so backing out of a step loses nothing.                          */

const wiz = { source: null, steps: [], at: 0, edits: {}, dropped: new Set() };

const FIELDS = {
  profile:   [['full_name', 'Name'], ['legal_name', 'Legal name'], ['pronouns', 'Pronouns']],
  contact:   [['display', 'Shown as'], ['value', 'Value'], ['kind', 'Kind']],
  entry:     [['org', 'Organisation'], ['title', 'Title / role'],
              ['date_display', 'Dates'], ['location', 'Location'], ['note', 'Note']],
  skill:     [['name', 'Name'], ['category', 'Category'], ['detail', 'Detail']],
  reference: [['name', 'Name'], ['title', 'Title'], ['org', 'Organisation'],
              ['email', 'Email'], ['phone', 'Phone']],
};

async function uploadFile(file) {
  if (!file) return;
  flash(`Reading ${file.name}…`);
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = () => reject(new Error('could not read that file'));
    reader.readAsDataURL(file);
  });

  try {
    const out = await api('POST', '/api/imports', { filename: file.name, data });
    const source = out.sources[0];
    flash(`Read ${source.filename} — ${Math.round((source.coverage || 0) * 100)}% of it accounted for.`);
    await refresh();
    await openWizard(source.id);
  } catch (err) { flash(err.message, 'error'); }
}

async function openWizard(sourceId) {
  const review = await api('GET', `/api/imports/${sourceId}`);
  wiz.source = review.source;
  wiz.steps = review.steps.filter(step => step.proposals.length);
  wiz.bullets = review.bullets || {};
  wiz.at = 0;
  wiz.edits = {};
  wiz.dropped = new Set();

  $('#onboarding').hidden = true;
  show('panel-import');
  if (!wiz.steps.length) {
    $('#wizard').hidden = true;
    flash('Nothing left to confirm in that file.');
    return;
  }
  $('#wizard').hidden = false;
  renderWizard();
}

function renderWizard() {
  const step = wiz.steps[wiz.at];
  if (!step) return;

  $('#wizard-title').textContent = step.title;
  $('#wizard-sub').textContent =
    `${wiz.source.filename} · step ${wiz.at + 1} of ${wiz.steps.length} · ` +
    `${step.proposals.length} found. Edit anything that is wrong, untick anything you don't want.`;

  const rail = $('#wizard-steps');
  rail.replaceChildren();
  wiz.steps.forEach((s, i) => {
    const li = document.createElement('li');
    li.className = i === wiz.at ? 'here' : (i < wiz.at ? 'done' : '');
    li.textContent = s.title;
    li.onclick = () => { wiz.at = i; renderWizard(); };
    rail.append(li);
  });

  const body = $('#wizard-body');
  body.replaceChildren();
  step.proposals.forEach(p => body.append(proposalCard(p, step)));
  body.append(addAnotherForm(step));

  $('#wizard-back').disabled = wiz.at === 0;
  $('#wizard-next').textContent =
    wiz.at === wiz.steps.length - 1 ? 'Confirm and finish' : 'Confirm and continue';
}

function proposalCard(p, step) {
  const card = document.createElement('article');
  card.className = 'card proposal';
  const staged = () => ({ ...p.payload, ...(wiz.edits[p.id] || {}) });

  const head = document.createElement('header');
  head.append(checkbox(!wiz.dropped.has(p.id), 'Add this to your library', on => {
    on ? wiz.dropped.delete(p.id) : wiz.dropped.add(p.id);
    card.classList.toggle('off', !on);
  }));
  const h3 = document.createElement('h3');
  h3.textContent = step.title.replace(/s$/, '');
  head.append(h3);
  if (p.confidence < 0.8) {
    const flag = document.createElement('span');
    flag.className = 'tag warn';
    flag.textContent = p.confidence < 0.6 ? 'check this one' : 'unsure';
    flag.title = `rule: ${p.rule}`;
    head.append(flag);
  }
  card.append(head);

  const grid = document.createElement('div');
  grid.className = 'proposal-fields';
  for (const [field, label] of FIELDS[p.target] || [['text', 'Text']]) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    wrap.innerHTML = `<span>${esc(label)}</span>`;
    const input = document.createElement('input');
    input.value = staged()[field] ?? '';
    input.placeholder = '—';
    input.oninput = () => {
      wiz.edits[p.id] = { ...(wiz.edits[p.id] || {}), [field]: input.value.trim() };
    };
    wrap.append(input);
    grid.append(wrap);
  }
  card.append(grid);

  const kids = (wiz.bullets || {})[p.id] || [];
  if (kids.length) {
    const ul = document.createElement('ul');
    ul.className = 'bullets';
    kids.forEach(b => {
      const li = document.createElement('li');
      li.textContent = b.payload.text || '';
      ul.append(li);
    });
    card.append(ul);
  }

  if (p.quote) {
    const src = document.createElement('details');
    src.className = 'quote';
    src.innerHTML = `<summary>from your file</summary><pre>${esc(p.quote)}</pre>`;
    card.append(src);
  }
  return card;
}

/** Anything the parser missed, typed in by hand — same step, same shape. */
function addAnotherForm(step) {
  const target = step.targets[step.targets.length - 1];
  const form = document.createElement('form');
  form.className = 'card add-another';
  const fields = FIELDS[target] || [['text', 'Text']];
  form.innerHTML = `<h3>Add another ${esc(step.title.replace(/s$/, '').toLowerCase())}</h3>`;
  const grid = document.createElement('div');
  grid.className = 'proposal-fields';
  fields.forEach(([field, label]) => {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    wrap.innerHTML = `<span>${esc(label)}</span>`;
    const input = document.createElement('input');
    input.name = field;
    wrap.append(input);
    grid.append(wrap);
  });
  form.append(grid);
  const add = document.createElement('button');
  add.type = 'submit';
  add.textContent = 'Add';
  form.append(add);

  form.onsubmit = async event => {
    event.preventDefault();
    const body = Object.fromEntries(
      [...new FormData(form)].filter(([, v]) => String(v).trim()));
    if (!Object.keys(body).length) return;
    const routes = { entry: '/api/entries', skill: '/api/skills',
                     reference: '/api/references', contact: '/api/contacts' };
    if (target === 'profile') {
      if (await write('PATCH', '/api/profile', body)) flash('Saved.');
      form.reset();
      return;
    }
    if (target === 'entry') body.kind = step.kinds?.[0] || 'position';
    if (target === 'skill') body.category = body.category || step.title;
    try {
      await api('POST', routes[target], body);
      form.reset();
      flash('Added.');
      await refresh();
    } catch (err) { flash(err.message, 'error'); }
  };
  return form;
}

async function commitStep({ accept = true } = {}) {
  const step = wiz.steps[wiz.at];
  if (!step) return;

  if (accept) {
    const keep = step.proposals.filter(p => !wiz.dropped.has(p.id));
    const drop = step.proposals.filter(p => wiz.dropped.has(p.id));
    const edits = {};
    keep.forEach(p => { if (wiz.edits[p.id]) edits[String(p.id)] = wiz.edits[p.id]; });

    try {
      if (drop.length) {
        await api('POST', `/api/imports/${wiz.source.id}/decide`,
                  { ids: drop.map(p => p.id), action: 'reject' });
      }
      if (keep.length) {
        const out = await api('POST', `/api/imports/${wiz.source.id}/decide`,
                              { ids: keep.map(p => p.id), action: 'accept', edits });
        if (out.failed) flash(`${out.done} added, ${out.failed} could not be`, 'error');
      }
    } catch (err) { flash(err.message, 'error'); return; }
  }

  wiz.at += 1;
  await refresh();
  if (wiz.at >= wiz.steps.length) {
    $('#wizard').hidden = true;
    flash('Import finished. Create a document when you are ready.');
    show('panel-documents');
    return;
  }
  renderWizard();
}

function renderImports() {
  const list = $('#import-list');
  list.replaceChildren();
  for (const s of db.imports?.sources ?? []) {
    const card = document.createElement('article');
    card.className = 'card';
    const pending = s.counts?.pending || 0;
    card.innerHTML =
      `<h3>${esc(s.filename)}</h3>` +
      `<p class="meta">${esc(s.kind)} · ${Math.round((s.coverage || 0) * 100)}% accounted for · ` +
      `${pending} awaiting you · ${s.counts?.accepted || 0} added · ` +
      `${s.unparsed} unplaced passage${s.unparsed === 1 ? '' : 's'}</p>`;
    if (pending) card.append(button('Review', 'small', () => openWizard(s.id)));
    card.append(deleteButton(
      `Discard the import of “${s.filename}”? Anything already added stays in your library.`,
      `/api/imports/${s.id}`));
    list.append(card);
  }
  if (!list.children.length) list.innerHTML = '<p class="empty">No imports yet.</p>';
}

/* --------------------------------------------------------------- wiring ---- */

function show(panelId) {
  $$('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.panel === panelId)));
  $$('.panel').forEach(p => { p.hidden = p.id !== panelId; });
}

function wireDropzone(zone, input) {
  if (!zone || !input) return;
  zone.onclick = () => input.click();
  input.onchange = () => uploadFile(input.files[0]);
  ['dragenter', 'dragover'].forEach(e => zone.addEventListener(e, ev => {
    ev.preventDefault(); zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(e => zone.addEventListener(e, ev => {
    ev.preventDefault(); zone.classList.remove('over');
  }));
  zone.addEventListener('drop', ev => uploadFile(ev.dataTransfer?.files?.[0]));
}

wireDropzone($('#dropzone'), $('#onboard-file'));
wireDropzone($('#dropzone-2'), $('#import-file'));

$('#skip-import').onclick = () => {
  localStorage.setItem('cv_db.skipped_import', '1');
  $('#onboarding').hidden = true;
  show('panel-documents');
};

$('#wizard-close').onclick = () => { $('#wizard').hidden = true; };
$('#wizard-back').onclick = () => { if (wiz.at) { wiz.at -= 1; renderWizard(); } };
$('#wizard-skip').onclick = () => commitStep({ accept: false });
$('#wizard-next').onclick = () => commitStep({ accept: true });

$('#new-document').onclick = () => {
  show('panel-documents');
  $('#d-title')?.focus();
  $('#d-title')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
};


/* ------------------------------------------------------------------ reload -- */

/** Reload everything and repaint. Cheap at this scale, and it keeps the page
 *  and the database from drifting apart. */
async function refresh() {
  const open = new Set($$('.entry-row[open]').map(d => d.dataset.id));

  [db.meta, db.library] = await Promise.all([
    api('GET', '/api/meta'),
    api('GET', '/api/library'),
  ]);

  // Fall back to the first document if the remembered one has been deleted.
  const wanted = db.meta.documents.find(d => d.id === activeId()) ?? db.meta.documents[0];
  if (wanted) {
    setActive(wanted.id);
    [db.doc, db.versions] = await Promise.all([
      api('GET', `/api/documents/${wanted.id}`),
      api('GET', `/api/documents/${wanted.id}/versions`),
    ]);
  } else {
    db.doc = null;
    db.versions = [];
    localStorage.removeItem(ACTIVE_KEY);
  }

  db.imports = await api('GET', '/api/imports');

  renderChrome();
  renderImports();
  renderProfile();
  renderTree();
  renderLibrary();
  renderDocuments();
  renderSkills();
  renderReferences();
  renderVersions();
  $$('.entry-row').forEach(d => { if (open.has(d.dataset.id)) d.open = true; });

  // A library with nothing in it and no import under way means a new user.
  const bare = !db.library.entries.length && !db.library.skills.length
               && !db.meta.documents.length;
  const skipped = localStorage.getItem('cv_db.skipped_import');
  $('#onboarding').hidden = !(bare && !skipped && $('#wizard').hidden);
}

refresh().catch(err => flash(`Could not reach the server: ${err.message}`, 'error'));
