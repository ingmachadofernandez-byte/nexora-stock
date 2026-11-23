import pandas as pd
import streamlit as st

from core.database import get_connection, init_db
from core.operaciones import render_modulo_recepcion, render_modulo_traslado
from core.ventas import render_modulo_ventas

st.set_page_config(
    page_title="MD STOCK / NEXORA STOCK",
    page_icon="📦",
    layout="wide",
)


def _inicializar_estado():
    st.session_state.setdefault("usuario", "OPERADOR_MD")
    st.session_state.setdefault("sonido_activo", True)


def _render_encabezado():
    col_titulo, col_sonido = st.columns([5, 1])
    with col_titulo:
        st.title("📦 MD STOCK")
        st.caption("Operación Scan-First • Captura de Código y Registro Directo")
    with col_sonido:
        st.session_state["sonido_activo"] = st.toggle(
            "Sonido",
            value=st.session_state["sonido_activo"],
            key="toggle_sonido_global",
        )


def _render_consulta_stock():
    st.subheader("📊 Consulta / Stock Actual")
    conn = get_connection()
    try:
        query = """
            SELECT
                i.ubicacion_qr AS Ubicacion,
                i.sku AS SKU,
                COALESCE(p.nombre, 'Producto ' || i.sku) AS Producto,
                COALESCE(i.lote, 'SIN-LOTE') AS Lote,
                COALESCE(i.fecha_vencimiento, 'N/A') AS Vencimiento,
                i.cantidad AS Cantidad
            FROM inventario i
            LEFT JOIN productos p ON i.sku = p.sku
            WHERE i.cantidad > 0
            ORDER BY i.id DESC
        """
        try:
            df_inv = pd.read_sql_query(query, conn)
        except Exception:
            query_fallback = """
                SELECT
                    ubicacion_qr AS Ubicacion,
                    sku AS SKU,
                    'Producto ' || sku AS Producto,
                    COALESCE(lote, 'SIN-LOTE') AS Lote,
                    COALESCE(fecha_vencimiento, 'N/A') AS Vencimiento,
                    cantidad AS Cantidad
                FROM inventario
                WHERE cantidad > 0
                ORDER BY id DESC
            """
            df_inv = pd.read_sql_query(query_fallback, conn)
    finally:
        conn.close()

    if df_inv.empty:
        st.info("No hay existencias registradas en el inventario en este momento.")
    else:
        st.dataframe(df_inv, use_container_width=True, hide_index=True)


def main():
    _inicializar_estado()
    init_db()

    with st.container(border=True):
        _render_encabezado()
        contexto = st.selectbox(
            "Contexto Operativo",
            ["RECEPCION", "TRASLADO", "VENTAS", "CONSULTA / STOCK"],
            index=0,
            key="selector_contexto_operativo",
        )

    res = {}
    usuario = st.session_state["usuario"]
    sonido_activo = st.session_state["sonido_activo"]

    with st.container(border=True):
        if contexto == "RECEPCION":
            render_modulo_recepcion(res, usuario, sonido_activo)
        elif contexto == "TRASLADO":
            render_modulo_traslado(res, usuario, sonido_activo)
        elif contexto == "VENTAS":
            render_modulo_ventas(res, usuario, sonido_activo)
        elif contexto == "CONSULTA / STOCK":
            _render_consulta_stock()


if __name__ == "__main__":
    main()