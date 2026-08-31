# Audit PDS multi-camera: Parquet → JSON → Parquet

Data dell'audit: 27 luglio 2026.

## Obiettivo

Verificare che lo schema canonico `config/pds_catalog_schema.json` permetta di ricostruire dal Parquet un JSON compatibile con il builder e di rigenerare un Parquet semanticamente e tecnicamente equivalente per tutte le camere PDS presenti nel catalogo.

L'audit è completamente locale e non interroga sorgenti NASA.

## Risultati

| Camera | Intervallo Sol | Prodotti | Righe ricostruite | Valori differenti | Colonne differenti | Tipi differenti | Esito |
|---|---:|---:|---:|---:|---:|---:|---|
| MASTCAM | 2600–2604 | 1.943 | 1.943 | 0 | 0 | 0 | PASS |
| MAHLI | 583–587 | 1.052 | 1.052 | 0 | 0 | 0 | PASS |
| NAVCAM | 268–272 | 756 | 756 | 0 | 0 | 0 | PASS |
| HAZCAM | 1181–1185 | 238 | 238 | 0 | 0 | 0 | PASS |
| MARDI | 0–4 | 1.504 | 1.504 | 0 | 0 | 0 | PASS |
| CHEMCAM | 2964–2968 | 290 | 290 | 0 | 0 | 0 | PASS |

Totale campionato: **5.783 prodotti**.

## Verifiche superate per ogni camera

- stesso numero di prodotti prima e dopo il round-trip;
- stesse 35 colonne;
- nessuna riga persa o aggiunta;
- nessun valore modificato;
- stesso insieme di URL IMG riconosciuto dal builder;
- struttura JSON caricata correttamente dal loader del builder;
- stesso ordine e stessi tipi canonici delle colonne dopo il casting;
- nessun valore `NaN` non valido scritto nel JSON.

## ChemCam

Il campione ChemCam verifica anche la convivenza tra prodotti con e senza campi specifici TIF.

Nel campione di 290 prodotti:

- 107 prodotti valorizzano `processing_level`;
- 107 prodotti valorizzano `image_format`;
- 107 prodotti valorizzano `tif_url`;
- 107 prodotti valorizzano `tif_name`;
- gli altri mantengono correttamente valori nulli;
- tutti i valori e i nulli vengono conservati nel round-trip.

Il test dimostra quindi che lo schema comune a 35 colonne gestisce anche i campi aggiuntivi ChemCam presenti nel catalogo PDS consolidato.

## Conclusione

La ricostruzione delle **righe prodotto** PDS è stata verificata con successo per tutte le camere:

```text
Catalog_PDS.parquet
→ JSON gerarchico per camera
→ Parquet rigenerato
→ applicazione schema canonico PDS v1
```

I prodotti ricostruiti sono semanticamente e tecnicamente equivalenti ai campioni originali.

## Audit completo successivo

Il round-trip è stato successivamente eseguito sull'intero catalogo PDS, Sol 0–3644, includendo tutte le camere.

| Misura | Risultato |
|---|---:|
| Righe originali | 387.276 |
| Righe ricostruite | 387.276 |
| Righe mancanti/aggiunte | 0 |
| Colonne mancanti/aggiunte | 0 |
| Valori differenti | 0 |
| Tipi differenti | 0 |
| URL IMG differenti | 0 |
| Dimensione Parquet originale | 23.158.625 byte |
| Dimensione JSON ricostruito | 609.955.688 byte (581,70 MiB) |
| Dimensione Parquet rigenerato | 23.037.170 byte (21,97 MiB) |
| Lettura Parquet | 1,22 s |
| Costruzione/scrittura JSON | 74,01 s |
| Rigenerazione/schema Parquet | 14,03 s |
| Confronto completo | 1,95 s |
| Tempo totale misurato | 94,56 s |
| Picco memoria del processo | 3,05 GiB |

Il catalogo completo è quindi reversibile a livello di prodotti e schema. La dimensione binaria del Parquet rigenerato non è identica byte-per-byte, ma contenuto, colonne, tipi, righe e valori coincidono. La differenza deriva dalla serializzazione/compressione Parquet e non da una perdita semantica.

Il picco di circa 3 GiB dimostra che la prima implementazione funziona ma non è ancora adatta a dispositivi con poca RAM. La conversione destinata agli utenti dovrà ridurre le copie simultanee in memoria oppure dichiarare un requisito minimo prudenziale.

Artefatti completi:

```text
data/catalog_json_rebuild/roundtrip_test/pds_full_0_3644/
```

## Cosa non è ancora dimostrato

L'audit non rende ancora il flusso pronto per la produzione. Restano da verificare:

1. generazione del file di stato del builder;
2. ultimo Sol realmente controllato per ogni camera;
3. elenco delle directory NASA già scandite;
4. versione delle regole e del builder usata per la release ufficiale;
5. aggiornamento reale di una copia JSON ricostruita su un piccolo intervallo remoto;
6. sostituzione atomica e validazione del catalogo completo;
7. conversione ottimizzata per ridurre il picco di memoria.

Il Parquet contiene i prodotti, ma non contiene una prova completa della copertura remota già controllata. Queste informazioni dovranno essere distribuite tramite manifest/stato ufficiale oppure inizializzate in modo esplicito.

## Artefatti

Schema canonico:

```text
config/pds_catalog_schema.json
```

Script riutilizzabile:

```text
devtools/audit_pds_parquet_json_roundtrip.py
```

Report e artefatti dei singoli campioni:

```text
data/catalog_json_rebuild/roundtrip_test/mastcam_2600_2604/
data/catalog_json_rebuild/roundtrip_test/mahli_583_587/
data/catalog_json_rebuild/roundtrip_test/navcam_268_272/
data/catalog_json_rebuild/roundtrip_test/hazcam_1181_1185/
data/catalog_json_rebuild/roundtrip_test/mardi_0_4/
data/catalog_json_rebuild/roundtrip_test/chemcam_2964_2968/
```

## Passaggio successivo consigliato

Definire il manifest/stato ufficiale PDS necessario per ricostruire ciò che il Parquet non contiene:

- release ufficiale;
- versione del builder e delle regole;
- ultimo Sol realmente controllato per ogni camera;
- profilo di costruzione;
- strategia per inizializzare `catalog.json.state.json`.
