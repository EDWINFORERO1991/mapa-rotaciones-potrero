
import streamlit as st
import pandas as pd
import folium
import zipfile
import xml.etree.ElementTree as ET
import re
from streamlit_folium import st_folium


# ============================================================
# PGVE - MAPA OPERATIVO
# Fuentes:
# 1. Tabla Maestra PGVE 2026.xlsx
# 2. Analisis_Rotaciones_Potrero_Actual.xlsx
# 3. KML_Potreros_PGVE.zip
# 4. KML_Puntos_PGVE.zip
# 5. KML_Lineas_PGVE.zip
# ============================================================

st.set_page_config(
    page_title="PGVE - Mapa Operativo",
    page_icon="🌱",
    layout="wide"
)

ARCHIVO_MAESTRO = "Tabla Maestra PGVE 2026.xlsx"
ARCHIVO_MOV = "Analisis_Rotaciones_Potrero_Actual.xlsx"
ZIP_POTREROS = "KML_Potreros_PGVE.zip"
ZIP_PUNTOS = "KML_Puntos_PGVE.zip"
ZIP_LINEAS = "KML_Lineas_PGVE.zip"


# ============================================================
# FUNCIONES
# ============================================================

def txt(v):
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def mostrar(v, sufijo=""):
    if v is None or pd.isna(v) or str(v).strip() == "":
        return "No disponible"
    return f"{v}{sufijo}"


def es_majada(codigo):
    codigo = txt(codigo)
    return codigo.startswith("M") and "-B" in codigo


def normalizar_rotacion(v):
    v = txt(v)
    if not v:
        return ""
    if v.startswith("R"):
        return v
    if v.isdigit():
        return f"R{int(v):02d}"
    # casos como 01VE en la Tabla Maestra
    m = re.match(r"^(\d{1,2})([A-Z]{2})$", v)
    if m:
        return f"R{int(m.group(1)):02d}{m.group(2)}"
    return v


def clave_rotacion(predio, rotacion):
    p = txt(predio)
    r = txt(rotacion)
    if not p or not r:
        return ""
    if r.startswith("R") and r.endswith(p):
        return r
    if r.startswith("R"):
        return r + p
    return f"R{int(r):02d}{p}" if r.isdigit() else r + p


def potrero_con_predio(codigo, predio):
    c = txt(codigo)
    p = txt(predio)
    if not c:
        return ""
    if p and c.endswith(p):
        return c
    if c.startswith("P") and "-R" in c and p:
        return c + p
    return c


def kml_ns():
    return {"k": "http://www.opengis.net/kml/2.2"}


def kml_name(root):
    ns = kml_ns()
    node = root.find(".//k:Placemark/k:name", ns)
    return txt(node.text) if node is not None and node.text else ""


def read_polygon_features(zpath):
    features = []
    with zipfile.ZipFile(zpath, "r") as z:
        names = [n for n in z.namelist() if n.lower().endswith(".kml")]
        for fname in names:
            root = ET.fromstring(z.read(fname))
            code = kml_name(root) or txt(fname.split("/")[-1].rsplit(".", 1)[0])
            ns = kml_ns()

            for poly in root.findall(".//k:Polygon", ns):
                node = poly.find(
                    ".//k:outerBoundaryIs/k:LinearRing/k:coordinates",
                    ns
                )
                if node is None or not node.text:
                    continue

                ring = []
                for p in node.text.strip().split():
                    parts = p.split(",")
                    if len(parts) >= 2:
                        try:
                            ring.append([float(parts[1]), float(parts[0])])
                        except ValueError:
                            pass

                if len(ring) >= 3:
                    features.append((code, ring))
    return features


def read_points(zpath):
    points = []
    with zipfile.ZipFile(zpath, "r") as z:
        names = [n for n in z.namelist() if n.lower().endswith(".kml")]
        for fname in names:
            root = ET.fromstring(z.read(fname))
            name = kml_name(root) or txt(fname.split("/")[-1].rsplit(".", 1)[0])
            ns = kml_ns()

            for node in root.findall(".//k:Point/k:coordinates", ns):
                if not node.text:
                    continue
                parts = node.text.strip().split(",")
                if len(parts) >= 2:
                    try:
                        points.append((name, float(parts[1]), float(parts[0])))
                    except ValueError:
                        pass
    return points


def read_lines(zpath):
    lines = []
    with zipfile.ZipFile(zpath, "r") as z:
        names = [n for n in z.namelist() if n.lower().endswith(".kml")]
        for fname in names:
            root = ET.fromstring(z.read(fname))
            name = kml_name(root) or txt(fname.split("/")[-1].rsplit(".", 1)[0])
            ns = kml_ns()

            for node in root.findall(".//k:LineString/k:coordinates", ns):
                if not node.text:
                    continue

                coords = []
                for p in node.text.strip().split():
                    parts = p.split(",")
                    if len(parts) >= 2:
                        try:
                            coords.append([float(parts[1]), float(parts[0])])
                        except ValueError:
                            pass

                if len(coords) >= 2:
                    lines.append((name, coords))
    return lines


def fecha_texto(v):
    if v is None or pd.isna(v):
        return "No disponible"
    try:
        return pd.to_datetime(v).strftime("%d/%m/%Y")
    except Exception:
        return str(v)


# ============================================================
# CARGAR TABLA MAESTRA
# ============================================================

try:
    maestro = pd.read_excel(
        ARCHIVO_MAESTRO,
        sheet_name="General Potreros"
    )
except Exception as e:
    st.error(f"No se pudo leer la Tabla Maestra: {e}")
    st.stop()

required_master = [
    "Predio", "Rotación", "Potrero", "Bebedero",
    "Área (ha)", "Estado", "Fecha Establecimiento"
]

missing = [c for c in required_master if c not in maestro.columns]

if missing:
    st.error("Faltan columnas en la Tabla Maestra: " + ", ".join(missing))
    st.stop()

for c in ["Predio", "Rotación", "Potrero", "Bebedero", "Estado"]:
    maestro[c] = maestro[c].apply(txt)

maestro["Área (ha)"] = pd.to_numeric(
    maestro["Área (ha)"], errors="coerce"
)

maestro["Es_Majada"] = maestro["Potrero"].apply(es_majada)

# Clave de rotación para el modelo
maestro["Clave_Rotacion"] = maestro.apply(
    lambda r: "" if r["Es_Majada"] else clave_rotacion(
        r["Predio"], r["Rotación"]
    ),
    axis=1
)

maestro_lookup = maestro.drop_duplicates("Potrero").set_index("Potrero")


# ============================================================
# CARGAR ANALISIS DE ROTACIONES
# ============================================================

try:
    mov = pd.read_excel(
        ARCHIVO_MOV,
        sheet_name="Estado_Rotaciones"
    )
except Exception as e:
    st.error(f"No se pudo leer el análisis de rotaciones: {e}")
    st.stop()

required_mov = [
    "Potrero",
    "Rotacion",
    "Última fecha de movimiento",
    "Lote",
    "Tipo de lote",
    "Cantidad de animales",
    "Altura promedio actual (cm)",
    "Altura promedio anterior (cm)",
    "Mediciones válidas",
    "Observaciones"
]

missing_mov = [c for c in required_mov if c not in mov.columns]

if missing_mov:
    st.error(
        "Faltan columnas en Analisis_Rotaciones_Potrero_Actual.xlsx: "
        + ", ".join(missing_mov)
    )
    st.stop()

for c in ["Potrero", "Rotacion", "Tipo de lote", "Observaciones"]:
    mov[c] = mov[c].apply(txt)

mov["Rotacion"] = mov["Rotacion"].apply(normalizar_rotacion)

mov["Última fecha de movimiento"] = pd.to_datetime(
    mov["Última fecha de movimiento"],
    errors="coerce"
)

# Este análisis corresponde al estado actual de Veraditas.
# La Tabla Maestra es la que determina la correspondencia espacial.
PREDIO_MOV = "VE"

mov["Clave_Rotacion"] = (
    mov["Rotacion"].apply(lambda r: clave_rotacion(PREDIO_MOV, r))
)

mov["Potrero_Actual"] = mov.apply(
    lambda r: potrero_con_predio(r["Potrero"], PREDIO_MOV),
    axis=1
)

# Un registro por rotación en este archivo.
mov_por_rotacion = {
    r["Clave_Rotacion"]: r
    for _, r in mov.iterrows()
    if r["Clave_Rotacion"]
}

# El potrero que actualmente ocupa el ganado.
mov_por_potrero = {
    r["Potrero_Actual"]: r
    for _, r in mov.iterrows()
    if r["Potrero_Actual"]
}


# ============================================================
# CARGAR KML
# ============================================================

try:
    potrero_features = read_polygon_features(ZIP_POTREROS)
    puntos = read_points(ZIP_PUNTOS)
    lineas = read_lines(ZIP_LINEAS)
except Exception as e:
    st.error(f"No se pudieron leer los KML: {e}")
    st.stop()

if not potrero_features:
    st.error("No se encontraron polígonos de potreros.")
    st.stop()


# ============================================================
# FILTROS
# ============================================================

st.sidebar.header("🔎 Filtros")

predios = sorted(maestro["Predio"].unique())

predio_sel = st.sidebar.selectbox(
    "Predio",
    ["TODOS"] + predios
)

mostrar_majadas = st.sidebar.checkbox(
    "Mostrar majadas",
    value=True
)

estado_sel = st.sidebar.selectbox(
    "Estado del potrero",
    ["TODOS", "ESTABLECIDO", "NO ESTABLECIDO"]
)

mostrar_puntos = st.sidebar.checkbox(
    "Mostrar puntos de infraestructura",
    value=True
)

mostrar_lineas = st.sidebar.checkbox(
    "Mostrar callejuelas",
    value=True
)


# ============================================================
# MÉTRICAS
# ============================================================

rotaciones = maestro[
    ~maestro["Es_Majada"]
][["Predio", "Clave_Rotacion"]].drop_duplicates()

rotaciones_validas = set(rotaciones["Clave_Rotacion"])

rotaciones_ocupadas = (
    set(mov_por_rotacion.keys())
    .intersection(rotaciones_validas)
)

area_rotaciones = maestro[
    ~maestro["Es_Majada"]
]["Área (ha)"].sum()

establecidos = len(
    maestro[
        ~maestro["Es_Majada"]
        & (maestro["Estado"] == "ESTABLECIDO")
    ]
)

no_establecidos = len(
    maestro[
        ~maestro["Es_Majada"]
        & (maestro["Estado"] != "ESTABLECIDO")
    ]
)

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric("Predios", maestro["Predio"].nunique())

with c2:
    st.metric(
        "Potreros",
        len(maestro[~maestro["Es_Majada"]])
    )

with c3:
    st.metric("Rotaciones", len(rotaciones))

with c4:
    st.metric(
        "Rotaciones ocupadas",
        len(rotaciones_ocupadas)
    )

with c5:
    st.metric(
        "Área de potreros",
        f"{area_rotaciones:,.1f} ha"
    )

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric(
        "Rotaciones disponibles",
        max(len(rotaciones) - len(rotaciones_ocupadas), 0)
    )

with c2:
    st.metric("Potreros establecidos", establecidos)

with c3:
    st.metric("Potreros no establecidos", no_establecidos)

with c4:
    st.metric(
        "Majadas",
        int(maestro["Es_Majada"].sum())
    )


# ============================================================
# TÍTULO
# ============================================================

st.title("🌱 Proyecto Ganadería Veraditas — PGVE")
st.caption(
    "Mapa operativo de potreros y rotaciones según la ubicación "
    "actual registrada"
)


# ============================================================
# MAPA
# ============================================================

# Centro inicial; luego se ajusta a los polígonos.
m = folium.Map(
    location=[4.5, -69.5],
    zoom_start=10,
    tiles="OpenStreetMap",
    control_scale=True
)

bounds = []


# ============================================================
# CAPA DE POTREROS
# ============================================================

for codigo, ring in potrero_features:

    codigo = txt(codigo)

    if codigo not in maestro_lookup.index:
        continue

    fila = maestro_lookup.loc[codigo]

    predio = txt(fila["Predio"])
    rotacion = txt(fila["Rotación"])
    bebedero = txt(fila["Bebedero"])
    area = fila["Área (ha)"]
    estado = txt(fila["Estado"])
    majada = bool(fila["Es_Majada"])

    # Filtros
    if majada and not mostrar_majadas:
        continue

    if predio_sel != "TODOS" and predio != predio_sel:
        continue

    if not majada and estado_sel != "TODOS":
        if estado != estado_sel:
            continue

    # Movimiento actual
    fila_mov = mov_por_potrero.get(codigo)
    ocupado = fila_mov is not None

    # Estilos
    if majada:
        color = "#7B1FA2"
        fill = "#AB47BC"
        opacity = 0.60
        estado_mapa = "MAJADA BOVINA"

    elif ocupado:
        color = "#1B5E20"
        fill = "#4CAF50"
        opacity = 0.78
        estado_mapa = "OCUPADO ACTUALMENTE"

    elif estado == "ESTABLECIDO":
        color = "#757575"
        fill = "#D9D9D9"
        opacity = 0.30
        estado_mapa = "DISPONIBLE"

    else:
        color = "#EF6C00"
        fill = "#FFB74D"
        opacity = 0.45
        estado_mapa = "NO ESTABLECIDO"

    # Popup
    if majada:

        popup_html = f"""
        <div style="font-family:Arial;min-width:280px;">
            <h3>{codigo}</h3>
            <b>Tipo:</b> Majada bovina<br>
            <b>Predio:</b> {predio}<br>
            <b>Área:</b> {mostrar(area, " ha")}<br>
            <b>Bebedero:</b> {mostrar(bebedero)}<br>
        </div>
        """

    else:

        if ocupado:

            fecha = fecha_texto(
                fila_mov["Última fecha de movimiento"]
            )

            popup_html = f"""
            <div style="font-family:Arial;min-width:330px;">

                <h3 style="margin-bottom:8px;">
                    {codigo}
                </h3>

                <b>Estado:</b>
                <span style="color:#1B5E20;">
                    OCUPADO ACTUALMENTE
                </span><br><br>

                <b>Predio:</b> {predio}<br>
                <b>Rotación:</b> {normalizar_rotacion(rotacion)}<br>
                <b>Área:</b> {mostrar(area, " ha")}<br>
                <b>Bebedero:</b> {mostrar(bebedero)}<br>

                <hr>

                <b>Último movimiento:</b> {fecha}<br>
                <b>Lote:</b> {mostrar(fila_mov["Lote"])}<br>
                <b>Tipo de lote:</b>
                {mostrar(fila_mov["Tipo de lote"])}<br>
                <b>Cantidad de animales:</b>
                {mostrar(fila_mov["Cantidad de animales"])}<br><br>

                <b>Altura promedio actual:</b>
                {mostrar(fila_mov["Altura promedio actual (cm)"], " cm")}<br>

                <b>Altura promedio anterior:</b>
                {mostrar(fila_mov["Altura promedio anterior (cm)"], " cm")}<br>

                <b>Mediciones válidas:</b>
                {mostrar(fila_mov["Mediciones válidas"])}<br><br>

                <b>Observaciones:</b><br>
                {mostrar(fila_mov["Observaciones"])}

            </div>
            """

        else:

            popup_html = f"""
            <div style="font-family:Arial;min-width:280px;">

                <h3>{codigo}</h3>

                <b>Estado:</b> {estado_mapa}<br><br>
                <b>Predio:</b> {predio}<br>
                <b>Rotación:</b> {normalizar_rotacion(rotacion)}<br>
                <b>Área:</b> {mostrar(area, " ha")}<br>
                <b>Bebedero:</b> {mostrar(bebedero)}<br>
                <b>Estado de establecimiento:</b> {estado}<br>

            </div>
            """

    folium.Polygon(
        locations=ring,
        color=color,
        weight=2,
        fill=True,
        fill_color=fill,
        fill_opacity=opacity,
        popup=folium.Popup(
            popup_html,
            max_width=400
        ),
        tooltip=f"{codigo} — {estado_mapa}"
    ).add_to(m)

    bounds.extend(ring)


# ============================================================
# CAPA DE LÍNEAS
# ============================================================

if mostrar_lineas:

    fg_lineas = folium.FeatureGroup(
        name="Callejuelas",
        show=True
    )

    for nombre, coords in lineas:

        folium.PolyLine(
            coords,
            color="#8B5A2B",
            weight=3,
            opacity=0.75,
            tooltip=nombre
        ).add_to(fg_lineas)

    fg_lineas.add_to(m)


# ============================================================
# CAPA DE PUNTOS
# ============================================================

if mostrar_puntos:

    fg_puntos = folium.FeatureGroup(
        name="Puntos de infraestructura",
        show=True
    )

    # Códigos de bebederos de la Tabla Maestra
    bebederos_maestro = set(
        maestro["Bebedero"]
        .dropna()
        .apply(txt)
    )

    for nombre, lat, lon in puntos:

        es_bebedero = txt(nombre) in bebederos_maestro

        if es_bebedero:
            icono = folium.Icon(
                color="blue",
                icon="tint",
                prefix="fa"
            )
            tipo = "Bebedero"
        else:
            icono = folium.Icon(
                color="gray",
                icon="info-sign"
            )
            tipo = "Infraestructura / punto"

        popup = folium.Popup(
            f"""
            <div style="font-family:Arial;">
                <b>{nombre}</b><br>
                Tipo: {tipo}
            </div>
            """,
            max_width=280
        )

        folium.Marker(
            [lat, lon],
            icon=icono,
            tooltip=nombre,
            popup=popup
        ).add_to(fg_puntos)

    fg_puntos.add_to(m)


folium.LayerControl(
    collapsed=False
).add_to(m)


# ============================================================
# AJUSTAR MAPA
# ============================================================

if bounds:

    lats = [p[0] for p in bounds]
    lons = [p[1] for p in bounds]

    m.fit_bounds(
        [
            [min(lats), min(lons)],
            [max(lats), max(lons)]
        ],
        padding=(20, 20)
    )


# ============================================================
# MOSTRAR
# ============================================================

st.subheader("Mapa operativo PGVE")

st_folium(
    m,
    width=None,
    height=680,
    returned_objects=[]
)


# ============================================================
# LEYENDA
# ============================================================

st.markdown(
    """
### Leyenda

🟢 **Verde:** potrero ocupado actualmente según el último
movimiento registrado.

⚪ **Gris:** potrero establecido sin ocupación actual registrada.

🟠 **Naranja:** potrero no establecido.

🟣 **Morado:** majada bovina.

🔵 **Punto azul:** bebedero.

🟤 **Línea café:** callejuela.

**Nota:** la ubicación corresponde al último movimiento
registrado en el sistema; no representa una verificación
GPS en tiempo real.
"""
)


# ============================================================
# CONTROL DE DATOS
# ============================================================

with st.expander("🔍 Control de datos"):

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.write("**Registros Tabla Maestra:**", len(maestro))

    with c2:
        st.write("**KML de potreros:**", len(potrero_features))

    with c3:
        st.write("**Rotaciones en análisis:**", len(mov))

    with c4:
        st.write("**Rotaciones ocupadas:**", len(rotaciones_ocupadas))

    with c5:
        st.write("**Puntos KML:**", len(puntos))

    codigos_maestro = set(maestro["Potrero"])
    codigos_kml = {c for c, _ in potrero_features}

    faltan_kml = sorted(codigos_maestro - codigos_kml)
    sobran_kml = sorted(codigos_kml - codigos_maestro)

    if not faltan_kml and not sobran_kml:
        st.success(
            "✓ Tabla Maestra y KML: correspondencia 194/194."
        )
    else:
        if faltan_kml:
            st.warning("Registros de Tabla Maestra sin KML:")
            st.write(faltan_kml)

        if sobran_kml:
            st.warning("KML sin registro en Tabla Maestra:")
            st.write(sobran_kml)

    st.info(
        f"Estado actual: {len(rotaciones_ocupadas)} de "
        f"{len(rotaciones)} rotaciones con movimiento registrado."
    )
