def render_modulo_ventas(res, usuario, sonido_activo):
    """Interfaz operativa de ventas/despachos con turno AM/PM, política FEFO y evidencia visual."""
    inicializar_tablas_ventas()
    turno_actual = determinar_turno_actual()

    st.subheader("🛒 Módulo de Ventas y Despachos (FEFO)")
    st.caption(f"Turno activo automático: **{turno_actual}** (Hora Colombia) • Descuento por vencimiento más próximo")

    df_disp = obtener_disponibilidad_inventario()
    if df_disp.empty:
        st.warning("No hay stock disponible en inventario para despachar.")
        return

    # Consolidar disponibilidad total por SKU para selección de pedido
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
                    # Fusionar si ya estaba en el carrito
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