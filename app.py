import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="Bábolna Körfuvar Generálás", layout="wide")
st.title("🚛 Bábolna Körfuvar Generálás")
st.markdown("---")

HU_PREFIX = 'HU '
BABOLNA_KEYWORD = 'Bábolna Rákóczi utca'


# ------------------------------------------------------------------
# Segédfüggvények
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
    """A kör tartalma alapján visszaadja a magyarázatot és a színt.

    - Zöld: teljes kör (kifelé és befelé együtt).
    - Narancs: részleges kör – vagy csak kifelé, vagy csak befelé, vagy csak semleges,
      vagy valamelyik hiányzik.
    """
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
# UI
# ------------------------------------------------------------------

uploaded_file = st.file_uploader("Válaszd ki a fuvarnapló Excel fájlt", type=["xlsx"])

if uploaded_file is not None:
    df = pd.read_excel(uploaded_file)
    st.success(f"✅ Fájl betöltve: {len(df)} sor")

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
            # Ez kell a "változó vontatmány" piros jelzéshez, így nem kell
            # körönként újra végigpörgetni a teljes df-et.
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
                jaratszamok_lista = legs_df['Járatszám'].astype(str).dropna().unique().tolist()
                all_jaratszamok = ' | '.join(jaratszamok_lista)

                # irányonkénti részhalmazok
                kifele_legs = legs_df[legs_df['Irány'].str.startswith('kifelé')]
                befele_legs = legs_df[legs_df['Irány'].str.startswith('befelé')]
                semleges_legs = legs_df[legs_df['Irány'] == 'semleges']

                kif_kezd_ido, kif_kezd_cim, kif_zar_ido, kif_zar_cim = get_interval_with_addresses(kifele_legs)
                sem_kezd_ido, sem_kezd_cim, sem_zar_ido, sem_zar_cim = get_interval_with_addresses(semleges_legs)
                bef_kezd_ido, bef_kezd_cim, bef_zar_ido, bef_zar_cim = get_interval_with_addresses(befele_legs)

                has_kifele = not kifele_legs.empty
                has_befele = not befele_legs.empty
                has_semleges = not semleges_legs.empty

                # Kör kezdete: elsősorban a kifelé kezdő időkapu.
                # Ha nincs kifelé szakasz: semleges, majd befelé.
                kor_kezd = (
                    kif_kezd_ido if pd.notna(kif_kezd_ido)
                    else (sem_kezd_ido if pd.notna(sem_kezd_ido) else bef_kezd_ido)
                )
                # Kör vége: elsősorban a befelé záró időkapu.
                # Ha nincs befelé szakasz: semleges, majd kifelé.
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
                    # Belső mezők – a későbbi költség/futás aggregáláshoz és a magyarázathoz
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
                # 1) Piros: változó vontatmány (előre indexelt lookup alapján)
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
                    # 2) Zöld / narancs: a kör tartalma alapján
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

            internal_cols = [
                '_Has_kifele', '_Has_befele', '_Has_semleges',
                '_Korben_Fuvarszam_lista', '_Korben_Jaratszam_lista',
            ]
            result_df_display = result_df.drop(columns=internal_cols, errors='ignore')

            def highlight_explanation(row):
                return [
                    row['Magyarázat_szín'] if col == 'Magyarázat' else ''
                    for col in row.index
                ]

            st.subheader("Generált körfuvarok (kiválasztott hónap szerint)")
            st.dataframe(result_df_display.style.apply(highlight_explanation, axis=1))

            # A letöltendő XLSX-ből a technikai 'Magyarázat_szín' oszlopot is kivesszük.
            xlsx_df = result_df_display.drop(columns=['Magyarázat_szín'], errors='ignore')

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                xlsx_df.to_excel(writer, index=False, sheet_name='körfuvarok')
            buffer.seek(0)
            st.download_button(
                label="📥 Körfuvarok letöltése (XLSX)",
                data=buffer,
                file_name=f"korfuvarok_{selected_year}_{selected_month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
