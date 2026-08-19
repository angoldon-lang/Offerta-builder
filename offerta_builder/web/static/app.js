/* Offerta Builder - interfaccia locale.
 *
 * Regola di fondo: qui non si calcola nulla. Il browser raccoglie i dati e
 * mostra quello che il backend ha calcolato (prezzi, margini, IVA, QA). Anche
 * i numeri digitati a mano viaggiano come testo: a interpretarli è il parser
 * italiano del server, lo stesso usato per le BOM.
 */

const state = {
  session: '',
  schema: null,
  boms: [],
  overrides: {},
  preview: null,
  inflight: null,
};

const GRUPPI = [
  { titolo: 'Cliente', campi: ['cliente', 'piva', 'indirizzo_cliente', 'referente', 'email_referente'] },
  { titolo: 'Offerta', campi: ['oggetto', 'autore', 'riferimento_offerta', 'data_offerta', 'validita_offerta'] },
  { titolo: 'Condizioni', campi: ['tipologia_pagamento', 'condizioni_pagamento', 'fatturazione', 'durata_contratto_anni', 'rinnovo'] },
  { titolo: 'Testi', campi: ['premessa', 'requisiti_cliente', 'esclusioni', 'note_commerciali', 'allegati'] },
];
const CAMPI_PREZZO = ['iva_percento', 'margine_minimo_percento'];
const CAMPI_SALTATI = ['servizi_aggiuntivi'];
const STORAGE_KEY = 'offerta-builder-form';

/* ------------------------------------------------------------------ utility */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function toast(messaggio) {
  const el = $('#toast');
  el.textContent = messaggio;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2400);
}

function el(tag, attrs = {}, ...figli) {
  const nodo = document.createElement(tag);
  Object.entries(attrs).forEach(([chiave, valore]) => {
    if (valore === null || valore === undefined || valore === false) return;
    if (chiave === 'class') nodo.className = valore;
    else if (chiave === 'text') nodo.textContent = valore;
    else if (chiave.startsWith('on')) nodo.addEventListener(chiave.slice(2), valore);
    else nodo.setAttribute(chiave, valore);
  });
  figli.flat().forEach((figlio) => {
    if (figlio === null || figlio === undefined) return;
    nodo.appendChild(typeof figlio === 'string' ? document.createTextNode(figlio) : figlio);
  });
  return nodo;
}

async function api(percorso, opzioni = {}) {
  const risposta = await fetch(percorso, opzioni);
  if (risposta.status === 410) {
    toast('Sessione scaduta: ricarico la pagina.');
    setTimeout(() => window.location.reload(), 1200);
    throw new Error('sessione scaduta');
  }
  const dati = await risposta.json().catch(() => ({}));
  if (!risposta.ok) throw new Error(dati.messaggio || `Errore ${risposta.status}`);
  return dati;
}

/* --------------------------------------------------------------------- form */

function specDi(nome) {
  return (state.schema.campi || []).find((campo) => campo.nome === nome);
}

function campoInput(spec) {
  const id = `campo-${spec.nome}`;
  const listaLunga = spec.tipo === 'list';
  let controllo;

  if (spec.nome === 'premessa') {
    controllo = el('textarea', { id, placeholder: 'Lascia vuoto per generarla dai dati dell\'offerta' });
  } else if (listaLunga) {
    controllo = el('textarea', { id, placeholder: 'Una voce per riga' });
  } else if (spec.tipo === 'choice' && spec.scelte.length) {
    controllo = el('select', { id }, spec.scelte.map((scelta) => el('option', { value: scelta, text: scelta })));
  } else {
    controllo = el('input', { type: 'text', id, placeholder: spec.esempio || '' });
  }
  controllo.dataset.campo = spec.nome;
  controllo.addEventListener('input', pianificaAnteprima);
  controllo.addEventListener('change', pianificaAnteprima);

  const etichetta = el('label', { for: id }, spec.etichetta, spec.obbligatorio ? el('span', { class: 'req', text: ' *' }) : null);
  return el(
    'div',
    { class: `campo${listaLunga || spec.nome === 'premessa' ? ' wide' : ''}` },
    etichetta,
    controllo,
    spec.aiuto ? el('span', { class: 'aiuto', text: spec.aiuto }) : null
  );
}

function costruisciForm() {
  const contenitore = $('#gruppi-form');
  contenitore.innerHTML = '';
  GRUPPI.forEach((gruppo) => {
    const campi = gruppo.campi
      .filter((nome) => !CAMPI_SALTATI.includes(nome) && !CAMPI_PREZZO.includes(nome))
      .map((nome) => specDi(nome))
      .filter(Boolean)
      .map(campoInput);
    contenitore.appendChild(
      el('div', { class: 'gruppo' }, el('h3', { text: gruppo.titolo }), el('div', { class: 'campi' }, campi))
    );
  });
}

function costruisciControlliPrezzo() {
  const contenitore = $('#controlli-prezzo');
  contenitore.innerHTML = '';

  const modalita = el('select', { id: 'pricing-mode', onchange: () => { aggiornaVisibilitaPrezzo(); pianificaAnteprima(); } },
    [
      el('option', { value: 'markup', text: 'Markup sul costo' }),
      el('option', { value: 'target_margin', text: 'Margine obiettivo' }),
      el('option', { value: 'manual', text: 'Prezzo manuale per riga' }),
    ]);
  contenitore.appendChild(el('div', { class: 'campo' }, el('label', { for: 'pricing-mode', text: 'Modalità' }), modalita));

  const markup = el('input', { type: 'text', id: 'pricing-markup', value: '30', oninput: pianificaAnteprima });
  contenitore.appendChild(el('div', { class: 'campo', id: 'box-markup' }, el('label', { for: 'pricing-markup', text: 'Markup %' }), markup));

  const margine = el('input', { type: 'text', id: 'pricing-margine', value: '30', oninput: pianificaAnteprima });
  contenitore.appendChild(el('div', { class: 'campo', id: 'box-margine' }, el('label', { for: 'pricing-margine', text: 'Margine obiettivo %' }), margine));

  const arrotondamento = el('select', { id: 'pricing-round', onchange: pianificaAnteprima },
    (state.schema.arrotondamenti || ['0.01']).map((valore) => el('option', { value: valore, text: valore === 'none' ? 'nessuno' : `${valore} EUR` })));
  arrotondamento.value = '0.01';
  contenitore.appendChild(el('div', { class: 'campo' }, el('label', { for: 'pricing-round', text: 'Arrotondamento' }), arrotondamento));

  CAMPI_PREZZO.map(specDi).filter(Boolean).forEach((spec) => contenitore.appendChild(campoInput(spec)));
  aggiornaVisibilitaPrezzo();
}

function aggiornaVisibilitaPrezzo() {
  const modalita = $('#pricing-mode').value;
  $('#box-markup').hidden = modalita !== 'markup';
  $('#box-margine').hidden = modalita !== 'target_margin';
  $('#nota-righe').textContent = modalita === 'manual'
    ? 'Modalita manuale: il prezzo unitario va inserito riga per riga.'
    : 'Il prezzo unitario e\' modificabile riga per riga: diventa una deroga manuale.';
}

/* ------------------------------------------------------------------ servizi */

function rigaServizio(dati = {}) {
  const campo = (etichetta, chiave, valore, tipo = 'text') =>
    el('div', { class: 'campo' },
      el('label', { text: etichetta }),
      el('input', { type: tipo, value: valore ?? '', 'data-servizio': chiave, oninput: pianificaAnteprima }));

  const riga = el('div', { class: 'servizio' },
    campo('Descrizione', 'descrizione', dati.descrizione),
    campo('Q.tà', 'quantita', dati.quantita ?? 1),
    campo('Prezzo unitario', 'prezzo_unitario', dati.prezzo_unitario),
    campo('Costo unitario', 'costo_unitario', dati.costo_unitario),
    el('button', { type: 'button', class: 'ghost', title: 'Rimuovi', onclick: (ev) => { ev.target.closest('.servizio').remove(); pianificaAnteprima(); } }, 'X')
  );
  return riga;
}

function raccogliServizi() {
  return $$('#servizi .servizio').map((riga) => {
    const valori = {};
    riga.querySelectorAll('[data-servizio]').forEach((input) => { valori[input.dataset.servizio] = input.value.trim(); });
    return valori;
  }).filter((servizio) => servizio.descrizione);
}

/* --------------------------------------------------------------- raccolta */

function raccogliForm() {
  const form = {};
  $$('[data-campo]').forEach((controllo) => {
    const spec = specDi(controllo.dataset.campo);
    const valore = controllo.value.trim();
    if (spec && spec.tipo === 'list') {
      form[spec.nome] = valore ? valore.split('\n').map((v) => v.trim()).filter(Boolean) : [];
    } else {
      form[controllo.dataset.campo] = valore;
    }
  });
  form.servizi_aggiuntivi = raccogliServizi();
  form.pricing = {
    mode: $('#pricing-mode').value,
    markup_percent: $('#pricing-markup').value.trim() || '0',
    target_margin_percent: $('#pricing-margine').value.trim() || '0',
    rounding: $('#pricing-round').value,
    overrides: Object.values(state.overrides),
  };
  return form;
}

function salvaLocale() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ form: raccogliForm(), overrides: state.overrides }));
  } catch (errore) { /* quota piena o modalità privata: non è critico */ }
}

function ripristinaLocale() {
  let salvato;
  try { salvato = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (errore) { salvato = null; }
  if (!salvato || !salvato.form) return;
  applicaForm(salvato.form);
  state.overrides = salvato.overrides || {};
}

function applicaForm(form) {
  Object.entries(form).forEach(([nome, valore]) => {
    if (nome === 'pricing' || nome === 'servizi_aggiuntivi') return;
    const controllo = document.querySelector(`[data-campo="${nome}"]`);
    if (!controllo) return;
    controllo.value = Array.isArray(valore) ? valore.join('\n') : (valore ?? '');
  });
  if (form.pricing) {
    $('#pricing-mode').value = form.pricing.mode || 'markup';
    $('#pricing-markup').value = form.pricing.markup_percent ?? '30';
    $('#pricing-margine').value = form.pricing.target_margin_percent ?? '30';
    $('#pricing-round').value = form.pricing.rounding || '0.01';
    aggiornaVisibilitaPrezzo();
  }
  const servizi = $('#servizi');
  servizi.innerHTML = '';
  (form.servizi_aggiuntivi || []).forEach((servizio) => servizi.appendChild(rigaServizio(servizio)));
}

/* ------------------------------------------------------------------ upload */

async function caricaFile(files, campo) {
  if (!files || !files.length) return;
  const dati = new FormData();
  dati.append('session', state.session);
  Array.from(files).forEach((file) => dati.append(campo, file));
  toast('Caricamento in corso...');
  const risposta = await api('/api/upload', { method: 'POST', body: dati });
  state.session = risposta.session;
  state.boms = risposta.boms;
  $('#stato-sessione').textContent = `sessione ${risposta.session.slice(0, 6)}`;

  if (risposta.template) {
    const tag = $('#tag-template');
    tag.textContent = risposta.template;
    tag.hidden = false;
  }
  const errori = $('#errori-upload');
  if (risposta.errori && risposta.errori.length) {
    errori.textContent = risposta.errori.join(' | ');
    errori.hidden = false;
  } else {
    errori.hidden = true;
  }
  applicaPrefill(risposta.prefill || {});
  disegnaBoms();
  pianificaAnteprima(0);
}

function applicaPrefill(prefill) {
  Object.entries(prefill).forEach(([nome, valore]) => {
    const controllo = document.querySelector(`[data-campo="${nome}"]`);
    if (controllo && !controllo.value.trim()) controllo.value = valore;
  });
}

function disegnaBoms() {
  const contenitore = $('#elenco-bom');
  contenitore.innerHTML = '';
  state.boms.forEach((bom, indice) => {
    const anomalie = (bom.anomalie || []).map((anomalia) =>
      el('div', { class: `voce${anomalia.severity === 'blocking' ? ' blocking' : ''}`, text: anomalia.message }));

    const righe = (bom.articoli || []).map((articolo) => el('tr', {},
      el('td', { class: 'num', text: String(articolo.n) }),
      el('td', { text: articolo.sku }),
      el('td', { text: articolo.descrizione }),
      el('td', { text: articolo.periodo }),
      el('td', { class: 'num', text: articolo.quantita }),
      el('td', { class: 'num', text: articolo.listino }),
      el('td', { class: 'num', text: articolo.sconto }),
      el('td', { class: 'num', text: articolo.costo })));

    contenitore.appendChild(el('div', { class: 'bom' },
      el('div', { class: 'bom-head' },
        el('span', { class: 'titolo', text: bom.distributore || 'Distributore non identificato' }),
        el('span', { class: 'meta', text: `${bom.file} - ${bom.righe} righe - costo ${bom.costo}` }),
        el('span', { class: 'meta', text: bom.quote ? `quote ${bom.quote}` : '' }),
        el('span', { class: 'meta', text: bom.validita ? `validita ${bom.validita}` : '' }),
        el('button', { type: 'button', class: 'ghost rimuovi', onclick: () => rimuoviBom(indice) }, 'Rimuovi')),
      anomalie.length ? el('div', { class: 'anomalies', style: 'padding:.5rem .8rem' }, anomalie) : null,
      el('details', {},
        el('summary', { text: `Mostra le ${bom.righe} righe lette` }),
        el('div', { class: 'table-scroll' },
          el('table', {},
            el('thead', {}, el('tr', {},
              el('th', { class: 'num', text: '#' }), el('th', { text: 'Codice' }), el('th', { text: 'Descrizione' }),
              el('th', { text: 'Periodo' }), el('th', { class: 'num', text: 'Q.ta' }),
              el('th', { class: 'num', text: 'Listino' }), el('th', { class: 'num', text: 'Sconto' }),
              el('th', { class: 'num', text: 'Costo' }))),
            el('tbody', {}, righe))))));
  });
}

async function rimuoviBom(indice) {
  const risposta = await api('/api/rimuovi-bom', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: state.session, indice }),
  });
  state.boms = risposta.boms;
  disegnaBoms();
  pianificaAnteprima(0);
}

/* --------------------------------------------------------------- anteprima */

let timerAnteprima = null;
function pianificaAnteprima(ritardo = 550) {
  salvaLocale();
  clearTimeout(timerAnteprima);
  timerAnteprima = setTimeout(anteprima, ritardo);
}

async function anteprima() {
  if (!state.session || !state.boms.length) return;
  const corpo = JSON.stringify({ session: state.session, form: raccogliForm(), force: true });
  const risposta = await api('/api/anteprima', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: corpo,
  }).catch(() => null);
  if (!risposta) return;
  state.preview = risposta;

  if (risposta.stato !== 'ok') {
    $('#msg-anteprima').textContent = risposta.messaggio || 'Anteprima non disponibile.';
    return;
  }
  disegnaTotali(risposta.totali);
  disegnaRighe(risposta.righe);
  disegnaAnomalie(risposta.anomalie || []);
  $('#msg-anteprima').textContent = `${risposta.totali.righe} righe - sconto medio ${risposta.totali.sconto_medio}`;
}

function disegnaTotali(totali) {
  $('#t-costo').textContent = totali.costo;
  $('#t-imponibile').textContent = totali.imponibile;
  $('#t-iva').textContent = totali.iva;
  $('#t-totale').textContent = totali.totale;
  $('#t-margine').textContent = `${totali.margine} (${totali.margine_percento})`;

  const soglia = parseFloat(($('[data-campo="margine_minimo_percento"]').value || '0').replace(',', '.')) || 0;
  const barra = $('#barra-margine');
  barra.hidden = false;
  barra.classList.toggle('sotto', soglia > 0 && totali.margine_valore < soglia);
  barra.querySelector('.fill').style.width = `${Math.max(0, Math.min(100, totali.margine_valore))}%`;
  barra.querySelector('.soglia').style.left = `${Math.max(0, Math.min(100, soglia))}%`;
  barra.title = `Margine ${totali.margine_percento} - soglia minima ${soglia}%`;
}

function disegnaRighe(righe) {
  const corpo = $('#tabella-righe tbody');
  corpo.innerHTML = '';
  if (!righe.length) {
    corpo.appendChild(el('tr', {}, el('td', { colspan: '9', class: 'vuoto', text: 'Nessuna riga: carica una BOM.' })));
    return;
  }
  const soglia = parseFloat(($('[data-campo="margine_minimo_percento"]').value || '0').replace(',', '.')) || 0;

  righe.forEach((riga) => {
    const chiave = riga.sku || riga.descrizione;
    const derogata = Boolean(state.overrides[chiave]);
    const input = el('input', {
      type: 'text', class: 'prezzo', value: riga.prezzo_unitario.replace(' EUR', ''),
      title: 'Modifica per fissare un prezzo manuale su questa riga',
    });
    input.addEventListener('change', () => {
      const valore = input.value.trim();
      if (valore) state.overrides[chiave] = { match: chiave, sell_net_unit: valore };
      else delete state.overrides[chiave];
      pianificaAnteprima(0);
    });

    const sottoSoglia = soglia > 0 && riga.margine_valore < soglia && riga.modalita !== 'servizio';
    corpo.appendChild(el('tr', { class: sottoSoglia ? 'sotto-soglia' : '' },
      el('td', { class: 'num', text: String(riga.indice + 1) }),
      el('td', { text: riga.sku }),
      el('td', { text: riga.descrizione }),
      el('td', { class: 'num', text: riga.quantita }),
      el('td', { class: 'num', text: riga.costo }),
      el('td', { class: 'num' }, input, derogata ? el('span', { class: 'manuale', text: 'deroga manuale' }) : null),
      el('td', { class: 'num', text: riga.totale }),
      el('td', { class: 'num', text: `${riga.margine} (${riga.margine_percento})` }),
      el('td', {}, derogata
        ? el('button', { type: 'button', class: 'link', onclick: () => { delete state.overrides[chiave]; pianificaAnteprima(0); } }, 'ripristina')
        : null)));
  });
}

function disegnaAnomalie(anomalie) {
  const contenitore = $('#anomalie');
  contenitore.innerHTML = '';
  const viste = new Set();
  anomalie.forEach((anomalia) => {
    if (viste.has(anomalia.message)) return;
    viste.add(anomalia.message);
    contenitore.appendChild(el('div', {
      class: `voce${anomalia.severity === 'blocking' ? ' blocking' : ''}`,
      text: anomalia.message,
    }));
  });
}

/* ----------------------------------------------------------------- genera */

async function genera() {
  if (!state.session || !state.boms.length) { toast('Carica prima una BOM.'); return; }
  const pulsanti = [$('#btn-genera'), $('#btn-genera-2')];
  pulsanti.forEach((b) => { b.disabled = true; });
  $('#btn-genera').textContent = 'Generazione in corso...';

  try {
    const risposta = await api('/api/genera', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session: state.session,
        form: raccogliForm(),
        pdf: $('#opt-pdf').checked,
        ai: $('#opt-ai').checked,
        force: $('#opt-force').checked,
      }),
    });
    mostraEsito(risposta);
  } catch (errore) {
    toast(errore.message);
  } finally {
    pulsanti.forEach((b) => { b.disabled = false; });
    $('#btn-genera').textContent = 'Genera offerta';
  }
}

function mostraEsito(risposta) {
  const esito = $('#esito');
  esito.hidden = false;
  const riepilogo = $('#qa-riepilogo');
  const lista = $('#qa-lista');
  const download = $('#download');
  lista.innerHTML = '';
  download.innerHTML = '';

  if (risposta.stato === 'bloccato') {
    riepilogo.className = 'alert error';
    riepilogo.textContent = `Flusso interrotto: ${risposta.messaggio}`;
    (risposta.anomalie || []).forEach((anomalia) => {
      lista.appendChild(el('li', {}, el('span', { class: 'badge fail', text: 'STOP' }), anomalia.message));
    });
    lista.appendChild(el('li', {}, el('span', { class: 'badge warn', text: 'NOTA' }),
      'Correggi i dati, oppure spunta "Procedi anche con anomalie bloccanti" per generare comunque.'));
    esito.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }

  const qa = risposta.qa || {};
  const stato = qa.status || 'ok';
  riepilogo.className = `alert ${stato === 'fail' ? 'error' : (stato === 'warn' ? 'warn' : 'ok')}`;
  riepilogo.textContent = stato === 'fail'
    ? `QA in errore: ${qa.errori} da correggere, ${qa.avvisi} avvisi. Il DOCX è stato generato per permetterti di vedere il problema.`
    : (stato === 'warn'
      ? `QA superato con ${qa.avvisi} avvisi da valutare.`
      : 'QA superato: nessuna anomalia.');

  (qa.controlli || []).forEach((controllo) => {
    lista.appendChild(el('li', {},
      el('span', { class: `badge ${controllo.esito}`, text: controllo.esito.toUpperCase() }),
      el('span', {}, el('strong', { text: `${controllo.titolo}: ` }), controllo.messaggio)));
  });
  (risposta.note || []).forEach((nota) => {
    lista.appendChild(el('li', {}, el('span', { class: 'badge warn', text: 'NOTA' }), nota.message));
  });

  (risposta.file || []).forEach((file) => {
    download.appendChild(el('a', { href: file.url, download: file.nome },
      el('strong', { text: file.nome }),
      el('span', { text: `${Math.max(1, Math.round(file.byte / 1024))} KB` })));
  });
  if ((risposta.file || []).length > 1) {
    download.appendChild(el('a', { href: risposta.zip, download: 'offerta.zip' },
      el('strong', { text: 'Tutto (zip)' }), el('span', { text: 'archivio completo' })));
  }
  if (risposta.totali) disegnaTotali(risposta.totali);
  toast('Offerta generata');
  esito.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* -------------------------------------------------------------------- init */

function collegaDropzone(zona, input, campo) {
  const nodo = $(zona);
  const controllo = $(input);
  nodo.addEventListener('click', (ev) => { if (ev.target !== controllo) controllo.click(); });
  controllo.addEventListener('change', () => caricaFile(controllo.files, campo));
  ['dragenter', 'dragover'].forEach((evento) =>
    nodo.addEventListener(evento, (ev) => { ev.preventDefault(); nodo.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((evento) =>
    nodo.addEventListener(evento, (ev) => { ev.preventDefault(); nodo.classList.remove('over'); }));
  nodo.addEventListener('drop', (ev) => caricaFile(ev.dataTransfer.files, campo));
}

async function init() {
  state.schema = await api('/api/schema');
  costruisciForm();
  costruisciControlliPrezzo();
  $('#servizi').innerHTML = '';
  ripristinaLocale();

  const data = document.querySelector('[data-campo="data_offerta"]');
  if (data && !data.value) data.value = state.schema.oggi;

  collegaDropzone('#drop-bom', '#input-bom', 'bom');
  collegaDropzone('#drop-template', '#input-template', 'template');
  $('#btn-aggiungi-servizio').addEventListener('click', () => { $('#servizi').appendChild(rigaServizio()); });
  $('#btn-genera').addEventListener('click', genera);
  $('#btn-genera-2').addEventListener('click', genera);
  $('#btn-nuova').addEventListener('click', async () => {
    if (!confirm('Ricomincio da capo? I file caricati vengono scartati.')) return;
    const risposta = await api('/api/nuova', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: state.session }),
    });
    state.session = risposta.session;
    state.boms = [];
    state.overrides = {};
    disegnaBoms();
    disegnaRighe([]);
    $('#esito').hidden = true;
    $('#tag-template').hidden = true;
    $('#msg-anteprima').textContent = 'Carica una BOM per vedere i totali.';
    toast('Nuova offerta');
  });
  disegnaRighe([]);
}

init().catch((errore) => toast(`Avvio non riuscito: ${errore.message}`));
