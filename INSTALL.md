# Guida all'installazione

Offerta Builder è un programma a riga di comando: si installa una volta, poi si
lancia con `offerta ...` dalla cartella dove vuoi gli output.

Tempo richiesto: **15 minuti** la prima volta.

---

## 1. Cosa serve

| Componente | Serve per | Obbligatorio |
| ---------- | --------- | ------------ |
| **Python 3.10 o superiore** | far girare il programma | si' |
| **Git** | scaricare e aggiornare il codice | si' (in alternativa: download ZIP) |
| **LibreOffice Writer** | convertire il DOCX in PDF (`--pdf`) | no |
| **Microsoft Word** | rileggere e ritoccare l'offerta generata | consigliato |

Il codice sta sul branch `claude/quote-generation-agent-mj5986` del repository
`angoldon-lang/Offerta-builder`.

---

## 2. Windows

### 2.1 Installa Python

1. Vai su <https://www.python.org/downloads/windows/> e scarica l'installer
   di Python 3.12 (64-bit).
2. Avvia l'installer e **spunta "Add python.exe to PATH"** prima di premere
   *Install Now*. È il passo che evita il 90% dei problemi successivi.
3. Apri **PowerShell** e verifica:

   ```powershell
   py --version
   ```

   Deve rispondere `Python 3.12.x` (o comunque 3.10+).

### 2.2 Installa Git

Scarica e installa Git da <https://git-scm.com/download/win>, lasciando le
opzioni predefinite. Verifica in PowerShell:

```powershell
git --version
```

### 2.3 Scarica il progetto

```powershell
cd $HOME\Documents
git clone -b claude/quote-generation-agent-mj5986 https://github.com/angoldon-lang/Offerta-builder.git
cd Offerta-builder
```

> Il branch va indicato esplicitamente con `-b`: il ramo principale del
> repository è ancora vuoto.

### 2.4 Crea l'ambiente e installa

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Se PowerShell rifiuta di eseguire lo script di attivazione
(`... non è possibile caricare il file ...`), sblocca la sessione corrente e
riprova:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Quando l'ambiente è attivo, il prompt inizia con `(.venv)`.

### 2.5 Verifica

```powershell
offerta --version
```

Deve rispondere con la versione installata, per esempio `offerta-builder 0.5.0`.

---

## 3. macOS e Linux

```bash
# macOS: se manca Python -> brew install python@3.12
python3 --version                     # deve essere 3.10 o superiore

cd ~/Documenti
git clone -b claude/quote-generation-agent-mj5986 https://github.com/angoldon-lang/Offerta-builder.git
cd Offerta-builder

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

offerta --version
```

---

## 4. Prova che funzioni

### Interfaccia web (il modo piu' comodo)

```bash
offerta web
```

Si apre il browser su <http://127.0.0.1:8000> con la pagina di lavorazione:
trascini le BOM e il template, compili i dati, e vedi l'anteprima dei totali
mentre scrivi. Il server ascolta solo sul tuo computer; per fermarlo, Ctrl+C nel
terminale.

### Da riga di comando

Dalla cartella del progetto, con l'ambiente attivo:

```bash
offerta build --bom examples/bom_vvalley_solarwinds.csv \
              --form examples/form_offerta.json \
              --template templates/offerta_ad_template.docx \
              --out prova
```

Devi vedere il riepilogo dell'offerta, l'esito dei controlli QA e, nella
cartella `prova/`, questi file:

| File | Cos'è |
| ---- | ------ |
| `offerta.docx` | l'offerta da rileggere e ritoccare in Word |
| `bom_normalizzata.json` | come è stata letta la BOM del distributore |
| `dati_offerta.json` | righe e totali usati per generare il documento |
| `controlli_qa.json` | esito di ogni controllo |
| `riepilogo_interno.html` | costi e margini, **da non inviare al cliente** |

Il PDF non viene generato: è voluto. Si chiede con `--pdf` a offerta chiusa.

---

## 5. Uso quotidiano

Ogni volta che apri un terminale nuovo devi riattivare l'ambiente:

```powershell
cd $HOME\Documents\Offerta-builder        # Windows
.\.venv\Scripts\Activate.ps1
```

```bash
cd ~/Documenti/Offerta-builder            # macOS/Linux
source .venv/bin/activate
```

Poi, o lanci `offerta web` e lavori nel browser, oppure segui il giro da
terminale:

```bash
# 1. prepara il form partendo dalla BOM del distributore
offerta form-init -o offerte/bper/form.json --bom offerte/bper/quote_vvalley.pdf

# 2. compila i campi obbligatori del form.json con Blocco note / VS Code

# 3. controlla come viene letta la BOM (sola lettura, nessun file generato)
offerta bom offerte/bper/quote_vvalley.pdf

# 4. genera l'offerta
offerta build --bom offerte/bper/quote_vvalley.pdf \
              --form offerte/bper/form.json \
              --template templates/offerta_ad_template.docx \
              --out offerte/bper/out

# 5. rileggi offerta.docx in Word, correggi, e se serve il PDF:
offerta build ... --pdf
```

Puoi passare più BOM insieme: `--bom quote1.pdf quote2.xlsx`.

---

## 6. Componenti opzionali

### 6.1 PDF (LibreOffice Writer)

Serve solo se usi `--pdf`.

| Sistema | Comando |
| ------- | ------- |
| Windows | installer da <https://it.libreoffice.org/download/> |
| macOS | `brew install --cask libreoffice` |
| Ubuntu/Debian | `sudo apt-get install libreoffice-writer` |

Su Windows, se `--pdf` non trova LibreOffice, aggiungi
`C:\Program Files\LibreOffice\program` al `PATH` oppure genera il PDF a mano da
Word (*File > Esporta > Crea PDF*), che per un'offerta è del tutto equivalente.

### 6.2 Riscrittura assistita dei testi (`--ai`)

```bash
pip install -e ".[ai]"
```

Poi imposta la chiave API:

```powershell
setx ANTHROPIC_API_KEY "la-tua-chiave"     # Windows: riapri il terminale dopo
```

```bash
export ANTHROPIC_API_KEY="la-tua-chiave"   # macOS/Linux
```

Riguarda solo premessa e descrizione della fornitura. Se il testo riscritto
contiene numeri non presenti nei dati calcolati, viene scartato in automatico.

---

## 7. Aggiornare all'ultima versione

Se l'interfaccia web è aperta, fermala prima con **Ctrl+C** nel terminale. Poi,
dalla cartella del progetto con l'ambiente attivo:

```bash
git pull
pip install -e .        # riallinea le dipendenze, è veloce se non è cambiato nulla
python -m pytest        # controllo facoltativo: devono passare tutti
offerta web             # riavvia l'interfaccia
```

Su Windows, con PowerShell:

```powershell
cd $HOME\Documents\Offerta-builder
.\.venv\Scripts\Activate.ps1
git pull
pip install -e .
offerta web
```

Dopo l'aggiornamento **ricarica la pagina nel browser** (Ctrl+F5): il file
JavaScript viene messo in cache, e senza ricarica forzata continueresti a usare
la versione precedente dell'interfaccia.

Per sapere quale versione stai usando: `offerta --version` da terminale, oppure
il numero in alto a destra nell'interfaccia. Se dopo il `git pull` il numero non
cambia, l'aggiornamento non è arrivato (o la pagina è ancora quella in cache).

Se `git pull` si lamenta di modifiche locali che non ricordi di aver fatto:

```bash
git status              # mostra cosa è cambiato
git checkout -- .       # scarta le modifiche locali e riprova il pull
```

---

## 8. Far girare i test

Utile dopo un aggiornamento, per essere sicuro che sia tutto a posto:

```bash
pip install pytest
python -m pytest
```

Attesi: **160 test verdi**.

---

## 9. Problemi frequenti

| Sintomo | Causa | Soluzione |
| ------- | ----- | --------- |
| `offerta : termine non riconosciuto` | ambiente virtuale non attivo | riattiva `.venv` (punto 5) |
| La pagina web non si apre | porta 8000 occupata | `offerta web --porta 8080` |
| `'py' non è riconosciuto` | Python installato senza *Add to PATH* | reinstalla Python spuntando l'opzione |
| `impossibile caricare il file Activate.ps1` | policy di PowerShell | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `ModuleNotFoundError: docx` | dipendenze non installate | `pip install -e .` con l'ambiente attivo |
| `Formato non supportato: .doc` | BOM in formato vecchio | salva la BOM come `.xlsx`, `.csv` o `.pdf` |
| `Conversione PDF non riuscita` | manca LibreOffice Writer | punto 6.1, oppure esporta il PDF da Word |
| `FLUSSO INTERROTTO: Form incompleto` | mancano campi obbligatori | il messaggio elenca quali: compilali nel `form.json` |
| `FLUSSO INTERROTTO: Import BOM` | la BOM non ha il costo di una riga | verifica il file; se è corretto così, rilancia con `--force` |
| `Nessuna tabella riconoscibile` | PDF scansionato (immagine) | chiedi al distributore la versione XLSX/CSV |

**`FLUSSO INTERROTTO` non è un errore del programma**: è il sistema che si
ferma perché manca un dato o non torna un conto, invece di tirare a indovinare.
Il messaggio dice sempre cosa confermare.

### Codici di uscita

Utili se un giorno vorrai lanciarlo da uno script:

| Codice | Significato |
| ------ | ----------- |
| `0` | tutto ok |
| `2` | flusso bloccato prima di generare il documento |
| `3` | documento generato, ma il QA ha rilevato errori da correggere |

---

## 10. Disinstallare

Basta cancellare la cartella del progetto: tutto (ambiente virtuale incluso) sta
li' dentro, non viene toccato nient'altro del sistema.
