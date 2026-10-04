import streamlit as st
import pandas as pd
import folium
import zipfile
import io
import xml.etree.ElementTree as ET
from streamlit_folium import st_folium


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Mapa de Potreros y Rotaciones",
    page_icon="🌱",
    layout="wide"
)

st.title("Mapa de Potreros y Rotaciones")
st.caption("Visualización de potreros ocupados según el último movimiento registrado")


# ============================================================
# ARCHIVOS DEL REPOSITORIO
# ============================================================

ARCHIVO_EXCEL = "Analisis_Rotaciones_Potrero_Actual.xlsx"
ARCHIVO_ZIP = "KML_Potreros_VE_BU.zip"


# ============================================================
# FUNCIÓN PARA EXTRAER POLÍGONOS DE KML
# ============================================================

def extraer_geometrias_kml(contenido_kml):

    root = ET.fromstring(contenido_kml)

    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    geometrias = []

    # --------------------------------------------------------
    # Buscar todos los Polygon
    # --------------------------------------------------------

    for polygon in root.findall(".//kml:Polygon", ns):

        coordenadas = []

        # Outer boundary
        outer = polygon.find(
            ".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates",
            ns
        )

        if outer is None:
            continue

        texto = outer.text

        if not texto:
            continue

        for punto in texto.strip().split():

            partes = punto.split(",")

            if len(partes) >= 2:

                lon = float(partes[0])
                lat = float(partes[1])

                coordenadas.append([lon, lat])

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

    root = ET.fromstring(contenido_kml)

    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    nombre = root.find(".//kml:Placemark/kml:name", ns)

    if nombre is not None and nombre.text:

        return nombre.text.strip()

    return None


# ============================================================
# LEER EXCEL
# ============================================================

try:

    df_rotaciones = pd.read_excel(ARCHIVO_EXCEL)

except Exception as e:

    st.error(f"No fue posible leer el archivo Excel: {e}")

    st.stop()


# ============================================================
# VALIDAR COLUMNA POTRERO
# ============================================================

if "Potrero" not in df_rotaciones.columns:

    st.error(
        "El archivo Excel no contiene una columna llamada 'Potrero'."
    )

    st.write("Columnas encontradas:")

    st.write(list(df_rotaciones.columns))

    st.stop()


# ============================================================
# OBTENER POTREROS ACTUALMENTE OCUPADOS
# ============================================================

potreros_ocupados = set(

    df_rotaciones["Potrero"]
    .dropna()
    .astype(str)
    .str.strip()
    .str.upper()

)

# Eliminar valores vacíos
potreros_ocupados = {
    x for x in potreros_ocupados
    if x and x != "NAN"
}


# ============================================================
# LEER TODOS LOS KML DEL ZIP
# ============================================================

features = []

try:

    with zipfile.ZipFile(ARCHIVO_ZIP, "r") as archivo_zip:

        archivos_kml = [
            nombre
            for nombre in archivo_zip.namelist()
            if nombre.lower().endswith(".kml")
        ]

        for nombre_archivo in archivos_kml:

            contenido = archivo_zip.read(nombre_archivo)

            # ----------------------------------------------
            # Código basado inicialmente en nombre del archivo
            # ----------------------------------------------

            codigo = nombre_archivo.split("/")[-1]

            codigo = codigo.rsplit(".", 1)[0]

            codigo = codigo.strip().upper()

            # ----------------------------------------------
            # Intentar obtener nombre desde el KML
            # ----------------------------------------------

            try:

                nombre_kml = obtener_nombre_kml(contenido)

                if nombre_kml:

                    nombre_kml = nombre_kml.strip().upper()

                    # Si parece código PX-RXX, utilizarlo
                    if nombre_kml.startswith("P") and "-R" in nombre_kml:

                        codigo = nombre_kml

            except Exception:

                pass

            # ----------------------------------------------
            # Extraer geometrías
            # ----------------------------------------------

            try:

                geometrias = extraer_geometrias_kml(contenido)

            except Exception:

                geometrias = []

            # ----------------------------------------------
            # Crear Features
            # ----------------------------------------------

            for geometria in geometrias:

                ocupado = codigo in potreros_ocupados

                features.append({

                    "type": "Feature",

                    "geometry": geometria,

                    "properties": {

                        "codigo": codigo,

                        "ocupado": ocupado

                    }

                })


except Exception as e:

    st.error(f"No fue posible leer el ZIP de KML: {e}")

    st.stop()


# ============================================================
# VALIDACIÓN
# ============================================================

if not features:

    st.warning(
        "No se encontraron polígonos dentro de los archivos KML."
    )

    st.stop()


# ============================================================
# INFORMACIÓN SUPERIOR
# ============================================================

col1, col2, col3 = st.columns(3)

with col1:

    st.metric(
        "Potreros encontrados",
        len({
            f["properties"]["codigo"]
            for f in features
        })
    )

with col2:

    st.metric(
        "Potreros ocupados",
        len(potreros_ocupados)
    )

with col3:

    st.metric(
        "Polígonos cargados",
        len(features)
    )


# ============================================================
# CREAR MAPA
# ============================================================

m = folium.Map(

    location=[4.5, -69.5],

    zoom_start=12,

    tiles="OpenStreetMap"
)


# ============================================================
# AGREGAR POLÍGONOS
# ============================================================

todos_los_puntos = []


for feature in features:

    codigo = feature["properties"]["codigo"]

    ocupado = feature["properties"]["ocupado"]

    # --------------------------------------------------------
    # Color según estado
    # --------------------------------------------------------

    if ocupado:

        color = "#2E7D32"
        relleno = "#4CAF50"
        opacidad = 0.70

    else:

        color = "#777777"
        relleno = "#D9D9D9"
        opacidad = 0.25

    # --------------------------------------------------------
# Popup con información de la rotación
# --------------------------------------------------------

estado = "OCUPADO ACTUALMENTE" if ocupado else "NO OCUPADO"

# Buscar información del potrero en el Excel
datos_potrero = df_rotaciones[
    df_rotaciones["Potrero"].astype(str).str.strip().str.upper() == codigo
]

if ocupado and not datos_potrero.empty:

    fila = datos_potrero.iloc[0]

    # Fecha del último movimiento
    fecha_movimiento = pd.to_datetime(
        fila["Última fecha de movimiento"],
        errors="coerce"
    )

    if pd.notna(fecha_movimiento):
        fecha_movimiento = fecha_movimiento.strftime("%d/%m/%Y")
    else:
        fecha_movimiento = "No disponible"

    # Función para mostrar valores vacíos de forma limpia
    def mostrar_valor(valor, sufijo=""):
        if pd.isna(valor) or str(valor).strip() == "":
            return "No disponible"
        return f"{valor}{sufijo}"

    lote = mostrar_valor(fila["Lote"])
    tipo_lote = mostrar_valor(fila["Tipo de lote"])
    cantidad = mostrar_valor(fila["Cantidad de animales"])
    altura_actual = mostrar_valor(
        fila["Altura promedio actual (cm)"],
        " cm"
    )
    altura_anterior = mostrar_valor(
        fila["Altura promedio anterior (cm)"],
        " cm"
    )
    observaciones = mostrar_valor(fila["Observaciones"])

    popup_html = f"""
    <div style="font-family:Arial; min-width:260px;">

        <h4 style="margin-bottom:8px;">
            {codigo}
        </h4>

        <b>Estado:</b> {estado}<br><br>

        <b>Rotación:</b> {fila["Rotacion"]}<br>
        <b>Último movimiento:</b> {fecha_movimiento}<br>
        <b>Lote:</b> {lote}<br>
        <b>Tipo de lote:</b> {tipo_lote}<br>
        <b>Cantidad de animales:</b> {cantidad}<br><br>

        <b>Altura promedio actual:</b> {altura_actual}<br>
        <b>Altura promedio anterior:</b> {altura_anterior}<br><br>

        <b>Observaciones:</b><br>
        {observaciones}

    </div>
    """

else:

    popup_html = f"""
    <div style="font-family:Arial;">

        <h4 style="margin-bottom:8px;">
            {codigo}
        </h4>

        <b>Estado:</b> {estado}

    </div>
    """

popup = folium.Popup(
    popup_html,
    max_width=350
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

        tooltip=codigo

    ).add_to(m)

    # --------------------------------------------------------
    # Guardar coordenadas para ajustar mapa
    # --------------------------------------------------------

    geometry = feature["geometry"]

    for ring in geometry["coordinates"]:

        for lon, lat in ring:

            todos_los_puntos.append(
                [lat, lon]
            )


# ============================================================
# AJUSTAR MAPA A LOS POTREROS
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

        [min(lats), min(lons)],

        [max(lats), max(lons)]

    ]

    m.fit_bounds(bounds)


# ============================================================
# MOSTRAR MAPA
# ============================================================

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

    🟢 **Verde:** potrero ocupado actualmente según el último movimiento registrado.

    ⚪ **Gris:** potrero disponible/no identificado como ocupado actualmente.

    💡 **Haz clic sobre un potrero para consultar su código `PX-RXX`.**
    """
)
