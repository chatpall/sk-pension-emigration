#!/usr/bin/env python3
"""
Modul 1, verzia 2.2: Emigračné "riedenie" slovenského dôchodkového systému
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
  suhrn.md                  – čitateľný súhrn

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
                    "popis": "časť by doma prácu nenašla, mladší profil = nižšia mzda"},
    "dolny":       {"zamestnanost_rel": 0.58, "mzda_podiel": 0.75,
                    "popis": "veľká časť odišla z nezamestnanosti / nízkopríjmových regiónov"},
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
    L = ["# Emigračné riedenie dôchodkového systému SR – súhrn (v2.2)", ""]

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


def main():
    VYSTUP.mkdir(exist_ok=True)
    dlha = nacitaj_diasporu()
    roky = suhrn_rokov(dlha)
    odhad = zvol_odhad(roky)
    vek = vekova_struktura(dlha, odhad)
    ref = sk_data()
    sc = scenare(odhad, ref)
    cas, panel = casovy_rad(roky, odhad, ref)

    odhad.to_csv(VYSTUP / "spolahlivost_krajin.csv", index=False)
    odhad[["geo", "definicia", "rok", "osoby_20_64", "hodnotenie"]].to_csv(VYSTUP / "diaspora_odhad.csv", index=False)
    vek.to_csv(VYSTUP / "vekova_struktura.csv")
    ref.to_csv(VYSTUP / "sk_referencne_data.csv")
    sc.to_csv(VYSTUP / "scenare.csv", index=False)
    cas.to_csv(VYSTUP / "casovy_rad.csv", index=False)
    zapis_suhrn(odhad, vek, ref, sc, cas, panel)

    pd.set_option("display.width", 200)
    print("\n=== SPOĽAHLIVOSŤ ===")
    print(odhad[["geo", "hodnotenie", "definicia", "rok", "osoby_20_64"]].to_string(index=False))
    print("\n=== HLAVNÝ VÝSLEDOK ===")
    print(sc[(sc.sadzba == HLAVNA_SADZBA)].round(1).to_string(index=False))
    print(f"\nHotovo. Výstupy v ./{VYSTUP}/ (súhrn: suhrn.md)")


if __name__ == "__main__":
    main()
