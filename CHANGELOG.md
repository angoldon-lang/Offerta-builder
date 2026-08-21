# Storico delle versioni

Il numero di versione si legge con `offerta --version` o in alto a destra
nell'interfaccia web. Se dopo un `git pull` il numero non cambia, l'aggiornamento
non è arrivato.

## 0.8.0

**Il rinnovo funziona davvero.** Prima accettava solo il DOCX e su alcuni
documenti rispondeva "documento non leggibile".

- si caricano anche **PDF** e i formati Word vecchi (`.doc`, `.rtf`, `.odt`),
  convertiti al volo con LibreOffice;
- l'offerta rinnovata **viene generata subito** dopo il caricamento;
- senza un modello caricato, il documento di partenza fa da modello: le sue
  righe vengono sostituite da quelle nuove;
- errori spiegati (formato non gestito, file protetto, documento rovinato)
  invece di un messaggio unico;
- nei PDF le tabelle spezzate fra due pagine vengono ricucite e le descrizioni
  andate a capo non diventano righe in più.

## 0.7.0

**Rinnovo di un'offerta scaduta.** Si carica la vecchia offerta e il programma
ne recupera dati, condizioni e righe con i prezzi, aggiorna date e revisione del
riferimento, applica un eventuale adeguamento percentuale e rigenera tutto sul
template corrente.

- lettura di offerte prodotte dal programma o scritte a mano in Word
  (copertina in caselle di testo o in tabella, colonne riconosciute
  dall'intestazione);
- le voci "Incluso" restano tali;
- senza costi di acquisto il margine non viene inventato: risulta "non
  calcolabile" nel riepilogo, nel QA e nel documento interno;
- il QA ricorda che nel rinnovo non c'è una quotazione distributore con cui
  confrontare validità e prezzi.

## 0.6.0

**Semplificare l'offerta.** La proposta calcolata dalla BOM è un punto di
partenza: ora si può ridurre e correggere prima di generare.

- voci aggiunte a mano nel blocco scelto (materiali o servizi), con prezzo
  anche testuale: una riga `Incluso` non altera i totali;
- requisiti ed esclusioni vuoti = sezione assente nel documento; i testi
  standard sono precompilati e si possono cancellare;
- il subtotale "TOTALE MATERIALI" sparisce quando non ci sono servizi;
- in offerta va la sola descrizione (codice e periodo solo se richiesto);
- importi con il simbolo `€`;
- tolte dal documento le note che il modello rivolge a chi scrive l'offerta.

## 0.5.0

**Il Word aziendale si carica com'è.** Un template senza segnaposto viene
compilato riconoscendo le etichette del modello (`[descrizione di dettaglio]`,
`TOTALE MATERIALI`, `Netto a Voi Riservato`, le condizioni di vendita, la
copertina nelle caselle di testo). Restano supportati i template con segnaposto
Jinja. Al caricamento l'interfaccia dice quali sezioni ha riconosciuto.

- righe dell'offerta modificabili una per una: codice, descrizione, quantità,
  prezzo, con esclusione e ripristino;
- condizioni di vendita a tendina, con "Altro" per i valori fuori elenco;
- il margine sotto soglia non blocca più: è un avviso, segnalato una volta sola
  e non una per riga;
- modalità di prezzo predefinita: margine obiettivo (prima era il markup);
- import PDF: quotazioni con intestazione fuori dal riquadro della tabella,
  righe di raggruppamento, totali intermedi e sconti a cascata;
- celle unite e caselle di testo lette correttamente dai controlli QA.

## 0.4.0

Interfaccia web locale (`offerta web`): upload delle BOM e del template,
form guidato, anteprima dei prezzi ricalcolata dal backend a ogni modifica,
esito QA e download dei file.

## 0.3.0

Guida di installazione passo passo per Windows, macOS e Linux.

## 0.2.0

Il DOCX diventa il deliverable: il PDF si genera solo su richiesta (`--pdf`),
e solo a QA superato.

## 0.1.0

Primo MVP: import BOM da CSV/XLSX/PDF, normalizzazione in uno schema unico,
form rapido, motore commerciale in `Decimal` (markup, margine obiettivo, prezzo
manuale), generazione DOCX su template, QA obbligatorio e riepilogo interno.
