/* cv_db — form wiring. No framework, no build step.

   Two halves, mirroring the schema. `db.library` is your experience and knows
   nothing about documents. `db.doc` is one arrangement over it: headings,
   placements, cut bullets, chosen skills. Everything on screen is one or the
   other joined at render time. */

'use strict';

const db = { meta: null, library: { entries: [], skills: [] }, doc: null };

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
    ['entries', 'skills', 'profile'].forEach(s => style.append(option(s, s)));
    style.value = sec.style;
    style.onchange = () => write('PATCH', `/api/sections/${sec.id}`, { style: style.value });
    head.append(style);

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
    } else if (sec.style === 'skills') {
      const note = document.createElement('p');
      note.className = 'hint';
      note.innerHTML = `${db.doc.skill_ids.length} of ${db.library.skills.length} skills ` +
                       `ticked for this document — choose them on the <b>Skills</b> tab.`;
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
  const summary = document.createElement('summary');
  summary.innerHTML =
    `<span class="title">${esc(entryLabel(e))}</span> ` +
    `<span class="tag">#${shown.length ? 'entry' : 'item'}</span> ` +
    `<span class="meta">${esc(e.date_display || '')}</span>`;
  wrap.append(summary);

  const bar = document.createElement('div');
  bar.className = 'entry-bar';
  bar.append(checkbox(!!placement.include, 'Print this in the document',
    on => write('PATCH', `/api/documents/${db.doc.document.id}/place/${e.id}`,
                { include: on ? 1 : 0 })));

  // Moving between headings is the whole point: same entry, different section.
  const move = document.createElement('select');
  move.className = 'style-select';
  move.title = 'Move to another heading';
  db.doc.sections.filter(s => s.style === 'entries')
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
    const sections = db.doc.sections.filter(s => s.style === 'entries');
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
  (db.doc?.sections ?? []).filter(s => s.style === 'entries')
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
    status.textContent = out.compiled ? `wrote ${out.path} and ${out.pdf}`
                                      : `wrote ${out.path} — PDF not compiled`;
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

$$('.tab').forEach(tab => {
  tab.onclick = () => {
    $$('.tab').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
    $$('.panel').forEach(p => { p.hidden = p.id !== tab.dataset.panel; });
  };
});

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
    db.doc = await api('GET', `/api/documents/${wanted.id}`);
  } else {
    db.doc = null;
    localStorage.removeItem(ACTIVE_KEY);
  }

  renderChrome();
  renderTree();
  renderLibrary();
  renderDocuments();
  renderSkills();
  $$('.entry-row').forEach(d => { if (open.has(d.dataset.id)) d.open = true; });
}

refresh().catch(err => flash(`Could not reach the server: ${err.message}`, 'error'));
