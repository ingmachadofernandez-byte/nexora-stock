from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
import urllib.parse

try:
    import altair as alt
    HAS_ALTAIR = True
except ImportError:
    HAS_ALTAIR = False


def _obtener_base_lotes() -> pd.DataFrame:
    base_dir = Path(__file__).resolve().parent.parent
    candidatos_excel = [
        base_dir / "Consolidado por Producto Detallado por Bodega - Lotes_20261124_200439.xlsx",
        base_dir / "data" / "Consolidado por Producto Detallado por Bodega - Lotes_20261124_200439.xlsx",
        base_dir.parent / "Consolidado por Producto Detallado por Bodega - Lotes_20261124_200439.xlsx",
        Path("Consolidado por Producto Detallado por Bodega - Lotes_20261124_200439.xlsx"),
    ]
    excel_path = next((p for p in candidatos_excel if p.exists()), None)
    if excel_path is None:
        return pd.DataFrame(
            columns=[
                "producto",
                "lote",
                "vencimiento",
                "existencia_lote",
                "principal_lote",
                "bodega_lote",
                "precio_unitario",
                "valor_lote",
            ]
        )

    df = pd.read_excel(excel_path, sheet_name="Consolidados")
    rows = []
    current_producto = None

    for _, r in df.iloc[7:].iterrows():
        c0 = r.get("Unnamed: 0")
        c2 = r.get("Unnamed: 2")
        c3 = r.get("Unnamed: 3")
        s0 = str(c0).strip() if pd.notna(c0) else ""
        s2 = str(c2).strip() if pd.notna(c2) else ""
        s3_num = pd.to_numeric(c3, errors="coerce")

        if not s0:
            continue
        if (
            s0 in ["2 ALMACEN", "1 Principal", "Registros sin Grupos de Inventario", "MED MEDICAMENTOS"]
            or s0.startswith("PNF ")
            or s0.startswith("Total para ")
        ):
            continue

        if pd.notna(c2) or pd.notna(s3_num):
            rows.append(
                {
                    "producto": current_producto,
                    "lote": s0,
                    "vencimiento": s2,
                    "existencia_lote": float(s3_num) if pd.notna(s3_num) else 0.0,
                }
            )
        else:
            current_producto = s0

    lot_df = pd.DataFrame(rows)
    if lot_df.empty:
        return lot_df

    prod_tot = (
        lot_df.groupby("producto", as_index=False)["existencia_lote"]
        .sum()
        .rename(columns={"existencia_lote": "existencia_producto"})
    )
    prod_tot["principal_prod"] = np.where(
        prod_tot["existencia_producto"] > 0,
        np.minimum(prod_tot["existencia_producto"], 100.0),
        0.0,
    )
    prod_tot["bodega_prod"] = np.where(
        prod_tot["existencia_producto"] > 100.0,
        prod_tot["existencia_producto"] - 100.0,
        0.0,
    )

    merged = lot_df.merge(prod_tot, on="producto", how="left")
    ratio_bodega = np.where(
        (merged["bodega_prod"] > 0) & (merged["existencia_producto"] > 0),
        np.maximum(merged["existencia_lote"], 0.0) / merged["existencia_producto"],
        0.0,
    )
    merged["bodega_lote"] = np.round(merged["bodega_prod"] * ratio_bodega, 2)
    merged["principal_lote"] = np.round(merged["existencia_lote"] - merged["bodega_lote"], 2)
    merged["precio_unitario"] = 0.0
    merged["valor_lote"] = 0.0
    return merged


def _asegurar_tablas_gobernanza(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS nextura_relevos_turno (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            turno TEXT NOT NULL,
            entrega_responsable TEXT NOT NULL,
            recibe_responsable TEXT NOT NULL,
            observaciones TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS nextura_extracciones_bodega (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            responsable TEXT NOT NULL,
            producto TEXT NOT NULL,
            lote TEXT NOT NULL,
            unidades REAL NOT NULL,
            motivo TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS nextura_perdidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            turno TEXT NOT NULL,
            ubicacion TEXT NOT NULL,
            tipo_perdida TEXT NOT NULL,
            producto TEXT NOT NULL,
            lote TEXT NOT NULL,
            unidades REAL NOT NULL,
            valor_dinero REAL NOT NULL DEFAULT 0.0,
            responsable TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _grafico_barras(df: pd.DataFrame, x_col: str, y_col: str, titulo: str, color_hex: str = "#1F6AFF") -> None:
    st.markdown(f"**{titulo}**")
    if df.empty:
        st.info("Sin registros para graficar todavía.")
        return
    if HAS_ALTAIR:
        chart = (
            alt.Chart(df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=color_hex)
            .encode(
                x=alt.X(f"{x_col}:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-25)),
                y=alt.Y(f"{y_col}:Q", title="Cantidad / Valor"),
                tooltip=[x_col, y_col],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.bar_chart(df.set_index(x_col)[y_col], height=260)


def render_tablero_nextura(conn=None, usuario: str = "OPERADOR_MD") -> None:
    st.subheader("Tablero de Control NEXTURA · Gobernanza y Cierre")
    st.caption("Turnos: AM (08:00–13:00) y PM (14:00–17:00) · Tope Principal: 100 und/producto · Alerta CEO: <= 70 und")

    if conn is not None:
        _asegurar_tablas_gobernanza(conn)

    df_lotes = _obtener_base_lotes()
    if df_lotes.empty:
        st.warning("No se encontró el archivo consolidado de lotes para calcular el tablero base.")
        return

    resumen_prod = df_lotes.groupby("producto", as_index=False).agg(
        existencia_total=("existencia_lote", "sum"),
        principal_und=("principal_lote", "sum"),
        bodega_und=("bodega_lote", "sum"),
        valor_total=("valor_lote", "sum"),
        lotes=("lote", "nunique"),
    )
    resumen_prod["alerta_70"] = resumen_prod["principal_und"] <= 70.0

    st.session_state.setdefault(
        "nextura_ventas_turno",
        pd.DataFrame(
            [
                {"Turno": "AM (08:00-13:00)", "Unidades_Vendidas": 0.0, "Dinero_Ventas": 0.0},
                {"Turno": "PM (14:00-17:00)", "Unidades_Vendidas": 0.0, "Dinero_Ventas": 0.0},
            ]
        ),
    )
    st.session_state.setdefault("nextura_perdidas_log", [])

    total_und = float(resumen_prod["existencia_total"].sum())
    total_prin = float(resumen_prod["principal_und"].sum())
    total_bod = float(resumen_prod["bodega_und"].sum())
    alertas_df = resumen_prod[resumen_prod["alerta_70"]].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Unidades Totales", f"{total_und:,.1f}")
    c2.metric("Principal (<=100/prod)", f"{total_prin:,.1f}")
    c3.metric("Bodega (Excedente)", f"{total_bod:,.1f}")
    c4.metric("Alerta Reabastecer (<=70)", f"{len(alertas_df)} prod.")

    st.divider()

    g1, g2 = st.columns(2)
    with g1:
        df_seg = pd.DataFrame(
            {
                "Segmento": ["Principal (Estantería)", "Bodega"],
                "Unidades": [total_prin, total_bod],
            }
        )
        _grafico_barras(df_seg, "Segmento", "Unidades", "Distribución: Principal vs. Bodega", "#0B1C2D")

    with g2:
        _grafico_barras(
            st.session_state["nextura_ventas_turno"],
            "Turno",
            "Dinero_Ventas",
            "Ventas en Dinero por Turno ($)",
            "#2FD1A2",
        )

    g3, g4 = st.columns(2)
    with g3:
        top_stock = resumen_prod.sort_values("existencia_total", ascending=False).head(8).copy()
        top_stock["Producto_Corto"] = top_stock["producto"].str.slice(0, 22)
        _grafico_barras(
            top_stock,
            "Producto_Corto",
            "existencia_total",
            "Top 8 Productos por Existencias",
            "#1F6AFF",
        )

    with g4:
        perd_rows = st.session_state["nextura_perdidas_log"]
        if perd_rows:
            df_perd = pd.DataFrame(perd_rows).groupby("turno", as_index=False)["unidades"].sum()
        else:
            df_perd = pd.DataFrame(
                {
                    "turno": ["AM (08:00-13:00)", "PM (14:00-17:00)"],
                    "unidades": [0.0, 0.0],
                }
            )
        _grafico_barras(df_perd, "turno", "unidades", "Pérdidas Registradas por Turno (Und)", "#E58A17")

    st.divider()

    tab_alertas, tab_bodega, tab_turnos, tab_perdidas, tab_lotes = st.tabs(
        [
            "Alerta CEO (<=70)",
            "Extracción Bodega",
            "Relevo Turnos AM/PM",
            "Pérdidas",
            "Lotes y Vencimientos",
        ]
    )

    with tab_alertas:
        st.markdown("**Productos con <= 70 unidades en Principal para notificar al CEO:**")
        if alertas_df.empty:
            st.success("Ningún producto está en o por debajo de 70 unidades.")
        else:
            st.dataframe(
                alertas_df[["producto", "principal_und", "bodega_und", "existencia_total"]],
                use_container_width=True,
                hide_index=True,
            )
            lista_ceo = "\n".join(
                f"- {r['producto'][:35]}: {r['principal_und']:.0f} und en Principal"
                for _, r in alertas_df.head(15).iterrows()
            )
            msg_ceo = (
                "NEXTURA (MYD) - Alerta Estanteria (<=70 und)\n"
                f"Debes reabastecer la estanteria desde Bodega:\n{lista_ceo}"
            )
            st.text_area("Mensaje listo para copiar / enviar al CEO por WhatsApp", value=msg_ceo, height=150)
            col_wa, col_info = st.columns([1, 2])
            with col_wa:
                wa_url = "https://wa.me/?text=" + urllib.parse.quote(msg_ceo)
                st.link_button("📲 Enviar por WhatsApp", wa_url, use_container_width=True)
            with col_info:
                st.caption("Abre WhatsApp con el mensaje precargado o usa el bloque de copia rápida.")
            st.code(msg_ceo, language=None)
    with tab_bodega:
        with st.form("form_extraccion_bodega"):
            resp_bod = st.text_input("Responsable que saca de Bodega *", value=usuario)
            prod_sel = st.selectbox("Producto", options=sorted(resumen_prod["producto"].unique()))
            lotes_prod = df_lotes[df_lotes["producto"] == prod_sel]["lote"].unique().tolist()
            lote_sel = st.selectbox("Lote escaneado", options=lotes_prod if lotes_prod else ["SIN-LOTE"])
            und_sacar = st.number_input("Unidades a extraer de Bodega", min_value=0.0, step=1.0, value=0.0)
            enviado_bod = st.form_submit_button("Registrar extracción de Bodega")
            if enviado_bod:
                if not resp_bod.strip():
                    st.error("Debes indicar el responsable que saca la información/mercancía de bodega.")
                else:
                    if conn is not None:
                        conn.execute(
                            """
                            INSERT INTO nextura_extracciones_bodega
                            (fecha_hora, responsable, producto, lote, unidades, motivo)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                datetime.now().isoformat(timespec="seconds"),
                                resp_bod.strip(),
                                prod_sel,
                                lote_sel,
                                float(und_sacar),
                                "Reabastecimiento Principal",
                            ),
                        )
                        conn.commit()
                    st.success(f"Extracción registrada por {resp_bod.strip()} ({und_sacar:.0f} und).")

    with tab_turnos:
        with st.form("form_relevo_turno"):
            turno_sel = st.selectbox("Turno de cierre", ["AM (08:00-13:00)", "PM (14:00-17:00)"])
            col_e, col_r = st.columns(2)
            quien_entrega = col_e.text_input("Responsable que ENTREGA físicamente *")
            quien_recibe = col_r.text_input("Responsable que RECIBE físicamente *")
            obs_turno = st.text_area("Observaciones / novedades de cierre")
            guardar_relevo = st.form_submit_button("Guardar cierre y relevo de turno")
            if guardar_relevo:
                if not quien_entrega.strip() or not quien_recibe.strip():
                    st.error("Debes registrar quién entrega y quién recibe el turno.")
                else:
                    if conn is not None:
                        conn.execute(
                            """
                            INSERT INTO nextura_relevos_turno
                            (fecha_hora, turno, entrega_responsable, recibe_responsable, observaciones)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                datetime.now().isoformat(timespec="seconds"),
                                turno_sel,
                                quien_entrega.strip(),
                                quien_recibe.strip(),
                                obs_turno.strip(),
                            ),
                        )
                        conn.commit()
                    st.success(f"Cierre {turno_sel} registrado: Entrega {quien_entrega} → Recibe {quien_recibe}.")

    with tab_perdidas:
        with st.form("form_perdida"):
            c_p1, c_p2, c_p3 = st.columns(3)
            p_turno = c_p1.selectbox("Turno", ["AM (08:00-13:00)", "PM (14:00-17:00)"])
            p_ubic = c_p2.selectbox("Ubicación", ["BODEGA", "PRINCIPAL"])
            p_tipo = c_p3.selectbox("Motivo de pérdida", ["DIFERENCIA_INVENTARIO", "VENCIMIENTO", "DAÑO"])
            p_prod = st.selectbox("Producto afectado", options=sorted(resumen_prod["producto"].unique()), key="p_prod")
            c_u, c_v, c_r = st.columns(3)
            p_und = c_u.number_input("Unidades perdidas", min_value=0.0, step=1.0, value=0.0)
            p_dinero = c_v.number_input("Valor pérdida ($)", min_value=0.0, step=100.0, value=0.0)
            p_resp = c_r.text_input("Responsable del reporte *", value=usuario)
            ok_perd = st.form_submit_button("Registrar pérdida")
            if ok_perd:
                if not p_resp.strip():
                    st.error("Indica el responsable del registro de pérdida.")
                else:
                    st.session_state["nextura_perdidas_log"].append(
                        {
                            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "turno": p_turno,
                            "ubicacion": p_ubic,
                            "tipo_perdida": p_tipo,
                            "producto": p_prod,
                            "unidades": float(p_und),
                            "valor_dinero": float(p_dinero),
                            "responsable": p_resp.strip(),
                        }
                    )
                    if conn is not None:
                        conn.execute(
                            """
                            INSERT INTO nextura_perdidas
                            (fecha_hora, turno, ubicacion, tipo_perdida, producto, lote, unidades, valor_dinero, responsable)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                datetime.now().isoformat(timespec="seconds"),
                                p_turno,
                                p_ubic,
                                p_tipo,
                                p_prod,
                                "LOTE-GENERAL",
                                float(p_und),
                                float(p_dinero),
                                p_resp.strip(),
                            ),
                        )
                        conn.commit()
                    st.success("Pérdida registrada correctamente.")

        if st.session_state["nextura_perdidas_log"]:
            st.dataframe(pd.DataFrame(st.session_state["nextura_perdidas_log"]), use_container_width=True, hide_index=True)

    with tab_lotes:
        st.dataframe(
            df_lotes[
                [
                    "producto",
                    "lote",
                    "vencimiento",
                    "existencia_lote",
                    "principal_lote",
                    "bodega_lote",
                    "precio_unitario",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
