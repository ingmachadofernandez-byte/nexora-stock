import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
import pandas as pd
import streamlit as st

from core.sheets_sync import sincronizar_movimiento_a_sheets

DB_PATH = "nexora_stock.db"
EVIDENCIAS_DIR = os.path.join("data", "evidencias")


def _get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_tablas_ventas():
    """Crea la tabla de auditoría de despachos y verifica columnas necesarias."""
    os.makedirs(EVIDENCIAS_DIR, exist_ok=True)
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS despachos_evidencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            turno TEXT NOT NULL,
            numero_factura TEXT NOT NULL,
            cliente TEXT,
            usuario TEXT NOT NULL,
            total_unidades INTEGER NOT NULL,
            ruta_foto_factura TEXT,
            ruta_foto_bolsa TEXT,
            verificacion_visual_ok INTEGER NOT NULL DEFAULT 1,
            observaciones TEXT
        )
    """)

    cursor.execute("PRAGMA table_info(despachos_evidencia)")
    columnas = [col[1] for col in cursor.fetchall()]
    if "verificacion_visual_ok" not in columnas:
        cursor.execute(
            "ALTER TABLE despachos_evidencia ADD COLUMN verificacion_visual_ok INTEGER NOT NULL DEFAULT 1"
        )

    conn.commit()
    conn.close()


def guardar_foto_comprimida(uploaded_file, prefijo: str, factura: str) -> str:
    """Comprime la imagen tomada desde el celular a máx 800px para ahorrar almacenamiento."""
    if uploaded_file is None:
        return ""
    os.makedirs(EVIDENCIAS_DIR, exist_ok=True)
    ahora = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y%m%d_%H%M%S")
    factura_limpia = "".join(c for c in factura if c.isalnum() or c in ("-", "_")) or "SIN_FAC"
    filename = f"{prefijo}_{factura_limpia}_{ahora}.jpg"
    filepath = os.path.join(EVIDENCIAS_DIR, filename)

    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((800, 800))
    img.save(filepath, format="JPEG", quality=72, optimize=True)
    return filepath


def obtener_disponibilidad_inventario() -> pd.DataFrame:
    """Consulta el stock disponible agrupado por SKU, Lote, Ubicación y Vencimiento (FEFO)."""
    conn = _get_connection()
    query = """
        SELECT 
            i.id,
            i.sku,
            COALESCE(p.nombre, 'Producto ' || i.sku) AS producto,
            i.lote,
            i.ubicacion_qr AS ubicacion,
            COALESCE(i.fecha_vencimiento, '9999-12-31') AS vencimiento,
            i.cantidad
        FROM inventario i
        LEFT JOIN productos p ON i.sku = p.sku
        WHERE i.cantidad > 0
        ORDER BY i.sku ASC, vencimiento ASC, i.id ASC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception:
        query_fallback = """
            SELECT 
                id,
                sku,
                'Producto ' || sku AS producto,
                lote,
                ubicacion_qr AS ubicacion,
                COALESCE(fecha_vencimiento, '9999-12-31') AS vencimiento,
                cantidad
            FROM inventario
            WHERE cantidad > 0
            ORDER BY sku ASC, vencimiento ASC, id ASC
        """
        df = pd.read_sql_query(query_fallback, conn)
    finally:
        conn.close()
    return df


def determinar_turno_actual() -> str:
    """Retorna 'AM' antes de la 1:00 PM y 'PM' desde la 1:00 PM (hora Colombia)."""
    hora = datetime.now(ZoneInfo("America/Bogota")).hour
    return "AM" if hora < 13 else "PM"


def procesar_despacho_venta(
    numero_factura: str,
    cliente: str,
    usuario: str,
    items_pedido: list[dict],
    foto_factura_file,
    foto_bolsa_file,
    verificacion_visual_ok: bool,
    observaciones: str = ""
) -> tuple[bool, str]:
    """
    Valida stock, exige confirmación visual factura vs bolsa, guarda fotos comprimidas,
    descuenta inventario (FEFO) y sincroniza movimientos con Google Sheets.
    """
    if not numero_factura or not numero_factura.strip():
        return False, "Debes ingresar el número de factura antes de despachar."
    if not items_pedido:
        return False, "No hay productos agregados en el pedido."
    if foto_factura_file is None:
        return False, "Falta la foto de la factura del vendedor."
    if foto_bolsa_file is None:
        return False, "Falta la foto de verificación de la bolsa/empaque."
    if not verificacion_visual_ok:
        return False, "Debes confirmar visualmente que los productos en la bolsa coinciden con la factura."

    inicializar_tablas_ventas()
    conn = _get_connection()
    cursor = conn.cursor()

    try:
        # 1. Validar stock suficiente por cada SKU antes de modificar la base de datos
        for item in items_pedido:
            sku = item["sku"]
            req = int(item["cantidad"])
            if req <= 0:
                return False, f"La cantidad solicitada para {sku} debe ser mayor a cero."

            cursor.execute(
                "SELECT COALESCE(SUM(cantidad), 0) FROM inventario WHERE sku = ? AND cantidad > 0",
                (sku,)
            )
            disponible = int(cursor.fetchone()[0])
            if disponible < req:
                return False, f"Stock insuficiente para {sku}: pides {req} UND y hay {disponible} UND disponibles."

        # 2. Guardar evidencias fotográficas comprimidas
        ruta_fac = guardar_foto_comprimida(foto_factura_file, "FAC", numero_factura)
        ruta_bolsa = guardar_foto_comprimida(foto_bolsa_file, "BOLSA", numero_factura)

        ahora_dt = datetime.now(ZoneInfo("America/Bogota"))
        ahora_str = ahora_dt.strftime("%Y-%m-%d %H:%M:%S")
        turno = determinar_turno_actual()
        total_unidades = sum(int(i["cantidad"]) for i in items_pedido)

        # 3. Registrar cabecera del despacho con fotos y validación visual
        cursor.execute("""
            INSERT INTO despachos_evidencia 
            (fecha_hora, turno, numero_factura, cliente, usuario, total_unidades, ruta_foto_factura, ruta_foto_bolsa, verificacion_visual_ok, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ahora_str,
            turno,
            numero_factura.strip(),
            (cliente or "").strip(),
            usuario,
            total_unidades,
            ruta_fac,
            ruta_bolsa,
            1 if verificacion_visual_ok else 0,
            (observaciones or "").strip()
        ))

        # 4. Descontar inventario aplicando FEFO (primero lo más próximo a vencer)
        movimientos_sheets = []
        for item in items_pedido:
            sku = item["sku"]
            pendiente = int(item["cantidad"])

            cursor.execute("""
                SELECT id, lote, ubicacion_qr, cantidad, COALESCE(fecha_vencimiento, '9999-12-31') AS venc
                FROM inventario
                WHERE sku = ? AND cantidad > 0
                ORDER BY venc ASC, id ASC
            """, (sku,))
            lotes = cursor.fetchall()

            for fila in lotes:
                if pendiente <= 0:
                    break
                inv_id = fila["id"]
                lote = fila["lote"] or "SIN-LOTE"
                ubicacion = fila["ubicacion_qr"] or "BOD-GEN"
                disp = int(fila["cantidad"])

                descontar = min(disp, pendiente)
                nuevo_saldo = disp - descontar

                cursor.execute(
                    "UPDATE inventario SET cantidad = ? WHERE id = ?",
                    (nuevo_saldo, inv_id)
                )

                detalle_mov = (
                    f"Venta Fac #{numero_factura.strip()} | Turno {turno} | "
                    f"Cliente: {(cliente or '').strip() or 'General'} | Cotejo Factura-Bolsa OK"
                )
                cursor.execute("""
                    INSERT INTO movimientos (fecha_hora, usuario, tipo_movimiento, sku, ubicacion, lote, cantidad, detalle)
                    VALUES (?, ?, 'SALIDA_VENTA', ?, ?, ?, ?, ?)
                """, (ahora_str, usuario, sku, ubicacion, lote, -descontar, detalle_mov))

                movimientos_sheets.append({
                    "usuario": usuario,
                    "tipo_movimiento": f"VENTA ({turno})",
                    "sku": sku,
                    "ubicacion": ubicacion,
                    "lote": lote,
                    "cantidad": -descontar,
                    "detalle": detalle_mov
                })
                pendiente -= descontar

        conn.commit()

        # 5. Sincronizar con Google Sheets (MD INVENTARIO)
        notas_sync = []
        for mov in movimientos_sheets:
            ok_s, msg_s = sincronizar_movimiento_a_sheets(
                usuario=mov["usuario"],
                tipo_movimiento=mov["tipo_movimiento"],
                sku=mov["sku"],
                ubicacion=mov["ubicacion"],
                lote=mov["lote"],
                cantidad=mov["cantidad"],
                detalle=mov["detalle"]
            )
            if not ok_s:
                notas_sync.append(msg_s)

        resumen = (
            f"✅ Pedido Factura #{numero_factura.strip()} despachado "
            f"({total_unidades} UND descontadas en Turno {turno}). "
            f"Cotejo visual y evidencias guardadas."
        )
        if notas_sync:
            resumen += f" ⚠️ Nota Sheets: {notas_sync[0]}"
        return True, resumen

    except Exception as e:
        conn.rollback()
        return False, f"Error al procesar despacho: {str(e)}"
    finally:
        conn.close()


def obtener_historial_despachos(limite: int = 50) -> pd.DataFrame:
    """Devuelve los últimos despachos registrados con sus evidencias para auditoría o tablero."""
    inicializar_tablas_ventas()
    conn = _get_connection()
    query = """
        SELECT 
            id,
            fecha_hora,
            turno,
            numero_factura,
            cliente,
            usuario,
            total_unidades,
            verificacion_visual_ok,
            ruta_foto_factura,
            ruta_foto_bolsa,
            observaciones
        FROM despachos_evidencia
        ORDER BY id DESC
        LIMIT ?
    """
    try:
        df = pd.read_sql_query(query, conn, params=(limite,))
    finally:
        conn.close()
    return df


def render_modulo_ventas(res, usuario, sonido_activo):
    """Interfaz operativa de ventas/despachos con turno AM/PM, política FEFO y evidencia visual."""
    inicializar_tablas_ventas()
    turno_actual = determinar_turno_actual()

    st.subheader("🛒 Módulo de Ventas y Despachos (FEFO)")
    st.caption(
        f"Turno activo automático: **{turno_actual}** (Hora Colombia) • Descuento por vencimiento más próximo"
    )

    df_disp = obtener_disponibilidad_inventario()
    if df_disp.empty:
        st.warning("No hay stock disponible en inventario para despachar.")
        return

    resumen_sku = (
        df_disp.groupby(["sku", "producto"], as_index=False)["cantidad"]
        .sum()
        .sort_values("sku")
    )
    opciones_sku = {
        f"{row['sku']} - {row['producto']} (Disp: {int(row['cantidad'])} UND)": row["sku"]
        for _, row in resumen_sku.iterrows()
    }

    st.session_state.setdefault("items_pedido_venta", [])

    with st.container(border=True):
        st.markdown("#### 1. Armar pedido del cliente")
        col_prod, col_cant = st.columns([3, 1])
        with col_prod:
            etiqueta_sel = st.selectbox(
                "Producto disponible:",
                list(opciones_sku.keys()),
                key="venta_sel_producto",
            )
        with col_cant:
            cant_sel = st.number_input(
                "Cantidad (UND):",
                min_value=1,
                value=1,
                step=1,
                key="venta_cant_producto",
            )

        c_add, c_clear = st.columns([2, 1])
        with c_add:
            if st.button("➕ Agregar al pedido", use_container_width=True, key="btn_agregar_item_venta"):
                sku_elegido = opciones_sku[etiqueta_sel]
                disp_total = int(
                    resumen_sku.loc[resumen_sku["sku"] == sku_elegido, "cantidad"].iloc[0]
                )
                acumulado_actual = sum(
                    int(x["cantidad"])
                    for x in st.session_state["items_pedido_venta"]
                    if x["sku"] == sku_elegido
                )
                if acumulado_actual + int(cant_sel) > disp_total:
                    st.error(
                        f"Supera lo disponible para {sku_elegido} ({disp_total} UND en total)."
                    )
                else:
                    fusionado = False
                    for item in st.session_state["items_pedido_venta"]:
                        if item["sku"] == sku_elegido:
                            item["cantidad"] = int(item["cantidad"]) + int(cant_sel)
                            fusionado = True
                            break
                    if not fusionado:
                        st.session_state["items_pedido_venta"].append(
                            {"sku": sku_elegido, "cantidad": int(cant_sel)}
                        )
                    st.rerun()

        with c_clear:
            if st.button("🗑️ Limpiar pedido", use_container_width=True, key="btn_limpiar_pedido_venta"):
                st.session_state["items_pedido_venta"] = []
                st.rerun()

        if st.session_state["items_pedido_venta"]:
            df_pedido = pd.DataFrame(st.session_state["items_pedido_venta"])
            df_pedido = df_pedido.merge(
                resumen_sku[["sku", "producto"]], on="sku", how="left"
            )[["sku", "producto", "cantidad"]]
            df_pedido.columns = ["SKU", "Producto", "Cantidad"]
            st.dataframe(df_pedido, use_container_width=True, hide_index=True)
        else:
            st.info("Agrega al menos un producto al pedido para registrar el despacho.")

    with st.container(border=True):
        st.markdown("#### 2. Datos de factura, evidencias y cotejo visual")
        with st.form("form_despacho_venta"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                numero_factura = st.text_input(
                    "Número de factura *",
                    placeholder="Ej: FAC-00124",
                )
            with col_f2:
                cliente = st.text_input(
                    "Cliente (opcional)",
                    placeholder="Ej: Cliente Mostrador / Tienda Norte",
                )

            col_cam1, col_cam2 = st.columns(2)
            with col_cam1:
                foto_factura = st.camera_input(
                    "Foto de la factura *",
                    key="cam_foto_factura_venta",
                )
            with col_cam2:
                foto_bolsa = st.camera_input(
                    "Foto de la bolsa / empaque *",
                    key="cam_foto_bolsa_venta",
                )

            verificacion_visual_ok = st.checkbox(
                "Confirmo visualmente que los productos en la bolsa coinciden con la factura",
                value=False,
            )
            observaciones = st.text_input(
                "Observaciones (opcional)",
                placeholder="Ej: Lote más próximo a vencer despachado primero",
            )

            confirmar_despacho = st.form_submit_button(
                "🚀 Confirmar Despacho y Descontar (FEFO)",
                type="primary",
                use_container_width=True,
            )

            if confirmar_despacho:
                ok, msg = procesar_despacho_venta(
                    numero_factura=numero_factura,
                    cliente=cliente,
                    usuario=usuario,
                    items_pedido=st.session_state["items_pedido_venta"],
                    foto_factura_file=foto_factura,
                    foto_bolsa_file=foto_bolsa,
                    verificacion_visual_ok=verificacion_visual_ok,
                    observaciones=observaciones,
                )
                if ok:
                    st.session_state["items_pedido_venta"] = []
                    if sonido_activo:
                        try:
                            from core.scan_engine import ScanEngine
                            ScanEngine.play_feedback_sound("OK", enabled=True)
                        except Exception:
                            pass
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with st.expander("📋 Últimos despachos registrados", expanded=False):
        df_hist = obtener_historial_despachos(limite=20)
        if df_hist.empty:
            st.info("Aún no hay despachos registrados.")
        else:
            st.dataframe(df_hist, use_container_width=True, hide_index=True)