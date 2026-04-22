import streamlit as st
import pandas as pd
import io
from openpyxl.styles import PatternFill

st.set_page_config(page_title="Bábolna Körfuvar Generálás", layout="wide")
st.title("🚛 Bábolna Körfuvar Generálás")
st.markdown("---")

HU_PREFIX = 'HU '
BABOLNA_KEYWORD = 'Bábolna Rákóczi utca'


# ------------------------------------------------------------------
# Segédfüggvények – fuvarnapló / kör építés
# ------------------------------------------------------------------

def _torzs_of(f_szam) -> str:
    """Fuvarszám-törzs a Fuvarszám-ból (az első '-' előtti rész)."""
    return str(f_szam).split('-')[0]


def _reszfeladat_of(f_szam):
    """Részfeladat-sorszám (int) a Fuvarszám-ból, vagy None, ha nem számszerű / nincs."""
    parts = str(f_szam).split('-')
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except (ValueError, TypeError):
        return None


def classify_leg_direction(row):
    """Egy részfeladat irányának meghatározása: kifelé / befelé / semleges / ismeretlen."""
    fel = str(row['Első Felvételi állomás cím'])
    le = str(row['Utolsó Leadási állomás cím'])
    tipus = str(row['Fuvarfeladat típusa'])

    fel_hu = fel.startswith(HU_PREFIX)
    le_hu = le.startswith(HU_PREFIX)
    fel_babolna = BABOLNA_KEYWORD in fel
    le_babolna = BABOLNA_KEYWORD in le

    # 1) Elsődleges: típus alapján
    if 'Export' in tipus:
        return 'kifelé-nemzetközi'
    if 'Import' in tipus:
        return 'befelé-nemzetközi'

    # 2) Harmadik országos: semleges
    if tipus.startswith('Harmadik országba szállítás'):
        return 'semleges'

    # 3) Másodlagos: cím logika (fallback)
    if fel_hu and not fel_babolna and le_babolna:
        return 'kifelé-belföldi'
    if fel_babolna and le_hu and not le_babolna:
        return 'kifelé-belföldi'
    if fel_babolna and not le_hu:
        return 'kifelé-nemzetközi'
    if not fel_hu and le_babolna:
        return 'befelé-nemzetközi'
    if fel_babolna and le_hu and not le_babolna:
        return 'befelé-belföldi'

    return 'ismeretlen'


def _torzs_start_end(group: pd.DataFrame):
    """Egy adott fuvarszám-törzs csoportjára visszaadja a törzs kezdő és záró sorát.
    - Ha van értelmezhető részfeladat szám (-1, -2, ...), akkor a legkisebb részfeladatszámú
      sor a kezdő, a legnagyobb részfeladatszámú a záró.
    - Ha nincs részfeladat szám, időrendi min/max lesz belőle.
    Visszatér: (row_start, row_end) vagy (None, None).
    """
    if group is None or group.empty:
        return (None, None)

    group = group.copy()
    group['_reszfeladat'] = group['Fuvarszám'].map(_reszfeladat_of)

    has_reszf = group['_reszfeladat'].notna()
    if has_reszf.any():
        sub = group[has_reszf]
        if len(sub) > 1:
            row_start = sub.loc[sub['_reszfeladat'].idxmin()]
            row_end = sub.loc[sub['_reszfeladat'].idxmax()]
            return (row_start, row_end)
        only = sub.iloc[0]
        return (only, only)

    # fallback: időrend
    valid_start = group.dropna(subset=['Első Felvételi állomás időkapu (dátum)'])
    valid_end = group.dropna(subset=['Utolsó Leadási állomás időkapu (dátum)'])
    if valid_start.empty or valid_end.empty:
        return (None, None)
    row_start = valid_start.loc[valid_start['Első Felvételi állomás időkapu (dátum)'].idxmin()]
    row_end = valid_end.loc[valid_end['Utolsó Leadási állomás időkapu (dátum)'].idxmax()]
    return (row_start, row_end)


def get_interval_with_addresses(legs_df: pd.DataFrame):
    """Adott részfeladat-halmazhoz (pl. egy kör "kifelé" sorai) visszaadja a
    (kezdő időkapu, kezdő cím, záró időkapu, záró cím) tuple-t.

    Minden benne szereplő fuvarszám-törzset KÜLÖN kezel: törzsenként meghatározza a
    törzs saját kezdetét és végét (_torzs_start_end), majd az összes törzs kezdő pontjai
    közül a legkorábbit, a záró pontok közül a legkésőbbit választja.
    """
    if legs_df is None or legs_df.empty:
        return (pd.NaT, None, pd.NaT, None)

    needed_cols = [
        'Fuvarszám',
        'Első Felvételi állomás időkapu (dátum)',
        'Utolsó Leadási állomás időkapu (dátum)',
        'Első Felvételi állomás cím',
        'Utolsó Leadási állomás cím',
    ]
    for c in needed_cols:
        if c not in legs_df.columns:
            return (pd.NaT, None, pd.NaT, None)

    legs_df = legs_df.copy()
    legs_df['_torzs'] = legs_df['Fuvarszám'].astype(str).map(_torzs_of)

    start_candidates = []  # list of (dt, addr)
    end_candidates = []
    for _torzs, grp in legs_df.groupby('_torzs'):
        row_start, row_end = _torzs_start_end(grp)
        if row_start is not None:
            sdt = row_start['Első Felvételi állomás időkapu (dátum)']
            sad = row_start['Első Felvételi állomás cím']
            if pd.notna(sdt):
                start_candidates.append((sdt, sad))
        if row_end is not None:
            edt = row_end['Utolsó Leadási állomás időkapu (dátum)']
            ead = row_end['Utolsó Leadási állomás cím']
            if pd.notna(edt):
                end_candidates.append((edt, ead))

    if not start_candidates or not end_candidates:
        return (pd.NaT, None, pd.NaT, None)

    start_dt, start_addr = min(start_candidates, key=lambda x: x[0])
    end_dt, end_addr = max(end_candidates, key=lambda x: x[0])
    return (start_dt, start_addr, end_dt, end_addr)


def _build_explanation(has_kifele: bool, has_befele: bool, has_semleges: bool):
    """A kör tartalma alapján visszaadja a magyarázatot és a színt."""
    if has_kifele and has_befele:
        return (
            "Teljes kör: kifelé és befelé szakasz is lezárult a körben.",
            "background-color: lightgreen",
        )

    if has_kifele and has_semleges and not has_befele:
        msg = "Részleges kör: kifelé + semleges szakasz van, hiányzik a befelé (import) zárás."
    elif has_kifele and not has_semleges and not has_befele:
        msg = "Részleges kör: csak kifelé szakasz(ok) vannak, hiányzik a befelé (import) zárás."
    elif not has_kifele and has_semleges and has_befele:
        msg = "Részleges kör: semleges + befelé szakasz van, hiányzik a kifelé (export) nyitás."
    elif not has_kifele and not has_semleges and has_befele:
        msg = "Részleges kör: csak befelé szakasz(ok) vannak, hiányzik a kifelé (export) nyitás."
    elif not has_kifele and has_semleges and not has_befele:
        msg = "Részleges kör: csak semleges (harmadik országos) szakasz(ok) vannak."
    else:
        msg = "Részleges / ismeretlen kör (irány nem sorolható be)."

    return (msg, "background-color: orange")


# ------------------------------------------------------------------
# Segédfüggvények – költség tábla
# ------------------------------------------------------------------

def parse_cost_file(uploaded_file):
    """Egy költség .xlsx-et alakít tiszta DataFrame-mé.

    A fájl szerkezete:
      - 1. sor (merged cellákkal): költség kategória nevek (pl. 'Adó', 'Alkatrész'...)
        minden kategória 3 oszlopot fog át: Költség, Km, EUR/Km
      - 2. sor: 'Költség' / 'Km' / 'EUR/Km' címkék
      - 3. sortól: adatok. Első oszlop a 'Járatszám'.

    A Km érték kategóriánként ismétlődik (mindig ugyanaz a járaton belül),
    ezért csak az ELSŐ Km oszlopot tartjuk meg.

    Visszatérés: (DataFrame[Járatszám, Km, <kategória1>, <kategória2>, ...],
                  kategória_nevek_listája)
    """
    raw = pd.read_excel(uploaded_file, header=None, sheet_name=0)
    if len(raw) < 3:
        return pd.DataFrame(columns=['Járatszám', 'Km']), []

    cost_row = raw.iloc[0].ffill()  # merged cellák miatt: ismétlődő kategória név 3 oszlopon át
    type_row = raw.iloc[1]

    cost_col_map = {}  # {kategória_név: oszlop_idx}
    km_col_idx = None
    for idx in range(1, len(type_row)):
        t = type_row.iloc[idx]
        cat = cost_row.iloc[idx] if idx < len(cost_row) else None
        if t == 'Költség' and pd.notna(cat):
            cost_col_map[str(cat).strip()] = idx
        elif t == 'Km' and km_col_idx is None:
            km_col_idx = idx  # csak az első Km oszlop

    data = raw.iloc[2:].reset_index(drop=True)

    out = pd.DataFrame()
    out['Járatszám'] = data.iloc[:, 0].astype(str).str.strip()
    if km_col_idx is not None:
        out['Km'] = pd.to_numeric(data.iloc[:, km_col_idx], errors='coerce')
    else:
        out['Km'] = pd.NA

    categories = list(cost_col_map.keys())
    for cat in categories:
        out[cat] = pd.to_numeric(data.iloc[:, cost_col_map[cat]], errors='coerce')

    # Üres / 'nan' járatszámok kidobása
    out = out[out['Járatszám'].str.len() > 0]
    out = out[~out['Járatszám'].isin(['nan', 'NaN', 'None'])].reset_index(drop=True)

    return out, categories


def load_all_cost_files(uploaded_files):
    """Több költség fájl beolvasása és összefűzése.

    Ha ugyanaz a járatszám több fájlban is szerepel, csak az ELSŐ előfordulást tartjuk meg
    (keep='first'), így egy járat csak egyszer számolódik az aggregálásnál.

    Visszatérés: (egyesített_cost_df, az_összes_kategória_neveinek_listája_union-ban)
                 vagy (None, []) ha nincs feldolgozható fájl.
    """
    if not uploaded_files:
        return None, []
    dfs = []
    all_cats = []
    for f in uploaded_files:
        try:
            cf, cats = parse_cost_file(f)
        except Exception as e:
            st.warning(f"A(z) '{getattr(f, 'name', '?')}' költség fájl beolvasása sikertelen: {e}")
            continue
        if cf is None or cf.empty:
            continue
        dfs.append(cf)
        for c in cats:
            if c not in all_cats:
                all_cats.append(c)
    if not dfs:
        return None, []
    combined = pd.concat(dfs, ignore_index=True, sort=False)
    combined = combined.drop_duplicates(subset='Járatszám', keep='first').reset_index(drop=True)
    return combined, all_cats


def aggregate_cost_for_rings(result_df: pd.DataFrame,
                             cost_df: pd.DataFrame,
                             cost_categories: list):
    """A körök járatszámai alapján aggregálja a költségtáblát körönként.

    Hozzáadott oszlopok:
      - 'Km'
      - minden 'cost_categories' elem
      - 'Teljes költség' (a kategória költségek sor-sum-ja)
      - 'Járati eredmény' = 'Összes díj részarány (EUR)' - 'Teljes költség'

    Ha egy kör egyetlen járata sem szerepel a költség táblában, akkor a fenti
    új oszlopok üresen (None / NaN) maradnak – nem tévesztjük meg zöldre a
    kezeletlen sorokat.
    """
    cost_map = cost_df.set_index('Járatszám').to_dict(orient='index')

    km_list = []
    cat_cols = {c: [] for c in cost_categories}
    total_cost = []

    for _, row in result_df.iterrows():
        kor_jaratok = row.get('_Korben_Jaratszam_lista', []) or []
        seen = set()
        km_sum = 0.0
        cat_sums = {c: 0.0 for c in cost_categories}
        any_match = False

        for j in kor_jaratok:
            jc = str(j).strip()
            if jc in seen:
                continue
            seen.add(jc)
            entry = cost_map.get(jc)
            if entry is None:
                continue
            any_match = True
            kv = entry.get('Km')
            if pd.notna(kv):
                km_sum += float(kv)
            for c in cost_categories:
                v = entry.get(c)
                if pd.notna(v):
                    cat_sums[c] += float(v)

        if any_match:
            km_list.append(km_sum)
            for c in cost_categories:
                cat_cols[c].append(cat_sums[c])
            total_cost.append(sum(cat_sums.values()))
        else:
            km_list.append(None)
            for c in cost_categories:
                cat_cols[c].append(None)
            total_cost.append(None)

    result_df = result_df.copy()
    result_df['Km'] = km_list
    for c in cost_categories:
        result_df[c] = cat_cols[c]
    result_df['Teljes költség'] = total_cost
    result_df['Járati eredmény'] = (
        pd.to_numeric(result_df['Összes díj részarány (EUR)'], errors='coerce')
        - pd.to_numeric(result_df['Teljes költség'], errors='coerce')
    )
    return result_df


def _css_to_openpyxl_fill(css: str):
    """CSS háttér stringből openpyxl PatternFill. None, ha nem ismert."""
    if not isinstance(css, str):
        return None
    if 'lightgreen' in css:
        return PatternFill('solid', start_color='C6EFCE')
    if 'orange' in css:
        return PatternFill('solid', start_color='FFD699')
    if 'lightcoral' in css:
        return PatternFill('solid', start_color='FFC7CE')
    return None


# ------------------------------------------------------------------
# UI
# ------------------------------------------------------------------

uploaded_file = st.file_uploader(
    "Válaszd ki a fuvarnapló Excel fájlt",
    type=["xlsx"],
)
cost_files = st.file_uploader(
    "Válaszd ki a költség Excel fájl(oka)t – opcionális, több is lehet",
    type=["xlsx"],
    accept_multiple_files=True,
)

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.success(f"✅ Fuvarnapló betöltve: {len(df)} sor")

    df['Utolsó Leadási állomás időkapu (dátum)'] = pd.to_datetime(
        df['Utolsó Leadási állomás időkapu (dátum)'], errors='coerce'
    )
    df['Első Felvételi állomás időkapu (dátum)'] = pd.to_datetime(
        df['Első Felvételi állomás időkapu (dátum)'], errors='coerce'
    )

    available_years = sorted(
        df['Utolsó Leadási állomás időkapu (dátum)'].dt.year.dropna().unique()
    )

    col1, col2 = st.columns(2)
    with col1:
        selected_year = st.selectbox("Válassz évet", available_years)
    with col2:
        selected_month = st.selectbox(
            "Válassz hónapot",
            range(1, 13),
            format_func=lambda x: f"{x}. hónap"
        )

    if st.button("🔄 Körfuvarok generálása", type="primary"):
        with st.spinner("Feldolgozás folyamatban..."):
            df['Irány'] = df.apply(classify_leg_direction, axis=1)

            # --------------------------------------------------------
            # Előre-indexelés: fuvarszám-törzs -> egyedi vontatmányok száma.
            # --------------------------------------------------------
            tmp_torzs = df['Fuvarszám'].astype(str).map(_torzs_of)
            torzs_vontatmany_count = (
                df.assign(_torzs=tmp_torzs)
                  .groupby('_torzs')['Vontatmány']
                  .nunique()
                  .to_dict()
            )

            korfuvarok = []
            global_kor_id = 0

            # --------------------------------------------------------
            # Körök építése az ÖSSZES sorból, vontatmányonként.
            # --------------------------------------------------------
            for vontatmany, grp in df.groupby('Vontatmány'):
                grp_sorted = grp.sort_values([
                    'Utolsó Leadási állomás időkapu (dátum)',
                    'Első Felvételi állomás időkapu (dátum)'
                ])

                current_kor_legs = []
                current_fuv_torzsek = set()
                current_jaratszamok = set()

                for _, row in grp_sorted.iterrows():
                    f_szam = str(row['Fuvarszám'])
                    j_szam = str(row['Járatszám'])
                    f_torzs = _torzs_of(f_szam)
                    irany = row['Irány']

                    if not current_kor_legs:
                        global_kor_id += 1
                        current_kor_legs = [row]
                        current_fuv_torzsek = {f_torzs}
                        current_jaratszamok = {j_szam}
                        continue

                    prev_irany = current_kor_legs[-1]['Irány']

                    kapcsolodik_szam = (
                        f_torzs in current_fuv_torzsek
                    ) or (
                        j_szam in current_jaratszamok
                    )

                    irany_osszetartozo = False
                    if prev_irany.startswith('kifelé') and irany in [
                        'semleges', 'befelé-nemzetközi', 'befelé-belföldi'
                    ]:
                        irany_osszetartozo = True
                    if prev_irany == 'semleges' and irany in [
                        'semleges', 'befelé-nemzetközi', 'befelé-belföldi'
                    ]:
                        irany_osszetartozo = True

                    if kapcsolodik_szam or irany_osszetartozo:
                        current_kor_legs.append(row)
                        current_fuv_torzsek.add(f_torzs)
                        current_jaratszamok.add(j_szam)
                    else:
                        korfuvarok.append((global_kor_id, vontatmany, current_kor_legs))
                        global_kor_id += 1
                        current_kor_legs = [row]
                        current_fuv_torzsek = {f_torzs}
                        current_jaratszamok = {j_szam}

                if current_kor_legs:
                    korfuvarok.append((global_kor_id, vontatmany, current_kor_legs))

            # --------------------------------------------------------
            # Kimeneti tábla építése MINDEN körből
            # --------------------------------------------------------
            output_rows = []
            for kor_id, vontatmany, legs in korfuvarok:
                legs_df = pd.DataFrame(legs)

                total_dij = (
                    legs_df['Díj részarány (EUR)'].sum()
                    if 'Díj részarány (EUR)' in legs_df.columns else 0
                )
                all_vontatok = ' | '.join(
                    legs_df['Vontató'].astype(str).dropna().unique().tolist()
                )
                jaratszamok_lista = (
                    legs_df['Járatszám'].astype(str).str.strip().dropna().unique().tolist()
                )
                all_jaratszamok = ' | '.join(jaratszamok_lista)

                kifele_legs = legs_df[legs_df['Irány'].str.startswith('kifelé')]
                befele_legs = legs_df[legs_df['Irány'].str.startswith('befelé')]
                semleges_legs = legs_df[legs_df['Irány'] == 'semleges']

                kif_kezd_ido, kif_kezd_cim, kif_zar_ido, kif_zar_cim = get_interval_with_addresses(kifele_legs)
                sem_kezd_ido, sem_kezd_cim, sem_zar_ido, sem_zar_cim = get_interval_with_addresses(semleges_legs)
                bef_kezd_ido, bef_kezd_cim, bef_zar_ido, bef_zar_cim = get_interval_with_addresses(befele_legs)

                has_kifele = not kifele_legs.empty
                has_befele = not befele_legs.empty
                has_semleges = not semleges_legs.empty

                kor_kezd = (
                    kif_kezd_ido if pd.notna(kif_kezd_ido)
                    else (sem_kezd_ido if pd.notna(sem_kezd_ido) else bef_kezd_ido)
                )
                kor_veg = (
                    bef_zar_ido if pd.notna(bef_zar_ido)
                    else (sem_zar_ido if pd.notna(sem_zar_ido) else kif_zar_ido)
                )

                row = {
                    'Kör ID': kor_id,
                    'Vontatmány': vontatmany,
                    'Vontatók': all_vontatok,
                    'Járatszámok': all_jaratszamok,
                    'Kör kezdete dátum': kor_kezd,
                    'Kör vége dátum': kor_veg,
                    'Kifelé kezdő időkapu': kif_kezd_ido,
                    'Kifelé kezdő cím': kif_kezd_cim,
                    'Kifelé záró időkapu': kif_zar_ido,
                    'Kifelé záró cím': kif_zar_cim,
                    'Nemzetközi (semleges) kezdő időkapu': sem_kezd_ido,
                    'Nemzetközi (semleges) kezdő cím': sem_kezd_cim,
                    'Nemzetközi (semleges) záró időkapu': sem_zar_ido,
                    'Nemzetközi (semleges) záró cím': sem_zar_cim,
                    'Befelé kezdő időkapu': bef_kezd_ido,
                    'Befelé kezdő cím': bef_kezd_cim,
                    'Befelé záró időkapu': bef_zar_ido,
                    'Befelé záró cím': bef_zar_cim,
                    'Részfeladatok száma': len(legs_df),
                    'Fuvarszámok': ', '.join(legs_df['Fuvarszám'].astype(str).tolist()),
                    'Összes díj részarány (EUR)': total_dij,
                    'Deviza': 'EUR',
                    '_Has_kifele': has_kifele,
                    '_Has_befele': has_befele,
                    '_Has_semleges': has_semleges,
                    '_Korben_Fuvarszam_lista': legs_df['Fuvarszám'].astype(str).tolist(),
                    '_Korben_Jaratszam_lista': jaratszamok_lista,
                }
                output_rows.append(row)

            result_df_all = pd.DataFrame(output_rows)

            # --------------------------------------------------------
            # Magyarázat + színezés
            # --------------------------------------------------------
            magy = []
            szin = []
            for _, row in result_df_all.iterrows():
                problem_torzs = None
                for f in row['_Korben_Fuvarszam_lista']:
                    torzs = _torzs_of(f)
                    if torzs_vontatmany_count.get(torzs, 1) > 1:
                        problem_torzs = torzs
                        break

                if problem_torzs is not None:
                    exp = (
                        f"Változó vontatmány hiba: a {problem_torzs} fuvarszám törzs "
                        f"több különböző vontatmányon fut."
                    )
                    color = "background-color: lightcoral"
                else:
                    exp, color = _build_explanation(
                        row['_Has_kifele'],
                        row['_Has_befele'],
                        row['_Has_semleges'],
                    )

                magy.append(exp)
                szin.append(color)

            result_df_all['Magyarázat'] = magy
            result_df_all['Magyarázat_szín'] = szin

            # --------------------------------------------------------
            # Szűrés a kiválasztott év + hónap szerint (kör vége dátum alapján)
            # --------------------------------------------------------
            kor_vege_ser = pd.to_datetime(result_df_all['Kör vége dátum'], errors='coerce')
            mask = (
                (kor_vege_ser.dt.year == selected_year)
                & (kor_vege_ser.dt.month == selected_month)
            )
            result_df = result_df_all[mask].reset_index(drop=True)

            # --------------------------------------------------------
            # Költség aggregáció (ha van költség fájl)
            # --------------------------------------------------------
            combined_cost_df, cost_categories = load_all_cost_files(cost_files)
            has_cost = combined_cost_df is not None and not combined_cost_df.empty

            if has_cost:
                result_df = aggregate_cost_for_rings(
                    result_df, combined_cost_df, cost_categories
                )
                st.info(
                    f"💶 Költség fájl(ok) feldolgozva: {len(combined_cost_df)} egyedi járat, "
                    f"{len(cost_categories)} költség kategória."
                )

            # --------------------------------------------------------
            # Display df: belső oszlopok eldobása
            # --------------------------------------------------------
            internal_cols = [
                '_Has_kifele', '_Has_befele', '_Has_semleges',
                '_Korben_Fuvarszam_lista', '_Korben_Jaratszam_lista',
            ]
            result_df_display = result_df.drop(columns=internal_cols, errors='ignore')

            def highlight_row(row):
                styles = []
                for col in row.index:
                    if col == 'Magyarázat':
                        styles.append(row.get('Magyarázat_szín', '') or '')
                    elif col == 'Járati eredmény':
                        v = row.get('Járati eredmény')
                        if pd.notna(v):
                            if v < 0:
                                styles.append('background-color: lightcoral; color: black')
                            elif v > 0:
                                styles.append('background-color: lightgreen; color: black')
                            else:
                                styles.append('')
                        else:
                            styles.append('')
                    else:
                        styles.append('')
                return styles

            st.subheader("Generált körfuvarok (kiválasztott hónap szerint)")
            st.dataframe(result_df_display.style.apply(highlight_row, axis=1))

            # --------------------------------------------------------
            # XLSX export színezéssel
            # --------------------------------------------------------
            xlsx_df = result_df_display.drop(columns=['Magyarázat_szín'], errors='ignore')

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                xlsx_df.to_excel(writer, index=False, sheet_name='körfuvarok')
                ws = writer.sheets['körfuvarok']

                # oszlop-index lookup a fejléc alapján
                header_to_col = {}
                for c in range(1, ws.max_column + 1):
                    header_to_col[ws.cell(row=1, column=c).value] = c

                # Járati eredmény: zöld / piros a jel szerint
                er_col = header_to_col.get('Járati eredmény')
                if er_col is not None:
                    green_fill = PatternFill('solid', start_color='C6EFCE')
                    red_fill = PatternFill('solid', start_color='FFC7CE')
                    for r in range(2, ws.max_row + 1):
                        cell = ws.cell(row=r, column=er_col)
                        v = cell.value
                        if isinstance(v, (int, float)):
                            if v < 0:
                                cell.fill = red_fill
                            elif v > 0:
                                cell.fill = green_fill

                # Magyarázat: ugyanazok a színek mint a UI-n (zöld / narancs / piros)
                magy_col = header_to_col.get('Magyarázat')
                if magy_col is not None and 'Magyarázat_szín' in result_df_display.columns:
                    szinek = result_df_display['Magyarázat_szín'].tolist()
                    for i, css in enumerate(szinek):
                        fill = _css_to_openpyxl_fill(css)
                        if fill is not None:
                            ws.cell(row=i + 2, column=magy_col).fill = fill

            buffer.seek(0)
            st.download_button(
                label="📥 Körfuvarok letöltése (XLSX)",
                data=buffer,
                file_name=f"korfuvarok_{selected_year}_{selected_month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
