import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from core.database import get_connection
from core.scan_engine import ScanEngine


def render_camera_scanner():
    """
    Escáner de cámara móvil con Quagga2 especializado en códigos de barras 1D
    (EAN-13, CODE-128, UPC) para iPhone / Safari / Chrome.
    """
    scanner_html = """
    <style>
        .scanner-wrap {
            max-width: 400px;
            margin: 0 auto;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        }
        .scanner-controls {
            display: flex;
            gap: 8px;
            justify-content: center;
            margin-bottom: 8px;
        }
        .scanner-btn {
            background-color: #2563eb;
            color: #ffffff;
            border: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
        }
        .scanner-btn.secondary {
            background-color: #475569;
        }
        #quagga-viewport {
            position: relative;
            width: 100%;
            height: 220px;
            border: 2px solid #2563eb;
            border-radius: 8px;
            background-color: #0f172a;
            overflow: hidden;
            box-sizing: border-box;
        }
        #quagga-viewport video,
        #quagga-viewport canvas {
            position: absolute;
            top: 0;
            left: 0;
            width: 100% !important;
            height: 100% !important;
            object-fit: cover;
        }
        #scanner-feedback {
            text-align: center;
            margin-top: 8px;
            font-weight: 600;
            font-size: 0.9rem;
            color: #1e40af;
            min-height: 20px;
        }
    </style>

    <div class="scanner-wrap">
        <div class="scanner-controls">
            <button type="button" id="btn-start-scan" class="scanner-btn" onclick="iniciarEscaner()">📷 Activar Cámara 1D</button>
            <button type="button" id="btn-stop-scan" class="scanner-btn secondary" onclick="detenerEscaner()">⏹ Detener</button>
        </div>
        <div id="quagga-viewport"></div>
        <div id="scanner-feedback">Pulsa "Activar Cámara 1D" y enfoca el código de barras horizontalmente.</div>
    </div>

    <script src="https://unpkg.com/@ericblade/quagga2@1.8.4/dist/quagga.min.js"></script>
    <script>
        let escaneoActivo = false;
        let codigoYaEnviado = false;

        function setFeedback(msg, isOk = false) {
            const el = document.getElementById("scanner-feedback");
            if (!el) return;
            el.style.color = isOk ? "#15803d" : "#1e40af";
            el.innerHTML = msg;
        }

        function enviarCodigoAApp(rawCode) {
            if (codigoYaEnviado) return;
            const codeClean = String(rawCode || "").trim();
            if (!codeClean) return;
            codigoYaEnviado = true;

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

        function detenerEscaner() {
            escaneoActivo = false;
            try {
                if (window.Quagga) {
                    Quagga.offDetected(onDetected);
                    Quagga.stop();
                }
            } catch (e) {}
            setFeedback("Cámara detenida.");
        }

        function onDetected(result) {
            if (!escaneoActivo || codigoYaEnviado) return;
            const code = result && result.codeResult && result.codeResult.code;
            if (!code) return;

            escaneoActivo = false;
            setFeedback("✅ Código detectado: " + code + " — enviando a registro...", true);
            detenerEscaner();
            enviarCodigoAApp(code);
        }

        function iniciarEscaner() {
            if (!window.Quagga) {
                setFeedback("⚠️ No cargó el motor Quagga2. Revisa la conexión o usa Entrada Manual.");
                return;
            }
            detenerEscaner();
            codigoYaEnviado = false;
            escaneoActivo = true;
            setFeedback("Iniciando cámara trasera...");

            Quagga.init({
                inputStream: {
                    name: "Live",
                    type: "LiveStream",
                    target: document.querySelector("#quagga-viewport"),
                    constraints: {
                        facingMode: "environment",
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    }
                },
                locator: {
                    patchSize: "medium",
                    halfSample: true
                },
                numOfWorkers: 2,
                decoder: {
                    readers: [
                        "ean_reader",
                        "ean_8_reader",
                        "code_128_reader",
                        "upc_reader",
                        "upc_e_reader"
                    ]
                },
                locate: true
            }, function(err) {
                if (err) {
                    escaneoActivo = false;
                    setFeedback("⚠️ No se pudo iniciar la cámara: " + (err.message || err));
                    return;
                }
                Quagga.onDetected(onDetected);
                Quagga.start();
                setFeedback("Cámara activa: alinea el código de barras de forma horizontal.");
            });
        }
    </script>
    """
    components.html(scanner_html, height=320)


def render_modulo_recepcion(res, usuario, sonido_activo):
    st.subheader("📥 Módulo de Recepción")

    modo = st.radio(
        "Método de captura:",
        ["📷 Cámara Móvil (1D)", "⌨️ Entrada Manual / Lector"],
        horizontal=True,
        key="rec_cam_modo",
    )
    if modo == "📷 Cámara Móvil (1D)":
        st.info("Activa la cámara y apunta horizontalmente al código de barras:")
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
