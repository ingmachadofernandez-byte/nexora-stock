import streamlit as st
import pandas as pd
from core.database import init_db, get_connection
from core.scan_engine import ScanEngine
from core.operaciones import render_modulo_recepcion, render_modulo_traslado
from core.operaciones import render_modulo_recepcion, render_modulo_traslado
from core.ventas import render_modulo_ventas

st.set_page_config(page_title="MD STOCK / NEXORA STOCK", page_icon="📦", layout="centered")

st.markdown(
    """
    <style>
        /* Centrado elegante y respiro visual en escritorio y móvil */
        .block-container {
            max-width: 780px;
            padding-top: 2rem;
            padding-bottom: 3rem;
            margin: 0 auto;
        }

        /* Tarjetas limpias para bloques operativos */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.45);
            padding: 16px 18px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
        }

        /* Botón principal con acento ejecutivo */
        .stButton > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
            background: linear-gradient(135deg, #1F6AFF 0%, #0EA5E9 100%);
            color: #FFFFFF;
            border: none;
            border-radius: 10px;
            font-weight: 600;
            padding: 0.6rem 1.2rem;
            transition: transform 0.12s ease, filter 0.12s ease;
        }

        .stButton > button[kind="primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
            filter: brightness(1.06);
            transform: translateY(-1px);
        }

        /* Inputs con bordes suaves y buen enfoque */
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div {
            border-radius: 9px;
        }

        /* Espaciado limpio entre opciones de radio */
        div[data-testid="stRadio"] > div {
            gap: 10px;
            flex-wrap: wrap;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def _asegurar_ubicacion(cur, ubicacion_qr: str):
    """Garantiza que la ubicación exista en 'ubicaciones' para cumplir con FOREIGN KEY."""
    ub_clean = (ubicacion_qr or "LOC-REC-01").strip().upper()
    cur.execute(
        """
        INSERT OR IGNORE INTO ubicaciones (codigo_qr, zona, pasillo, nivel, descripcion)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ub_clean, "Recepción", "General", "Piso", "Ubicación creada automáticamente"),
    )
    return ub_clean


init_db()

st.session_state.setdefault("usuario", "op1")
st.session_state.setdefault("sonido_activo", True)
st.session_state.setdefault("ultimo_resultado", None)
st.session_state.setdefault("codigo_pendiente_alta", None)

# 1. Contenedor del encabezado, contexto operativo y sonido
with st.container(border=True):
    st.title("📦 MD STOCK")
    st.caption("Operación Scan-First • Captura de Código y Registro Directo")

    col_ctx, col_snd = st.columns([3, 1])
    with col_ctx:
        contexto = st.selectbox(
            "Contexto Operativo",
            ["RECEPCION", "TRASLADO", "VENTAS", "CONSULTA / STOCK"]
    with col_snd:
        st.session_state["sonido_activo"] = st.toggle("🔊 Sonido", value=st.session_state["sonido_activo"])

# Si la cámara o el escáner devolvió un código en query_params (?code=... o ?auto_code=...)
codigo_url = st.query_params.get("code", None) or st.query_params.get("auto_code", None)
if codigo_url:
    if "code" in st.query_params:
        del st.query_params["code"]
    if "auto_code" in st.query_params:
        del st.query_params["auto_code"]

    res = ScanEngine.process_scan(
        raw_code=codigo_url,
        contexto=contexto,
        usuario=st.session_state["usuario"],
    )
    st.session_state["ultimo_resultado"] = res
    ScanEngine.play_feedback_sound(res["status"], enabled=st.session_state["sonido_activo"])

    # Si el código no está registrado, lo guardamos como pendiente de alta rápida
    if res["status"] == "ERROR":
        st.session_state["codigo_pendiente_alta"] = codigo_url.strip()
    else:
        st.session_state["codigo_pendiente_alta"] = None

res = st.session_state["ultimo_resultado"]
if res:
    if res["status"] == "OK":
        st.success(f"✅ {res['mensaje']}")

        # Si es un producto ya existente en el catálogo, permitir registrar/sumar stock directamente
        if res.get("tipo") == "PRODUCTO" and res.get("data"):
            prod = res["data"]
            with st.container(border=True):
                st.markdown(f"### 📦 Cargar Stock a Inventario: **{prod['nombre']}** (`{prod['sku']}`)")
                col1, col2 = st.columns(2)
                with col1:
                    cant_exist = st.number_input("Cantidad a ingresar:", min_value=1, value=1, step=1, key="cant_prod_exist")
                    lote_exist = st.text_input("Lote:", value="LOT-2026A", placeholder="Ej: LOT-2026A", key="lote_prod_exist")
                with col2:
                    ub_exist = st.text_input("Ubicación:", value="LOC-REC-01", key="ub_prod_exist")
                    venc_exist = st.text_input("Vencimiento:", value="N/A", key="venc_prod_exist")

                if st.button("📥 Registrar Producto en Inventario", type="primary", use_container_width=True, key="btn_reg_prod_exist"):
                    conn = get_connection()
                    try:
                        cur = conn.cursor()
                        lote_val = lote_exist.strip() or "SIN-LOTE"
                        venc_val = venc_exist.strip() or "N/A"
                        ub_val = _asegurar_ubicacion(cur, ub_exist)

                        existente = cur.execute(
                            """
                            SELECT id, cantidad FROM inventario
                            WHERE ubicacion_qr = ? AND sku = ? AND lote = ?
                            """,
                            (ub_val, prod["sku"], lote_val),
                        ).fetchone()

                        if existente:
                            cur.execute(
                                "UPDATE inventario SET cantidad = cantidad + ?, fecha_vencimiento = ? WHERE id = ?",
                                (int(cant_exist), venc_val, existente["id"]),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO inventario (ubicacion_qr, sku, lote, fecha_vencimiento, cantidad)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (ub_val, prod["sku"], lote_val, venc_val, int(cant_exist)),
                            )

                        conn.commit()
                    finally:
                        conn.close()

                    ScanEngine.log_event(
                        st.session_state["usuario"],
                        contexto,
                        prod["sku"],
                        "PRODUCTO",
                        "OK",
                        f"Sumadas {cant_exist} UND de {prod['nombre']} en {ub_val} (Lote: {lote_val})"
                    )
                    ScanEngine.play_feedback_sound("OK", enabled=st.session_state["sonido_activo"])
                    st.success(f"✅ ¡Stock actualizado! Se sumaron {cant_exist} UND de '{prod['nombre']}' en {ub_val}.")
                    st.session_state["ultimo_resultado"] = {
                        "status": "OK",
                        "mensaje": f"Ingresadas {cant_exist} UND de {prod['nombre']} en {ub_val}."
                    }
                    st.rerun()

    elif res["status"] == "DUPLICADO":
        st.warning(f"⚠️ {res['mensaje']}")
    else:
        st.error(f"❌ {res['mensaje']}")

# Formulario de Alta Rápida + Ingreso a Inventario usando el código ya escaneado
codigo_nuevo = st.session_state["codigo_pendiente_alta"]
if codigo_nuevo:
    with st.container(border=True):
        st.markdown(f"### 🆕 Registrar y cargar a inventario: `{codigo_nuevo}`")
        with st.form("form_alta_inventario"):
            nombre = st.text_input("Nombre del producto", placeholder="Ej: Suplemento / Frasco 120ml")
            col1, col2 = st.columns(2)
            with col1:
                lote = st.text_input("Lote", placeholder="Ej: 01626")
                cantidad = st.number_input("Cantidad a ingresar", min_value=1, value=1, step=1)
            with col2:
                vencimiento = st.text_input("Vencimiento", placeholder="Ej: 17/01/2028")
                ubicacion = st.text_input("Ubicación inicial", value="LOC-REC-01")

            guardar = st.form_submit_button("📥 Registrar Producto en Inventario", type="primary", use_container_width=True)
            if guardar:
                if not nombre.strip():
                    st.warning("Escribe al menos el nombre del producto.")
                else:
                    conn = get_connection()
                    try:
                        cur = conn.cursor()
                        sku = f"SKU-{codigo_nuevo[-6:]}"

                        # Inserta en catálogo de productos si no existe
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO productos (sku, codigo_barras, nombre, unidad, requiere_lote)
                            VALUES (?, ?, ?, 'UND', 1)
                            """,
                            (sku, codigo_nuevo, nombre.strip()),
                        )

                        # Verifica si ya existe el SKU en productos
                        row_prod = cur.execute(
                            "SELECT sku FROM productos WHERE codigo_barras = ? OR sku = ?",
                            (codigo_nuevo, sku),
                        ).fetchone()
                        sku_final = row_prod["sku"] if row_prod else sku

                        # Actualiza o inserta en inventario asegurando ubicación válida
                        lote_val = lote.strip() or "SIN-LOTE"
                        venc_val = vencimiento.strip() or "N/A"
                        ub_val = _asegurar_ubicacion(cur, ubicacion)

                        existente = cur.execute(
                            """
                            SELECT id, cantidad FROM inventario
                            WHERE ubicacion_qr = ? AND sku = ? AND lote = ?
                            """,
                            (ub_val, sku_final, lote_val),
                        ).fetchone()

                        if existente:
                            cur.execute(
                                "UPDATE inventario SET cantidad = cantidad + ?, fecha_vencimiento = ? WHERE id = ?",
                                (int(cantidad), venc_val, existente["id"]),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO inventario (ubicacion_qr, sku, lote, fecha_vencimiento, cantidad)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (ub_val, sku_final, lote_val, venc_val, int(cantidad)),
                            )

                        conn.commit()
                    finally:
                        conn.close()

                    ScanEngine.log_event(
                        st.session_state["usuario"],
                        contexto,
                        codigo_nuevo,
                        "PRODUCTO_NUEVO",
                        "OK",
                        f"Alta y carga de {cantidad} UND de '{nombre.strip()}' ({sku_final}) en {ub_val} (Lote: {lote_val})"
                    )
                    ScanEngine.play_feedback_sound("OK", enabled=st.session_state["sonido_activo"])
                    st.session_state["codigo_pendiente_alta"] = None
                    st.session_state["ultimo_resultado"] = {
                        "status": "OK",
                        "mensaje": f"Producto '{nombre.strip()}' ({codigo_nuevo}) guardado con {cantidad} UND en {ub_val}.",
                    }
                    st.rerun()

# 2. Contenedor para el módulo activo (Recepción, Traslado, Inventario Actual)
with st.container(border=True):
if contexto == "RECEPCION":, elif contexto == "TRASLADO":, elif contexto == "VENTAS":
        render_modulo_ventas(res, st.session_state["usuario"], st.session_state["sonido_activo"])
    else:
        st.subheader("📊 Inventario Actual")
        conn = get_connection()
        try:
            df_inv = pd.read_sql_query(
                """
                SELECT i.ubicacion_qr AS Ubicacion, i.sku AS SKU, p.nombre AS Producto,
                       i.lote AS Lote, i.fecha_vencimiento AS Vencimiento, i.cantidad AS Cantidad
                FROM inventario i
                LEFT JOIN productos p ON i.sku = p.sku
                ORDER BY i.id DESC
                """,
                conn,
            )
        finally:
            conn.close()
        st.dataframe(df_inv, use_container_width=True, hide_index=True)