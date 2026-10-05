import streamlit as st
import pandas as pd
import folium
import zipfile
import xml.etree.ElementTree as ET
from streamlit_folium import st_folium


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="PGVE - Mapa de Potreros",
    page_icon="🌱",
    layout="wide"
)

st.title("🌱 Proyecto Ganadería Veraditas — PGVE")
st.caption(
    "Mapa operativo de potreros y rotaciones según el último "
    "movimiento registrado"
)

ARCHIVO_MAESTRO = "Tabla Maestra PGVE 2026.xlsx"
ARCHIVO_MOVIMIENTOS = "Analisis_Rotaciones_Potrero_Actual.xlsx"
ARCHIVO_KML = "KML_Potreros_PGVE.zip"


# ============================================================
# FUNCIONES
# ============================================================

def limpiar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip().upper()


def mostrar_valor(valor, sufijo=""):
    if valor is None or pd.isna(valor) or str(valor).strip() == "":
        return "No disponible"
    return f"{valor}{sufijo}"


def es_majada(codigo):
    codigo = limpiar_texto(codigo)
    return codigo.startswith("M") and "-B" in codigo


def normalizar_rotacion(valor):
    valor = limpiar_texto(valor)
    if not valor:
        return ""
    if valor.startswith("R"):
        return valor
    if valor.isdigit():
        return f"R{int(valor):02d}"
    return valor


def normalizar_potrero(codigo, predio=""):
    """
    Convierte P1-R09 -> P1-R09VE.
    Si ya termina en el predio, lo conserva.
    """
    codigo = limpiar_texto(codigo)
    predio = limpiar_texto(predio)

    if not codigo:
        return ""

    if predio and codigo.endswith(predio):
        return codigo

    if codigo.startswith("P") and "-R" in codigo and predio:
        return f"{codigo}{predio}"

    return codigo


def clave_rotacion(predio, rotacion):
    predio = limpiar_texto(predio)
    rotacion = normalizar_rotacion(rotacion)

    if not predio or not rotacion:
        return ""

    return f"{rotacion}{predio}"


def buscar_columna(df, candidatos):
    """
    Devuelve el primer nombre de columna existente entre candidatos.
    """
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def extraer_geometrias_kml(contenido):
    root = ET.fromstring(contenido)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    geometrias = []

    for polygon in root.findall(".//kml:Polygon", ns):
        outer = polygon.find(
            ".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates",
            ns
        )

        if outer is None or not outer.text:
            continue

        coords = []

        for punto in outer.text.strip().split():
            partes = punto.split(",")

            if len(partes) >= 2:
                try:
                    lon = float(partes[0])
                    lat = float(partes[1])
                    coords.append([lon, lat])
                except ValueError:
                    pass

        if len(coords) >= 3:
            geometrias.append({
                "type": "Polygon",
                "coordinates": [coords]
            })

    return geometrias


def obtener_nombre_kml(contenido):
    try:
        root = ET.fromstring(contenido)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}

        nombre = root.find(
            ".//kml:Placemark/kml:name",
            ns
        )

        if nombre is not None and nombre.text:
            return limpiar_texto(nombre.text)

    except Exception:
        pass

    return ""


# ============================================================
# TABLA MAESTRA
# ============================================================

try:
    df_maestro = pd.read_excel(
        ARCHIVO_MAESTRO,
        sheet_name="General Potreros"
    )
except Exception as e:
    st.error(f"No fue posible leer la Tabla Maestra: {e}")
    st.stop()


columnas_maestro = [
    "Predio",
    "Rotación",
    "Potrero",
    "Bebedero",
    "Área (ha)",
    "Estado",
    "Fecha Establecimiento"
]

faltantes = [
    c for c in columnas_maestro
    if c not in df_maestro.columns
]

if faltantes:
    st.error(
        "Faltan columnas en la Tabla Maestra: "
        + ", ".join(faltantes)
    )
    st.stop()


for c in ["Predio", "Rotación", "Potrero", "Bebedero", "Estado"]:
    df_maestro[c] = df_maestro[c].apply(limpiar_texto)

df_maestro["Rotación"] = (
    df_maestro["Rotación"].apply(normalizar_rotacion)
)

df_maestro["Área (ha)"] = pd.to_numeric(
    df_maestro["Área (ha)"],
    errors="coerce"
)

df_maestro["Es_Majada"] = (
    df_maestro["Potrero"].apply(es_majada)
)

df_maestro_lookup = (
    df_maestro
    .drop_duplicates("Potrero")
    .set_index("Potrero")
)


# ============================================================
# ANÁLISIS DE MOVIMIENTOS
# ============================================================

try:
    df_mov = pd.read_excel(ARCHIVO_MOVIMIENTOS)
except Exception as e:
    st.error(
        f"No fue posible leer el archivo de movimientos: {e}"
    )
    st.stop()


# Columnas principales del análisis consolidado.
col_rotacion = buscar_columna(
    df_mov,
    ["Rotacion_Codigo", "Rotación_Codigo", "Rotacion", "Rotación"]
)

col_fecha = buscar_columna(
    df_mov,
    ["Fecha_Movimiento", "Fecha Movimiento", "Fecha de Registro"]
)

col_ubicacion = buscar_columna(
    df_mov,
    ["Ubicacion_Ingreso", "Ubicación_Ingreso", "Ubicacion Ingreso"]
)

if not col_rotacion or not col_ubicacion:
    st.error(
        "No se encontraron las columnas necesarias del análisis "
        "de movimientos."
    )
    st.write("Columnas encontradas:")
    st.write(list(df_mov.columns))
    st.stop()


df_mov["_Rotacion"] = (
    df_mov[col_rotacion]
    .apply(normalizar_rotacion)
)

df_mov["_Ubicacion"] = (
    df_mov[col_ubicacion]
    .apply(limpiar_texto)
)

if col_fecha:
    df_mov["_Fecha"] = pd.to_datetime(
        df_mov[col_fecha],
        errors="coerce"
    )
else:
    df_mov["_Fecha"] = pd.NaT


# Fecha/hora secundaria para desempate
col_hora = buscar_columna(
    df_mov,
    ["Fecha_Hora_Registro", "Time", "Timestamp"]
)

if col_hora:
    df_mov["_FechaHora"] = pd.to_datetime(
        df_mov[col_hora],
        errors="coerce"
    )
else:
    df_mov["_FechaHora"] = pd.NaT


# Response como tercer desempate
col_response = buscar_columna(
    df_mov,
    ["Response", "response"]
)

if col_response:
    df_mov["_Response"] = pd.to_numeric(
        df_mov[col_response]
        .astype(str)
        .str.extract(r"(\d+)", expand=False),
        errors="coerce"
    )
else:
    df_mov["_Response"] = pd.NA


# El análisis actual corresponde a Veraditas.
# Si posteriormente el Excel trae Predio, se utiliza.
col_predio = buscar_columna(
    df_mov,
    ["Predio", "Predio_Codigo"]
)

if col_predio:
    df_mov["_Predio"] = (
        df_mov[col_predio].apply(limpiar_texto)
    )
else:
    df_mov["_Predio"] = "VE"


# ============================================================
# ÚLTIMO MOVIMIENTO POR PREDIO + ROTACIÓN
# ============================================================

df_mov = df_mov.sort_values(
    by=[
        "_Predio",
        "_Rotacion",
        "_Fecha",
        "_FechaHora",
        "_Response"
    ],
    ascending=True,
    na_position="first"
).copy()

ultimo_movimiento = (
    df_mov
    .drop_duplicates(
        subset=["_Predio", "_Rotacion"],
        keep="last"
    )
    .copy()
)

ultimo_movimiento["Clave_Rotacion"] = (
    ultimo_movimiento["_Rotacion"]
    + ultimo_movimiento["_Predio"]
)

ultimo_movimiento["Potrero_Actual"] = (
    ultimo_movimiento.apply(
        lambda f: normalizar_potrero(
            f["_Ubicacion"],
            f["_Predio"]
        ),
        axis=1
    )
)


# Diccionario: R09VE -> fila del último movimiento
mov_por_rotacion = {
    fila["Clave_Rotacion"]: fila
    for _, fila in ultimo_movimiento.iterrows()
    if fila["Clave_Rotacion"]
}


# Diccionario: P1-R09VE -> fila del movimiento que actualmente
# ocupa ese potrero
mov_por_potrero = {
    fila["Potrero_Actual"]: fila
    for _, fila in ultimo_movimiento.iterrows()
    if fila["Potrero_Actual"]
}


rotaciones_ocupadas = set(mov_por_rotacion.keys())


# ============================================================
# KML DE POTREROS
# ============================================================

features = []

try:
    with zipfile.ZipFile(ARCHIVO_KML, "r") as z:
        archivos_kml = [
            n for n in z.namelist()
            if n.lower().endswith(".kml")
        ]

        for nombre_archivo in archivos_kml:
            contenido = z.read(nombre_archivo)

            codigo = (
                nombre_archivo
                .split("/")[-1]
                .rsplit(".", 1)[0]
            )

            codigo = limpiar_texto(codigo)

            nombre_interno = obtener_nombre_kml(contenido)

            if nombre_interno:
                codigo = nombre_interno

            try:
                geometrias = extraer_geometrias_kml(
                    contenido
                )
            except Exception:
                continue

            for geometria in geometrias:
                features.append({
                    "type": "Feature",
                    "geometry": geometria,
                    "properties": {
                        "codigo": codigo
                    }
                })

except Exception as e:
    st.error(
        f"No fue posible leer el ZIP de KML: {e}"
    )
    st.stop()


if not features:
    st.error("No se encontraron polígonos en el ZIP.")
    st.stop()


# ============================================================
# MÉTRICAS
# ============================================================

df_rotaciones = df_maestro[
    ~df_maestro["Es_Majada"]
].copy()

rotaciones_totales = (
    df_rotaciones[
        ["Predio", "Rotación"]
    ]
    .drop_duplicates()
)

numero_rotaciones = len(rotaciones_totales)

numero_rotaciones_ocupadas = len(
    rotaciones_ocupadas.intersection(
        {
            clave_rotacion(p, r)
            for p, r in zip(
                rotaciones_totales["Predio"],
                rotaciones_totales["Rotación"]
            )
        }
    )
)

numero_rotaciones_disponibles = max(
    numero_rotaciones - numero_rotaciones_ocupadas,
    0
)

area_rotaciones = df_rotaciones["Área (ha)"].sum()

establecidos = len(
    df_rotaciones[
        df_rotaciones["Estado"] == "ESTABLECIDO"
    ]
)

no_establecidos = len(
    df_rotaciones[
        df_rotaciones["Estado"] != "ESTABLECIDO"
    ]
)

numero_majadas = int(
    df_maestro["Es_Majada"].sum()
)


# ============================================================
# FILTROS
# ============================================================

st.sidebar.header("🔎 Filtros")

predios = sorted(
    df_maestro["Predio"].dropna().unique()
)

predio_seleccionado = st.sidebar.selectbox(
    "Predio",
    ["TODOS"] + predios
)

mostrar_majadas = st.sidebar.checkbox(
    "Mostrar majadas",
    value=True
)

estado_seleccionado = st.sidebar.selectbox(
    "Estado del potrero",
    ["TODOS", "ESTABLECIDO", "NO ESTABLECIDO"]
)


# ============================================================
# INDICADORES
# ============================================================

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric(
        "Predios",
        df_maestro["Predio"].nunique()
    )

with c2:
    st.metric(
        "Potreros",
        len(df_rotaciones)
    )

with c3:
    st.metric(
        "Rotaciones",
        numero_rotaciones
    )

with c4:
    st.metric(
        "Rotaciones ocupadas",
        numero_rotaciones_ocupadas
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
        numero_rotaciones_disponibles
    )

with c2:
    st.metric(
        "Potreros establecidos",
        establecidos
    )

with c3:
    st.metric(
        "Potreros no establecidos",
        no_establecidos
    )

with c4:
    st.metric(
        "Majadas",
        numero_majadas
    )


# ============================================================
# MAPA
# ============================================================

m = folium.Map(
    location=[4.5, -69.5],
    zoom_start=11,
    tiles="OpenStreetMap",
    control_scale=True
)

todos_los_puntos = []


for feature in features:

    codigo = limpiar_texto(
        feature["properties"]["codigo"]
    )

    # --------------------------------------------------------
    # Maestro
    # --------------------------------------------------------

    fila_maestro = None

    if codigo in df_maestro_lookup.index:
        fila_maestro = df_maestro_lookup.loc[codigo]

    if fila_maestro is not None:

        predio = limpiar_texto(
            fila_maestro["Predio"]
        )

        rotacion = normalizar_rotacion(
            fila_maestro["Rotación"]
        )

        bebedero = limpiar_texto(
            fila_maestro["Bebedero"]
        )

        area = fila_maestro["Área (ha)"]

        estado_establecimiento = limpiar_texto(
            fila_maestro["Estado"]
        )

    else:

        predio = ""
        rotacion = ""
        bebedero = ""
        area = None
        estado_establecimiento = ""

    majada = es_majada(codigo)

    # --------------------------------------------------------
    # Filtros
    # --------------------------------------------------------

    if majada and not mostrar_majadas:
        continue

    if (
        predio_seleccionado != "TODOS"
        and predio != predio_seleccionado
    ):
        continue

    if not majada and estado_seleccionado != "TODOS":

        if estado_establecimiento != estado_seleccionado:
            continue

    # --------------------------------------------------------
    # Estado actual
    # --------------------------------------------------------

    fila_mov = mov_por_potrero.get(codigo)

    ocupado = fila_mov is not None

    # --------------------------------------------------------
    # Colores
    # --------------------------------------------------------

    if majada:

        color = "#8E44AD"
        relleno = "#BB8FCE"
        opacidad = 0.65
        estado_mapa = "MAJADA BOVINA"

    elif ocupado:

        color = "#1B5E20"
        relleno = "#4CAF50"
        opacidad = 0.75
        estado_mapa = (
            "OCUPADO — ÚLTIMO MOVIMIENTO REGISTRADO"
        )

    elif estado_establecimiento == "ESTABLECIDO":

        color = "#757575"
        relleno = "#D9D9D9"
        opacidad = 0.30
        estado_mapa = "DISPONIBLE"

    else:

        color = "#F39C12"
        relleno = "#F8C471"
        opacidad = 0.45
        estado_mapa = "NO ESTABLECIDO"

    # --------------------------------------------------------
    # Información del movimiento
    # --------------------------------------------------------

    if fila_mov is not None:

        fecha_mov = fila_mov.get("_Fecha")

        if pd.notna(fecha_mov):
            fecha_mov_texto = fecha_mov.strftime(
                "%d/%m/%Y"
            )
        else:
            fecha_mov_texto = "No disponible"

        col_lote = buscar_columna(
            df_mov,
            ["Numero del Lote", "Número del Lote", "Lote"]
        )

        col_tipo_lote = buscar_columna(
            df_mov,
            ["Tipo de Lote", "Tipo de lote"]
        )

        col_cantidad = buscar_columna(
            df_mov,
            [
                "Cantidad de Animales Lote",
                "Cantidad de animales",
                "Cantidad Animales"
            ]
        )

        lote = (
            mostrar_valor(fila_mov.get(col_lote))
            if col_lote else "No disponible"
        )

        tipo_lote = (
            mostrar_valor(fila_mov.get(col_tipo_lote))
            if col_tipo_lote else "No disponible"
        )

        cantidad = (
            mostrar_valor(fila_mov.get(col_cantidad))
            if col_cantidad else "No disponible"
        )

        altura_actual = mostrar_valor(
            fila_mov.get(
                "Altura promedio actual (cm)"
            ),
            " cm"
        )

        altura_anterior = mostrar_valor(
            fila_mov.get(
                "Altura promedio anterior (cm)"
            ),
            " cm"
        )

        observaciones = mostrar_valor(
            fila_mov.get("Observaciones")
        )

        ubicacion_actual = mostrar_valor(
            fila_mov.get("Potrero_Actual")
        )

    else:

        fecha_mov_texto = "No disponible"
        lote = "No disponible"
        tipo_lote = "No disponible"
        cantidad = "No disponible"
        altura_actual = "No disponible"
        altura_anterior = "No disponible"
        observaciones = "No disponible"
        ubicacion_actual = "No disponible"

    # --------------------------------------------------------
    # Popup
    # --------------------------------------------------------

    if majada:

        popup_html = f"""
        <div style="font-family:Arial; min-width:280px;">
            <h3>{codigo}</h3>

            <b>Tipo:</b> Majada bovina<br>
            <b>Predio:</b> {predio}<br>
            <b>Área:</b> {mostrar_valor(area, " ha")}<br>
            <b>Bebedero:</b> {mostrar_valor(bebedero)}<br>
        </div>
        """

    else:

        popup_html = f"""
        <div style="font-family:Arial; min-width:320px;">

            <h3 style="margin-bottom:10px;">
                {codigo}
            </h3>

            <b>Estado:</b> {estado_mapa}<br><br>

            <b>Predio:</b> {predio}<br>
            <b>Rotación:</b> {rotacion}<br>
            <b>Área:</b> {mostrar_valor(area, " ha")}<br>
            <b>Bebedero:</b> {mostrar_valor(bebedero)}<br>
            <b>Estado establecimiento:</b>
            {mostrar_valor(estado_establecimiento)}<br>

            <hr>

            <b>Último movimiento:</b>
            {fecha_mov_texto}<br>

            <b>Ubicación actual:</b>
            {ubicacion_actual}<br>

            <b>Lote:</b>
            {lote}<br>

            <b>Tipo de lote:</b>
            {tipo_lote}<br>

            <b>Cantidad de animales:</b>
            {cantidad}<br><br>

            <b>Altura promedio actual:</b>
            {altura_actual}<br>

            <b>Altura promedio anterior:</b>
            {altura_anterior}<br><br>

            <b>Observaciones:</b><br>
            {observaciones}

        </div>
        """

    popup = folium.Popup(
        popup_html,
        max_width=400
    )

    folium.GeoJson(
        feature,

        style_function=lambda feature,
            color=color,
            relleno=relleno,
            opacidad=opacidad: {
                "color": color,
                "weight": 2,
                "fillColor": relleno,
                "fillOpacity": opacidad
            },

        highlight_function=lambda feature: {
            "weight": 4,
            "fillOpacity": 0.85
        },

        popup=popup,

        tooltip=folium.Tooltip(
            codigo,
            sticky=True
        )

    ).add_to(m)

    # --------------------------------------------------------
    # Bounds
    # --------------------------------------------------------

    for ring in feature["geometry"]["coordinates"]:
        for lon, lat in ring:
            todos_los_puntos.append([lat, lon])


# ============================================================
# AJUSTAR EXTENSIÓN
# ============================================================

if todos_los_puntos:

    lats = [p[0] for p in todos_los_puntos]
    lons = [p[1] for p in todos_los_puntos]

    m.fit_bounds(
        [
            [min(lats), min(lons)],
            [max(lats), max(lons)]
        ],
        padding=(20, 20)
    )


# ============================================================
# MOSTRAR MAPA
# ============================================================

st.subheader("Mapa operativo PGVE")

st_folium(
    m,
    width=None,
    height=700,
    returned_objects=[]
)


# ============================================================
# LEYENDA
# ============================================================

st.markdown(
    """
### Leyenda

🟢 **Verde:** rotación ocupada según el último movimiento registrado.

⚪ **Gris:** potrero establecido sin ocupación actual registrada.

🟠 **Naranja:** potrero no establecido.

🟣 **Morado:** majada bovina.

**Nota:** la ubicación corresponde al último movimiento registrado
en el sistema; no representa una verificación GPS en tiempo real.
"""
)


# ============================================================
# CONTROL DE DATOS
# ============================================================

with st.expander("🔍 Control de datos"):

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.write(
            "**Registros Tabla Maestra:**",
            len(df_maestro)
        )

    with c2:
        st.write(
            "**KML encontrados:**",
            len({
                f["properties"]["codigo"]
                for f in features
            })
        )

    with c3:
        st.write(
            "**Potreros con movimiento:**",
            len(mov_por_potrero)
        )

    with c4:
        st.write(
            "**Rotaciones con movimiento:**",
            numero_rotaciones_ocupadas
        )

    codigos_kml = {
        f["properties"]["codigo"]
        for f in features
    }

    codigos_maestro = set(
        df_maestro["Potrero"]
    )

    kml_sin_maestro = (
        codigos_kml - codigos_maestro
    )

    maestro_sin_kml = (
        codigos_maestro - codigos_kml
    )

    if not kml_sin_maestro:
        st.success(
            "✓ Todos los KML tienen correspondencia "
            "en la Tabla Maestra."
        )
    else:
        st.warning(
            "KML sin correspondencia:"
        )
        st.write(sorted(kml_sin_maestro))

    if not maestro_sin_kml:
        st.success(
            "✓ Todos los registros de la Tabla Maestra "
            "tienen correspondencia espacial."
        )
    else:
        st.warning(
            "Registros de la Tabla Maestra sin KML:"
        )
        st.write(sorted(maestro_sin_kml))

    st.info(
        "Integración de movimientos: "
        f"{numero_rotaciones_ocupadas} rotaciones con último "
        "movimiento identificado."
    )
