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
  righe: {},
  rinnovo: null,
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
  if (!risposta.ok) throw new Error(dati.messaggio || dati.errore || `Errore ${risposta.status}`);
  return dati;
}

/* --------------------------------------------------------------------- form */

function specDi(nome) {
  return (state.schema.campi || []).find((campo) => campo.nome === nome);
}

const VALORE_ALTRO = '__altro__';

function campoInput(spec) {
  const id = `campo-${spec.nome}`;
  const listaLunga = spec.tipo === 'list';
  const proposte = (spec.scelte && spec.scelte.length) ? spec.scelte : (spec.suggerimenti || []);
  let controllo;
  let libero = null;

  if (spec.nome === 'premessa') {
    controllo = el('textarea', { id, placeholder: 'Lascia vuoto per generarla dai dati dell\'offerta' });
  } else if (listaLunga) {
    controllo = el('textarea', { id, placeholder: 'Una voce per riga' });
  } else if (proposte.length) {
    // Tendina con i valori piu' usati, piu' "Altro" per scriverne uno diverso.
    controllo = el('select', { id },
      el('option', { value: '', text: '- scegli -' }),
      proposte.map((scelta) => el('option', { value: scelta, text: scelta })),
      el('option', { value: VALORE_ALTRO, text: 'Altro (scrivi tu)...' }));
    libero = el('input', {
      type: 'text', placeholder: spec.esempio || 'Valore personalizzato', hidden: true,
      oninput: pianificaAnteprima,
    });
    libero.dataset.campoLibero = spec.nome;
    controllo.addEventListener('change', () => {
      libero.hidden = controllo.value !== VALORE_ALTRO;
      if (!libero.hidden) libero.focus();
    });
  } else {
    controllo = el('input', { type: 'text', id, placeholder: spec.esempio || '' });
  }
  if (spec.default && controllo.tagName !== 'SELECT' && !controllo.value) controllo.value = spec.default;
  controllo.dataset.campo = spec.nome;
  controllo.addEventListener('input', pianificaAnteprima);
  controllo.addEventListener('change', pianificaAnteprima);

  const etichetta = el('label', { for: id }, spec.etichetta, spec.obbligatorio ? el('span', { class: 'req', text: ' *' }) : null);
  return el(
    'div',
    { class: `campo${listaLunga || spec.nome === 'premessa' ? ' wide' : ''}` },
    etichetta,
    controllo,
    libero,
    spec.aiuto ? el('span', { class: 'aiuto', text: spec.aiuto }) : null
  );
}

function valoreCampo(controllo) {
  if (controllo.tagName === 'SELECT' && controllo.value === VALORE_ALTRO) {
    const libero = controllo.parentElement.querySelector('[data-campo-libero]');
    return libero ? libero.value.trim() : '';
  }
  return controllo.value.trim();
}

function impostaCampo(controllo, valore) {
  if (controllo.tagName !== 'SELECT') {
    controllo.value = valore;
    return;
  }
  const opzioni = Array.from(controllo.options).map((o) => o.value);
  const libero = controllo.parentElement.querySelector('[data-campo-libero]');
  if (valore && !opzioni.includes(valore)) {
    controllo.value = VALORE_ALTRO;
    if (libero) { libero.value = valore; libero.hidden = false; }
  } else {
    controllo.value = valore;
    if (libero) libero.hidden = controllo.value !== VALORE_ALTRO;
  }
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
      el('option', { value: 'target_margin', text: 'Margine obiettivo (sul prezzo di vendita)' }),
      el('option', { value: 'markup', text: 'Markup (ricarico sul costo)' }),
      el('option', { value: 'manual', text: 'Prezzo manuale per riga' }),
    ]);
  contenitore.appendChild(el('div', { class: 'campo' }, el('label', { for: 'pricing-mode', text: 'Modalità' }), modalita));

  const markup = el('input', { type: 'text', id: 'pricing-markup', value: '30', oninput: pianificaAnteprima });
  contenitore.appendChild(el('div', { class: 'campo', id: 'box-markup' },
    el('label', { for: 'pricing-markup', text: 'Markup % sul costo' }), markup,
    el('span', { class: 'aiuto', text: 'costo x (1 + markup)' })));

  const margine = el('input', { type: 'text', id: 'pricing-margine', value: '30', oninput: pianificaAnteprima });
  contenitore.appendChild(el('div', { class: 'campo', id: 'box-margine' },
    el('label', { for: 'pricing-margine', text: 'Margine obiettivo %' }), margine,
    el('span', { class: 'aiuto', text: 'margine effettivo sul venduto' })));

  const arrotondamento = el('select', { id: 'pricing-round', onchange: pianificaAnteprima },
    (state.schema.arrotondamenti || ['0.01']).map((valore) => el('option', { value: valore, text: valore === 'none' ? 'nessuno' : `${valore} EUR` })));
  arrotondamento.value = '0.01';
  contenitore.appendChild(el('div', { class: 'campo' }, el('label', { for: 'pricing-round', text: 'Arrotondamento' }), arrotondamento));

  CAMPI_PREZZO.map(specDi).filter(Boolean).forEach((spec) => contenitore.appendChild(campoInput(spec)));

  const adeguamento = el('input', { type: 'text', id: 'pricing-adeguamento', value: '0', oninput: pianificaAnteprima });
  const boxAdeguamento = el('div', { class: 'campo', id: 'box-adeguamento', hidden: true },
    el('label', { for: 'pricing-adeguamento', text: 'Adeguamento prezzi %' }), adeguamento,
    el('span', { class: 'aiuto', text: 'sui prezzi ripresi dalla vecchia offerta' }));
  contenitore.appendChild(boxAdeguamento);

  const estese = el('input', { type: 'checkbox', id: 'pricing-descrizioni', onchange: pianificaAnteprima });
  contenitore.appendChild(el('div', { class: 'campo' },
    el('label', { for: 'pricing-descrizioni', text: 'Descrizioni' }),
    el('label', { class: 'check' }, estese, ' codice e periodo in descrizione')));

  $('#pricing-mode').value = 'target_margin';
  aggiornaVisibilitaPrezzo();
}

function aggiornaVisibilitaPrezzo() {
  const modalita = $('#pricing-mode').value;
  $('#box-markup').hidden = modalita !== 'markup';
  $('#box-margine').hidden = modalita !== 'target_margin';
  $('#nota-righe').textContent = modalita === 'manual'
    ? 'Modalità manuale: il prezzo va scritto riga per riga nella tabella qui sotto.'
    : 'Codice, descrizione, quantità e prezzo sono modificabili riga per riga. Il prezzo parte già dal '
      + 'margine impostato qui sopra; se lo riscrivi resta quello che hai scritto tu.';
}

/* ------------------------------------------------------------------ servizi */

function rigaServizio(dati = {}) {
  const campo = (etichetta, chiave, valore, titolo = '') =>
    el('div', { class: 'campo' },
      el('label', { text: etichetta }),
      el('input', { type: 'text', value: valore ?? '', 'data-servizio': chiave, title: titolo, oninput: pianificaAnteprima }));

  const blocco = el('select', { 'data-servizio': 'blocco', onchange: pianificaAnteprima },
    el('option', { value: 'prodotti', text: 'Materiali' }),
    el('option', { value: 'servizi', text: 'Servizi' }));
  blocco.value = dati.blocco || 'servizi';

  return el('div', { class: 'servizio' },
    campo('Descrizione', 'descrizione', dati.descrizione),
    el('div', { class: 'campo' }, el('label', { text: 'Blocco' }), blocco),
    campo('Q.tà', 'quantita', dati.quantita ?? 1),
    campo('Prezzo', 'prezzo_unitario', dati.prezzo_unitario, 'Un importo, oppure un testo come "Incluso"'),
    campo('Costo', 'costo_unitario', dati.costo_unitario),
    el('button', { type: 'button', class: 'ghost', title: 'Rimuovi', onclick: (ev) => { ev.target.closest('.servizio').remove(); pianificaAnteprima(); } }, 'X')
  );
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
    const valore = valoreCampo(controllo);
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
  form.righe = Object.values(state.righe);
  form.descrizioni_estese = $('#pricing-descrizioni').checked;
  form.adeguamento_percent = $('#pricing-adeguamento').value.trim() || '0';
  // Le voci aggiunte a mano vanno nel blocco scelto: materiali o servizi.
  const voci = raccogliServizi();
  form.servizi_aggiuntivi = voci.filter((v) => v.blocco !== 'prodotti');
  form.righe_aggiuntive = voci.filter((v) => v.blocco === 'prodotti');
  return form;
}

function salvaLocale() {
  try {
    const form = raccogliForm();
    delete form.righe;  // le modifiche di riga valgono per le BOM caricate ora
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ form, overrides: state.overrides }));
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
    impostaCampo(controllo, Array.isArray(valore) ? valore.join('\n') : String(valore ?? ''));
  });
  if (form.descrizioni_estese !== undefined) $('#pricing-descrizioni').checked = Boolean(form.descrizioni_estese);
  if (form.pricing) {
    $('#pricing-mode').value = form.pricing.mode || 'markup';
    $('#pricing-markup').value = form.pricing.markup_percent ?? '30';
    $('#pricing-margine').value = form.pricing.target_margin_percent ?? '30';
    $('#pricing-round').value = form.pricing.rounding || '0.01';
    aggiornaVisibilitaPrezzo();
  }
  const servizi = $('#servizi');
  servizi.innerHTML = '';
  (form.servizi_aggiuntivi || []).forEach((voce) => servizi.appendChild(rigaServizio({ ...voce, blocco: 'servizi' })));
  (form.righe_aggiuntive || []).forEach((voce) => servizi.appendChild(rigaServizio({ ...voce, blocco: 'prodotti' })));
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
  // Le modifiche di riga sono legate alla posizione: cambiando l'insieme delle
  // BOM ripartono da zero, altrimenti finirebbero sulle righe sbagliate.
  state.righe = {};
  forzaRidisegnoRighe();
  aggiornaContatoreModifiche();
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

async function caricaOffertaPrecedente(files) {
  if (!files || !files.length) return;
  const dati = new FormData();
  dati.append('session', state.session);
  dati.append('offerta', files[0]);
  dati.append('giorni_validita', ($('#rinnovo-giorni') || {}).value || '30');
  toast('Lettura offerta precedente...');

  const risposta = await api('/api/offerta-precedente', { method: 'POST', body: dati })
    .catch((errore) => { mostraErroreRinnovo(errore.message); return null; });
  if (!risposta || risposta.stato !== 'ok') return;

  state.session = risposta.session;
  state.boms = risposta.boms;
  state.righe = {};
  state.rinnovo = risposta;
  forzaRidisegnoRighe();
  aggiornaContatoreModifiche();

  const tag = $('#tag-vecchia');
  tag.textContent = risposta.file;
  tag.hidden = false;

  // Nel rinnovo i dati della vecchia offerta vincono su quelli a video.
  Object.entries(risposta.form || {}).forEach(([nome, valore]) => {
    const controllo = document.querySelector(`[data-campo="${nome}"]`);
    if (controllo && valore) impostaCampo(controllo, String(valore));
  });

  $('#box-adeguamento').hidden = false;
  if (risposta.template) {
    const tagTemplate = $('#tag-template');
    tagTemplate.textContent = risposta.template;
    tagTemplate.hidden = false;
  }

  const info = $('#rinnovo-info');
  info.className = 'alert ok';
  info.textContent = `Rinnovo da "${risposta.file}": ${risposta.righe} righe recuperate, `
    + `totale precedente ${risposta.totale_precedente || 'n/d'}. `
    + 'Date e riferimento sono già aggiornati; il margine resta sconosciuto finché non carichi una BOM aggiornata.'
    + (risposta.template ? ' Il documento caricato fa anche da modello.' : '');
  info.hidden = false;

  disegnaBoms();
  // L'offerta rinnovata si genera subito: si trova già pronta da rileggere.
  await anteprima();
  await genera();
}

function mostraErroreRinnovo(messaggio) {
  const info = $('#rinnovo-info');
  info.className = 'alert error';
  info.textContent = messaggio;
  info.hidden = false;
  toast('Offerta precedente non letta');
}

function applicaPrefill(prefill) {
  Object.entries(prefill).forEach(([nome, valore]) => {
    const controllo = document.querySelector(`[data-campo="${nome}"]`);
    if (controllo && !valoreCampo(controllo)) impostaCampo(controllo, valore);
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
        el('span', { class: 'meta', text: bom.validita ? `validità ${bom.validita}` : '' }),
        el('span', { class: 'meta', text: bom.periodo_contratto || '' }),
        el('span', { class: 'meta', title: 'Condizioni fra distributore e rivenditore, non verso il cliente', text: bom.pagamento_distributore ? `pagamento distributore: ${bom.pagamento_distributore}` : '' }),
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
  state.righe = {};
  forzaRidisegnoRighe();
  aggiornaContatoreModifiche();
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
  $('#t-margine').textContent = totali.margine_percento
    ? `${totali.margine} (${totali.margine_percento})`
    : totali.margine;

  const soglia = parseFloat(($('[data-campo="margine_minimo_percento"]').value || '0').replace(',', '.')) || 0;
  const barra = $('#barra-margine');
  if (totali.margine_noto === false) {
    barra.hidden = true;
    $('#t-margine').textContent = totali.margine;
    return;
  }
  barra.hidden = false;
  barra.classList.toggle('sotto', soglia > 0 && totali.margine_valore < soglia);
  barra.querySelector('.fill').style.width = `${Math.max(0, Math.min(100, totali.margine_valore))}%`;
  barra.querySelector('.soglia').style.left = `${Math.max(0, Math.min(100, soglia))}%`;
  barra.title = `Margine ${totali.margine_percento} - soglia minima ${soglia}%`;
}

function modificaDi(indice, riferimento) {
  if (!state.righe[indice]) state.righe[indice] = { indice, riferimento };
  return state.righe[indice];
}

function registraModifica(tr, input) {
  if (input) input.dataset.dirty = '1';
  const indice = Number(tr.dataset.indice);
  const modifica = modificaDi(indice, tr.dataset.riferimento);
  // Vengono inviati solo i campi toccati davvero: cosi' correggere una
  // descrizione non blocca anche il prezzo calcolato dal margine.
  tr.querySelectorAll('input[data-colonna]').forEach((campo) => {
    if (campo.dataset.dirty === '1') modifica[campo.dataset.colonna] = campo.value.trim();
  });
  aggiornaContatoreModifiche();
  pianificaAnteprima();
}

function ripristinaRiga(indice) {
  delete state.righe[indice];
  aggiornaContatoreModifiche();
  forzaRidisegnoRighe();
  pianificaAnteprima(0);
}

function forzaRidisegnoRighe() {
  const corpo = $('#tabella-righe tbody');
  if (corpo) corpo.dataset.chiavi = '';
}

function aggiornaContatoreModifiche() {
  const quante = Object.keys(state.righe).length;
  const pulsante = $('#btn-azzera-righe');
  if (!pulsante) return;
  pulsante.hidden = quante === 0;
  pulsante.textContent = quante === 1 ? 'Azzera 1 modifica di riga' : `Azzera ${quante} modifiche di riga`;
}

function testoMargine(riga) {
  if (riga.esclusa) return '-';
  if (!riga.margine_percento) return 'n/d';
  return `${riga.margine} (${riga.margine_percento})`;
}

function prezzoModificabile(riga) {
  // Nel campo si scrive l'importo senza simbolo, oppure il testo così com'è
  // (una riga "Incluso" resta "Incluso").
  return (riga.prezzo_unitario || '').replace(' €', '').replace(' EUR', '');
}

function cellaTesto(riga, colonna, valore, classe) {
  const input = el('input', {
    type: 'text', class: `cella ${classe || ''}`, value: valore || '',
    title: 'Clicca e scrivi: questo testo finisce nell\'offerta', placeholder: 'vuoto',
  });
  input.dataset.colonna = colonna;
  input.dataset.valoreServer = valore || '';
  if (state.righe[riga.indice] && state.righe[riga.indice][colonna] !== undefined) input.dataset.dirty = '1';
  input.addEventListener('input', (ev) => registraModifica(ev.target.closest('tr'), ev.target));
  return input;
}

function disegnaRighe(righe) {
  const corpo = $('#tabella-righe tbody');
  if (!righe.length) {
    corpo.dataset.chiavi = '';
    corpo.innerHTML = '';
    corpo.appendChild(el('tr', {}, el('td', { colspan: '9', class: 'vuoto', text: 'Nessuna riga: carica una BOM.' })));
    return;
  }

  const impronta = righe.map((riga) => `${riga.indice}:${riga.esclusa ? 1 : 0}`).join('|');
  if (corpo.dataset.chiavi === impronta) {
    aggiornaCelleRighe(righe);
    return;
  }
  corpo.dataset.chiavi = impronta;
  corpo.innerHTML = '';

  righe.forEach((riga) => {
    const tr = el('tr', { class: riga.esclusa ? 'riga-esclusa' : '' });
    tr.dataset.indice = String(riga.indice);
    tr.dataset.riferimento = riga.riferimento || '';

    tr.appendChild(el('td', { class: 'num numero', text: riga.esclusa ? '-' : String(riga.numero) }));
    tr.appendChild(el('td', {}, cellaTesto(riga, 'sku', riga.sku, 'c-sku')));
    tr.appendChild(el('td', {}, cellaTesto(riga, 'descrizione', riga.descrizione, 'c-desc')));
    tr.appendChild(el('td', { class: 'num' }, cellaTesto(riga, 'quantita', riga.quantita_valore, 'c-qta num')));
    tr.appendChild(el('td', { class: 'num costo', text: riga.costo, title: 'Costo di acquisto dalla BOM' }));
    tr.appendChild(el('td', { class: 'num' },
      cellaTesto(riga, 'prezzo_unitario', prezzoModificabile(riga), 'c-prezzo prezzo num'),
      el('span', { class: 'manuale', text: riga.modificata ? 'modificata' : '' })));
    tr.appendChild(el('td', { class: 'num totale', text: riga.esclusa ? 'esclusa' : riga.totale }));
    tr.appendChild(el('td', { class: 'num margine', text: testoMargine(riga) }));

    const azioni = el('td', { class: 'azioni' });
    if (riga.esclusa) {
      azioni.appendChild(el('button', {
        type: 'button', class: 'link', title: 'Rimetti la riga nell\'offerta',
        onclick: () => { modificaDi(riga.indice, riga.riferimento).escludi = false; forzaRidisegnoRighe(); pianificaAnteprima(0); },
      }, 'rimetti'));
    } else {
      azioni.appendChild(el('button', {
        type: 'button', class: 'link', title: 'Togli la riga dall\'offerta',
        onclick: () => { modificaDi(riga.indice, riga.riferimento).escludi = true; aggiornaContatoreModifiche(); forzaRidisegnoRighe(); pianificaAnteprima(0); },
      }, 'togli'));
    }
    if (state.righe[riga.indice]) {
      azioni.appendChild(el('button', {
        type: 'button', class: 'link', title: 'Torna ai valori della BOM',
        onclick: () => ripristinaRiga(riga.indice),
      }, 'ripristina'));
    }
    tr.appendChild(azioni);
    corpo.appendChild(tr);
  });
  aggiornaCelleRighe(righe);
}

function aggiornaCelleRighe(righe) {
  const soglia = parseFloat(($('[data-campo="margine_minimo_percento"]').value || '0').replace(',', '.')) || 0;
  righe.forEach((riga) => {
    const tr = $(`#tabella-righe tbody tr[data-indice="${riga.indice}"]`);
    if (!tr) return;
    tr.querySelector('.numero').textContent = riga.esclusa ? '-' : String(riga.numero);
    tr.querySelector('.costo').textContent = riga.costo;
    tr.querySelector('.totale').textContent = riga.esclusa ? 'esclusa' : riga.totale;
    tr.querySelector('.margine').textContent = testoMargine(riga);
    const manuale = tr.querySelector('.manuale');
    if (manuale) manuale.textContent = riga.modificata ? 'modificata' : '';

    // Senza costo il margine non si conosce: inutile colorare la riga di rosso.
    const margineNoto = Boolean(riga.margine_percento);
    const sottoSoglia = margineNoto && !riga.esclusa && soglia > 0
      && riga.margine_valore < soglia && riga.modalita !== 'servizio';
    tr.classList.toggle('sotto-soglia', sottoSoglia);

    // I campi che l'utente sta compilando non vengono toccati.
    tr.querySelectorAll('input[data-colonna]').forEach((campo) => {
      if (document.activeElement === campo || campo.dataset.dirty === '1') return;
      const valori = {
        sku: riga.sku,
        descrizione: riga.descrizione,
        quantita: riga.quantita_valore,
        prezzo_unitario: prezzoModificabile(riga),
      };
      campo.value = valori[campo.dataset.colonna] ?? campo.value;
    });
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

function collegaDropzoneRinnovo() {
  const nodo = $('#drop-vecchia');
  const controllo = $('#input-vecchia');
  nodo.addEventListener('click', (ev) => { if (ev.target !== controllo) controllo.click(); });
  controllo.addEventListener('change', () => caricaOffertaPrecedente(controllo.files));
  ['dragenter', 'dragover'].forEach((evento) =>
    nodo.addEventListener(evento, (ev) => { ev.preventDefault(); nodo.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((evento) =>
    nodo.addEventListener(evento, (ev) => { ev.preventDefault(); nodo.classList.remove('over'); }));
  nodo.addEventListener('drop', (ev) => caricaOffertaPrecedente(ev.dataTransfer.files));
}

async function init() {
  state.schema = await api('/api/schema');
  costruisciForm();
  costruisciControlliPrezzo();
  $('#servizi').innerHTML = '';
  ripristinaLocale();

  const data = document.querySelector('[data-campo="data_offerta"]');
  if (data && !data.value) data.value = state.schema.oggi;

  // Requisiti ed esclusioni partono dai testi standard: si modificano o si
  // svuotano, e se restano vuoti la sezione non compare in offerta.
  Object.entries(state.schema.testi_standard || {}).forEach(([nome, voci]) => {
    const controllo = document.querySelector(`[data-campo="${nome}"]`);
    if (controllo && !controllo.value.trim()) controllo.value = voci.join('\n');
  });

  collegaDropzone('#drop-bom', '#input-bom', 'bom');
  collegaDropzone('#drop-template', '#input-template', 'template');
  collegaDropzoneRinnovo();
  $('#btn-aggiungi-servizio').addEventListener('click', () => { $('#servizi').appendChild(rigaServizio()); });
  $('#btn-azzera-righe').addEventListener('click', () => {
    state.righe = {};
    aggiornaContatoreModifiche();
    forzaRidisegnoRighe();
    pianificaAnteprima(0);
  });
  aggiornaContatoreModifiche();
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
    state.righe = {};
    state.rinnovo = null;
    forzaRidisegnoRighe();
    aggiornaContatoreModifiche();
    $('#tag-vecchia').hidden = true;
    $('#rinnovo-info').hidden = true;
    $('#box-adeguamento').hidden = true;
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
