from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

from core.database import get_connection

try:
    import gspread
    from google.oauth2.service_account import Credentials

    GSPREAD_AVAILABLE = True
except Exception:
    GSPREAD_AVAILABLE = False


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_SPREADSHEET_ID = "1MPonaYaN7H5_TC3YHkgzFSnHPau0o4oGc0Jk7Pfcl2g"


def _get_spreadsheet():
    if not GSPREAD_AVAILABLE:
        return None, "Falta instalar gspread o google-auth en requirements.txt."

    if "gcp_service_account" not in st.secrets:
        return None, "Falta 'gcp_service_account' en Streamlit Secrets."

    spreadsheet_id = str(
        st.secrets.get("spreadsheet_id") or DEFAULT_SPREADSHEET_ID
    ).strip()
    if not spreadsheet_id:
        return None, "Falta 'spreadsheet_id' en Streamlit Secrets."

    sa_info = dict(st.secrets["gcp_service_account"])
    if "private_key" in sa_info and isinstance(sa_info["private_key"], str):
        sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(spreadsheet_id), None


def _get_or_create_worksheet(spreadsheet, title: str, headers: list[str]):
    try:
        ws = spreadsheet.worksheet(title)
    except Exception:
        ws = spreadsheet.add_worksheet(
            title=title,
            rows=1000,
            cols=max(10, len(headers) + 2),
        )

    existing = ws.get_all_values()
    if not existing:
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


def sincronizar_movimiento_a_sheets(
    usuario: str,
    tipo_movimiento: str,
    sku: str,
    ubicacion: str,
    lote: str,
    cantidad: int,
    detalle: str = "",
) -> tuple[bool, str]:
    try:
        spreadsheet, err = _get_spreadsheet()
        if err or spreadsheet is None:
            msg = err or "No se pudo abrir la hoja de Google Sheets."
            print(f"[SHEETS_SYNC] {msg}")
            return False, msg

        conn = get_connection()
        try:
            df_inv = pd.read_sql_query(
                """
                SELECT
                    i.ubicacion_qr AS Ubicacion,
                    i.sku AS SKU,
                    COALESCE(p.nombre, '') AS Producto,
                    i.lote AS Lote,
                    COALESCE(CAST(i.fecha_vencimiento AS TEXT), 'None') AS Vencimiento,
                    COALESCE(i.cantidad, 0) AS Cantidad
                FROM inventario i
                LEFT JOIN productos p ON i.sku = p.sku
                ORDER BY i.id DESC
                """,
                conn,
            )
        finally:
            conn.close()

        inv_headers = ["Ubicacion", "SKU", "Producto", "Lote", "Vencimiento", "Cantidad"]
        ws_inv = _get_or_create_worksheet(spreadsheet, "Inventario_Actual", inv_headers)

        rows_inv = [inv_headers]
        if not df_inv.empty:
            for _, r in df_inv.iterrows():
                rows_inv.append([
                    str(r["Ubicacion"] or ""),
                    str(r["SKU"] or ""),
                    str(r["Producto"] or ""),
                    str(r["Lote"] or ""),
                    str(r["Vencimiento"] or "None"),
                    int(r["Cantidad"] or 0),
                ])

        ws_inv.clear()
        ws_inv.update(values=rows_inv, range_name="A1", value_input_option="USER_ENTERED")

        mov_headers = [
            "Fecha_Hora",
            "Usuario",
            "Tipo_Movimiento",
            "SKU",
            "Ubicacion",
            "Lote",
            "Cantidad",
            "Detalle",
        ]
        ws_mov = _get_or_create_worksheet(spreadsheet, "Movimientos", mov_headers)
        ahora = datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d %H:%M:%S")
        ws_mov.append_row(
            [
                ahora,
                str(usuario or ""),
                str(tipo_movimiento or ""),
                str(sku or ""),
                str(ubicacion or ""),
                str(lote or ""),
                int(cantidad),
                str(detalle or ""),
            ],
            value_input_option="USER_ENTERED",
        )

        return True, "Sincronizado con Google Sheets."
    except Exception as exc:
        msg = f"Error al sincronizar con Google Sheets: {exc}"
        print(f"[SHEETS_SYNC] {msg}")
        return False, msg