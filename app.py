import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="Bábolna Körfuvar Generálás", layout="wide")

st.title("🚛 Bábolna Körfuvar Generálás")
st.markdown("---")

HU_PREFIX = 'HU '
BABOLNA_KEYWORD = 'Bábolna Rákóczi utca'


def classify_leg_direction(row):
    fel = str(row['Első Felvételi állomás cím'])
    le = str(row['Utolsó Leadási állomás cím'])
    tipus = str(row['Fuvarfeladat típusa'])

    fel_hu = fel.startswith(HU_PREFIX)
    le_hu = le.startswith(HU_PREFIX)
    fel_babolna = BABOLNA_KEYWORD in fel
    le_babolna = BABOLNA_KEYWORD in le

    # Elsődleges szabály: típus alapján
    if 'Export' in tipus:
        return 'kifelé-nemzetközi'
    if 'Import' in tipus:
        return 'befelé-nemzetközi'

    # Harmadik országos: semleges
    if tipus.startswith('Harmadik országba szállítás'):
        return 'semleges'

    # Másodlagos szabály: cím logika (fallback)
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


def get_interval_with_addresses(legs_df: pd.DataFrame):
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

    if legs_df['Első Felvételi állomás időkapu (dátum)'].dropna().empty or \
       legs_df['Utolsó Leadási állomás időkapu (dátum)'].dropna().empty:
        return (pd.NaT, None, pd.NaT, None)

    legs_df = legs_df.copy()
    legs_df['Fuvar_torzs'] = legs_df['Fuvarszám'].astype(str).str.split('-').str[0]

    dup_torzsek = legs_df['Fuvar_torzs'].value_counts()
    dup_torzsek = dup_torzsek[dup_torzsek > 1].index.tolist()

    if dup_torzsek:
        t = dup_torzsek[0]
        same = legs_df[legs_df['Fuvar_torzs'] == t].copy()

        if same.empty:
            valid_start = legs_df.dropna(subset=['Első Felvételi állomás időkapu (dátum)'])
            valid_end = legs_df.dropna(subset=['Utolsó Leadási állomás időkapu (dátum)'])

            if valid_start.empty or valid_end.empty:
                return (pd.NaT, None, pd.NaT, None)

            idx_start = valid_start['Első Felvételi állomás időkapu (dátum)'].idxmin()
            idx_end = valid_end['Utolsó Leadási állomás időkapu (dátum)'].idxmax()
            row_start = legs_df.loc[idx_start]
            row_end = legs_df.loc[idx_end]
        else:
            same['Reszfeladat'] = (
                same['Fuvarszám'].astype(str).str.split('-').str[1].astype(int)
            )
            row_start = same.loc[same['Reszfeladat'].idxmin()]
            row_end = same.loc[same['Reszfeladat'].idxmax()]
    else:
        valid_start = legs_df.dropna(subset=['Első Felvételi állomás időkapu (dátum)'])
        valid_end = legs_df.dropna(subset=['Utolsó Leadási állomás időkapu (dátum)'])

        if valid_start.empty or valid_end.empty:
            return (pd.NaT, None, pd.NaT, None)

        idx_start = valid_start['Első Felvételi állomás időkapu (dátum)'].idxmin()
        idx_end = valid_end['Utolsó Leadási állomás időkapu (dátum)'].idxmax()
        row_start = legs_df.loc[idx_start]
        row_end = legs_df.loc[idx_end]

    start_dt = row_start['Első Felvételi állomás időkapu (dátum)']
    start_addr = row_start['Első Felvételi állomás cím']
    end_dt = row_end['Utolsó Leadási állomás időkapu (dátum)']
    end_addr = row_end['Utolsó Leadási állomás cím']

    return (start_dt, start_addr, end_dt, end_addr)


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

            korfuvarok = []
            global_kor_id = 0

            # Körök építése az ÖSSZES sorból
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
                    f_torzs = f_szam.split('-')[0]
                    irany = row['Irány']

                    if not current_kor_legs:
                        global_kor_id += 1
                        current_kor_legs = [row]
                        current_fuv_torzsek = {f_torzs}
                        current_jaratszamok = {j_szam}
                        continue

                    prev_irany = current_kor_legs[-1]['Irány']

                    kapcsolodik_szam = (f_torzs in current_fuv_torzsek) or (j_szam in current_jaratszamok)

                    irany_osszetartozo = False
                    if prev_irany.startswith('kifelé') and irany in ['semleges', 'befelé-nemzetközi', 'befelé-belföldi']:
                        irany_osszetartozo = True
                    if prev_irany == 'semleges' and irany in ['semleges', 'befelé-nemzetközi', 'befelé-belföldi']:
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

            # Kimeneti táblázat építése MINDEN körből
            output_rows = []
            for kor_id, vontatmany, legs in korfuvarok:
                legs_df = pd.DataFrame(legs)

                total_dij = legs_df['Díj részarány (EUR)'].sum() if 'Díj részarány (EUR)' in legs_df.columns else 0

                all_vontatok = ' | '.join(
                    legs_df['Vontató'].astype(str).dropna().unique().tolist()
                )
                all_jaratszamok = ' | '.join(
                    legs_df['Járatszám'].astype(str).dropna().unique().tolist()
                )

                first = legs_df.iloc[0]
                last = legs_df.iloc[-1]

                kifele_legs = legs_df[legs_df['Irány'].str.startswith('kifelé')]
                befele_legs = legs_df[legs_df['Irány'].str.startswith('befelé')]
                semleges_legs = legs_df[legs_df['Irány'] == 'semleges']

                kif_kezd_ido, kif_kezd_cim, kif_zar_ido, kif_zar_cim = get_interval_with_addresses(kifele_legs)
                sem_kezd_ido, sem_kezd_cim, sem_zar_ido, sem_zar_cim = get_interval_with_addresses(semleges_legs)
                bef_kezd_ido, bef_kezd_cim, bef_zar_ido, bef_zar_cim = get_interval_with_addresses(befele_legs)

                iranyok_korben = legs_df['Irány'].tolist()
                teljes_kor = any(i.startswith('kifelé') for i in iranyok_korben) and \
                             any(i.startswith('befelé') for i in iranyok_korben)

                row = {
                    'Kör ID': kor_id,
                    'Vontatmány': vontatmany,
                    'Vontatók': all_vontatok,
                    'Járatszámok': all_jaratszamok,
                    'Kör kezdete dátum': first['Első Felvételi állomás időkapu (dátum)'],
                    'Kör vége dátum': last['Utolsó Leadási állomás időkapu (dátum)'],

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

                    '_Teljes_kor': teljes_kor,
                    '_Korben_Fuvarszam_lista': legs_df['Fuvarszám'].astype(str).tolist(),
                }
                output_rows.append(row)

            result_df_all = pd.DataFrame(output_rows)

            # Magyarázat + szín meghatározása
            magy = []
            szin = []

            for idx, row in result_df_all.iterrows():
                teljes_kor = row['_Teljes_kor']
                kor_fuv_lista = row['_Korben_Fuvarszam_lista']

                # default: narancs, később pontosítjuk
                exp = ""
                color = "background-color: orange"

                # Teljes kör esetén zöld alap
                if teljes_kor:
                    exp = "Teljes kifelé–befelé kör lezárása után új kör indul."
                    color = "background-color: lightgreen"

                # Piros: ugyanazon fuvarszám-törzs több vontatmánnyal
                # végig a teljes eredeti df-en nézzük
                valtozo_vontatmany = False
                problem_fuv_torzs = None
                for f in kor_fuv_lista:
                    torzs = f.split('-')[0]
                    same_torzs = df[df['Fuvarszám'].astype(str).str.startswith(torzs + "-")]
                    if not same_torzs.empty:
                        if same_torzs['Vontatmány'].nunique() > 1:
                            valtozo_vontatmany = True
                            problem_fuv_torzs = torzs
                            break

                if valtozo_vontatmany:
                    exp = f"Változó vontatmány hiba: a {problem_fuv_torzs} fuvarszám törzs több különböző vontatmányon fut."
                    color = "background-color: lightcoral"

                # Ha sem zöld, sem piros nem lett, építsünk részletes narancs magyarázatot
                if not exp:
                    changes = []

                    # nézzük a következő kört, ha van
                    if idx < len(result_df_all) - 1:
                        next_row = result_df_all.iloc[idx + 1]

                        # irányperiféria: utolsó és következő kör irányai
                        # (csak információs jelleggel)
                        # Fuvarszám-törzs és járatszám metszet
                        current_fuv_torzsek = {
                            f.split('-')[0] for f in row['_Korben_Fuvarszam_lista']
                        }
                        next_fuv_torzsek = {
                            f.split('-')[0] for f in next_row['_Korben_Fuvarszam_lista']
                        }
                        common_torzs = current_fuv_torzsek.intersection(next_fuv_torzsek)
                        common_jarat = set(
                            row['Járatszámok'].split(' | ')
                            if isinstance(row['Járatszámok'], str) and row['Járatszámok'] else []
                        ).intersection(
                            set(next_row['Járatszámok'].split(' | ')
                                if isinstance(next_row['Járatszámok'], str) and next_row['Járatszámok'] else [])
                        )

                        if not common_torzs:
                            changes.append("fuvarszám-törzs változás")
                        if not common_jarat:
                            changes.append("járatszám változás")

                        # irány mint információ: jelen kör irányai
                        iranyok = row['_Korben_Fuvarszam_lista']  # csak placeholder, ha kellene bővíteni

                    if not changes:
                        changes.append("irány/járat/fuvarszám mintázat eltérés")

                    exp = "Új kör indul, mert " + ", ".join(changes) + " történik."
                    color = "background-color: orange"

                magy.append(exp)
                szin.append(color)

            result_df_all['Magyarázat'] = magy
            result_df_all['Magyarázat_szín'] = szin

            mask = (
                (result_df_all['Kör vége dátum'].dt.year == selected_year) &
                (result_df_all['Kör vége dátum'].dt.month == selected_month)
            )
            result_df = result_df_all[mask].reset_index(drop=True)

            result_df_display = result_df.drop(
                columns=['_Teljes_kor', '_Korben_Fuvarszam_lista'],
                errors='ignore'
            )

            def highlight_explanation(row):
                return [
                    row['Magyarázat_szín'] if col == 'Magyarázat' else ''
                    for col in row.index
                ]

            st.subheader("Generált körfuvarok (kiválasztott hónap szerint)")
            st.dataframe(result_df_display.style.apply(highlight_explanation, axis=1))

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                result_df_display.to_excel(writer, index=False, sheet_name='körfuvarok')
            buffer.seek(0)

            st.download_button(
                label="📥 Körfuvarok letöltése (XLSX)",
                data=buffer,
                file_name=f"korfuvarok_{selected_year}_{selected_month}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
