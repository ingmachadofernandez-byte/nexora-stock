import pandas as pd
import streamlit as st

from core.database import get_connection, init_db
from core.operaciones import render_modulo_recepcion, render_modulo_traslado
from core.ventas import render_modulo_ventas
from core.tablero_nextura import render_tablero_nextura
from pathlib import Path


st.set_page_config(
    page_title="MD STOCK / NEXORA STOCK",
    page_icon="📦",
    layout="wide",
)


def _inicializar_estado():
    st.session_state.setdefault("usuario", "OPERADOR_MD")
    st.session_state.setdefault("sonido_activo", True)


def _render_encabezado():
    base_dir = Path(__file__).resolve().parent
    candidatos = [
        base_dir / "assets" / "LOGO N .jpeg",
        base_dir.parent / "assets" / "LOGO N .jpeg",
    ]
    logo_path = next((p for p in candidatos if p.exists()), None)

    col_logo, col_texto = st.columns([1, 6], vertical_alignment="center")
    with col_logo:
        if logo_path is not None:
            st.image(str(logo_path), width=215)
    with col_texto:
        st.markdown("### NEXTURA")
        st.caption("Control Operativo MYD · MD STOCK")


def _render_consulta_stock():
elif contexto == "TABLERO / GOBERNANZA":
conn_tab = get_connection()
try:
    render_tablero_nextura(conn_tab)
finally:
    conn_tab.close()
    st.subheader("Consulta / Stock Actual")
    conn = get_connection()
    try:
        query = """
        SELECT
            i.ubicacion_qr AS Ubicacion,
            i.sku AS SKU,
            COALESCE(p.nombre, 'Producto ' || i.sku) AS Producto,
            COALESCE(i.lote, 'SIN-LOTE') AS Lote,
            COALESCE(i.fecha_vencimiento, '') AS Vencimiento,
            COALESCE(i.cantidad, 0) AS Cantidad
        FROM inventario i
        LEFT JOIN productos p ON p.sku = i.sku
        """
        df_inv = pd.read_sql_query(query, conn)
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
            ["RECEPCION", "TRASLADO", "VENTAS", "CONSULTA / STOCK", "TABLERO / GOBERNANZA"],
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
        elif contexto == "TABLERO / GOBERNANZA":
            conn_tab = get_connection()
            try:
                render_tablero_nextura(conn_tab)
            finally:
                conn_tab.close()


if __name__ == "__main__":
    main()
