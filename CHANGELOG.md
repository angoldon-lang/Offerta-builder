# Storico delle versioni

Il numero di versione si legge con `offerta --version` o in alto a destra
nell'interfaccia web. Se dopo un `git pull` il numero non cambia, l'aggiornamento
non è arrivato.

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
