#!/usr/bin/env python3
"""
Modul 1, verzia 2.4: Emigračné "riedenie" slovenského dôchodkového systému
========================================================================

Novinky oproti v1:
  * Pre každú krajinu sa zvolí jedna definícia (narodení v SR, inak občania SR),
    takže chýbajúce krajiny (DE, IE, PT …) sa doplnia z dát o občianstve.
  * Česko: voliteľná definícia (CZ_DEFINICIA), lebo „narodení v SR“ zahŕňa aj
    presuny z čias Československa.
  * UK sa zadáva ručne (sčítanie 2021/22), Eurostat ho už nevracia.
  * Mzdový koeficient pre jednotlivé krajiny (napr. UK = nízkokvalifikovaný profil).
  * Tri sadzby poistného: 14 % / 18 % / 22,75 %.
  * Veková štruktúra diaspóry podľa krajín.
  * Časový rad 2010 → posledný rok pre stabilný panel krajín.
  * Hodnotenie spoľahlivosti dát pre každú krajinu.

Spustenie:  pip install requests pandas   →   python sk_dochodky_emigracia.py
            (alebo v IDLE: File → Open → F5)

Výstupy v ./vystup:
  spolahlivost_krajin.csv   – krajina, použitá definícia, rok, počet, hodnotenie, dôvody
  diaspora_odhad.csv        – zvolený odhad 20–64 pre každú krajinu
  vekova_struktura.csv      – päťročné vekové skupiny podľa krajín
  sk_referencne_data.csv    – slovenské vstupy podľa rokov
  scenare.csv               – scenáre × sadzby (posledný rok)
  casovy_rad.csv            – vývoj riedenia v čase (stabilný panel krajín)
  slovnik_dat.csv           – popis každého stĺpca: význam, jednotka, importované/vypočítané, zdroj, vzorec
  parametre.csv             – hodnoty všetkých predpokladov a pravidiel použitých v behu
  suhrn.md                  – čitateľný súhrn
  index.html                – stránka s metodikou a aktuálnymi číslami (aj do docs/index.html)

CSV sú v kódovaní UTF-8 s BOM (Excel zobrazí diakritiku), oddeľovač je čiarka.

Zdroje (Eurostat JSON-stat API): migr_pop3ctb, migr_pop1ctz, demo_pjan,
lfsa_ergan, nama_10_fte, spr_exp_pens. UK: Census 2021 (ONS), 2022 (NRS),
2021 (NISRA).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    import pandas as pd
    import requests
except ImportError:
    sys.exit("Chýbajú balíky. Spusti: pip install requests pandas")

# ---------------------------------------------------------------------------
# PARAMETRE
# ---------------------------------------------------------------------------

API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
ROK_OD = 2010

HOSTITELIA = [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "CH", "NO", "IS", "LI",
]

VEKOVE_SKUPINY = ["Y20-24", "Y25-29", "Y30-34", "Y35-39", "Y40-44",
                  "Y45-49", "Y50-54", "Y55-59", "Y60-64"]

# Česko: "obcania_SR" (konzervatívne, bez presunov z čias ČSFR)
#        alebo "narodeni_v_SR" (horná hranica)
CZ_DEFINICIA = "obcania_SR"

# Ručné odhady pre krajiny, ktoré Eurostat nepokrýva.
# UK: 79 193 osôb narodených v SR (všetky veky; Census 2021 E&W + NI, 2022 Scotland).
#     Podiel 20–64 je PREDPOKLAD (0,75) – zameniť, ak sa nájde tabuľka podľa veku.
MANUALNE = {
    "UK": {
        "rok": 2021,
        "osoby_20_64": round(79_193 * 0.75),
        "definicia": "narodeni_v_SR",
        "zdroj": "Census 2021/22 (ONS, NRS, NISRA): 79 193 všetky veky × predpoklad 0,75 pre 20–64",
    },
}

# Sadzby poistného, ktoré by sa v SR odviedli z hrubej mzdy (zákon 461/2003 Z.z.)
SADZBY = {
    "14%_I_pilier_sporitel": 0.14,     # len to, čo ostane v priebežnom pilieri pri sporiteľovi
    "18%_starobne": 0.18,              # celé starobné poistenie (vrátane 4 % do II. piliera)
    "22.75%_starobne+RFS": 0.2275,     # + rezervný fond solidarity (kryje deficity)
}
HLAVNA_SADZBA = "18%_starobne"

# zamestnanost_rel = násobok skutočnej miery zamestnanosti občanov SR v danom roku
# (v časovom rade sa tak kontrafaktuál prispôsobí trhu práce: 2013 ≈ 65 %, 2024 ≈ 78 %)
SCENARE = {
    "horny":       {"zamestnanost_rel": 1.00, "mzda_podiel": 1.00,
                    "popis": "všetci by pracovali ako priemerný občan SR za priemernú mzdu"},
    "realisticky": {"zamestnanost_rel": 0.83, "mzda_podiel": 0.85,
                    "popis": "časť by doma prácu nenašla, mladší profil znamená nižšiu mzdu"},
    "dolny":       {"zamestnanost_rel": 0.58, "mzda_podiel": 0.75,
                    "popis": "veľká časť odišla z nezamestnanosti alebo z nízkopríjmových regiónov"},
}
HLAVNY_SCENAR = "realisticky"

# Násobok mzdového podielu podľa krajiny (1.0 = bez úpravy).
# UK: ONS APS 2015/16 – ~50 % Slovákov v pomocných profesiách a ako operátori.
MZDA_KOEF_KRAJINA = {"UK": 0.85}

# Pravidlá hodnotenia spoľahlivosti
PRAH_AKTUALNOST = 2023          # starší rok → "orientačné"
PRAH_NESULAD = 1.6              # pomer definícií mimo [1/1.6, 1.6] → "orientačné"
PRAH_MALY_POCET = 500           # pod týmto počtom → poznámka (štatisticky málo významné)
PANEL_MIN_PODIEL_ROKOV = 0.7    # do časového radu len krajiny s ≥70 % rokov
PANEL_DOPLN_ROKY = 3            # chýbajúci okrajový rok sa doplní najbližšou hodnotou (max. 3 roky)

VYSTUP = Path("vystup")


# ---------------------------------------------------------------------------
# Eurostat JSON-stat
# ---------------------------------------------------------------------------

def stiahni(dataset: str, params: dict) -> dict:
    q = [(k, str(i)) for k, v in params.items()
         for i in (v if isinstance(v, (list, tuple)) else [v])]
    for pokus in range(4):
        try:
            r = requests.get(API + dataset, params=q, timeout=180)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (413, 429, 500, 502, 503):
                time.sleep(5 * (pokus + 1))
                continue
            raise RuntimeError(f"{dataset}: HTTP {r.status_code} – {r.text[:200]}")
        except requests.RequestException as e:
            if pokus == 3:
                raise RuntimeError(f"{dataset}: {e}") from e
            print(f"  … opakujem ({e})")
            time.sleep(5 * (pokus + 1))
    raise RuntimeError(f"{dataset}: nepodarilo sa stiahnuť")


def jsonstat_df(js: dict) -> pd.DataFrame:
    ids, sizes = js["id"], js["size"]
    kody = []
    for d in ids:
        idx = js["dimension"][d]["category"]["index"]
        kody.append(idx if isinstance(idx, list)
                    else [k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])])
    hodnoty = js.get("value", {})
    if isinstance(hodnoty, list):
        hodnoty = {str(i): v for i, v in enumerate(hodnoty) if v is not None}
    status = js.get("status", {}) or {}
    if isinstance(status, list):
        status = {str(i): s for i, s in enumerate(status) if s}
    mult = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        mult[i] = mult[i + 1] * sizes[i + 1]
    riadky = []
    for poz_str, val in hodnoty.items():
        poz = int(poz_str)
        rec = {d: kody[i][(poz // mult[i]) % sizes[i]] for i, d in enumerate(ids)}
        rec["value"] = val
        rec["flag"] = status.get(poz_str, "")
        riadky.append(rec)
    df = pd.DataFrame(riadky)
    if "time" in df:
        df["time"] = df["time"].astype(int)
    return df


def stiahni_po_krajinach(dataset: str, params: dict) -> pd.DataFrame:
    try:
        return jsonstat_df(stiahni(dataset, {**params, "geo": HOSTITELIA}))
    except RuntimeError as e:
        print(f"   hromadný dopyt zlyhal ({str(e)[:80]}), skúšam krajiny po jednej")
        casti = []
        for g in HOSTITELIA:
            try:
                casti.append(jsonstat_df(stiahni(dataset, {**params, "geo": g})))
            except RuntimeError:
                print(f"   - {g}: bez dát")
        return pd.concat(casti, ignore_index=True) if casti else pd.DataFrame()


# ---------------------------------------------------------------------------
# Krok A – diaspóra
# ---------------------------------------------------------------------------

def nacitaj_diasporu() -> pd.DataFrame:
    """Dlhá tabuľka: definicia, geo, time, age, value, flag (len kompletné roky)."""
    casti = []
    for nazov, dataset, dim in [("narodeni_v_SR", "migr_pop3ctb", "c_birth"),
                                ("obcania_SR", "migr_pop1ctz", "citizen")]:
        print(f"[A] {dataset} ({nazov}) …")
        df = stiahni_po_krajinach(dataset, {dim: "SK", "age": VEKOVE_SKUPINY, "sex": "T",
                                            "unit": "NR", "sinceTimePeriod": ROK_OD})
        if df.empty:
            continue
        df = df[["geo", "time", "age", "value", "flag"]].copy()
        df["definicia"] = nazov
        casti.append(df)
    dlha = pd.concat(casti, ignore_index=True)
    n = dlha.groupby(["definicia", "geo", "time"])["age"].transform("nunique")
    return dlha[n == len(VEKOVE_SKUPINY)].reset_index(drop=True)


def suhrn_rokov(dlha: pd.DataFrame) -> pd.DataFrame:
    """definicia, geo, time → osoby_20_64, priznaky."""
    return (dlha.groupby(["definicia", "geo", "time"])
                .agg(osoby_20_64=("value", "sum"),
                     nulove_skupiny=("value", lambda s: int((s == 0).sum())),
                     priznaky=("flag", lambda s: ",".join(sorted({f for f in s if f}))))
                .reset_index())


def podozrive(r) -> bool:
    """Veľa nulových vekových skupín pri nenulovom súčte = chybné/neúplné členenie (napr. BE)."""
    return r.nulove_skupiny >= 3 and r.osoby_20_64 >= PRAH_MALY_POCET


def zvol_odhad(roky: pd.DataFrame) -> pd.DataFrame:
    """Pre každú krajinu: zvolená definícia + posledný rok + hodnotenie spoľahlivosti."""
    posl = roky.loc[roky.groupby(["definicia", "geo"])["time"].idxmax()]
    born = posl[posl.definicia == "narodeni_v_SR"].set_index("geo")
    cit = posl[posl.definicia == "obcania_SR"].set_index("geo")

    riadky = []
    for g in sorted(set(HOSTITELIA) | set(MANUALNE)):
        if g in MANUALNE:
            m = MANUALNE[g]
            riadky.append({"geo": g, "definicia": m["definicia"], "rok": m["rok"],
                           "osoby_20_64": m["osoby_20_64"], "alternativa": None,
                           "pomer_definicii": None, "priznaky": "", "zdroj": m["zdroj"]})
            continue
        mb, mc = g in born.index, g in cit.index
        if not (mb or mc):
            riadky.append({"geo": g, "definicia": None, "rok": None, "osoby_20_64": None,
                           "alternativa": None, "pomer_definicii": None, "priznaky": "",
                           "zdroj": "Eurostat – bez dát"})
            continue
        if g == "CZ" and mb and mc:
            pref = CZ_DEFINICIA
        elif mb and mc:
            b, c = born.loc[g], cit.loc[g]
            # občianstvo, ak sú dáta o narodení výrazne staršie alebo podozrivé
            if b.time < c.time - 2 or (podozrive(b) and not podozrive(c)):
                pref = "obcania_SR"
            else:
                pref = "narodeni_v_SR"
        else:
            pref = "narodeni_v_SR" if mb else "obcania_SR"
        hl = born.loc[g] if pref == "narodeni_v_SR" else cit.loc[g]
        alt = (cit.loc[g] if pref == "narodeni_v_SR" else born.loc[g]) if (mb and mc) else None
        if alt is not None and abs(int(alt.time) - int(hl.time)) > 2:
            alt = None   # krížová kontrola má zmysel len pri porovnateľnom roku
        pomer = (hl.osoby_20_64 / alt.osoby_20_64) if alt is not None and alt.osoby_20_64 else None
        riadky.append({"geo": g, "definicia": pref, "rok": int(hl.time),
                       "osoby_20_64": float(hl.osoby_20_64),
                       "alternativa": float(alt.osoby_20_64) if alt is not None else None,
                       "pomer_definicii": pomer, "priznaky": hl.priznaky,
                       "podozrive_clenenie": bool(podozrive(hl)),
                       "zdroj": f"Eurostat {'migr_pop3ctb' if pref == 'narodeni_v_SR' else 'migr_pop1ctz'}"})
    out = pd.DataFrame(riadky)
    out[["hodnotenie", "dovody"]] = out.apply(ohodnot, axis=1, result_type="expand")
    return out.sort_values("osoby_20_64", ascending=False, na_position="last")


def ohodnot(r) -> tuple[str, str]:
    """Pravidlá: spoľahlivé / orientačné / chýba."""
    if pd.isna(r.osoby_20_64):
        return "chýba", "Eurostat nemá dáta v potrebnom vekovom členení"
    dovody = []
    if r.geo in MANUALNE:
        dovody.append("ručný odhad mimo Eurostatu")
    if r.rok < PRAH_AKTUALNOST:
        dovody.append(f"starý rok ({int(r.rok)})")
    if r.get("podozrive_clenenie", False) is True:
        dovody.append("podozrivé vekové členenie (viac nulových skupín)")
    if r.priznaky:
        dovody.append(f"príznak Eurostatu: {r.priznaky} (e = odhad, u = nízka spoľahlivosť)")
    if pd.notna(r.pomer_definicii) and not (1 / PRAH_NESULAD <= r.pomer_definicii <= PRAH_NESULAD):
        dovody.append(f"nesúlad definícií (pomer {r.pomer_definicii:.2f})")
    if pd.isna(r.alternativa) and r.geo not in MANUALNE:
        dovody.append("len jedna definícia, nedá sa krížovo overiť")
    hodn = "orientačné" if dovody else "spoľahlivé"
    if r.osoby_20_64 < PRAH_MALY_POCET:
        dovody.append("malý počet (vplyv na výsledok zanedbateľný)")
    return hodn, "; ".join(dovody) or "aktuálne, dve definície sa zhodujú"


def vekova_struktura(dlha: pd.DataFrame, odhad: pd.DataFrame) -> pd.DataFrame:
    kl = odhad.dropna(subset=["definicia"])[["geo", "definicia", "rok"]]
    kl = kl[~kl.geo.isin(MANUALNE)]
    v = dlha.merge(kl, left_on=["geo", "definicia", "time"], right_on=["geo", "definicia", "rok"])
    t = v.pivot_table(index="geo", columns="age", values="value", aggfunc="sum")[VEKOVE_SKUPINY]
    t["spolu_20_64"] = t.sum(axis=1)
    t["podiel_45_64_%"] = 100 * t[["Y45-49", "Y50-54", "Y55-59", "Y60-64"]].sum(axis=1) / t["spolu_20_64"]
    return t.sort_values("spolu_20_64", ascending=False).round(1)


# ---------------------------------------------------------------------------
# Krok B – slovenské referenčné dáta podľa rokov
# ---------------------------------------------------------------------------

def sk_data() -> pd.DataFrame:
    print("[B] slovenské referenčné dáta …")
    js = stiahni("demo_pjan", {"geo": "SK", "sex": "T",
                               "age": [f"Y{v}" for v in range(20, 65)],
                               "sinceTimePeriod": ROK_OD})
    d = jsonstat_df(js)
    n = d.groupby("time")["age"].nunique()
    pop = d.groupby("time")["value"].sum()[n == 45].rename("populacia_20_64")

    d = jsonstat_df(stiahni("lfsa_ergan", {"geo": "SK", "sex": "T", "age": "Y20-64",
                                           "citizen": "NAT", "unit": "PC",
                                           "sinceTimePeriod": ROK_OD}))
    zam = (d.set_index("time")["value"] / 100).rename("zamestnanost_20_64")

    d = jsonstat_df(stiahni("nama_10_fte", {"geo": "SK", "unit": "EUR", "sinceTimePeriod": ROK_OD}))
    mzda = d.set_index("time")["value"].rename("priemerna_mzda_rok_eur")

    d = jsonstat_df(stiahni("spr_exp_pens", {"geo": "SK", "unit": "MIO_EUR", "spdepm": "TOTAL",
                                             "spdepb": ["TOTAL", "OLD", "AOLD"],
                                             "sinceTimePeriod": ROK_OD}))
    p = d.pivot_table(index="time", columns="spdepb", values="value")
    vyd = pd.DataFrame({"vydavky_dochodky_spolu_mil": p["TOTAL"],
                        "vydavky_starobne_mil": p["OLD"] + p.get("AOLD", 0)})

    ref = pd.concat([pop, zam, mzda, vyd], axis=1).sort_index()
    ref.index.name = "rok"
    return ref


def posledna(ref: pd.DataFrame, stlpec: str) -> tuple[int, float]:
    s = ref[stlpec].dropna()
    return int(s.index.max()), float(s.iloc[-1])


# ---------------------------------------------------------------------------
# Krok C – scenáre, časový rad
# ---------------------------------------------------------------------------

def odvody(pocet: float, geo: str, zam: float, mzda: float, sc: dict, sadzba: float) -> tuple[float, float]:
    prac = pocet * zam * sc["zamestnanost_rel"]
    koef = sc["mzda_podiel"] * MZDA_KOEF_KRAJINA.get(geo, 1.0)
    return prac, prac * mzda * koef * sadzba


def scenare(odhad: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    _, zam = posledna(ref, "zamestnanost_20_64")
    _, mzda = posledna(ref, "priemerna_mzda_rok_eur")
    _, pop = posledna(ref, "populacia_20_64")
    _, vyd = posledna(ref, "vydavky_starobne_mil")
    domaci = pop * zam
    data = odhad.dropna(subset=["osoby_20_64"])
    riadky = []
    for sc_n, sc in SCENARE.items():
        for sd_n, sd in SADZBY.items():
            for hodn in ["všetky", "len spoľahlivé"]:
                d = data if hodn == "všetky" else data[data.hodnotenie == "spoľahlivé"]
                prac = ods = 0.0
                for _, r in d.iterrows():
                    p, o = odvody(r.osoby_20_64, r.geo, zam, mzda, sc, sd)
                    prac += p; ods += o
                riadky.append({"scenar": sc_n, "sadzba": sd_n, "krajiny": hodn,
                               "emigranti_20_64": round(d.osoby_20_64.sum()),
                               "chybajuci_pracujuci": round(prac),
                               "pct_domacich_pracujucich": 100 * prac / domaci,
                               "usle_odvody_mil_eur": ods / 1e6,
                               "pct_vydavkov_starobne": 100 * ods / (vyd * 1e6)})
    return pd.DataFrame(riadky)


def casovy_rad(roky: pd.DataFrame, odhad: pd.DataFrame, ref: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Stabilný panel: krajiny so zvolenou definíciou dostupnou v ≥80 % rokov; medzery interpolované."""
    kl = odhad.dropna(subset=["definicia"])
    kl = kl[~kl.geo.isin(MANUALNE)][["geo", "definicia"]]
    r = roky.merge(kl, on=["geo", "definicia"])
    if r.empty:
        return pd.DataFrame(), []
    vsetky_roky = list(range(ROK_OD, int(r.time.max()) + 1))
    t = r.pivot_table(index="time", columns="geo", values="osoby_20_64").reindex(vsetky_roky)
    pokrytie = t.notna().mean()
    panel = sorted(pokrytie[pokrytie >= PANEL_MIN_PODIEL_ROKOV].index)
    povodne = t[panel].notna()
    t = (t[panel].interpolate(limit_area="inside")
                 .ffill(limit=PANEL_DOPLN_ROKY).bfill(limit=PANEL_DOPLN_ROKY))
    doplnene = (~povodne & t.notna()).sum(axis=1)
    t = t.dropna()                       # len roky, kde má hodnotu celý panel
    sc, sd = SCENARE[HLAVNY_SCENAR], SADZBY[HLAVNA_SADZBA]
    riadky = []
    for rok, rad in t.iterrows():
        if rok not in ref.index or ref.loc[rok].isna().any():
            continue
        x = ref.loc[rok]
        prac = ods = 0.0
        for geo, n in rad.items():
            p, o = odvody(n, geo, x.zamestnanost_20_64, x.priemerna_mzda_rok_eur, sc, sd)
            prac += p; ods += o
        domaci = x.populacia_20_64 * x.zamestnanost_20_64
        riadky.append({"rok": int(rok), "emigranti_panel_20_64": round(rad.sum()),
                       "doplnene_krajiny": int(doplnene.loc[rok]),
                       "pct_domacich_pracujucich": 100 * prac / domaci,
                       "usle_odvody_mil_eur": ods / 1e6,
                       "pct_vydavkov_starobne": 100 * ods / (x.vydavky_starobne_mil * 1e6)})
    return pd.DataFrame(riadky), panel


# ---------------------------------------------------------------------------
# Súhrn
# ---------------------------------------------------------------------------

def fmt(x, d=0):
    return "–" if pd.isna(x) else f"{x:,.{d}f}".replace(",", " ")


def zapis_suhrn(odhad, vek, ref, sc, cas, panel):
    L = ["# Emigračné riedenie dôchodkového systému SR – súhrn (v2.4)", ""]

    L += ["## 1. Spoľahlivosť dát podľa krajín", "",
          "| krajina | hodnotenie | definícia | rok | osoby 20–64 | dôvody |",
          "|---|---|---|---|---:|---|"]
    for _, r in odhad.iterrows():
        rok = "–" if pd.isna(r.rok) else int(r.rok)
        defin = r.definicia if isinstance(r.definicia, str) else "–"
        L.append(f"| {r.geo} | {r.hodnotenie} | {defin} | {rok} | "
                 f"{fmt(r.osoby_20_64)} | {r.dovody} |")
    for h in ["spoľahlivé", "orientačné", "chýba"]:
        d = odhad[odhad.hodnotenie == h]
        L.append(f"\n- **{h}**: {len(d)} krajín, {fmt(d.osoby_20_64.sum())} osôb"
                 f" – {', '.join(d.geo)}")
    L.append("")

    L += ["## 2. Slovenské referenčné dáta (posledný rok)", ""]
    for c in ref.columns:
        rok, v = posledna(ref, c)
        L.append(f"- {c}: {fmt(v, 2)} ({rok})")
    L.append("")

    L += ["## 3. Scenáre (posledný rok)", "",
          "| scenár | sadzba | krajiny | emigranti 20–64 | chýbajúci pracujúci | % domácich | ušlé odvody (mil. €) | % výdavkov na starobné |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for _, r in sc.iterrows():
        L.append(f"| {r.scenar} | {r.sadzba} | {r.krajiny} | {fmt(r.emigranti_20_64)} | "
                 f"{fmt(r.chybajuci_pracujuci)} | {r.pct_domacich_pracujucich:.1f} % | "
                 f"{fmt(r.usle_odvody_mil_eur)} | {r.pct_vydavkov_starobne:.1f} % |")
    L += ["", "Scenáre:"] + [f"- **{k}**: {v['popis']}" for k, v in SCENARE.items()] + [""]

    L += ["## 4. Veková štruktúra (top 10)", "",
          "| krajina | 20–64 | podiel 45–64 |", "|---|---:|---:|"]
    for g, r in vek.head(10).iterrows():
        L.append(f"| {g} | {fmt(r.spolu_20_64)} | {r['podiel_45_64_%']:.0f} % |")
    L.append("")

    L += [f"## 5. Časový rad ({HLAVNY_SCENAR}, {HLAVNA_SADZBA})", "",
          f"Panel krajín (dostupné ≥{PANEL_MIN_PODIEL_ROKOV:.0%} rokov): {', '.join(panel) or '–'}. "
          "UK a krajiny s krátkym radom nie sú zahrnuté, preto sú úrovne nižšie ako v bode 3 – "
          "dôležitý je trend.", "",
          "| rok | emigranti (panel) | doplnené krajiny | % domácich pracujúcich | ušlé odvody (mil. €) | % výdavkov na starobné |",
          "|---|---:|---:|---:|---:|---:|"]
    for _, r in cas.iterrows():
        L.append(f"| {int(r.rok)} | {fmt(r.emigranti_panel_20_64)} | {int(r.doplnene_krajiny)} | "
                 f"{r.pct_domacich_pracujucich:.1f} % | "
                 f"{fmt(r.usle_odvody_mil_eur)} | {r.pct_vydavkov_starobne:.1f} % |")

    L += ["", "## Obmedzenia",
          "- UK: ručný odhad (podiel 20–64 je predpoklad).",
          f"- CZ: použitá definícia {CZ_DEFINICIA} (zmeň CZ_DEFINICIA).",
          "- Mimo EÚ/EFTA a UK nezahrnuté; pendleri s pobytom v SR nie sú v zrkadlových dátach.",
          "- Nezohľadnené: remitencie, vyslaní pracovníci, imigranti do SR, nižšie budúce nároky emigrantov."]
    (VYSTUP / "suhrn.md").write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# Dátový slovník – popis každého stĺpca v každom výstupnom CSV
# ---------------------------------------------------------------------------
# typ:  importované                 – hodnota prevzatá zo zdroja (prípadne len prevod jednotky)
#       vypočítané z importovaných  – súčet/kombinácia importovaných hodnôt (vzorec vo „vypocet“)
#       vypočítané                  – výsledok modelu (vzorec vo „vypocet“)
#       ručne zadané                – parameter alebo odhad zadaný v skripte
#       klasifikácia                – hodnota priradená pravidlom
#       identifikátor               – kľúč riadku (rok, krajina, scenár)

API_ZDROJ = "Eurostat API"


def _stlpec(subor, stlpec, popis, jednotka, typ, zdroj="", vypocet="", poznamka=""):
    return {"subor": subor, "stlpec": stlpec, "popis": popis, "jednotka": jednotka,
            "typ": typ, "zdroj": zdroj, "vypocet": vypocet, "poznamka": poznamka}


def datovy_slovnik() -> list[dict]:
    sc = SCENARE[HLAVNY_SCENAR]
    D = []

    # --- sk_referencne_data.csv -------------------------------------------
    f = "sk_referencne_data.csv"
    D += [
        _stlpec(f, "rok", "Kalendárny rok, ku ktorému sa údaje vzťahujú", "rok", "identifikátor",
                poznamka="Populácia je k 1. januáru daného roku, ostatné ukazovatele sú ročné. Prázdna bunka = Eurostat za daný rok ešte nepublikoval údaj."),
        _stlpec(f, "populacia_20_64", "Počet obyvateľov SR vo veku 20–64 rokov k 1. januáru", "osoby",
                "vypočítané z importovaných",
                f"{API_ZDROJ}: demo_pjan (geo=SK, sex=T, age=Y20 … Y64)",
                "súčet 45 jednotlivých rokov veku Y20 + Y21 + … + Y64",
                "Rok sa použije, len ak je k dispozícii všetkých 45 rokov veku. Ide o ľudí s trvalým pobytom v SR, takže obsahuje aj emigrantov, ktorí sa neodhlásili (dvojité započítanie)."),
        _stlpec(f, "zamestnanost_20_64", "Miera zamestnanosti občanov SR vo veku 20–64 rokov", "podiel (0–1)",
                "importované",
                f"{API_ZDROJ}: lfsa_ergan (geo=SK, sex=T, age=Y20-64, citizen=NAT, unit=PC)",
                "hodnota v percentách ÷ 100 (len prevod jednotky)",
                "Výberové zisťovanie pracovných síl (VZPS/LFS). Meria ľudí, ktorí v SR skutočne žijú. 0,78 = 78 % zamestnaných."),
        _stlpec(f, "priemerna_mzda_rok_eur", "Priemerná ročná hrubá mzda na ekvivalent plného úväzku", "EUR za rok",
                "importované",
                f"{API_ZDROJ}: nama_10_fte (geo=SK, unit=EUR)", "",
                "Údaj z národných účtov; je o niečo vyšší ako priemerná mesačná mzda ŠÚ SR × 12."),
        _stlpec(f, "vydavky_dochodky_spolu_mil", "Všetky výdavky na dôchodky (starobné, predčasné, invalidné, pozostalostné a ďalšie)",
                "mil. EUR", "importované",
                f"{API_ZDROJ}: spr_exp_pens (geo=SK, spdepb=TOTAL, spdepm=TOTAL, unit=MIO_EUR)", "",
                "Metodika ESSPROS."),
        _stlpec(f, "vydavky_starobne_mil", "Výdavky na starobné a predčasné starobné dôchodky", "mil. EUR",
                "vypočítané z importovaných",
                f"{API_ZDROJ}: spr_exp_pens (spdepb=OLD a AOLD, spdepm=TOTAL, unit=MIO_EUR)",
                "OLD (starobný dôchodok) + AOLD (predčasný starobný dôchodok)",
                "Menovateľ pre všetky ukazovatele „% výdavkov na starobné dôchodky“."),
    ]

    # --- diaspora_odhad.csv a spolahlivost_krajin.csv -------------------------
    spolocne = lambda f: [
        _stlpec(f, "geo", "Kód hostiteľskej krajiny", "kód", "identifikátor",
                poznamka="Kódy Eurostatu (napr. AT = Rakúsko, CZ = Česko, EL = Grécko, UK = Spojené kráľovstvo)."),
        _stlpec(f, "definicia", "Definícia, podľa ktorej je počet určený", "text", "klasifikácia",
                "", "narodeni_v_SR, ak existuje a nie je o viac ako 2 roky staršia ani podozrivá; inak obcania_SR; "
                    f"pre CZ podľa parametra CZ_DEFINICIA ({CZ_DEFINICIA})",
                "narodeni_v_SR = osoby narodené na Slovensku; obcania_SR = osoby so slovenským občianstvom."),
        _stlpec(f, "rok", "Rok, z ktorého pochádza počet osôb", "rok", "importované",
                f"{API_ZDROJ}: časová dimenzia datasetu zvolenej definície",
                "najnovší rok, v ktorom je všetkých 9 vekových skupín 20–64",
                "Pre UK ručne zadaný rok sčítania (2021)."),
        _stlpec(f, "osoby_20_64", "Počet osôb vo veku 20–64 rokov v hostiteľskej krajine", "osoby",
                "vypočítané z importovaných (UK: ručne zadané)",
                f"{API_ZDROJ}: migr_pop3ctb (c_birth=SK) alebo migr_pop1ctz (citizen=SK); sex=T, unit=NR",
                "súčet 9 päťročných skupín Y20-24 + Y25-29 + … + Y60-64",
                f"UK: {MANUALNE['UK']['zdroj']}." if "UK" in MANUALNE else ""),
        _stlpec(f, "hodnotenie", "Hodnotenie spoľahlivosti počtu", "spoľahlivé / orientačné / chýba", "klasifikácia",
                "", f"spoľahlivé, ak: rok ≥ {PRAH_AKTUALNOST}, bez príznaku e/u, pomer definícií v rozsahu "
                    f"{1/PRAH_NESULAD:.3f}–{PRAH_NESULAD}, obe definície z porovnateľného roku, nie ručný odhad, "
                    "členenie nie je podozrivé; inak orientačné; chýba = bez dát",
                "Podrobne v metodike, časť 3."),
    ]
    D += spolocne("diaspora_odhad.csv")
    f = "spolahlivost_krajin.csv"
    D += spolocne(f) + [
        _stlpec(f, "alternativa", "Počet osôb 20–64 podľa druhej definície", "osoby", "vypočítané z importovaných",
                f"{API_ZDROJ}: dataset druhej definície (migr_pop1ctz alebo migr_pop3ctb)",
                "súčet 9 päťročných vekových skupín",
                "Prázdne, ak druhá definícia chýba alebo je od zvolenej vzdialená viac ako 2 roky."),
        _stlpec(f, "pomer_definicii", "Pomer zvolenej a druhej definície", "pomer", "vypočítané",
                "", "osoby_20_64 ÷ alternativa",
                f"Hodnota mimo {1/PRAH_NESULAD:.3f}–{PRAH_NESULAD} = nesúlad definícií. 1,0 = úplná zhoda."),
        _stlpec(f, "priznaky", "Príznaky kvality, ktoré Eurostat uvádza pri hodnotách", "kódy", "importované",
                f"{API_ZDROJ}: pole „status“ v odpovedi JSON-stat",
                "zjednotenie príznakov všetkých 9 vekových skupín",
                "e = odhad, u = nízka spoľahlivosť, b = zlom v časovom rade, p = predbežné, c = dôverné."),
        _stlpec(f, "podozrive_clenenie", "Či je vekové členenie podozrivé", "True / False", "vypočítané",
                "", f"True, ak 3 a viac vekových skupín má hodnotu 0 a súčet je aspoň {PRAH_MALY_POCET}",
                "Signalizuje chybu alebo neúplnosť dát (napr. Belgicko podľa krajiny narodenia)."),
        _stlpec(f, "zdroj", "Pôvod čísla", "text", "identifikátor",
                poznamka="Názov datasetu Eurostatu alebo popis ručného odhadu."),
        _stlpec(f, "dovody", "Dôvody, prečo krajina dostala dané hodnotenie", "text", "klasifikácia",
                "", "zoznam podmienok, ktoré krajina nesplnila",
                "„malý počet“ je len poznámka a hodnotenie nezhoršuje."),
    ]

    # --- vekova_struktura.csv ---------------------------------------------
    f = "vekova_struktura.csv"
    D.append(_stlpec(f, "geo", "Kód hostiteľskej krajiny", "kód", "identifikátor",
                     poznamka="UK chýba, lebo ručný odhad nemá vekové členenie."))
    for a in VEKOVE_SKUPINY:
        od, do = a[1:].split("-")
        D.append(_stlpec(f, a, f"Počet osôb vo veku {od}–{do} rokov", "osoby", "importované",
                         f"{API_ZDROJ}: dataset a rok zvolenej definície (pozri diaspora_odhad.csv)", "",
                         "Hodnota prevzatá bez úprav."))
    D += [
        _stlpec(f, "spolu_20_64", "Počet osôb vo veku 20–64 spolu", "osoby", "vypočítané z importovaných",
                "", "súčet stĺpcov Y20-24 až Y60-64", "Zhoduje sa s osoby_20_64 v diaspora_odhad.csv."),
        _stlpec(f, "podiel_45_64_%", "Podiel osôb vo veku 45–64 rokov", "%", "vypočítané",
                "", "(Y45-49 + Y50-54 + Y55-59 + Y60-64) ÷ spolu_20_64 × 100",
                "Vysoký podiel naznačuje dávnejšiu migráciu; nízky podiel mladých ľudí (študenti, nedávny odchod)."),
    ]

    # --- scenare.csv ----------------------------------------------------------
    f = "scenare.csv"
    vz = "N = osoby_20_64, z = zamestnanost_20_64, α = podiel zamestnanosti scenára, w = priemerna_mzda_rok_eur, β = podiel na mzde, γ = mzdový koeficient krajiny, s = sadzba"
    D += [
        _stlpec(f, "scenar", "Scenár kontrafaktuálu", "text", "ručne zadané", "parameter SCENARE",
                "", "; ".join(f"{k}: α = {v['zamestnanost_rel']}, β = {v['mzda_podiel']}" for k, v in SCENARE.items())),
        _stlpec(f, "sadzba", "Sadzba poistného použitá vo výpočte", "text", "ručne zadané",
                "parameter SADZBY; zákon č. 461/2003 Z. z.", "",
                "; ".join(f"{k} = {v:.4g}" for k, v in SADZBY.items())),
        _stlpec(f, "krajiny", "Ktoré krajiny sú započítané", "všetky / len spoľahlivé", "klasifikácia",
                "", "„len spoľahlivé“ = krajiny s hodnotením spoľahlivé",
                "„len spoľahlivé“ slúži ako tvrdá spodná hranica."),
        _stlpec(f, "emigranti_20_64", "Počet emigrantov 20–64 vo vybraných krajinách", "osoby", "vypočítané",
                "", "Σ osoby_20_64 vybraných krajín"),
        _stlpec(f, "chybajuci_pracujuci", "Koľko emigrantov by v SR pracovalo", "osoby", "vypočítané",
                "", "Σ N × z × α", f"{vz}. z je posledný dostupný rok."),
        _stlpec(f, "pct_domacich_pracujucich", "Chýbajúci pracujúci ako % pracujúcich v SR", "%", "vypočítané",
                "", "chybajuci_pracujuci ÷ (populacia_20_64 × z) × 100",
                "Mierne podhodnotené pre dvojité započítanie v populácii SR."),
        _stlpec(f, "usle_odvody_mil_eur", "Poistné, ktoré by emigranti odviedli v SR", "mil. EUR za rok", "vypočítané",
                "", "Σ N × z × α × w × β × γ × s ÷ 1 000 000", f"{vz}. γ: {MZDA_KOEF_KRAJINA}, ostatné krajiny 1,0."),
        _stlpec(f, "pct_vydavkov_starobne", "Ušlé poistné ako % výdavkov na starobné dôchodky", "%", "vypočítané",
                "", "usle_odvody_mil_eur ÷ vydavky_starobne_mil × 100",
                "Výdavky z posledného roku, za ktorý ich Eurostat publikoval."),
    ]

    # --- casovy_rad.csv -----------------------------------------------------
    f = "casovy_rad.csv"
    D += [
        _stlpec(f, "rok", "Kalendárny rok", "rok", "identifikátor",
                poznamka="Len roky, pre ktoré sú k dispozícii aj všetky slovenské referenčné dáta."),
        _stlpec(f, "emigranti_panel_20_64", "Počet emigrantov 20–64 v paneli krajín", "osoby",
                "vypočítané z importovaných",
                f"{API_ZDROJ}: migr_pop3ctb / migr_pop1ctz podľa zvolenej definície krajiny",
                f"súčet krajín s dátami aspoň v {PANEL_MIN_PODIEL_ROKOV:.0%} rokov; chýbajúce vnútorné roky lineárne "
                f"interpolované, okrajové doplnené najbližšou hodnotou (najviac {PANEL_DOPLN_ROKY} roky)",
                "Bez UK a krajín s krátkym radom, preto nižšie ako v scenare.csv. Sleduje sa trend."),
        _stlpec(f, "doplnene_krajiny", "Počet krajín, ktorých hodnota bola v danom roku doplnená", "počet", "vypočítané",
                "", "počet krajín bez pôvodného údaja v danom roku",
                "0 = všetky hodnoty sú pôvodné. Vyššie číslo = menej presný rok."),
        _stlpec(f, "pct_domacich_pracujucich", "Chýbajúci pracujúci ako % pracujúcich v SR", "%", "vypočítané",
                "", "Σ N(t) × z(t) × α ÷ (populacia_20_64(t) × z(t)) × 100",
                f"Scenár {HLAVNY_SCENAR} (α = {sc['zamestnanost_rel']}). Všetky veličiny z daného roku t."),
        _stlpec(f, "usle_odvody_mil_eur", "Ušlé poistné v danom roku", "mil. EUR za rok", "vypočítané",
                "", "Σ N(t) × z(t) × α × w(t) × β × γ × s ÷ 1 000 000",
                f"Scenár {HLAVNY_SCENAR}, sadzba {HLAVNA_SADZBA}. Nominálne eurá daného roku."),
        _stlpec(f, "pct_vydavkov_starobne", "Ušlé poistné ako % výdavkov na starobné dôchodky v danom roku", "%",
                "vypočítané", "", "usle_odvody_mil_eur(t) ÷ vydavky_starobne_mil(t) × 100",
                "Citlivé na načasovanie valorizácie dôchodkov (napr. roky 2022–2023)."),
    ]
    return D


def parametre_tabulka() -> pd.DataFrame:
    r = [
        ("ROK_OD", ROK_OD, "prvý rok sťahovaných dát", "nastavenie"),
        ("CZ_DEFINICIA", CZ_DEFINICIA, "definícia použitá pre Česko", "predpoklad"),
        ("HLAVNY_SCENAR", HLAVNY_SCENAR, "scenár pre časový rad", "nastavenie"),
        ("HLAVNA_SADZBA", HLAVNA_SADZBA, "sadzba pre časový rad", "nastavenie"),
        ("PRAH_AKTUALNOST", PRAH_AKTUALNOST, "najstarší rok pre hodnotenie spoľahlivé", "pravidlo"),
        ("PRAH_NESULAD", PRAH_NESULAD, "max. pomer definícií pre hodnotenie spoľahlivé", "pravidlo"),
        ("PRAH_MALY_POCET", PRAH_MALY_POCET, "hranica malého počtu osôb", "pravidlo"),
        ("PANEL_MIN_PODIEL_ROKOV", PANEL_MIN_PODIEL_ROKOV, "min. pokrytie rokov pre panel časového radu", "pravidlo"),
        ("PANEL_DOPLN_ROKY", PANEL_DOPLN_ROKY, "max. počet doplnených okrajových rokov", "pravidlo"),
    ]
    for k, v in SADZBY.items():
        r.append((f"SADZBY[{k}]", v, "sadzba poistného z hrubej mzdy", "zákon č. 461/2003 Z. z."))
    for k, v in SCENARE.items():
        r.append((f"SCENARE[{k}].zamestnanost_rel", v["zamestnanost_rel"], "α – podiel slovenskej miery zamestnanosti", "predpoklad"))
        r.append((f"SCENARE[{k}].mzda_podiel", v["mzda_podiel"], "β – podiel na priemernej mzde", "predpoklad"))
    for k, v in MZDA_KOEF_KRAJINA.items():
        r.append((f"MZDA_KOEF_KRAJINA[{k}]", v, "γ – mzdový koeficient krajiny", "predpoklad (ONS APS 2015/16)"))
    for k, m in MANUALNE.items():
        r.append((f"MANUALNE[{k}].osoby_20_64", m["osoby_20_64"], m["zdroj"], "ručný odhad"))
    return pd.DataFrame(r, columns=["parameter", "hodnota", "popis", "druh"])


def zapis_slovnik(vystupy: dict[str, pd.DataFrame]) -> None:
    """Zapíše slovnik_dat.csv a parametre.csv a overí, že každý stĺpec má popis."""
    sl = pd.DataFrame(datovy_slovnik())
    popisane = set(zip(sl.subor, sl.stlpec))
    chyba = [(s, c) for s, df in vystupy.items() for c in df.columns if (s, c) not in popisane]
    navyse = [(s, c) for s, c in popisane if s in vystupy and c not in vystupy[s].columns]
    for s, c in chyba:
        print(f"   ! slovník: chýba popis stĺpca {s} → {c}")
    for s, c in navyse:
        print(f"   ! slovník: popísaný stĺpec, ktorý vo výstupe nie je: {s} → {c}")
    poradie = {s: i for i, s in enumerate(vystupy)}
    sl["_p"] = sl.subor.map(poradie)
    sl = sl.sort_values("_p", kind="stable").drop(columns="_p")
    zapis_csv(sl, "slovnik_dat.csv")
    zapis_csv(parametre_tabulka(), "parametre.csv")


def zapis_csv(df: pd.DataFrame, nazov: str) -> None:
    # utf-8-sig: Excel správne zobrazí diakritiku
    df.to_csv(VYSTUP / nazov, index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Generovanie stránky s metodikou (docs/index.html) zo šablóny
# ---------------------------------------------------------------------------

VERZIA = "2.4"
SABLONA = Path(__file__).resolve().parent.parent / "docs" / "sablona.html"
AKTUALIZOVAT_DOCS = True     # True = prepíše aj docs/index.html (pre GitHub Pages)

NAZVY_KRAJIN = {
    "AT": "Rakúsko", "BE": "Belgicko", "BG": "Bulharsko", "CY": "Cyprus", "CZ": "Česko",
    "DE": "Nemecko", "DK": "Dánsko", "EE": "Estónsko", "EL": "Grécko", "ES": "Španielsko",
    "FI": "Fínsko", "FR": "Francúzsko", "HR": "Chorvátsko", "HU": "Maďarsko", "IE": "Írsko",
    "IT": "Taliansko", "LT": "Litva", "LU": "Luxembursko", "LV": "Lotyšsko", "MT": "Malta",
    "NL": "Holandsko", "PL": "Poľsko", "PT": "Portugalsko", "RO": "Rumunsko", "SE": "Švédsko",
    "SI": "Slovinsko", "CH": "Švajčiarsko", "NO": "Nórsko", "IS": "Island",
    "LI": "Lichtenštajnsko", "UK": "Spojené kráľovstvo",
}
NAZVY_SCENAROV = {"horny": "horný", "realisticky": "realistický", "dolny": "dolný"}
PILL = {"spoľahlivé": "ok", "orientačné": "mid", "chýba": "no"}


def _cislo(x, d=0):
    """Slovenský formát: medzera ako oddeľovač tisícov, desatinná čiarka."""
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def _pct(x, d=1):
    return f"{_cislo(x, d)} %"


def _mil(x):
    if x >= 1000:
        return f"{_cislo(x / 1000, 2)} mld. €"
    return f"{_cislo(x if x < 100 else round(x, -1))} mil. €"


def _ciarky(text):
    return __import__("re").sub(r"(\d)\.(\d)", r"\1,\2", str(text))


def _nazov(geo):
    return NAZVY_KRAJIN.get(geo, geo)


def _zoznam(geos):
    n = [_nazov(g) for g in geos]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " a " + n[-1]


def hodnoty_stranky(odhad, sc, cas, ref, panel) -> dict:
    import json, math, datetime
    h = {}
    dnes = datetime.date.today()
    h["DATUM"] = f"{dnes.day}. {dnes.month}. {dnes.year}"
    h["VERZIA"] = VERZIA
    h["ROK_OD"] = str(ROK_OD)
    h["SCENAR_TXT"] = NAZVY_SCENAROV.get(HLAVNY_SCENAR, HLAVNY_SCENAR)
    h["SADZBA_TXT"] = _pct(SADZBY[HLAVNA_SADZBA] * 100, 0 if (SADZBY[HLAVNA_SADZBA] * 100).is_integer() else 2)
    h["ROK_VYD"] = str(posledna(ref, "vydavky_starobne_mil")[0])

    # --- hlavné výsledky
    vs = sc[sc.krajiny == "všetky"]
    hl = vs[(vs.scenar == HLAVNY_SCENAR) & (vs.sadzba == HLAVNA_SADZBA)].iloc[0]
    h["KPI_EMIGRANTI"] = f"~{_cislo(hl.emigranti_20_64 / 1000)} tis."
    h["KPI_PCT_DOM"] = _pct(hl.pct_domacich_pracujucich)
    h["KPI_ODVODY"] = "~" + _mil(hl.usle_odvody_mil_eur)
    h["KPI_PCT_VYD"] = _pct(hl.pct_vydavkov_starobne)
    sp = sc[(sc.krajiny == "len spoľahlivé") & (sc.scenar == "dolny")].sort_values("usle_odvody_mil_eur").iloc[0]
    h["ROZSAH_TXT"] = (
        f"Rozsah všetkých scenárov a sadzieb je {_mil(vs.usle_odvody_mil_eur.min())} až "
        f"{_mil(vs.usle_odvody_mil_eur.max())} ročne, teda {_cislo(vs.pct_vydavkov_starobne.min())} až "
        f"{_cislo(vs.pct_vydavkov_starobne.max())} % výdavkov na starobné dôchodky. Ak počítame len krajiny "
        f"so spoľahlivými dátami a najopatrnejší scenár, dostaneme tvrdú spodnú hranicu "
        f"{_mil(sp.usle_odvody_mil_eur)} ({_pct(sp.pct_vydavkov_starobne)}).")

    # --- postup
    if CZ_DEFINICIA == "obcania_SR":
        cz = ("Výnimkou je Česko. Tam sa používa definícia občanov, lebo „narodení v SR“ zahŕňa aj ľudí, "
              "ktorí sa presťahovali ešte v Československu.")
    else:
        cz = ("Pre Česko sa používa definícia narodených v SR. Je to horná hranica, lebo zahŕňa aj ľudí, "
              "ktorí sa presťahovali ešte v Československu.")
    man = " ".join(f"{_nazov(g)} Eurostat nehlási, preto ho dopĺňame ručne: {_ciarky(m['zdroj'])}."
                   for g, m in MANUALNE.items())
    h["KROK_A_VYNIMKY"] = f"{cz} {man}".strip()
    h["GAMMA_TXT"] = ", ".join(f"{g} = {_cislo(v, 2)}" for g, v in MZDA_KOEF_KRAJINA.items()) + ", ostatné 1,0"
    h["SCENARE_RIADKY"] = "\n".join(
        f'      <tr><td>{NAZVY_SCENAROV.get(k, k).capitalize()}</td><td class="n">{_cislo(v["zamestnanost_rel"], 2)}</td>'
        f'<td class="n">{_cislo(v["mzda_podiel"], 2)}</td><td>{v["popis"]}</td></tr>' for k, v in SCENARE.items())

    # --- spoľahlivosť
    h["PRAH_ROK"] = str(PRAH_AKTUALNOST)
    h["PRAH_NESULAD"] = _cislo(PRAH_NESULAD, 1)
    h["PRAH_MALY"] = _cislo(PRAH_MALY_POCET)
    riadky = []
    for hod in ["spoľahlivé", "orientačné", "chýba"]:
        d = odhad[odhad.hodnotenie == hod]
        suma = "–" if d.osoby_20_64.isna().all() else _cislo(d.osoby_20_64.sum())
        riadky.append(f'      <tr><td><span class="pill {PILL[hod]}">{hod}</span></td><td class="n">{len(d)}</td>'
                      f'<td class="n">{suma}</td><td>{", ".join(d.geo) or "–"}</td></tr>')
    h["SPOLAHLIVOST_RIADKY"] = "\n".join(riadky)

    dostupne = odhad.dropna(subset=["osoby_20_64"])
    orient = dostupne[dostupne.hodnotenie == "orientačné"].head(3)
    if len(orient):
        podiel = 100 * orient.osoby_20_64.sum() / dostupne.osoby_20_64.sum()
        casti = [f"{_nazov(r.geo)} ({_cislo(r.osoby_20_64 / 1000)} tis.; {_ciarky(r.dovody)})" for _, r in orient.iterrows()]
        h["NAJVACSIE_ORIENTACNE"] = (f"Najväčšie krajiny s orientačnými dátami sú {'; '.join(casti)}. "
                                     f"Spolu tvoria {_pct(podiel, 0)} odhadovanej diaspóry, takže neistota v nich "
                                     "ovplyvňuje výsledok najviac.")
    else:
        h["NAJVACSIE_ORIENTACNE"] = "Všetky krajiny s dátami majú hodnotenie spoľahlivé."
    obc = [g for g in odhad[odhad.definicia == "obcania_SR"].geo]
    h["OBCANIA_V_BEHU"] = (f"V tomto behu sa definícia občanov použila pre: {_zoznam(obc)}." if obc
                           else "V tomto behu sa definícia občanov nepoužila pre žiadnu krajinu.")
    pr = []
    for _, r in dostupne.head(4).iterrows():
        defin = "narodení v SR" if r.definicia == "narodeni_v_SR" else "slovenskí občania"
        t = f"<strong>{_nazov(r.geo)}:</strong> rok {int(r.rok)}, {defin}: {_cislo(r.osoby_20_64)}"
        if pd.notna(r.alternativa):
            t += f"; druhá definícia {_cislo(r.alternativa)} (pomer {_cislo(r.pomer_definicii, 2)})"
        t += f". Výsledok: <span class=\"pill {PILL[r.hodnotenie]}\">{r.hodnotenie}</span>"
        if r.hodnotenie != "spoľahlivé":
            t += f" – {_ciarky(r.dovody)}"
        pr.append(f"        <li>{t}</li>")
    h["PRIKLADY"] = "\n".join(pr)
    chyba = list(odhad[odhad.hodnotenie == "chýba"].geo)
    h["CHYBAJUCE_TXT"] = ((f"Chýba {', '.join(_nazov(g) for g in chyba)}, ako aj krajiny mimo Európy (USA, Kanada, Austrália)." if chyba
                           else "Chýbajú krajiny mimo Európy (USA, Kanada, Austrália)."))

    # --- časový rad
    h["PANEL_PCT"] = _pct(PANEL_MIN_PODIEL_ROKOV * 100, 0)
    h["PANEL_N"] = str(len(panel))
    h["PANEL_DOPLN"] = str(PANEL_DOPLN_ROKY)
    c = cas.sort_values("rok").reset_index(drop=True)
    pop = c.rok.map(ref["populacia_20_64"])
    base = c.pct_domacich_pracujucich
    up = base * pop / (pop - c.emigranti_panel_20_64)
    exp_ = c.pct_vydavkov_starobne
    h["JS_L"] = json.dumps([str(int(y)) for y in c.rok])
    h["JS_BASE"] = json.dumps([round(float(x), 2) for x in base])
    h["JS_UP"] = json.dumps([round(float(x), 2) for x in up])
    h["JS_EXP"] = json.dumps([round(float(x), 2) for x in exp_])
    h["Y_MAX"] = str(math.ceil(max(up.max(), exp_.max()) + 0.5))
    y0, yN = int(c.rok.iloc[0]), int(c.rok.iloc[-1])
    h["ARIA"] = (f"Čiarový graf {y0} až {yN}. Pomer emigrantov k domácim pracujúcim {_pct(base.iloc[0])} až "
                 f"{_pct(base.iloc[-1])}, horná hranica pásma {_pct(up.iloc[0])} až {_pct(up.iloc[-1])}. "
                 f"Ušlé poistné ako podiel výdavkov {_pct(exp_.iloc[0])} až {_pct(exp_.iloc[-1])}.")

    smer = (" Systém teda stráca čoraz väčšiu časť potenciálnych platiteľov." if base.iloc[-1] > base.iloc[0]
            else " Podiel chýbajúcich platiteľov sa teda zmenšuje.")
    h["CITANIE_01"] = ("<strong>Plná modrá čiara</strong> ukazuje, koľko percent domácich pracujúcich by tvorili "
                       f"emigranti, keby pracovali na Slovensku. Medzi rokmi {y0} a {yN} sa zmenila z "
                       f"{_pct(base.iloc[0])} na {_pct(base.iloc[-1])}.{smer}")
    sirka = up - base
    i = int(sirka.idxmax())
    h["CITANIE_02"] = ("<strong>Modré pásmo</strong> zobrazuje neistotu z dvojitého započítania. Veľa emigrantov "
                       "sa neodhlási z trvalého pobytu, a tak sú v slovenskej populácii aj v diaspóre. Spodný okraj "
                       "predpokladá, že nikto nie je započítaný dvakrát. Horný okraj (prerušovaná čiara) predpokladá, "
                       "že všetci emigranti z panelu stále figurujú v populácii SR. Skutočnosť je niekde v pásme. "
                       f"Šírka pásma je najviac {_cislo(sirka.max(), 1)} percentuálneho bodu (rok {int(c.rok[i])}).")
    k = min(5, len(c))
    h["CITANIE_03"] = ("<strong>Oranžová bodkovaná čiara</strong> ukazuje ušlé poistné ako podiel skutočných výdavkov "
                       "na starobné dôchodky. Dvojité započítanie sa jej netýka, lebo výdavky sú reálne vyplatené "
                       f"peniaze. V roku {yN} je {_pct(exp_.iloc[-1])}, priemer posledných {k} rokov je "
                       f"{_pct(exp_.tail(k).mean())}.")
    if len(c) >= 2:
        zmena = exp_.diff().abs()
        j = int(zmena.idxmax())
        r0, r1 = int(c.rok[j - 1]), int(c.rok[j])
        g_ods = 100 * (c.usle_odvody_mil_eur[j] / c.usle_odvody_mil_eur[j - 1] - 1)
        g_vyd = 100 * (ref.loc[r1, "vydavky_starobne_mil"] / ref.loc[r0, "vydavky_starobne_mil"] - 1)
        t = (f"<strong>Najväčšia ročná zmena</strong> oranžovej čiary je medzi rokmi {r0} a {r1} "
             f"({_pct(exp_[j - 1])} → {_pct(exp_[j])}). Ušlé poistné sa zmenilo o {_cislo(g_ods, 1)} %, "
             f"výdavky na starobné dôchodky o {_cislo(g_vyd, 1)} %.")
        if abs(g_ods - g_vyd) > 5:
            t += (" Zmenu teda spôsobil rozdielny rast oboch veličín, nie zmena počtu emigrantov ani chyba dát. "
                  "Ušlé poistné rastie spolu s mzdami, výdavky s valorizáciou dôchodkov, ktorá sa riadi infláciou "
                  "z minulého obdobia. Keď sa tieto dva rasty rozídu, podiel sa pohne.")
        h["CITANIE_04"] = t
    else:
        h["CITANIE_04"] = "Časový rad má len jeden rok, zmeny sa nedajú porovnať."
    dopl = [f"{int(r.rok)} ({int(r.doplnene_krajiny)})" for _, r in c.iterrows() if r.doplnene_krajiny > 0]
    t = (f"<strong>Doplnené hodnoty</strong> (rok a počet krajín): {', '.join(dopl)}. Tieto roky sú menej presné."
         if dopl else "<strong>Doplnené hodnoty:</strong> žiadny rok neobsahuje doplnené hodnoty.")
    pokles = c.emigranti_panel_20_64.pct_change() * 100
    for j in pokles.index[pokles < -5]:
        t += (f" <strong>Pokles v roku {int(c.rok[j])}</strong> ({_cislo(pokles[j], 1).replace('-', '−')} %) môže byť revízia dát "
              "hostiteľských krajín, napríklad po sčítaní obyvateľov.")
    h["CITANIE_05"] = t
    return h


def generuj_stranku(odhad, sc, cas, ref, panel, ciele=None) -> None:
    import re
    if not SABLONA.exists():
        print(f"   (šablóna {SABLONA} neexistuje, stránka sa negeneruje)")
        return
    html = SABLONA.read_text(encoding="utf-8")
    hodnoty = hodnoty_stranky(odhad, sc, cas, ref, panel)
    html = re.sub(r"\{\{([A-Z_0-9]+)\}\}", lambda m: str(hodnoty.get(m.group(1), m.group(0))), html)
    html = html.replace("<!-- ŠABLÓNA: index.html generuje skript src/sk_dochodky_emigracia.py. Upravuj tento súbor, "
                        "nie index.html. Značky {{...}} dopĺňa skript. -->\n",
                        "<!-- Vygenerované skriptom src/sk_dochodky_emigracia.py zo šablóny docs/sablona.html. "
                        "Neupravuj ručne. -->\n")
    zvysne = sorted(set(re.findall(r"\{\{([A-Z_0-9]+)\}\}", html)))
    if zvysne:
        print(f"   ! stránka: nevyplnené značky {zvysne}")
    if ciele is None:
        ciele = [VYSTUP / "index.html"] + ([SABLONA.parent / "index.html"] if AKTUALIZOVAT_DOCS else [])
    for p in ciele:
        Path(p).write_text(html, encoding="utf-8")
        print(f"   stránka zapísaná: {p}")


def main():
    VYSTUP.mkdir(exist_ok=True)
    dlha = nacitaj_diasporu()
    roky = suhrn_rokov(dlha)
    odhad = zvol_odhad(roky)
    vek = vekova_struktura(dlha, odhad)
    ref = sk_data()
    sc = scenare(odhad, ref)
    cas, panel = casovy_rad(roky, odhad, ref)

    vystupy = {
        "sk_referencne_data.csv": ref.reset_index(),
        "diaspora_odhad.csv": odhad[["geo", "definicia", "rok", "osoby_20_64", "hodnotenie"]],
        "spolahlivost_krajin.csv": odhad,
        "vekova_struktura.csv": vek.reset_index(),
        "scenare.csv": sc,
        "casovy_rad.csv": cas,
    }
    for nazov, df in vystupy.items():
        zapis_csv(df, nazov)
    zapis_slovnik(vystupy)
    zapis_suhrn(odhad, vek, ref, sc, cas, panel)
    generuj_stranku(odhad, sc, cas, ref, panel)

    pd.set_option("display.width", 200)
    print("\n=== SPOĽAHLIVOSŤ ===")
    print(odhad[["geo", "hodnotenie", "definicia", "rok", "osoby_20_64"]].to_string(index=False))
    print("\n=== HLAVNÝ VÝSLEDOK ===")
    print(sc[(sc.sadzba == HLAVNA_SADZBA)].round(1).to_string(index=False))
    print(f"\nHotovo. Výstupy v ./{VYSTUP}/ (súhrn: suhrn.md)")


if __name__ == "__main__":
    main()
