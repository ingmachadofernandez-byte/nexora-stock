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
    """Consulta el stock disponible de forma segura adaptándose al esquema real de SQLite."""
    columnas_base = ["id", "sku", "producto", "lote", "ubicacion", "vencimiento", "cantidad"]
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='inventario'"
        )
        if cursor.fetchone() is None:
            return pd.DataFrame(columns=columnas_base)

        cursor.execute("PRAGMA table_info(inventario)")
        cols_inv = {row[1] for row in cursor.fetchall()}

        col_ub = "ubicacion_qr" if "ubicacion_qr" in cols_inv else ("ubicacion" if "ubicacion" in cols_inv else "'BOD-GEN'")
        col_lote = "lote" if "lote" in cols_inv else "'SIN-LOTE'"
        col_venc = (
            "COALESCE(i.fecha_vencimiento, '9999-12-31')"
            if "fecha_vencimiento" in cols_inv
            else "'9999-12-31'"
        )
        col_cant = "cantidad" if "cantidad" in cols_inv else "0"

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='productos'"
        )
        tiene_productos = cursor.fetchone() is not None

        if tiene_productos:
            query = f"""
                SELECT
                    i.id AS id,
                    i.sku AS sku,
                    COALESCE(p.nombre, 'Producto ' || i.sku) AS producto,
                    COALESCE(i.{col_lote}, 'SIN-LOTE') AS lote,
                    COALESCE(i.{col_ub}, 'BOD-GEN') AS ubicacion,
                    {col_venc} AS vencimiento,
                    i.{col_cant} AS cantidad
                FROM inventario i
                LEFT JOIN productos p ON i.sku = p.sku
                WHERE i.{col_cant} > 0
                ORDER BY i.sku ASC, vencimiento ASC, i.id ASC
            """
        else:
            query = f"""
                SELECT
                    id AS id,
                    sku AS sku,
                    'Producto ' || sku AS producto,
                    COALESCE({col_lote}, 'SIN-LOTE') AS lote,
                    COALESCE({col_ub}, 'BOD-GEN') AS ubicacion,
                    {col_venc.replace("i.", "")} AS vencimiento,
                    {col_cant} AS cantidad
                FROM inventario
                WHERE {col_cant} > 0
                ORDER BY sku ASC, vencimiento ASC, id ASC
            """

        return pd.read_sql_query(query, conn)
    except Exception:
        return pd.DataFrame(columns=columnas_base)
    finally:
        conn.close()


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
        cursor.execute("PRAGMA table_info(inventario)")
        cols_inv = {row[1] for row in cursor.fetchall()}
        col_ub = "ubicacion_qr" if "ubicacion_qr" in cols_inv else ("ubicacion" if "ubicacion" in cols_inv else "'BOD-GEN'")
        col_lote = "lote" if "lote" in cols_inv else "'SIN-LOTE'"
        col_venc = "COALESCE(fecha_vencimiento, '9999-12-31')" if "fecha_vencimiento" in cols_inv else "'9999-12-31'"

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

            cursor.execute(f"""
                SELECT id, {col_lote} AS lote, {col_ub} AS ubicacion_qr, cantidad, {col_venc} AS venc
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
        return False, f"Error al procesar despacho: str "