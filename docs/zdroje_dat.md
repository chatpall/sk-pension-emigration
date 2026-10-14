# Zdroje dát a prístup k nim

Tento dokument popisuje, odkiaľ skript `src/sk_dochodky_emigracia.py` berie každý vstupný údaj, ako sa k nemu technicky dostane a čo s ním urobí. Cieľom je, aby sa dal každý údaj nezávisle overiť a celý výpočet zopakovať.

Prehľad:

| # | Vstup | Databáza | Pôvodný zdroj | Spôsob získania |
|---|---|---|---|---|
| 1 | Slováci v cudzine podľa krajiny narodenia | Eurostat `migr_pop3ctb` | národné štatistické úrady hostiteľských krajín | API, automaticky |
| 2 | Slováci v cudzine podľa občianstva | Eurostat `migr_pop1ctz` | národné štatistické úrady hostiteľských krajín | API, automaticky |
| 3 | Populácia SR podľa veku | Eurostat `demo_pjan` | Štatistický úrad SR | API, automaticky |
| 4 | Miera zamestnanosti v SR | Eurostat `lfsa_ergan` | ŠÚ SR, výberové zisťovanie pracovných síl | API, automaticky |
| 5 | Priemerná mzda v SR | Eurostat `nama_10_fte` | ŠÚ SR, národné účty | API, automaticky |
| 6 | Výdavky na dôchodky v SR | Eurostat `spr_exp_pens` | ŠÚ SR, systém ESSPROS | API, automaticky |
| 7 | Slováci v Spojenom kráľovstve | sčítanie 2021/22 | ONS, NRS, NISRA | ručne zadané v skripte |
| 8 | Profil práce Slovákov v UK | ONS Annual Population Survey | ONS | ručne zadaný koeficient |
| 9 | Sadzby poistného | zákony SR | Slov-Lex | ručne zadané v skripte |

---

## 1. Technický prístup k Eurostatu

### Rozhranie

Všetky automatické vstupy (1–6) pochádzajú z verejného rozhrania **Eurostat Statistics API**, verzia 1.0:

```
https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{kód_datasetu}?{filtre}
```

- **Registrácia ani kľúč nie sú potrebné.** Rozhranie je verejné a bezplatné.
- **Metóda:** jednoduchý HTTP GET cez knižnicu `requests`.
- **Formát odpovede:** JSON-stat 2.0. Je to štandardný formát pre štatistické kocky: obsahuje zoznam dimenzií (napr. krajina, vek, rok), ich kódy a plochý zoznam hodnôt.
- **Filtre** sa zadávajú ako parametre URL. Ak má dimenzia viac hodnôt, parameter sa opakuje (`age=Y20-24&age=Y25-29&…`). Parameter `sinceTimePeriod=2010` obmedzí časové obdobie na roky od 2010 (hodnota z parametra `ROK_OD`).

### Postup pri každom dopyte (funkcia `stiahni`)

1. Skript zostaví URL z kódu datasetu a filtrov.
2. Odošle požiadavku s časovým limitom **180 sekúnd**.
3. Ak server odpovie kódom **413, 429, 500, 502 alebo 503** (príliš veľký dopyt, príliš veľa dopytov, chyba servera) alebo spojenie zlyhá, skript počká 5, 10, 15 a 20 sekúnd a skúsi to znova. Maximálne sú **4 pokusy**.
4. Iná chyba (napr. 400 pri neexistujúcom kóde) sa okamžite ohlási.

### Hromadný dopyt a záložný postup (funkcia `stiahni_po_krajinach`)

Pri datasetoch o diaspóre (1 a 2) sa najprv odošle **jeden hromadný dopyt** pre všetkých 30 hostiteľských krajín naraz. Ak zlyhá, skript prejde krajiny **po jednej**. Krajina, ktorá vráti chybu, sa zaznamená ako „bez dát“ a beh pokračuje.

Hostiteľské krajiny (parameter `HOSTITELIA`): AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, CH, NO, IS, LI.

### Spracovanie odpovede (funkcia `jsonstat_df`)

1. Z každej dimenzie sa načíta zoznam kódov v poradí, ktoré určuje odpoveď.
2. Hodnoty sú uložené v jednom plochom zozname. Pozícia každej hodnoty sa prepočíta späť na kombináciu kódov (krajina × vek × rok…).
3. **Chýbajúce hodnoty** Eurostat neposiela vôbec. V tabuľke preto nevzniknú nuly, ale riadok jednoducho chýba.
4. **Príznaky kvality** (pole `status`, napr. `e` = odhad, `u` = nízka spoľahlivosť, `b` = zlom v rade, `p` = predbežné) sa uložia vedľa hodnoty a neskôr sa použijú pri hodnotení spoľahlivosti.

### Reprodukovateľnosť

- Skript dáta **neukladá do vyrovnávacej pamäte**. Pri každom behu sťahuje aktuálnu verziu.
- Eurostat a národné úrady **spätne revidujú** staršie roky. Dva behy v rôznych dňoch preto môžu dať mierne odlišné výsledky aj za rovnaké roky.
- Na presné zopakovanie výsledku slúžia archivované výstupy v `data/vysledky_RRRR-MM-DD/`. Spolu s dátumom behu sa dá každé číslo dohľadať.

---

## 2. Jednotlivé databázy Eurostatu

### 2.1 `migr_pop3ctb` – populácia podľa krajiny narodenia

| | |
|---|---|
| **Čo obsahuje** | Počet obyvateľov k 1. januáru podľa krajiny narodenia, veku a pohlavia |
| **Pôvodný zdroj** | národné štatistické úrady hostiteľských krajín; podľa krajiny vychádzajú z registrov obyvateľstva, sčítaní alebo ich kombinácie |
| **Právny základ** | nariadenie (ES) č. 862/2007 o štatistike migrácie; skupiny krajín narodenia definuje nariadenie Komisie (EÚ) č. 351/2010 |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/migr_pop3ctb/default/table> |

**Presný dopyt skriptu:**

| Dimenzia | Hodnota | Význam |
|---|---|---|
| `c_birth` | `SK` | narodení na Slovensku |
| `geo` | 30 hostiteľských krajín | krajina, ktorá údaj hlási |
| `age` | `Y20-24`, `Y25-29`, … `Y60-64` | 9 päťročných vekových skupín |
| `sex` | `T` | spolu muži a ženy |
| `unit` | `NR` | počet osôb |
| `sinceTimePeriod` | `2010` | roky od 2010 |

Príklad pre jednu krajinu (dá sa otvoriť v prehliadači):

```
https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/migr_pop3ctb?c_birth=SK&geo=AT&sex=T&unit=NR&age=Y20-24&age=Y25-29&age=Y30-34&age=Y35-39&age=Y40-44&age=Y45-49&age=Y50-54&age=Y55-59&age=Y60-64&sinceTimePeriod=2010
```

**Spracovanie:** ponechajú sa len roky, v ktorých krajina hlási všetkých 9 vekových skupín. Súčet skupín dáva počet osôb vo veku 20–64. Pre každú krajinu sa použije najnovší taký rok.

**Známe obmedzenia:** niektoré krajiny (napr. Nemecko) krajinu narodenia v tomto členení nehlásia; Spojené kráľovstvo už v databáze nie je; pri niektorých krajinách sú posledné dáta staršie.

### 2.2 `migr_pop1ctz` – populácia podľa občianstva

| | |
|---|---|
| **Čo obsahuje** | Počet obyvateľov k 1. januáru podľa občianstva, veku a pohlavia |
| **Pôvodný zdroj** | národné štatistické úrady hostiteľských krajín (registre obyvateľstva, registre cudzincov, sčítania) |
| **Právny základ** | nariadenie (ES) č. 862/2007 o štatistike migrácie |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/migr_pop1ctz/default/table> |

**Presný dopyt:** rovnaký ako pri 2.1, len namiesto `c_birth=SK` sa použije `citizen=SK` (slovenskí občania).

**Spracovanie:** rovnaké ako pri 2.1. Slúži ako druhá definícia na krížovú kontrolu a ako náhrada tam, kde údaje podľa krajiny narodenia chýbajú, sú staršie o viac ako 2 roky alebo majú chybné vekové členenie.

### 2.3 `demo_pjan` – populácia SR podľa veku

| | |
|---|---|
| **Čo obsahuje** | Počet obyvateľov SR k 1. januáru podľa jednotlivých rokov veku |
| **Pôvodný zdroj** | Štatistický úrad SR, štatistika obyvateľstva |
| **Právny základ** | nariadenie (EÚ) č. 1260/2013 o európskej demografickej štatistike |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/demo_pjan/default/table> |
| **Metadáta** | <https://ec.europa.eu/eurostat/cache/metadata/en/demo_pop_esms.htm> |

**Presný dopyt:** `geo=SK`, `sex=T`, `age=Y20`, `Y21`, … `Y64` (45 hodnôt), `sinceTimePeriod=2010`.

**Spracovanie:** súčet 45 rokov veku dáva populáciu vo veku 20–64. Rok sa použije, len ak je k dispozícii všetkých 45 hodnôt.

**Obmedzenie:** údaje vychádzajú z evidencie obyvateľov s pobytom v SR. Emigranti, ktorí sa neodhlásili, sú tu započítaní, hoci žijú v zahraničí (dvojité započítanie, v grafe zobrazené ako pásmo).

### 2.4 `lfsa_ergan` – miera zamestnanosti

| | |
|---|---|
| **Čo obsahuje** | Miera zamestnanosti podľa pohlavia, veku a občianstva (ročný priemer) |
| **Pôvodný zdroj** | ŠÚ SR, výberové zisťovanie pracovných síl (VZPS), prieskum domácností |
| **Právny základ** | nariadenie (EÚ) 2019/1700 o integrovanej európskej štatistike o osobách a domácnostiach; definície zamestnanosti podľa vykonávacieho nariadenia (EÚ) 2019/2240 (štandardy MOP) |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/lfsa_ergan/default/table> |
| **Metadáta** | <https://ec.europa.eu/eurostat/cache/metadata/en/lfsa_esms.htm> |

**Presný dopyt:**

```
https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/lfsa_ergan?geo=SK&sex=T&age=Y20-64&citizen=NAT&unit=PC&sinceTimePeriod=2010
```

**Spracovanie:** hodnota v percentách sa vydelí 100 (napr. 78,1 % → 0,781).

**Prečo občania SR (`citizen=NAT`):** kontrafaktuál predpokladá, že emigranti by sa na slovenskom trhu práce správali ako ostatní občania SR.

### 2.5 `nama_10_fte` – priemerná mzda na plný úväzok

| | |
|---|---|
| **Čo obsahuje** | Priemerná ročná hrubá mzda na zamestnanca prepočítaná na plný úväzok |
| **Pôvodný zdroj** | ŠÚ SR, národné účty |
| **Právny základ** | nariadenie Rady (EÚ) č. 549/2013 o európskom systéme národných a regionálnych účtov (ESA 2010) |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/nama_10_fte/default/table> |
| **Metadáta** | <https://ec.europa.eu/eurostat/cache/metadata/en/nama10_esms.htm> |

**Presný dopyt:**

```
https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_fte?geo=SK&unit=EUR&sinceTimePeriod=2010
```

**Spracovanie:** bez úprav, v eurách za rok.

**Poznámka:** údaj z národných účtov je o niečo vyšší ako priemerná mesačná mzda, ktorú zverejňuje ŠÚ SR, vynásobená 12. Rozdiel vyplýva z inej metodiky a z prepočtu na plný úväzok.

### 2.6 `spr_exp_pens` – výdavky na dôchodky

| | |
|---|---|
| **Čo obsahuje** | Výdavky na dôchodky podľa druhu dôchodku, v mil. EUR |
| **Pôvodný zdroj** | ŠÚ SR, európsky systém integrovanej štatistiky sociálnej ochrany (ESSPROS); primárne údaje pochádzajú od inštitúcií, ktoré dávky vyplácajú, najmä od Sociálnej poisťovne |
| **Právny základ** | nariadenie (ES) č. 458/2007 o ESSPROS; definície a klasifikácie v nariadení Komisie (ES) č. 10/2008 |
| **Prehliadač dát** | <https://ec.europa.eu/eurostat/databrowser/view/spr_exp_pens/default/table> |
| **Metadáta** | <https://ec.europa.eu/eurostat/cache/metadata/en/spr_esms.htm> |

**Presný dopyt:**

```
https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/spr_exp_pens?geo=SK&unit=MIO_EUR&spdepm=TOTAL&spdepb=TOTAL&spdepb=OLD&spdepb=AOLD&sinceTimePeriod=2010
```

| Kód | Význam |
|---|---|
| `spdepb=TOTAL` | všetky dôchodky |
| `spdepb=OLD` | starobný dôchodok |
| `spdepb=AOLD` | predčasný starobný dôchodok |
| `spdepm=TOTAL` | bez ohľadu na testovanie príjmu |

**Spracovanie:** `vydavky_starobne_mil = OLD + AOLD`. Táto suma je menovateľom všetkých ukazovateľov „% výdavkov na starobné dôchodky“.

**Obmedzenie:** údaje ESSPROS vychádzajú s oneskorením približne dvoch rokov. Posledný rok výpočtu preto určujú práve tieto dáta.

---

## 3. Ručne zadané vstupy

Tieto údaje skript nesťahuje. Sú zapísané v časti `PARAMETRE` a pri každom behu sa vypíšu do `vystup/parametre.csv`.

### 3.1 Slováci v Spojenom kráľovstve (`MANUALNE["UK"]`)

| | |
|---|---|
| **Hodnota** | 79 193 osôb narodených na Slovensku, všetky veky |
| **Pôvodné zdroje** | sčítanie 2021: Anglicko a Wales (ONS, dataset „Country of birth (extended)“), Severné Írsko (NISRA, tabuľka MS-A18); sčítanie 2022: Škótsko (National Records of Scotland, tabuľka UV204) |
| **Kde sme číslo našli** | súhrn s odkazmi na pôvodné tabuľky: <https://en.wikipedia.org/wiki/Slovaks_in_the_United_Kingdom> |
| **Úprava** | × 0,75 = odhadovaný podiel osôb vo veku 20–64 (predpoklad) → 59 395 |
| **Prečo ručne** | po odchode z EÚ Eurostat dáta za Spojené kráľovstvo nepublikuje |

**Odporúčanie:** číslo overiť priamo v tabuľkách ONS, NRS a NISRA a podiel 0,75 nahradiť skutočným vekovým členením zo sčítania.

### 3.2 Mzdový koeficient pre UK (`MZDA_KOEF_KRAJINA["UK"] = 0,85`)

| | |
|---|---|
| **Pôvodný zdroj** | ONS, Annual Population Survey, ad hoc tabuľka 007890 „Slovakians in employment broken down by occupation, qualifications, gender, age and employment length“ (vytvorená 2017, obdobia 2006/07 – 2015/16) |
| **Odkaz** | <https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/adhocs/007890slovakiansinemploymentbrokendownbyoccupationqualificationsgenderageandemploymentlength> |
| **Čo z nej vychádza** | v období 2015/16 pracovalo asi 36 % Slovákov v UK na pomocných pozíciách a ďalších 14 % ako operátori strojov |
| **Úprava** | koeficient 0,85 je úsudok odvodený z tohto profilu, nie priamy údaj |
| **Licencia** | Open Government Licence v3.0 |

### 3.3 Sadzby poistného (`SADZBY`)

| Sadzba | Zloženie | Právny predpis |
|---|---|---|
| 14 % | časť starobného poistenia, ktorá ostane v I. pilieri pri sporiteľovi v II. pilieri | zákon č. 461/2003 Z. z. o sociálnom poistení; zákon č. 43/2004 Z. z. o starobnom dôchodkovom sporení, § 64 |
| 18 % | starobné poistenie: zamestnanec 4 % + zamestnávateľ 14 % | zákon č. 461/2003 Z. z. |
| 22,75 % | starobné poistenie + rezervný fond solidarity 4,75 % (zamestnávateľ) | zákon č. 461/2003 Z. z. |

- Znenie zákonov: <https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/2003/461/> a <https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/2004/43/>
- Prehľad sadzieb, z ktorého sme vychádzali: <https://rulecalc.com/sk/zamestnanec/sadzby-poistneho-sp-sk>

**Odporúčanie:** pred zverejnením výsledkov sadzby overiť v aktuálnom znení zákona na Slov-Lexe alebo na stránke Sociálnej poisťovne. Pri zmene zákona treba upraviť parameter `SADZBY`.

### 3.4 Koordinácia dôchodkov v EÚ (len rámec, nie vstup do výpočtu)

Nariadenie (ES) č. 883/2004 o koordinácii systémov sociálneho zabezpečenia vysvetľuje, prečo si emigranti budujú nárok na dôchodok v krajine, kde pracujú. Do výpočtu nevstupuje ako číslo.
Znenie: <https://eur-lex.europa.eu/legal-content/SK/ALL/?uri=CELEX:32004R0883>

---

## 4. Ako overiť jednotlivé číslo

1. V `vystup/slovnik_dat.csv` nájdi stĺpec, ktorý ťa zaujíma. Pole `zdroj` uvádza dataset a filtre, pole `vypocet` vzorec.
2. Pri importovanom údaji otvor príslušnú URL z časti 2 v prehliadači. Eurostat vráti JSON s rovnakými hodnotami, z ktorých počítal skript.
3. Pohodlnejšie je otvoriť **prehliadač dát** (odkaz pri každom datasete), nastaviť rovnaké filtre a porovnať hodnotu v tabuľke.
4. Pri vypočítanom údaji použi vzorec zo slovníka a hodnoty z ostatných stĺpcov alebo súborov.
5. Ak sa číslo líši, skontroluj dátum behu. Eurostat medzitým mohol dáta revidovať.
