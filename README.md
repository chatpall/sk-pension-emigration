# Model emigrácie a odhad je vplyvu na dôchodkový systém

Odhad, koľko poistného chýba priebežnému dôchodkovému systému (1. pilier) preto, že časť ľudí v produktívnom veku žije a pracuje v iných krajinách Európy.

**[Metodika s interaktívnym grafom](https://chatpall.github.io/sk-pension-emigration/)** (zdrojový súbor: [`docs/index.html`](docs/index.html))

## Hlavné výsledky (dáta k 14. 10. 2026)

| Ukazovateľ | Hodnota |
|---|---:|
| Slováci vo veku 20–64 v EÚ/EFTA a UK | ~308 tisíc |
| Chýbajúci pracujúci voči domácim (realistický scenár) | 7,8 % |
| Ušlé poistné ročne (realistický scenár, sadzba 18 %) | ~600 mil. € |
| Podiel na výdavkoch na starobné dôchodky (2024) | 6,3 % |
| Rozsah všetkých scenárov a sadzieb | 290 mil. – 1,08 mld. € (3 – 11 %) |
| Tvrdá spodná hranica (len spoľahlivé krajiny, dolný scenár) | 75 mil. € (0,8 %) |

Vývoj 2010–2024 (panel 17 krajín bez UK): pomer emigrantov k domácim pracujúcim stúpol z 3,1 % na 5,5 %. Ušlé poistné ako podiel výdavkov na starobné dôchodky stúplo z 2,9 % na ~4,6 % a od roku 2017 sa drží okolo 4,5 %.

## Ako to funguje

1. **Diaspóra** – zrkadlové štatistiky Eurostatu: koľko ľudí narodených na Slovensku (alebo slovenských občanov) vo veku 20–64 hlásia hostiteľské krajiny. UK sa dopĺňa ručne zo sčítania 2021/22.
2. **Slovenské referenčné dáta** – populácia, miera zamestnanosti, priemerná mzda a výdavky na dôchodky za roky 2010–2025.
3. **Kontrafaktuál** – koľko poistného by títo ľudia odviedli, keby pracovali v SR. Počíta sa v troch scenároch (horný, realistický, dolný) a pri troch sadzbách (14 %, 18 %, 22,75 %).
4. **Spoľahlivosť** – každá krajina dostane hodnotenie *spoľahlivé / orientačné / chýba* podľa pevných pravidiel.
5. **Časový rad** – vývoj od roku 2010 pre krajiny so súvislými dátami.

Podrobnosti, vzorce, zdroje a obmedzenia sú v [metodike](docs/index.html).

## Spustenie

Potrebný je Python 3.10 alebo novší.

```bash
pip install -r requirements.txt
python src/sk_dochodky_emigracia.py
```

Výsledky sa uložia do priečinka `vystup/`:

| Súbor | Obsah |
|---|---|
| `suhrn.md` | čitateľný súhrn všetkých výsledkov |
| `spolahlivost_krajin.csv` | hodnotenie každej krajiny a dôvody |
| `diaspora_odhad.csv` | zvolený odhad počtu osôb 20–64 pre každú krajinu |
| `vekova_struktura.csv` | päťročné vekové skupiny podľa krajín |
| `sk_referencne_data.csv` | slovenské vstupy podľa rokov |
| `scenare.csv` | scenáre × sadzby za posledný rok |
| `casovy_rad.csv` | vývoj riedenia v čase |
| `casovy_rad_krajiny.csv` | rozpis časového radu po krajinách a rokoch: pôvodná, interpolovaná alebo doplnená hodnota |
| `slovnik_dat.csv` | popis každého stĺpca: význam, jednotka, či je importovaný alebo vypočítaný, zdroj a vzorec |
| `parametre.csv` | hodnoty všetkých predpokladov a pravidiel použitých v behu |
| `index.html` | stránka s metodikou vyplnená číslami z tohto behu |

### Stránka s metodikou

Na konci behu skript vyplní šablónu `docs/sablona.html` aktuálnymi číslami a zapíše `vystup/index.html` aj `docs/index.html` (GitHub Pages). Text a vzhľad stránky sa upravujú v `docs/sablona.html`; `docs/index.html` sa pri každom behu prepíše. Ak nechceš meniť `docs/index.html`, nastav v skripte `AKTUALIZOVAT_DOCS = False`.

CSV súbory sú v kódovaní UTF-8 s BOM, takže Excel správne zobrazí diakritiku.

Predpoklady (scenáre, sadzby, odhad pre UK, definícia pre Česko) sa nastavujú v časti `PARAMETRE` na začiatku skriptu.

Výsledky z behu 14. 10. 2026 sú uložené v [`data/vysledky_2026-10-14/`](data/vysledky_2026-10-14/).

## Zdroje dát

| Údaj | Zdroj |
|---|---|
| Populácia podľa krajiny narodenia / občianstva | Eurostat `migr_pop3ctb`, `migr_pop1ctz` |
| Populácia SR podľa veku | Eurostat `demo_pjan` |
| Miera zamestnanosti 20–64 | Eurostat `lfsa_ergan` |
| Priemerná ročná mzda na plný úväzok | Eurostat `nama_10_fte` |
| Výdavky na dôchodky (ESSPROS) | Eurostat `spr_exp_pens` |
| Slováci v UK | sčítanie 2021/22 (ONS, NRS, NISRA); profil práce: ONS Annual Population Survey |
| Sadzby poistného | zákon č. 461/2003 Z. z., zákon č. 43/2004 Z. z. |
| Koordinácia dôchodkov v EÚ | nariadenie (ES) č. 883/2004 |

Presný postup prístupu k dátam, pôvodné zdroje, právny základ a príklady dopytov pre každú databázu: [`docs/zdroje_dat.md`](docs/zdroje_dat.md).

Dáta Eurostatu sa sťahujú cez verejné API bez registrácie: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/`.

## Hlavné obmedzenia

- Kontrafaktuál (koľko ľudí by doma pracovalo a za akú mzdu) je predpoklad, preto sa počíta v scenároch.
- Chýbajú Poľsko, Francúzsko, Španielsko, Chorvátsko, Grécko, Cyprus, Malta a krajiny mimo Európy.
- Pendleri s trvalým pobytom v SR nie sú v zrkadlových dátach.
- Emigranti, ktorí sa neodhlásili z trvalého pobytu, sú v populácii SR započítaní dvakrát. V grafe je to zobrazené ako pásmo neistoty.
- Nezohľadnené: remitencie, vyslaní pracovníci, imigranti do SR a nižšie budúce nároky emigrantov.

## Plán

- [x] Modul 1: emigračné riedenie (tento repozitár)
- [ ] Ukazovateľ ušlého poistného voči celkovému výberu poistného alebo HDP
- [ ] Overenie počtu platiteľov z výročných správ Sociálnej poisťovne
- [ ] Pendleri z výberového zisťovania pracovných síl ŠÚ SR
- [ ] Modul 2: demografická projekcia do roku 2060 (Eurostat EUROPOP2023)

## História verzií

- **2.6** – modelový príklad výpočtu jedného roka na stránke s metodikou (vzorec, parametre, kroky, kontrola zhody)
- **2.5** – rozpis časového radu po krajinách (`casovy_rad_krajiny.csv`) a podiel doplnených osôb v každom roku
- **2.4** – stránka s metodikou sa generuje zo šablóny `docs/sablona.html` z výsledkov behu
- **2.3** – dátový slovník (`slovnik_dat.csv`) a zoznam parametrov (`parametre.csv`), CSV v UTF-8 s BOM
- **2.2** – krížová kontrola definícií len pri porovnateľnom roku
- **2.1** – oprava výberu definície (staré alebo chybné dáta), relatívna zamestnanosť v scenároch, doplnenie okrajových rokov v časovom rade
- **2.0** – kombinácia definícií, UK zo sčítania, mzdový koeficient podľa krajiny, tri sadzby, veková štruktúra, časový rad, hodnotenie spoľahlivosti
- **1.0** – prvý odhad pre posledný rok

## Licencia

Kód je pod licenciou MIT (pozri [LICENSE](LICENSE)). Dáta Eurostatu podliehajú [pravidlám opätovného použitia Eurostatu](https://ec.europa.eu/eurostat/about-us/policies/copyright), dáta ONS licencii Open Government Licence v3.0.

Odhady sú orientačné a slúžia na rádové zhodnotenie problému, nie ako oficiálna štatistika.
