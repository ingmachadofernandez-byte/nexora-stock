from __future__ import annotations
from typing import Optional
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from io import BytesIO
from PIL import Image, ImageOps
from core.database import get_connection
from core.scan_engine import ScanEngine

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False


def decodificar_imagen_automatica(image_bytes: bytes) -> Optional[str]:
    """
    Decodifica códigos de barras 1D/QR desde una foto capturada con el celular,
    probando rotaciones (0, 90, 180, 270) y mejora de contraste automático.
    """
    if not PYZBAR_AVAILABLE or not image_bytes:
        return None

    try:
        img = Image.open(BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("L")
        img_contrast = ImageOps.autocontrast(img)

        for base_img in (img, img_contrast):
            for angle in (0, 90, 180, 270):
                rotated = base_img.rotate(angle, expand=True) if angle else base_img
                results = pyzbar_decode(rotated)
                if results:
                    raw = results[0].data.decode("utf-8", errors="ignore").strip()
                    if raw:
                        return raw
    except Exception:
        return None

    return None


def registrar_ingreso_automatico(codigo: str, usuario: str, sonido_activo: bool, cantidad: int = 1, ubicacion: str = "LOC-REC-01", lote: str = "LOT-AUTO"):
    """
    Actualiza el inventario directamente en SQLite sin intervención humana:
    - Si el código/SKU existe en productos, suma cantidad en inventario.
    - Si no existe, crea el producto automáticamente y registra la entrada.
    """
    codigo_clean = str(codigo).strip()
    if not codigo_clean:
        return False, "Código vacío."

    conn = get_connection()
    cur = conn.cursor()

    # Buscar producto por código de barras o SKU
    prod = cur.execute(
        "SELECT sku, nombre FROM productos WHERE codigo_barras = ? OR sku = ?",
        (codigo_clean, codigo_clean),
    ).fetchone()

    if prod:
        sku = prod["sku"]
        nombre = prod["nombre"]
    else:
        sufijo = codigo_clean[-6:] if len(codigo_clean) >= 6 else codigo_clean
        sku = f"SKU-{sufijo}"
        nombre = f"Producto {codigo_clean}"
        cols = [c["name"] for c in cur.execute("PRAGMA table_info(productos)").fetchall()]
        if "categoria" in cols:
            cur.execute(
                """INSERT OR IGNORE INTO productos (sku, codigo_barras, nombre, categoria, unidad)
                   VALUES (?, ?, ?, ?, ?)""",
                (sku, codigo_clean, nombre, "General", "UND"),
            )
        else:
            cur.execute(
                """INSERT OR IGNORE INTO productos (sku, codigo_barras, nombre, unidad, requiere_lote)
                   VALUES (?, ?, ?, 'UND', 1)""",
                (sku, codigo_clean, nombre),
            )

    # Verificar si ya existe registro en inventario para ese SKU, lote y ubicación
    inv = cur.execute(
        """SELECT id, cantidad FROM inventario
           WHERE sku = ? AND lote = ? AND ubicacion_qr = ?""",
        (sku, lote, ubicacion),
    ).fetchone()

    if inv:
        nueva_cant = int(inv["cantidad"]) + int(cantidad)
        cur.execute(
            "UPDATE inventario SET cantidad = ? WHERE id = ?",
            (nueva_cant, inv["id"]),
        )
    else:
        nueva_cant = int(cantidad)
        cur.execute(
            """INSERT INTO inventario (sku, lote, ubicacion_qr, cantidad)
               VALUES (?, ?, ?, ?)""",
            (sku, lote, ubicacion, nueva_cant),
        )

    conn.commit()
    conn.close()

    ScanEngine.log_event(
        usuario,
        "RECEPCION_AUTO",
        sku,
        "PRODUCTO",
        "OK",
        f"Ingreso automático +{cantidad} UND ({codigo_clean}) en {ubicacion} | Total: {nueva_cant}",
    )
    ScanEngine.play_feedback_sound("OK", enabled=sonido_activo)
    return True, f"✅ Código {codigo_clean} ({nombre}) detectado y sumado (+{cantidad} UND) en {ubicacion}. Stock en ubicación: {nueva_cant} UND."


def render_camera_scanner():
    """
    Escáner de cámara en vivo (opcional/complementario) con Quagga2.
    """
    scanner_html = """
    <style>
        .scanner-wrap { max-width: 400px; margin: 0 auto; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
        .scanner-controls { display: flex; gap: 8px; justify-content: center; margin-bottom: 8px; }
        .scanner-btn { background-color: #2563eb; color: #fff; border: none; padding: 8px 14px; border-radius: 6px; font-size: 14px; cursor: pointer; }
        .scanner-btn.secondary { background-color: #475569; }
        #quagga-viewport { position: relative; width: 100%; height: 200px; border: 2px solid #2563eb; border-radius: 8px; background: #0f172a; overflow: hidden; }
        #quagga-viewport video, #quagga-viewport canvas { position: absolute; top: 0; left: 0; width: 100% !important; height: 100% !important; object-fit: cover; }
        #scanner-feedback { text-align: center; margin-top: 6px; font-weight: 600; font-size: 0.85rem; color: #1e40af; }
    </style>
    <div class="scanner-wrap">
        <div class="scanner-controls">
            <button type="button" class="scanner-btn" onclick="iniciarEscaner()">📷 Activar Video 1D</button>
            <button type="button" class="scanner-btn secondary" onclick="detenerEscaner()">⏹ Detener</button>
        </div>
        <div id="quagga-viewport"></div>
        <div id="scanner-feedback">Modo video continuo (opcional).</div>
    </div>
    <script src="https://unpkg.com/@ericblade/quagga2@1.8.4/dist/quagga.min.js"></script>
    <script>
        let escaneoActivo = false;
        let codigoYaEnviado = false;
        function setFeedback(msg, isOk = false) {
            const el = document.getElementById("scanner-feedback");
            if (el) { el.style.color = isOk ? "#15803d" : "#1e40af"; el.innerHTML = msg; }
        }
        function enviarCodigoAApp(rawCode) {
            if (codigoYaEnviado) return;
            const codeClean = String(rawCode || "").trim();
            if (!codeClean) return;
            codigoYaEnviado = true;
            for (const win of [window.top, window.parent, window]) {
                try {
                    const url = new URL(win.location.href);
                    url.searchParams.set("auto_code", codeClean);
                    win.location.href = url.toString();
                    return;
                } catch (e) {}
            }
        }
        function detenerEscaner() {
            escaneoActivo = false;
            try { if (window.Quagga) { Quagga.offDetected(onDetected); Quagga.stop(); } } catch (e) {}
            setFeedback("Video detenido.");
        }
        function onDetected(result) {
            if (!escaneoActivo || codigoYaEnviado) return;
            const code = result && result.codeResult && result.codeResult.code;
            if (!code) return;
            escaneoActivo = false;
            setFeedback("✅ Detectado: " + code, true);
            detenerEscaner();
            enviarCodigoAApp(code);
        }
        function iniciarEscaner() {
            if (!window.Quagga) { setFeedback("⚠️ Motor no cargado."); return; }
            detenerEscaner();
            codigoYaEnviado = false;
            escaneoActivo = true;
            Quagga.init({
                inputStream: { name: "Live", type: "LiveStream", target: document.querySelector("#quagga-viewport"), constraints: { facingMode: "environment" } },
                locator: { patchSize: "medium", halfSample: true },
                numOfWorkers: 2,
                decoder: { readers: ["ean_reader", "ean_8_reader", "code_128_reader", "upc_reader"] },
                locate: true
            }, function(err) {
                if (err) { escaneoActivo = false; setFeedback("⚠️ Error cámara: " + err); return; }
                Quagga.onDetected(onDetected);
                Quagga.start();
                setFeedback("Video activo: centra el código.");
            });
        }
    </script>
    """
    components.html(scanner_html, height=290)


def render_modulo_recepcion(res, usuario, sonido_activo):
    st.subheader("📥 Módulo de Recepción (Automático + Respaldo)")

    # Procesar si llegó un auto_code desde el escáner en vivo
    auto_code_param = st.query_params.get("auto_code")
    if auto_code_param and st.session_state.get("ultimo_auto_code") != auto_code_param:
        st.session_state["ultimo_auto_code"] = auto_code_param
        ok, msg = registrar_ingreso_automatico(auto_code_param, usuario, sonido_activo)
        if ok:
            st.success(msg)
        del st.query_params["auto_code"]

    modo = st.radio(
        "Método de captura:",
        [
            "📸 Foto Automática (Sin intervención)",
            "📷 Escáner Video en Vivo",
            "⌨️ Entrada Manual (Opcional)",
        ],
        horizontal=True,
        key="rec_cam_modo",
    )

    if modo == "📸 Foto Automática (Sin intervención)":
        st.info("Toma una foto nítida al código de barras. El sistema lo leerá y sumará +1 UND al inventario automáticamente.")
        foto = st.camera_input("Capturar código de barras", key="cam_auto_recepcion")

        if foto is not None:
            img_bytes = foto.getvalue()
            foto_hash = hash(img_bytes)

            if st.session_state.get("ultima_foto_procesada") != foto_hash:
                with st.spinner("Leyendo código y actualizando inventario automáticamente..."):
                    codigo_leido = decodificar_imagen_automatica(img_bytes)

                if codigo_leido:
                    st.session_state["ultima_foto_procesada"] = foto_hash
                    ok, msg = registrar_ingreso_automatico(codigo_leido, usuario, sonido_activo)
                    if ok:
                        st.success(msg)
                        st.balloons()
                else:
                    st.warning("⚠️ No se logró distinguir el código en esa foto. Acerca un poco más el código con buena luz y toma otra foto.")

    elif modo == "📷 Escáner Video en Vivo":
        st.info("Apunta horizontalmente al código de barras para captura y registro automático:")
        render_camera_scanner()

    else:
        with st.form("form_rec_manual_in"):
            code_in = st.text_input(
                "Código de barras o SKU:",
                placeholder="Ej: 7703889125705 o SKU-1001",
            )
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                cant_in = st.number_input("Cantidad:", min_value=1, value=1, step=1)
            with col_m2:
                ubic_in = st.text_input("Ubicación:", value="LOC-REC-01")

            submitted = st.form_submit_button(
                "⚡ Registrar en Inventario", type="primary", use_container_width=True
            )
            if submitted and code_in:
                ok, msg = registrar_ingreso_automatico(
                    code_in.strip(),
                    usuario,
                    sonido_activo,
                    cantidad=int(cant_in),
                    ubicacion=ubic_in.strip().upper() or "LOC-REC-01",
                )
                if ok:
                    st.success(msg)


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
