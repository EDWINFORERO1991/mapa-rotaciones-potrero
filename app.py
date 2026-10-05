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
    "Mapa operativo de potreros y rotaciones "
    "según la ubicación actual registrada"
)


# ============================================================
# ARCHIVOS DEL REPOSITORIO
# ============================================================

ARCHIVO_MAESTRO = "Tabla Maestra PGVE 2026.xlsx"
ARCHIVO_MOVIMIENTOS = "Analisis_Rotaciones_Potrero_Actual.xlsx"
ARCHIVO_KML = "KML_Potreros_PGVE.zip"


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def limpiar_texto(valor):
    """Convierte un valor a texto limpio y mayúsculas."""
    if pd.isna(valor):
        return ""
    return str(valor).strip().upper()


def mostrar_valor(valor, sufijo=""):
    """Muestra valores vacíos como No disponible."""
    if pd.isna(valor) or str(valor).strip() == "":
        return "No disponible"

    return f"{valor}{sufijo}"


def es_majada(codigo):
    """
    Identifica las majadas mediante su nomenclatura:
    M1-B01SS, M2-B01SS, M1-B01CA, etc.
    """
    codigo = limpiar_texto(codigo)
    return codigo.startswith("M") and "-B" in codigo


def obtener_rotacion_desde_potrero(codigo):
    """
    Ejemplo:
    P1-R01VE -> R01VE
    P2-R26SS -> R26SS
    """
    codigo = limpiar_texto(codigo)

    if "-R" in codigo:
        parte = codigo.split("-R", 1)[1]

        # El resultado queda como 01VE, 26SS, etc.
        return "R" + parte

    return ""


# ============================================================
# FUNCIÓN PARA EXTRAER GEOMETRÍAS KML
# ============================================================

def extraer_geometrias_kml(contenido_kml):

    root = ET.fromstring(contenido_kml)

    ns = {
        "kml": "http://www.opengis.net/kml/2.2"
    }

    geometrias = []

    for polygon in root.findall(".//kml:Polygon", ns):

        outer = polygon.find(
            ".//kml:outerBoundaryIs/"
            "kml:LinearRing/"
            "kml:coordinates",
            ns
        )

        if outer is None or not outer.text:
            continue

        coordenadas = []

        for punto in outer.text.strip().split():

            partes = punto.split(",")

            if len(partes) >= 2:

                try:
                    lon = float(partes[0])
                    lat = float(partes[1])

                    coordenadas.append(
                        [lon, lat]
                    )

                except ValueError:
                    continue

        if len(coordenadas) >= 3:

            geometrias.append({
                "type": "Polygon",
                "coordinates": [coordenadas]
            })

    return geometrias


# ============================================================
# OBTENER NOMBRE DEL KML
# ============================================================

def obtener_nombre_kml(contenido_kml):

    try:

        root = ET.fromstring(contenido_kml)

        ns = {
            "kml": "http://www.opengis.net/kml/2.2"
        }

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
# LEER TABLA MAESTRA
# ============================================================

try:

    df_maestro = pd.read_excel(
        ARCHIVO_MAESTRO,
        sheet_name="General Potreros"
    )

except Exception as e:

    st.error(
        f"No fue posible leer la Tabla Maestra: {e}"
    )

    st.stop()


# ============================================================
# VALIDAR TABLA MAESTRA
# ============================================================

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
        "Faltan columnas en la Tabla Maestra:"
    )

    st.write(faltantes)

    st.stop()


# ============================================================
# NORMALIZAR TABLA MAESTRA
# ============================================================

for columna in [
    "Predio",
    "Rotación",
    "Potrero",
    "Bebedero",
    "Estado"
]:

    df_maestro[columna] = (
        df_maestro[columna]
        .apply(limpiar_texto)
    )


df_maestro["Es_Majada"] = (
    df_maestro["Potrero"]
    .apply(es_majada)
)


df_maestro["Área (ha)"] = pd.to_numeric(
    df_maestro["Área (ha)"],
    errors="coerce"
)


# ============================================================
# LEER ANÁLISIS DE MOVIMIENTOS
# ============================================================

try:

    df_mov = pd.read_excel(
        ARCHIVO_MOVIMIENTOS
    )

except Exception as e:

    st.error(
        f"No fue posible leer el archivo de movimientos: {e}"
    )

    st.stop()


# ============================================================
# VALIDAR COLUMNA POTRERO EN MOVIMIENTOS
# ============================================================

if "Potrero" not in df_mov.columns:

    st.error(
        "El archivo de movimientos no contiene "
        "la columna 'Potrero'."
    )

    st.stop()


df_mov["Potrero"] = (
    df_mov["Potrero"]
    .apply(limpiar_texto)
)


# ============================================================
# OBTENER ROTACIÓN DESDE LOS MOVIMIENTOS
# ============================================================

if "Rotacion" in df_mov.columns:

    df_mov["Rotacion"] = (
        df_mov["Rotacion"]
        .apply(limpiar_texto)
    )

else:

    df_mov["Rotacion"] = (
        df_mov["Potrero"]
        .apply(obtener_rotacion_desde_potrero)
    )


# ============================================================
# OBTENER PREDIO DESDE EL POTRERO
# ============================================================

if "Predio" in df_mov.columns:

    df_mov["Predio"] = (
        df_mov["Predio"]
        .apply(limpiar_texto)
    )

else:

    mapa_predio = (
        df_maestro
        .drop_duplicates("Potrero")
        .set_index("Potrero")["Predio"]
        .to_dict()
    )

    df_mov["Predio"] = (
        df_mov["Potrero"]
        .map(mapa_predio)
        .fillna("")
    )


# ============================================================
# IDENTIFICAR POTREROS OCUPADOS
# ============================================================

potreros_ocupados = set(
    df_mov["Potrero"]
    .dropna()
    .astype(str)
    .str.strip()
    .str.upper()
)

potreros_ocupados = {
    x for x in potreros_ocupados
    if x and x != "NAN"
}


# ============================================================
# IDENTIFICAR ROTACIONES OCUPADAS
# ============================================================

rotaciones_ocupadas = set()

for _, fila in df_mov.iterrows():

    predio = limpiar_texto(fila.get("Predio", ""))
    rotacion = limpiar_texto(fila.get("Rotacion", ""))

    if predio and rotacion:

        rotaciones_ocupadas.add(
            f"{rotacion}{predio}"
        )


# ============================================================
# LEER KML
# ============================================================

features = []

errores_kml = []

try:

    with zipfile.ZipFile(
        ARCHIVO_KML,
        "r"
    ) as archivo_zip:

        archivos_kml = [
            nombre
            for nombre in archivo_zip.namelist()
            if nombre.lower().endswith(".kml")
        ]

        for nombre_archivo in archivos_kml:

            contenido = archivo_zip.read(
                nombre_archivo
            )

            # ------------------------------------------------
            # Código inicial desde nombre del archivo
            # ------------------------------------------------

            codigo = (
                nombre_archivo
                .split("/")[-1]
                .rsplit(".", 1)[0]
            )

            codigo = limpiar_texto(codigo)

            # ------------------------------------------------
            # Intentar obtener nombre interno del KML
            # ------------------------------------------------

            nombre_interno = obtener_nombre_kml(
                contenido
            )

            if nombre_interno:

                codigo = nombre_interno

            # ------------------------------------------------
            # Extraer geometrías
            # ------------------------------------------------

            try:

                geometrias = (
                    extraer_geometrias_kml(
                        contenido
                    )
                )

            except Exception as e:

                errores_kml.append(
                    f"{codigo}: {e}"
                )

                continue

            # ------------------------------------------------
            # Crear Features
            # ------------------------------------------------

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


# ============================================================
# VALIDACIÓN ESPACIAL
# ============================================================

if not features:

    st.error(
        "No se encontraron polígonos en el ZIP."
    )

    st.stop()


# ============================================================
# CREAR DICCIONARIO DE LA TABLA MAESTRA
# ============================================================

df_maestro_lookup = (
    df_maestro
    .drop_duplicates("Potrero")
    .set_index("Potrero")
)


# ============================================================
# IDENTIFICAR ROTACIONES DEL MAESTRO
# ============================================================

df_rotaciones_maestro = (
    df_maestro[
        ~df_maestro["Es_Majada"]
    ]
    .copy()
)

rotaciones_totales = (
    df_rotaciones_maestro[
        ["Predio", "Rotación"]
    ]
    .drop_duplicates()
)

numero_rotaciones = len(
    rotaciones_totales
)


# ============================================================
# ROTACIONES OCUPADAS REALES
# ============================================================

rotaciones_ocupadas_validas = set()

for _, fila in df_mov.iterrows():

    predio = limpiar_texto(
        fila.get("Predio", "")
    )

    rotacion = limpiar_texto(
        fila.get("Rotacion", "")
    )

    if predio and rotacion:

        clave = (
            f"{rotacion}{predio}"
        )

        if not (
            rotacion == ""
            or predio == ""
        ):

            rotaciones_ocupadas_validas.add(
                clave
            )


numero_rotaciones_ocupadas = len(
    rotaciones_ocupadas_validas
)

numero_rotaciones_disponibles = max(
    numero_rotaciones -
    numero_rotaciones_ocupadas,
    0
)


# ============================================================
# ÁREA
# ============================================================

area_total = df_maestro[
    "Área (ha)"
].sum()

area_rotaciones = df_rotaciones_maestro[
    "Área (ha)"
].sum()

area_majadas = df_maestro[
    df_maestro["Es_Majada"]
]["Área (ha)"].sum()


# ============================================================
# ESTADOS DE ESTABLECIMIENTO
# ============================================================

establecidos = len(
    df_maestro[
        ~df_maestro["Es_Majada"]
        & (
            df_maestro["Estado"]
            .str.upper()
            == "ESTABLECIDO"
        )
    ]
)

no_establecidos = len(
    df_maestro[
        ~df_maestro["Es_Majada"]
        & (
            df_maestro["Estado"]
            .str.upper()
            != "ESTABLECIDO"
        )
    ]
)


# ============================================================
# FILTROS
# ============================================================

st.sidebar.header("🔎 Filtros")

predios_disponibles = sorted(
    df_maestro["Predio"]
    .dropna()
    .unique()
)

predio_seleccionado = st.sidebar.selectbox(
    "Predio",
    ["TODOS"] + predios_disponibles
)


mostrar_majadas = st.sidebar.checkbox(
    "Mostrar majadas",
    value=True
)


estado_seleccionado = st.sidebar.selectbox(
    "Estado del potrero",
    [
        "TODOS",
        "Establecido",
        "No Establecido"
    ]
)


# ============================================================
# INFORMACIÓN SUPERIOR
# ============================================================

col1, col2, col3, col4, col5 = st.columns(5)

with col1:

    st.metric(
        "Predios",
        df_maestro["Predio"].nunique()
    )

with col2:

    st.metric(
        "Potreros",
        len(
            df_maestro[
                ~df_maestro["Es_Majada"]
            ]
        )
    )

with col3:

    st.metric(
        "Rotaciones",
        numero_rotaciones
    )

with col4:

    st.metric(
        "Rotaciones ocupadas",
        numero_rotaciones_ocupadas
    )

with col5:

    st.metric(
        "Área de potreros",
        f"{area_rotaciones:,.1f} ha"
    )


# ============================================================
# SEGUNDA FILA DE INDICADORES
# ============================================================

col1, col2, col3, col4 = st.columns(4)

with col1:

    st.metric(
        "Rotaciones disponibles",
        numero_rotaciones_disponibles
    )

with col2:

    st.metric(
        "Potreros establecidos",
        establecidos
    )

with col3:

    st.metric(
        "Potreros no establecidos",
        no_establecidos
    )

with col4:

    st.metric(
        "Majadas",
        len(
            df_maestro[
                df_maestro["Es_Majada"]
            ]
        )
    )


# ============================================================
# CREAR MAPA
# ============================================================

m = folium.Map(
    location=[4.5, -69.5],
    zoom_start=11,
    tiles="OpenStreetMap",
    control_scale=True
)


# ============================================================
# COORDENADAS PARA EXTENSIÓN
# ============================================================

todos_los_puntos = []


# ============================================================
# AGREGAR POLÍGONOS
# ============================================================

for feature in features:

    codigo = feature[
        "properties"
    ]["codigo"]

    codigo = limpiar_texto(codigo)

    # --------------------------------------------------------
    # Buscar información en tabla maestra
    # --------------------------------------------------------

    if codigo in df_maestro_lookup.index:

        fila_maestro = (
            df_maestro_lookup
            .loc[codigo]
        )

    else:

        fila_maestro = None

    # --------------------------------------------------------
    # Determinar si es majada
    # --------------------------------------------------------

    majada = es_majada(codigo)

    # --------------------------------------------------------
    # Filtro de majadas
    # --------------------------------------------------------

    if majada and not mostrar_majadas:
        continue

    # --------------------------------------------------------
    # Datos maestro
    # --------------------------------------------------------

    if fila_maestro is not None:

        predio = limpiar_texto(
            fila_maestro["Predio"]
        )

        rotacion = limpiar_texto(
            fila_maestro["Rotación"]
        )

        bebedero = limpiar_texto(
            fila_maestro["Bebedero"]
        )

        area = fila_maestro["Área (ha)"]

        estado_establecimiento = (
            limpiar_texto(
                fila_maestro["Estado"]
            )
        )

        fecha_establecimiento = (
            fila_maestro[
                "Fecha Establecimiento"
            ]
        )

    else:

        predio = ""
        rotacion = ""
        bebedero = ""
        area = None
        estado_establecimiento = ""
        fecha_establecimiento = None

    # --------------------------------------------------------
    # Filtro por predio
    # --------------------------------------------------------

    if (
        predio_seleccionado != "TODOS"
        and predio != predio_seleccionado
    ):
        continue

    # --------------------------------------------------------
    # Filtro por estado
    # --------------------------------------------------------

    if not majada:

        if (
            estado_seleccionado
            != "TODOS"
        ):

            if (
                estado_establecimiento
                != estado_seleccionado.upper()
            ):
                continue

    # --------------------------------------------------------
    # Estado de ocupación
    # --------------------------------------------------------

    ocupado = (
        codigo in potreros_ocupados
    )

    # --------------------------------------------------------
    # Colores
    # --------------------------------------------------------

    if majada:

        color = "#8E44AD"
        relleno = "#BB8FCE"
        opacidad = 0.65
        estado_mapa = "MAJADA"

    elif ocupado:

        color = "#1B5E20"
        relleno = "#4CAF50"
        opacidad = 0.75
        estado_mapa = (
            "OCUPADO — ÚLTIMO MOVIMIENTO REGISTRADO"
        )

    elif (
        estado_establecimiento
        == "ESTABLECIDO"
    ):

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
    # Buscar movimiento
    # --------------------------------------------------------

    datos_mov = df_mov[
        df_mov["Potrero"]
        == codigo
    ]

    if not datos_mov.empty:

        fila_mov = (
            datos_mov.iloc[0]
        )

    else:

        fila_mov = None

    # --------------------------------------------------------
    # Construir popup
    # --------------------------------------------------------

    if majada:

        popup_html = f"""
        <div style="font-family:Arial; min-width:280px;">

            <h3 style="margin-bottom:10px;">
                {codigo}
            </h3>

            <b>Tipo:</b> Majada<br>
            <b>Predio:</b> {predio}<br>
            <b>Área:</b> {mostrar_valor(area, " ha")}<br>
            <b>Bebedero:</b> {mostrar_valor(bebedero)}<br>

            <hr>

            <b>Estado:</b> Majada bovina
        </div>
        """

    else:

        # --------------------------------------------
        # Información de movimiento
        # --------------------------------------------

        if fila_mov is not None:

            fecha_mov = ""

            if (
                "Última fecha de movimiento"
                in df_mov.columns
            ):

                fecha_mov = pd.to_datetime(
                    fila_mov[
                        "Última fecha de movimiento"
                    ],
                    errors="coerce"
                )

            if pd.notna(fecha_mov):

                fecha_mov = (
                    fecha_mov.strftime(
                        "%d/%m/%Y"
                    )
                )

            else:

                fecha_mov = (
                    "No disponible"
                )

            lote = mostrar_valor(
                fila_mov.get(
                    "Lote",
                    None
                )
            )

            tipo_lote = mostrar_valor(
                fila_mov.get(
                    "Tipo de lote",
                    None
                )
            )

            cantidad = mostrar_valor(
                fila_mov.get(
                    "Cantidad de animales",
                    None
                )
            )

            altura_actual = mostrar_valor(
                fila_mov.get(
                    "Altura promedio actual (cm)",
                    None
                ),
                " cm"
            )

            altura_anterior = mostrar_valor(
                fila_mov.get(
                    "Altura promedio anterior (cm)",
                    None
                ),
                " cm"
            )

            observaciones = mostrar_valor(
                fila_mov.get(
                    "Observaciones",
                    None
                )
            )

        else:

            fecha_mov = "No disponible"
            lote = "No disponible"
            tipo_lote = "No disponible"
            cantidad = "No disponible"
            altura_actual = "No disponible"
            altura_anterior = "No disponible"
            observaciones = "No disponible"

        popup_html = f"""
        <div style="font-family:Arial; min-width:300px;">

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
            {fecha_mov}<br>

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
        max_width=380
    )

    # --------------------------------------------------------
    # Agregar polígono
    # --------------------------------------------------------

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
    # Guardar coordenadas
    # --------------------------------------------------------

    geometry = feature[
        "geometry"
    ]

    for ring in geometry[
        "coordinates"
    ]:

        for lon, lat in ring:

            todos_los_puntos.append(
                [lat, lon]
            )


# ============================================================
# AJUSTAR MAPA
# ============================================================

if todos_los_puntos:

    lats = [
        punto[0]
        for punto in todos_los_puntos
    ]

    lons = [
        punto[1]
        for punto in todos_los_puntos
    ]

    bounds = [
        [
            min(lats),
            min(lons)
        ],
        [
            max(lats),
            max(lons)
        ]
    ]

    m.fit_bounds(
        bounds,
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

    🟢 **Verde:** rotación ocupada según el último
    movimiento registrado.

    ⚪ **Gris:** potrero establecido sin ocupación
    identificada en el último movimiento.

    🟠 **Naranja:** potrero no establecido.

    🟣 **Morado:** majada bovina.

    **Nota:** la ubicación mostrada corresponde al
    último movimiento registrado en el sistema; no
    representa una verificación GPS en tiempo real.
    """
)


# ============================================================
# RESUMEN DE CONTROL
# ============================================================

with st.expander("🔍 Control de datos"):

    col1, col2, col3 = st.columns(3)

    with col1:

        st.write(
            "**Registros Tabla Maestra:**",
            len(df_maestro)
        )

    with col2:

        st.write(
            "**KML encontrados:**",
            len(
                {
                    f["properties"]["codigo"]
                    for f in features
                }
            )
        )

    with col3:

        st.write(
            "**Potreros con movimiento:**",
            len(potreros_ocupados)
        )

    # --------------------------------------------------------
    # KML sin maestro
    # --------------------------------------------------------

    codigos_kml = {
        f["properties"]["codigo"]
        for f in features
    }

    codigos_maestro = set(
        df_maestro["Potrero"]
    )

    kml_sin_maestro = (
        codigos_kml
        - codigos_maestro
    )

    maestro_sin_kml = (
        codigos_maestro
        - codigos_kml
    )

    if not kml_sin_maestro:

        st.success(
            "✓ Todos los KML tienen correspondencia "
            "en la Tabla Maestra."
        )

    else:

        st.warning(
            "KML sin correspondencia en la Tabla Maestra:"
        )

        st.write(
            sorted(kml_sin_maestro)
        )

    if not maestro_sin_kml:

        st.success(
            "✓ Todos los registros de la Tabla Maestra "
            "tienen correspondencia espacial."
        )

    else:

        st.warning(
            "Registros de la Tabla Maestra sin KML:"
        )

        st.write(
            sorted(maestro_sin_kml)
        )
