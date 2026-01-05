import streamlit as st

st.set_page_config(page_title="Painel Coleção - Zoologia", layout="wide")

# agora sim, resto dos imports
import sys
import typing_extensions
import pandas as pd
import plotly.express as px
import os
from pathlib import Path
import pydeck as pdk
import re
import xml.etree.ElementTree as ET
from openai import OpenAI
import json
import hashlib
import time

# ✅ debug SEM usar st.* aqui em cima
# se quiser debugar, faça depois, lá embaixo no app, ou use print()

# -----------------------------------------
# FUNÇÕES
# -----------------------------------------
@st.cache_data(show_spinner=False)
def load_data(arquivos):
    dfs_list = []
    for caminho in arquivos:
        if os.path.exists(caminho):
            try:
                df_temp = pd.read_excel(caminho, engine="openpyxl")
                dfs_list.append(df_temp)
            except Exception as e:
                st.error(f"Erro ao ler {caminho}: {e}")
    if not dfs_list:
        return pd.DataFrame()
    return pd.concat(dfs_list, ignore_index=True)

# Função usada para localizar arquivos de foto pelo número de ID do indivíduo
def find_photos_by_tombo(tombo_value: str, fotos_dir: Path):
    """
    Retorna lista de arquivos de imagem cujo NOME contém o tombo (case-insensitive).
    """
    if tombo_value is None:
        return []

    # normaliza: string "limpa" (pra evitar caracteres esquisitos)
    tombo = str(tombo_value).strip()
    if not tombo:
        return []

    # busca em extensões comuns
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    matches = []
    for p in fotos_dir.iterdir():
        if p.is_file() and p.suffix.lower() in exts:
            if tombo.lower() in p.name.lower():
                matches.append(p)
    return sorted(matches)

def sidebar_multiselect_filter(df_source_for_options, col_name, key_prefix="f"):
    # opções sempre a partir do DF "base" (estável)
    s_base = df_source_for_options[col_name].fillna("(vazio)").astype(str)
    options = sorted(s_base.unique())

    key_ms = f"{key_prefix}_{col_name}_ms"

    with st.sidebar.expander(f"Filtro: {col_name}", expanded=False):
        c1, c2 = st.columns(2)

        # init state
        if key_ms not in st.session_state:
            st.session_state[key_ms] = options.copy()

        # saneia: remove do estado qualquer item que não existe mais nas options
        st.session_state[key_ms] = [x for x in st.session_state[key_ms] if x in options]

        if c1.button("Tudo", key=f"{key_prefix}_{col_name}_all"):
            st.session_state[key_ms] = options.copy()

        if c2.button("Nenhum", key=f"{key_prefix}_{col_name}_none"):
            st.session_state[key_ms] = []

        selected = st.multiselect(
            "Selecione (digite para buscar)",
            options,
            default=st.session_state[key_ms],  # agora sempre válido
            key=key_ms,
            placeholder="Comece a digitar..."
        )

    return selected

def cascade_multiselect(df_current, col_name, key_prefix="f"):
    # opções baseadas no DF atual (já filtrado pelos filtros anteriores)
    s = df_current[col_name].fillna("(vazio)").astype(str)
    options = sorted(s.unique())

    key_ms = f"{key_prefix}_{col_name}_ms"

    with st.sidebar.expander(f"Filtro: {col_name}", expanded=False):
        c1, c2 = st.columns(2)

        # init: por padrão seleciona tudo que existe no estado atual
        if key_ms not in st.session_state:
            st.session_state[key_ms] = options.copy()

        # SANEAR: remove seleções que não existem mais nas opções atuais
        st.session_state[key_ms] = [x for x in st.session_state[key_ms] if x in options]

        if c1.button("Tudo", key=f"{key_prefix}_{col_name}_all"):
            st.session_state[key_ms] = options.copy()

        if c2.button("Nenhum", key=f"{key_prefix}_{col_name}_none"):
            st.session_state[key_ms] = []

        selected = st.multiselect(
            "Selecione (digite para buscar)",
            options,
            default=st.session_state[key_ms],
            key=key_ms,
            placeholder="Comece a digitar..."
        )

    return selected

def cascade_filter_autoall(df_current, col_name, key_prefix="f"):
    s = df_current[col_name].fillna("(vazio)").astype(str)
    options = sorted(s.unique())

    key_ms = f"{key_prefix}_{col_name}_ms"
    key_touched = f"{key_prefix}_{col_name}_touched"

    def _mark_touched():
        st.session_state[key_touched] = True

    # init touched
    if key_touched not in st.session_state:
        st.session_state[key_touched] = False

    # Se o usuário AINDA NÃO mexeu nesse filtro, mantenha SEMPRE "tudo selecionado"
    if (key_ms not in st.session_state) or (st.session_state[key_touched] is False):
        st.session_state[key_ms] = options.copy()
    else:
        # Se o usuário já mexeu, saneia (remove valores que não existem mais)
        st.session_state[key_ms] = [x for x in st.session_state[key_ms] if x in options]

    with st.sidebar.expander(f"Filtro: {col_name}", expanded=False):
        c1, c2 = st.columns(2)

        if c1.button("Tudo", key=f"{key_prefix}_{col_name}_all"):
            st.session_state[key_ms] = options.copy()
            st.session_state[key_touched] = False  # volta ao modo "auto-all"

        if c2.button("Nenhum", key=f"{key_prefix}_{col_name}_none"):
            st.session_state[key_ms] = []
            st.session_state[key_touched] = True  # usuário escolheu restringir

        selected = st.multiselect(
            "Selecione (digite para buscar)",
            options,
            default=st.session_state[key_ms],
            key=key_ms,
            on_change=_mark_touched,
            placeholder="Comece a digitar..."
        )

    return selected

def date_range_filter(df, date_col, key_prefix="d"):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    valid_dates = df[date_col].dropna()
    if valid_dates.empty:
        return df

    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()

    with st.sidebar.expander(f"Filtro: {date_col}", expanded=False):
        key_date = f"{key_prefix}_{date_col}_range"
        if key_date not in st.session_state:
            st.session_state[key_date] = (min_date, max_date)

        data_range = st.date_input(
            "Selecione o intervalo",
            value=st.session_state[key_date],
            key=key_date
        )

    if isinstance(data_range, tuple) and len(data_range) == 2:
        start_date, end_date = pd.to_datetime(data_range[0]), pd.to_datetime(data_range[1])
        mask = (df[date_col].isna()) | ((df[date_col] >= start_date) & (df[date_col] <= end_date))
        return df[mask]

    return df

def clear_all_filters():
    # remove tudo que termina com _ms (multiselects) e _range (datas)
    keys_to_delete = [k for k in st.session_state.keys() if k.endswith("_ms") or k.endswith("_range")]
    for k in keys_to_delete:
        del st.session_state[k]
    st.rerun()

# Função para gerenciar o arquivo kml e fazer o de-para do nome da coordenada para o Id do individuo

def parse_kml_points(kml_path: Path) -> pd.DataFrame:
    """
    Extrai pontos de um KML e retorna um DF com colunas:
      - 'N tombo coleção'
      - 'lat'
      - 'lon'

    Tenta obter o tombo em:
      1) Placemark/name
      2) Placemark/ExtendedData/Data[@name=...]/value (vários nomes possíveis)
    """
    if not kml_path.exists():
        return pd.DataFrame(columns=["N tombo coleção", "lat", "lon"])

    tree = ET.parse(kml_path)
    root = tree.getroot()

    # namespace KML (geralmente existe)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    def _find_text(elem, path_no_ns, path_ns):
        # tenta sem namespace e com namespace
        t = elem.findtext(path_no_ns)
        if t is None:
            t = elem.findtext(path_ns, namespaces=ns)
        return t

    def _get_tombo(pm):
        # 1) <name>
        name = _find_text(pm, "name", "kml:name")
        if name and name.strip():
            return name.strip()

        # 2) ExtendedData/Data
        # tenta alguns nomes comuns de campo
        candidates = {"N tombo coleção", "N_tombo_colecao", "tombo", "Tombo", "N_tombo"}
        # percorre todos Data
        for data in pm.findall(".//Data"):
            key = data.get("name")
            if key in candidates:
                val = data.findtext("value")
                if val and val.strip():
                    return val.strip()

        for data in pm.findall(".//kml:Data", namespaces=ns):
            key = data.get("name")
            if key in candidates:
                val = data.findtext("kml:value", namespaces=ns)
                if val and val.strip():
                    return val.strip()

        return None

    rows = []

    # pega placemarks com ponto
    placemarks = root.findall(".//Placemark") or root.findall(".//kml:Placemark", namespaces=ns)
    for pm in placemarks:
        tombo = _get_tombo(pm)

        # Point/coordinates: "lon,lat,alt" (alt opcional)
        coords = (
            _find_text(pm, ".//Point/coordinates", ".//kml:Point/kml:coordinates")
            or _find_text(pm, ".//coordinates", ".//kml:coordinates")
        )
        if not coords:
            continue

        # pode ter espaços/linhas; pegue o primeiro par
        coord_str = coords.strip().split()[0]
        parts = coord_str.split(",")
        if len(parts) < 2:
            continue

        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue

        if tombo is None:
            # se não achou tombo, ignora (ou você pode guardar como None)
            continue

        rows.append({"N tombo coleção": tombo, "lat": lat, "lon": lon})

    return pd.DataFrame(rows).drop_duplicates(subset=["N tombo coleção"])

# -----------------------------------------
# APP
# -----------------------------------------
st.title("Painel de Gestão da Coleção - Laboratório de Zoologia IF Barbacena")


# logo (se existir)
logo_path = Path("assets/logo_horizontal_barbacena-2.png")

FOTOS_DIR = Path("assets/fotos_colecao")
FOTOS_DIR.mkdir(parents=True, exist_ok=True)

KML_PATH = Path("assets/coordenadas/coletas.kml")
df_kml = parse_kml_points(KML_PATH)

if logo_path.exists():
    st.image(str(logo_path))

arquivos = [
    "dados_painel/Referência Amphibia.xlsx",
    "dados_painel/Referência Aves.xlsx",
    "dados_painel/Referência Mammalia.xlsx",
    "dados_painel/Referência Reptilia.xlsx",
]

dfs = load_data(arquivos)

# ===============================
# COORDENADAS (KML + FALLBACK)  ✅ ÚNICO BLOCO
# ===============================
dfs = dfs.copy()

# garante chave limpa
if "N tombo coleção" in dfs.columns:
    dfs["N tombo coleção"] = dfs["N tombo coleção"].astype(str).str.strip()

# remove qualquer coluna antiga de coordenadas pra evitar colisão
for c in ["lat", "lon", "long"]:
    if c in dfs.columns:
        dfs.drop(columns=[c], inplace=True)

# merge com KML (se existir)
if "N tombo coleção" in dfs.columns and not df_kml.empty:
    df_kml = df_kml.copy()
    df_kml["N tombo coleção"] = df_kml["N tombo coleção"].astype(str).str.strip()
    dfs = dfs.merge(df_kml, on="N tombo coleção", how="left")

# garante que as colunas existam SEMPRE (mesmo se não tiver KML)
if "lat" not in dfs.columns:
    dfs["lat"] = pd.NA
if "lon" not in dfs.columns:
    dfs["lon"] = pd.NA

# fallback só onde estiver vazio
dfs["lat"] = pd.to_numeric(dfs["lat"], errors="coerce").fillna(-21.2264)
dfs["lon"] = pd.to_numeric(dfs["lon"], errors="coerce").fillna(-43.7742)

# seu padrão antigo usava "long"
dfs["long"] = dfs["lon"]

if dfs.empty:
    st.warning("Nenhum arquivo foi carregado. Verifique a pasta `dados_painel/` e os nomes dos arquivos.")
    st.stop()


df_filtered = dfs.copy()

# -----------------------
# SIDEBAR: FILTROS (dinâmicos)
# -----------------------
st.sidebar.header("Filtros")

if st.sidebar.button("Limpar TODOS os filtros"):
    keys_to_delete = [
        k for k in st.session_state.keys()
        if k.endswith("_ms") or k.endswith("_touched") or k.endswith("_range")
    ]
    for k in keys_to_delete:
        del st.session_state[k]
    st.rerun()

filter_order = [
    "Classe",
    "Ordem",
    "Familia",
    "Nome cientifico",
    "Nome comum",
    "Municipio",
    "Vidro",
    "Armario",
    "Coletor",
    "Idade",
    "Sexo",
]

df_filtered = dfs.copy()

for col in filter_order:
    if col in df_filtered.columns:
        selected = cascade_filter_autoall(df_filtered, col)
        s = df_filtered[col].fillna("(vazio)").astype(str)
        df_filtered = df_filtered[s.isin(selected)]

if "Data entrada" in df_filtered.columns:
    df_filtered = date_range_filter(df_filtered, "Data entrada")


# -----------------------
# KPIs
# -----------------------
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

with kpi1:
    st.metric("Quantidade de indivíduos", int(df_filtered.shape[0]))

with kpi2:
    st.metric("Mamíferos", int(df_filtered.loc[df_filtered.get("Classe").astype(str) == "Mammalia"].shape[0]) if "Classe" in df_filtered.columns else 0)

with kpi3:
    st.metric("Aves", int(df_filtered.loc[df_filtered.get("Classe").astype(str) == "Aves"].shape[0]) if "Classe" in df_filtered.columns else 0)

with kpi4:
    st.metric("Répteis", int(df_filtered.loc[df_filtered.get("Classe").astype(str) == "Reptilia"].shape[0]) if "Classe" in df_filtered.columns else 0)

with kpi5:
    st.metric("Anfíbios", int(df_filtered.loc[df_filtered.get("Classe").astype(str) == "Amphibia"].shape[0]) if "Classe" in df_filtered.columns else 0)


kpi6, kpi7, kpi8, kpi9 = st.columns(4)

with kpi6:
    st.metric("Quantidade de ordens distintas", int(df_filtered.get("Ordem").nunique()))
with kpi7:
    st.metric("Quantidade de famílias distintas", int(df_filtered.get("Familia").nunique()))
with kpi8:
    st.metric("Quantidade de espécies distintas", int(df_filtered.get("Nome cientifico").nunique()))
with kpi9:
    st.metric("Quantidade de municípios com coleta", int(df_filtered.get("Municipio").nunique()))

st.subheader("Amostragem dos Dados (clique numa linha para ver foto)")

# Mostra a tabela com seleção de linha
event = st.dataframe(
    df_filtered,
    use_container_width=True,
    hide_index=True,
    selection_mode="single-row",
    on_select="rerun",
)

selected_tombo = None
if event and "selection" in event and event["selection"].get("rows"):
    row_idx = event["selection"]["rows"][0]  # índice na visão atual do df_filtered
    if "N tombo coleção" in df_filtered.columns:
        selected_tombo = df_filtered.iloc[row_idx]["N tombo coleção"]

st.divider()

st.subheader("Foto do exemplar (por N tombo coleção)")

if "N tombo coleção" not in df_filtered.columns:
    st.info("A coluna 'N tombo coleção' não existe no dataset.")
else:
    if selected_tombo is None:
        st.info("Clique em uma linha na tabela para selecionar um 'N tombo coleção' e ver a foto.")
    else:
        st.write(f"**N tombo coleção selecionado:** {selected_tombo}")

        fotos = find_photos_by_tombo(selected_tombo, FOTOS_DIR)

        if not fotos:
            st.warning("Nenhuma foto encontrada na pasta 'fotos/' cujo nome contenha esse N tombo coleção.")
        else:
            # mostra todas (se tiver mais de uma)
            st.image([str(p) for p in fotos], caption=[p.name for p in fotos], use_container_width=True)

st.subheader("Upload de novas fotos")

uploaded_files = st.file_uploader(
    "Envie uma ou mais imagens (serão salvas em fotos/)",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    saved = 0
    for uf in uploaded_files:
        # nome seguro (remove path e caracteres estranhos)
        safe_name = Path(uf.name).name
        safe_name = re.sub(r"[^A-Za-z0-9._\-() ]+", "_", safe_name)

        out_path = FOTOS_DIR / safe_name

        # evita sobrescrever sem querer (opcional)
        #if out_path.exists():
        #    stem = out_path.stem
        #    suffix = out_path.suffix
        #    i = 1
        #    while (FOTOS_DIR / f"{stem} ({i}){suffix}").exists():
        #        i += 1
        #    out_path = FOTOS_DIR / f"{stem} ({i}){suffix}"

        out_path.write_bytes(uf.getbuffer())
        saved += 1

    st.success(f"{saved} arquivo(s) salvo(s) em: {FOTOS_DIR.resolve()}")


# -----------------------
# CONTAGEM POR MUNICÍPIO
# -----------------------
if "Municipio" in df_filtered.columns:
    municipio_count = (
        df_filtered.assign(Municipio=df_filtered["Municipio"].fillna("(vazio)").astype(str))
        .groupby("Municipio")
        .size()
        .reset_index(name="Contagem")
        .sort_values(by="Contagem", ascending=False)
        .reset_index(drop=True)
    )

    fig_municipio = px.bar(
        municipio_count,
        x="Municipio",
        y="Contagem",
        labels={"Municipio": "Município", "Contagem": "Número de Linhas"},
        title="Contagem por Município"
    )
    st.plotly_chart(fig_municipio, use_container_width=True)

# -----------------------
# CONTAGEM POR MÊS
# -----------------------
if "Data entrada" in df_filtered.columns:
    df_tmp = df_filtered.copy()
    df_tmp["Data entrada"] = pd.to_datetime(df_tmp["Data entrada"], errors="coerce")
    df_tmp["Mês"] = df_tmp["Data entrada"].dt.to_period("M").astype(str)

    mes_count = (
        df_tmp.dropna(subset=["Mês"])
        .groupby("Mês")
        .size()
        .reset_index(name="Contagem")
        .sort_values("Mês")
    )

    fig_mes = px.bar(
        mes_count,
        x="Mês",
        y="Contagem",
        labels={"Mês": "Mês", "Contagem": "Número de Linhas"},
        title="Contagem por Mês"
    )
    st.plotly_chart(fig_mes, use_container_width=True)

# -----------------------
# BOXPLOT DO PESO
# -----------------------
if "Peso (g)" in df_filtered.columns:
    df_box = df_filtered.copy()
    df_box["Peso (g)"] = pd.to_numeric(df_box["Peso (g)"], errors="coerce")
    df_box = df_box.dropna(subset=["Peso (g)"])

    st.subheader("Boxplot do Peso (g) por variável categórica")

    opcoes_boxplot = ["Nome cientifico", "Familia", "Sexo", "Idade", "Municipio"]
    opcoes_boxplot = [c for c in opcoes_boxplot if c in df_box.columns]

    if opcoes_boxplot:
        default_axis = opcoes_boxplot[0]
        boxplot_x_axis = st.selectbox(
            "Selecione a variável para o eixo X do boxplot:",
            opcoes_boxplot,
            index=0
        )

        fig_box = px.box(
            df_box,
            x=boxplot_x_axis,
            y="Peso (g)",
            labels={boxplot_x_axis: boxplot_x_axis.capitalize(), "Peso (g)": "Peso (g)"},
            title=f"Distribuição do Peso (g) por {boxplot_x_axis.capitalize()}"
        )
        st.plotly_chart(fig_box, use_container_width=True)

        st.write("Estatísticas descritivas (medidas)")
        columns_to_describe = [
            "Peso (g)",
            "Cp rostro anal (mm)",
            "Cp cauda (mm)",
            "Cp pata D (mm)",
            "Cp pata T (mm)",
            "Cp orelha (mm)",
            "Cp ante braço (mm)",
            "Cp trago (mm)",
            "Cp folha nasal (mm)",
            "Cp tarso (mm)",
            "Altura bico (mm)",
            "Largura bico (mm)",
            "Cp bico (mm)",
            "Cp asa (mm)",
            "Cp cabeça (mm)",
            "Cp olho narina (mm)",
            "Cp femur (mm)",
            "Cp tibia (mm)",
            "Cp umero (mm)",
            "Cp interorbital (mm)",
            "Cp timpano (mm)",
            "Cp interparotidica (mm)",
            "D palpebra (mm)",
            "N escamas (mm)",
            "Alt cabeça (mm)",
            "Lar cabeça (mm)",
            "Cp internasal (mm)",
            "Cp carpo (mm)",
        ]
        columns_to_describe = [c for c in columns_to_describe if c in df_box.columns]
        if columns_to_describe:
            st.dataframe(df_box[columns_to_describe].describe().T.round(2), use_container_width=True)
    else:
        st.info("Nenhuma coluna categórica padrão (Nome cientifico/Familia/Sexo/Idade/Municipio) foi encontrada para o boxplot.")
else:
    st.info("A coluna 'Peso (g)' não foi encontrada no arquivo.")


# -----------------------
# MAPA (pydeck)
# -----------------------
st.subheader("Mapa de Coordenadas (WIP)")

df_geo = df_filtered.copy()
df_geo["lat"] = pd.to_numeric(df_geo["lat"], errors="coerce")
df_geo["lon"] = pd.to_numeric(df_geo["lon"], errors="coerce")
df_geo = df_geo.dropna(subset=["lat", "lon"])

if df_geo.empty:
    st.info("Sem coordenadas válidas para exibir no mapa.")
else:
    # enquadramento automático
    view_state = pdk.data_utils.compute_view(df_geo[["lon", "lat"]])
    view_state.pitch = 0
    view_state.bearing = 0

    # garante colunas pro tooltip
    if "N tombo coleção" not in df_geo.columns:
        df_geo["N tombo coleção"] = ""
    if "Nome cientifico" not in df_geo.columns:
        df_geo["Nome cientifico"] = ""

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_geo,
        get_position="[lon, lat]",

        # 🔴 cor forte (vermelho) com leve transparência
        get_fill_color=[220, 38, 38, 180],   # RGBA

        # 🔹 ponto menor, consistente em qualquer zoom
        get_radius=.004,
        radius_units="pixels",

        pickable=True,
        auto_highlight=True,

        # destaque no hover
        highlight_color=[0, 0, 0, 255],
    )

    st.pydeck_chart(
        pdk.Deck(
            map_style="mapbox://styles/mapbox/satellite-streets-v12",
            initial_view_state=view_state,
            layers=[layer],
            tooltip={
                "html": """
                <b>N tombo coleção:</b> {N tombo coleção}<br/>
                <b>Nome científico:</b> {Nome cientifico}
                """,
                "style": {
                    "backgroundColor": "rgba(255,255,255,0.95)",
                    "color": "black",
                    "fontSize": "13px",
                    "padding": "8px",
                },
            },
        )
    )

st.subheader("Assistente (pergunte sobre os arquivos)")

