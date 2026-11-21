import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from core.database import get_connection
from core.scan_engine import ScanEngine


def render_camera_scanner():
    """
    Escáner de cámara móvil con html5-qrcode.
    Recuadro rectangular compacto para códigos de barras/QR y envío de ?code= a la app.
    """
    scanner_html = """
    <style>
        #reader {
            width: 100%;
            max-width: 380px;
            margin: 0 auto;
            border: 2px solid #2563eb;
            border-radius: 8px;
            background-color: #f8fafc;
            overflow: hidden;
            box-sizing: border-box;
        }
        #reader button {
            background-color: #2563eb;
            color: #ffffff;
            border: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            margin: 4px;
        }
        #reader select {
            padding: 6px 10px;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            font-size: 14px;
            margin: 4px;
            max-width: 90%;
        }
        #reader a {
            display: none !important;
        }
    </style>

    <div id="reader"></div>
    <div id="scanner-feedback" style="text-align: center; margin-top: 6px; font-weight: 500; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 0.9rem; color: #1e40af;"></div>

    <script src="https://unpkg.com/html5-qrcode"></script>
    <script>
        const config = {
            fps: 15,
            qrbox: { width: 260, height: 105 },
            experimentalFeatures: {
                useBarCodeDetectorIfSupported: true
            },
            formatsToSupport: [
                Html5QrcodeSupportedFormats.EAN_13,
                Html5QrcodeSupportedFormats.EAN_8,
                Html5QrcodeSupportedFormats.UPC_A,
                Html5QrcodeSupportedFormats.UPC_E,
                Html5QrcodeSupportedFormats.CODE_128,
                Html5QrcodeSupportedFormats.QR_CODE
            ]
        };

        let isScanning = true;

        function enviarCodigoAApp(rawCode) {
            const codeClean = String(rawCode || "").trim();
            if (!codeClean) return;

            const targets = [];
            try { targets.push(window.top); } catch (e) {}
            try {
                if (window.parent && !targets.includes(window.parent)) {
                    targets.push(window.parent);
                }
            } catch (e) {}
            targets.push(window);

            for (const win of targets) {
                try {
                    const url = new URL(win.location.href);
                    url.searchParams.set("code", codeClean);
                    win.location.href = url.toString();
                    return;
                } catch (e) {}
            }
        }

        function onScanSuccess(decodedText, decodedResult) {
            if (isScanning && decodedText) {
                isScanning = false;
                const limpio = String(decodedText).trim();
                const feedbackEl = document.getElementById("scanner-feedback");
                if (feedbackEl) {
                    feedbackEl.innerHTML = "✅ Código detectado: " + limpio + " — enviando a registro...";
                }
                try {
                    html5QrcodeScanner.clear();
                } catch (e) {}
                enviarCodigoAApp(limpio);
            }
        }

        function onScanFailure(error) {
            // Ignorar caídas normales de fotograma mientras enfoca el código
        }

        const html5QrcodeScanner = new Html5QrcodeScanner(
            "reader",
            config,
            /* verbose= */ false
        );
        html5QrcodeScanner.render(onScanSuccess, onScanFailure);
    </script>
    """
    components.html(scanner_html, height=320)


def render_modulo_recepcion(res, usuario, sonido_activo):
    st.subheader("📥 Módulo de Recepción")

    modo = st.radio(
        "Método de captura:",
        ["📷 Cámara Móvil (1080p)", "⌨️ Entrada Manual / Lector"],
        horizontal=True,
        key="rec_cam_modo",
    )
    if modo == "📷 Cámara Móvil (1080p)":
        st.info("Apunta la cámara al código de barras o QR:")
        render_camera_scanner()
    else:
        with st.form("form_rec_manual_in"):
            code_in = st.text_input(
                "Código de barras o SKU:",
                placeholder="Ej: 7702001001015, SKU-1001, o nuevo",
            )
            submitted = st.form_submit_button(
                "⚡ Procesar Escaneo", type="primary", use_container_width=True
            )
            if submitted and code_in:
                st.query_params["code"] = code_in.strip()
                st.rerun()


def render_modulo_traslado(res, usuario, sonido_activo):
    st.subheader("🔄 Módulo de Traslado Interno")

    conn = get_connection()
    prods = pd.read_sql_query(
        """SELECT DISTINCT i.sku, p.nombre, i.ubicacion_qr, i.lote, i.cantidad 
           FROM inventario i LEFT JOIN productos p ON i.sku = p.sku WHERE i.cantidad > 0""",
        conn,
    )
    conn.close()

    if prods.empty:
        st.info("No hay inventario disponible para trasladar.")
        return

    with st.form("form_traslado_op"):
        opciones = [
            f"{row['sku']} - {row['nombre']} | Ubic: {row['ubicacion_qr']} | Lote: {row['lote']} (Disp: {row['cantidad']})"
            for _, row in prods.iterrows()
        ]
        seleccion = st.selectbox("Selecciona ítem a trasladar:", opciones)
        col1, col2 = st.columns(2)
        with col1:
            cant_traslado = st.number_input(
                "Cantidad a trasladar:", min_value=1, value=1, step=1
            )
        with col2:
            dest_ubic = st.text_input(
                "Ubicación destino (QR):", value="LOC-A01-N2", placeholder="Ej: LOC-A01-N1"
            )

        btn_trasladar = st.form_submit_button(
            "🔄 Confirmar Traslado", type="primary", use_container_width=True
        )
        if btn_trasladar and seleccion:
            idx = opciones.index(seleccion)
            item = prods.iloc[idx]
            sku = item["sku"]
            lote = item["lote"]
            orig_ub = item["ubicacion_qr"]
            cant_disp = int(item["cantidad"])

            if cant_traslado > cant_disp:
                st.error(
                    f"La cantidad ({cant_traslado}) supera lo disponible ({cant_disp})."
                )
            elif orig_ub == dest_ubic.strip().upper():
                st.warning("La ubicación de destino debe ser diferente al origen.")
            else:
                dest_ub = dest_ubic.strip().upper()
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """UPDATE inventario SET cantidad = cantidad - ? 
                       WHERE sku = ? AND lote = ? AND ubicacion_qr = ?""",
                    (int(cant_traslado), sku, lote, orig_ub),
                )
                dest_exist = cur.execute(
                    """SELECT id FROM inventario WHERE sku = ? AND lote = ? AND ubicacion_qr = ?""",
                    (sku, lote, dest_ub),
                ).fetchone()
                if dest_exist:
                    cur.execute(
                        """UPDATE inventario SET cantidad = cantidad + ? WHERE id = ?""",
                        (int(cant_traslado), dest_exist["id"]),
                    )
                else:
                    cur.execute(
                        """INSERT INTO inventario (sku, lote, ubicacion_qr, cantidad) VALUES (?, ?, ?, ?)""",
                        (sku, lote, dest_ub, int(cant_traslado)),
                    )
                conn.commit()
                conn.close()
                ScanEngine.log_event(
                    usuario,
                    "TRASLADO",
                    sku,
                    "PRODUCTO",
                    "OK",
                    f"Trasladadas {cant_traslado} UND de {orig_ub} a {dest_ub}",
                )
                ScanEngine.play_feedback_sound("OK", enabled=sonido_activo)
                st.success(f"✅ Trasladadas {cant_traslado} UND de {orig_ub} a {dest_ub}")
                st.rerun()