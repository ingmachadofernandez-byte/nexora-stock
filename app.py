import streamlit as st
import pandas as pd
from core.database import init_db, get_connection
from core.scan_engine import ScanEngine
from core.operaciones import render_modulo_recepcion, render_modulo_traslado

st.set_page_config(page_title="MD STOCK / NEXORA STOCK", page_icon="📦", layout="centered")
init_db()

st.session_state.setdefault("usuario", "op1")
st.session_state.setdefault("sonido_activo", True)
st.session_state.setdefault("ultimo_resultado", None)
st.session_state.setdefault("codigo_pendiente_alta", None)

st.title("📦 MD STOCK")
st.caption("Operación Scan-First • Captura de Código y Registro Directo")

col_ctx, col_snd = st.columns([3, 1])
with col_ctx:
    contexto = st.selectbox(
        "Contexto Operativo",
        ["RECEPCION", "TRASLADO", "CONSULTA / STOCK"],
    )
with col_snd:
    st.session_state["sonido_activo"] = st.toggle("🔊 Sonido", value=st.session_state["sonido_activo"])

# Si la cámara devolvió un código en query_params (por ejemplo ?code=7501054500193)
codigo_url = st.query_params.get("code", None)
if codigo_url:
    del st.query_params["code"]
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
                    cur = conn.cursor()
                    lote_val = lote_exist.strip() or "SIN-LOTE"
                    venc_val = venc_exist.strip() or "N/A"
                    ub_val = ub_exist.strip() or "LOC-REC-01"

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

                    # Verifica si ya existe el SKU en productos (por si el INSERT OR IGNORE se saltó)
                    row_prod = cur.execute(
                        "SELECT sku FROM productos WHERE codigo_barras = ? OR sku = ?",
                        (codigo_nuevo, sku),
                    ).fetchone()
                    sku_final = row_prod["sku"] if row_prod else sku

                    # Actualiza o inserta en inventario
                    lote_val = lote.strip() or "SIN-LOTE"
                    venc_val = vencimiento.strip() or "N/A"
                    ub_val = ubicacion.strip() or "LOC-REC-01"

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
                    conn.close()
                    st.session_state["codigo_pendiente_alta"] = None
                    st.session_state["ultimo_resultado"] = {
                        "status": "OK",
                        "mensaje": f"Producto '{nombre.strip()}' ({codigo_nuevo}) guardado con {cantidad} UND en {ub_val}.",
                    }
                    st.rerun()

st.divider()

if contexto == "RECEPCION":
    render_modulo_recepcion(res, st.session_state["usuario"], st.session_state["sonido_activo"])
elif contexto == "TRASLADO":
    render_modulo_traslado(res, st.session_state["usuario"], st.session_state["sonido_activo"])
else:
    st.subheader("📊 Inventario Actual")
    conn = get_connection()
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
    conn.close()
    st.dataframe(df_inv, use_container_width=True, hide_index=True)
