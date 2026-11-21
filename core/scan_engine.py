import time
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
from core.database import get_connection


class ScanEngine:
    """Motor central de escaneo Scan-First para NEXORA STOCK."""

    DEBOUNCE_SECONDS = 1.8  # Ventana anti-lectura duplicada accidental

    @staticmethod
    def play_feedback_sound(status: str, enabled: bool = True):
        """Emite retroalimentación sonora vía Web Audio API (sin archivos externos)."""
        if not enabled:
            return

        if status == "OK":
            # Beep agudo doble de confirmación
            js_code = """
            <script>
            (function() {
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(880, ctx.currentTime);
                    osc.frequency.setValueAtTime(1174.66, ctx.currentTime + 0.08);
                    gain.gain.setValueAtTime(0.25, ctx.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.22);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start();
                    osc.stop(ctx.currentTime + 0.22);
                } catch(e) {}
            })();
            </script>
            """
        else:
            # Tono grave de alerta / error / duplicado
            js_code = """
            <script>
            (function() {
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sawtooth';
                    osc.frequency.setValueAtTime(220, ctx.currentTime);
                    osc.frequency.setValueAtTime(165, ctx.currentTime + 0.15);
                    gain.gain.setValueAtTime(0.3, ctx.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start();
                    osc.stop(ctx.currentTime + 0.35);
                } catch(e) {}
            })();
            </script>
            """
        components.html(js_code, height=0, width=0)

    @staticmethod
    def classify_and_lookup(raw_code: str) -> dict:
        """
        Identifica el tipo de código escaneado y consulta su correspondencia en la BD.
        Retorna dict con: tipo, encontrado, data, codigo_limpio
        """
        code = raw_code.strip().upper()
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # 1. Código QR de Ubicación (Prefijo LOC-)
            if code.startswith("LOC-"):
                cursor.execute("SELECT * FROM ubicaciones WHERE codigo_qr = ?", (code,))
                row = cursor.fetchone()
                return {
                    "tipo": "UBICACION",
                    "encontrado": row is not None,
                    "data": dict(row) if row else None,
                    "codigo_limpio": code,
                }

            # 2. Código QR de Pedido (Prefijo PED-)
            if code.startswith("PED-"):
                cursor.execute("SELECT * FROM pedidos WHERE codigo_qr = ?", (code,))
                row = cursor.fetchone()
                return {
                    "tipo": "PEDIDO",
                    "encontrado": row is not None,
                    "data": dict(row) if row else None,
                    "codigo_limpio": code,
                }

            # 3. Código de Lote (Prefijo LOT-)
            if code.startswith("LOT-"):
                return {
                    "tipo": "LOTE",
                    "encontrado": True,
                    "data": {"lote": code},
                    "codigo_limpio": code,
                }

            # 4. Producto por SKU o Código de Barras Comercial
            cursor.execute(
                "SELECT * FROM productos WHERE sku = ? OR codigo_barras = ?",
                (code, code),
            )
            prod = cursor.fetchone()
            if prod:
                # Consultar existencias totales actuales
                cursor.execute(
                    "SELECT COALESCE(SUM(cantidad), 0) AS total FROM inventario WHERE sku = ?",
                    (prod["sku"],),
                )
                stock_total = cursor.fetchone()["total"]
                prod_dict = dict(prod)
                prod_dict["stock_total"] = stock_total
                return {
                    "tipo": "PRODUCTO",
                    "encontrado": True,
                    "data": prod_dict,
                    "codigo_limpio": code,
                }

            return {
                "tipo": "DESCONOCIDO",
                "encontrado": False,
                "data": None,
                "codigo_limpio": code,
            }
        finally:
            conn.close()

    @staticmethod
    def log_event(usuario: str, contexto: str, codigo: str, tipo: str, resultado: str, mensaje: str):
        """Registra obligatoriamente cada evento de escaneo en la base de datos."""
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO log_escaneos
                   (fecha_hora, usuario, contexto, codigo_leido, tipo_codigo, resultado, mensaje)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    usuario,
                    contexto,
                    codigo,
                    tipo,
                    resultado,
                    mensaje,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def process_scan(cls, raw_code: str, contexto: str, usuario: str, allow_duplicate: bool = False) -> dict:
        """
        Flujo central de 9 pasos del Scan Engine:
        Captura -> Anti-duplicados -> Clasificación -> Consulta BD -> Validación -> Auditoría -> Respuesta.
        """
        if not raw_code or not raw_code.strip():
            return {"status": "EMPTY", "mensaje": "Lectura vacía."}

        code = raw_code.strip().upper()
        now = time.time()

        # Control de lectura duplicada accidental
        last_code = st.session_state.get("last_scan_code")
        last_time = st.session_state.get("last_scan_time", 0.0)

        if not allow_duplicate and code == last_code and (now - last_time) < cls.DEBOUNCE_SECONDS:
            msg = f"Lectura duplicada bloqueada ({code}). Espera {cls.DEBOUNCE_SECONDS}s."
            cls.log_event(usuario, contexto, code, "DUPLICADO", "DUPLICADO", msg)
            return {
                "status": "DUPLICADO",
                "tipo": "DUPLICADO",
                "codigo": code,
                "data": None,
                "mensaje": msg,
            }

        # Actualizar marca de tiempo de última lectura válida
        st.session_state["last_scan_code"] = code
        st.session_state["last_scan_time"] = now

        # Clasificar y consultar en base de datos
        lookup = cls.classify_and_lookup(code)
        tipo = lookup["tipo"]

        if not lookup["encontrado"]:
            msg = f"Código no reconocido en el sistema: {code}"
            cls.log_event(usuario, contexto, code, tipo, "ERROR", msg)
            return {
                "status": "ERROR",
                "tipo": tipo,
                "codigo": code,
                "data": None,
                "mensaje": msg,
            }

        # Construcción de respuesta exitosa según el tipo detectado
        data = lookup["data"]
        if tipo == "PRODUCTO":
            msg = f"Producto identificado: {data['nombre']} ({data['sku']}) | Stock actual: {data['stock_total']} {data['unidad']}"
        elif tipo == "UBICACION":
            msg = f"Ubicación identificada: {data['codigo_qr']} ({data['zona']} - {data['pasillo']} - {data['nivel']})"
        elif tipo == "PEDIDO":
            msg = f"Pedido identificado: {data['codigo_qr']} | Cliente: {data['cliente']} | Estado: {data['estado']}"
        elif tipo == "LOTE":
            msg = f"Lote leído: {data['lote']}"
        else:
            msg = f"Código válido: {code}"

        cls.log_event(usuario, contexto, code, tipo, "OK", msg)
        return {
            "status": "OK",
            "tipo": tipo,
            "codigo": code,
            "data": data,
            "mensaje": msg,
        }
