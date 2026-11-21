import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
try:
    from streamlit_qrcode_scanner import qrcode_scanner
except ImportError:
    from qrcode_scanner import qrcode_scanner

from core.database import init_db, get_connection
from core.scan_engine import ScanEngine

st.set_page_config(page_title="NEXORA STOCK | Scan Engine", page_icon="📦", layout="centered")
init_db()

def render_barcode_camera_scanner(key: str = "cam_scanner"):
    """
    Renderiza el escáner de cámara móvil de alta resolución (1080p)
    con configuración optimizada para códigos de barra (EAN-13, UPC, Code-128) y QR.
    """
    scanned_from_url = st.query_params.get("barcode_scanned")
    if scanned_from_url:
        del st.query_params["barcode_scanned"]
        return scanned_from_url

    scanner_html = """
    <div id="reader" style="width: 100%; max-width: 450px; margin: 0 auto; border-radius: 8px; overflow: hidden;"></div>
    <div id="scanner-feedback" style="text-align: center; margin-top: 6px; font-weight: 500; font-family: sans-serif; font-size: 0.9rem; color: #1e40af;"></div>
    <script src="https://unpkg.com/html5-qrcode"></script>
    <script>
        const config = {
            fps: 15,
            qrbox: { width: 300, height: 120 },
            aspectRatio: 1.777778,
            experimentalFeatures: {
                useBarCodeDetectorIfSupported: true // Usa el acelerador nativo de iPhone/Android/Chrome si está disponible
            },
            formatsToSupport: [
                Html5QrcodeSupportedFormats.EAN_13,
                Html5QrcodeSupportedFormats.EAN_8,
                Html5QrcodeSupportedFormats.UPC_A,
                Html5QrcodeSupportedFormats.CODE_128,
                Html5QrcodeSupportedFormats.QR_CODE
            ]
        };

        let isScanning = true;
        function onScanSuccess(decodedText, decodedResult) {
            if (isScanning && decodedText) {
                isScanning = false;
                document.getElementById('scanner-feedback').innerHTML = '✅ Código detectado: ' + decodedText;
                try {
                    const parentUrl = new URL(window.parent.location.href);
                    parentUrl.searchParams.set("barcode_scanned", decodedText);
                    window.parent.location.href = parentUrl.href;
                } catch(e) {
                    console.log("Escaneado:", decodedText);
                }
            }
        }

        const html5QrCode = new Html5Qrcode("reader");
        html5QrCode.start(
            { 
                facingMode: "environment",
                width: { min: 640, ideal: 1920 },
                height: { min: 480, ideal: 1080 }
            },
            config,
            onScanSuccess
        ).catch(err => {
            console.log("Iniciando fallback...");
        });
    </script>
    """
    components.html(scanner_html, height=350)

    # Soporte complementario mediante qrcode_scanner
    try:
        code = qrcode_scanner(key=key)
        if code:
            return code
    except Exception:
        pass

    return None

# Estado inicial de sesión operativa
if "usuario" not in st.session_state:
    st.session_state["usuario"] = "op1"
if "sonido_activo" not in st.session_state:
    st.session_state["sonido_activo"] = True
if "ultimo_resultado" not in st.session_state:
    st.session_state["ultimo_resultado"] = None

# Encabezado operativo compacto
st.title("📦 NEXORA STOCK")
st.caption("Motor Operativo Scan-First • Fase 2: Validación Central de Escaneo")

col_ctx, col_snd = st.columns([3, 1])
with col_ctx:
    contexto = st.selectbox(
        "Contexto Operativo Activo",
        ["CONSULTA / TEST", "RECEPCION", "PICKING", "VERIFICACION", "DESPACHO", "TRASLADO", "INVENTARIO"],
    )
with col_snd:
    st.session_state["sonido_activo"] = st.toggle("🔊 Sonido", value=st.session_state["sonido_activo"])

st.divider()

# Modo de captura: Lector Bluetooth/Rápido o Cámara Móvil
modo_lectura = st.radio(
    "Dispositivo de captura:",
    ["🔫 Lector Bluetooth / Teclado Rápido", "📷 Cámara Móvil (QR / Códigos)"],
    horizontal=True,
)

codigo_capturado = None

if modo_lectura == "🔫 Lector Bluetooth / Teclado Rápido":
    with st.form("form_scan_hid", clear_on_submit=True):
        entrada = st.text_input(
            "Escanea aquí (Lector Bluetooth o escribe un código de prueba y presiona Enter):",
            placeholder="Ej: 7702001001015, SKU-1001, LOC-A01-N1, PED-2026-001",
        )
        submitted = st.form_submit_button("⚡ Procesar Escaneo", use_container_width=True)
        if submitted and entrada:
            codigo_capturado = entrada
else:
    st.info("Apunta la cámara al código QR o código de barras:")
    qr_code = render_barcode_camera_scanner()
    if qr_code:
        codigo_capturado = qr_code

# Ejecutar Scan Engine si llegó un código
if codigo_capturado:
    resultado = ScanEngine.process_scan(
        raw_code=codigo_capturado,
        contexto=contexto,
        usuario=st.session_state["usuario"],
    )
    st.session_state["ultimo_resultado"] = resultado
    ScanEngine.play_feedback_sound(resultado["status"], enabled=st.session_state["sonido_activo"])

# Mostrar tarjeta de resultado inmediato
res = st.session_state["ultimo_resultado"]
if res:
    if res["status"] == "OK":
        st.success(f"✅ **[{res['tipo']}]** {res['mensaje']}")
        if res["data"]:
            st.json(res["data"])
    elif res["status"] == "DUPLICADO":
        st.warning(f"⚠️ **DUPLICADO:** {res['mensaje']}")
    else:
        st.error(f"❌ **ERROR:** {res['mensaje']}")

# Panel de códigos de prueba rápidos y log de auditoría
with st.expander("🧪 Códigos de prueba precargados en la BD"):
    st.markdown("""
    - **Productos (EAN-13 o SKU):** `7702001001015` (`SKU-1001`), `7702001001022` (`SKU-1002`), `7702001001039` (`SKU-1003`)
    - **Ubicaciones:** `LOC-A01-N1`, `LOC-A01-N2`, `LOC-REC-01`, `LOC-DES-01`
    - **Pedidos:** `PED-2026-001`
    - **Lotes:** `LOT-2026A`, `LOT-2026B`
    """)

with st.expander("📋 Auditoría en tiempo real (log_escaneos)", expanded=True):
    conn = get_connection()
    df_logs = pd.read_sql_query(
        "SELECT id, fecha_hora, usuario, contexto, codigo_leido, tipo_codigo, resultado, mensaje FROM log_escaneos ORDER BY id DESC LIMIT 10",
        conn,
    )
    conn.close()
    st.dataframe(df_logs, use_container_width=True, hide_index=True)
