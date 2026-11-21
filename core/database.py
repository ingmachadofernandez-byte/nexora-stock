import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join("data", "nexora_stock.db")

def get_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Usuarios / Operarios
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL CHECK(rol IN ('operario', 'supervisor', 'admin')),
        pin TEXT NOT NULL
    )
    """)

    # 2. Catálogo de Productos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS productos (
        sku TEXT PRIMARY KEY,
        codigo_barras TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        unidad TEXT DEFAULT 'UND',
        requiere_lote INTEGER DEFAULT 1
    )
    """)

    # 3. Ubicaciones de Bodega
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ubicaciones (
        codigo_qr TEXT PRIMARY KEY,
        zona TEXT NOT NULL,
        pasillo TEXT NOT NULL,
        nivel TEXT NOT NULL,
        descripcion TEXT
    )
    """)

    # 4. Inventario por Producto, Lote y Ubicación
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL,
        ubicacion_qr TEXT NOT NULL,
        lote TEXT DEFAULT 'SIN-LOTE',
        fecha_vencimiento TEXT,
        cantidad INTEGER NOT NULL DEFAULT 0,
        UNIQUE(sku, ubicacion_qr, lote),
        FOREIGN KEY (sku) REFERENCES productos(sku),
        FOREIGN KEY (ubicacion_qr) REFERENCES ubicaciones(codigo_qr)
    )
    """)

    # 5. Pedidos y Líneas de Picking
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        codigo_qr TEXT PRIMARY KEY,
        cliente TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'PENDIENTE',
        operario_asignado TEXT,
        fecha_creacion TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedido_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_qr TEXT NOT NULL,
        sku TEXT NOT NULL,
        ubicacion_sugerida TEXT NOT NULL,
        lote_sugerido TEXT,
        cantidad_solicitada INTEGER NOT NULL,
        cantidad_recogida INTEGER NOT NULL DEFAULT 0,
        cantidad_verificada INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (pedido_qr) REFERENCES pedidos(codigo_qr),
        FOREIGN KEY (sku) REFERENCES productos(sku)
    )
    """)

    # 6. Auditoría de Todos los Eventos de Escaneo (Regla Técnica #9)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS log_escaneos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_hora TEXT NOT NULL,
        usuario TEXT NOT NULL,
        contexto TEXT NOT NULL,
        codigo_leido TEXT NOT NULL,
        tipo_codigo TEXT NOT NULL,
        resultado TEXT NOT NULL,
        mensaje TEXT NOT NULL
    )
    """)

    conn.commit()
    seed_demo_data(conn)
    conn.close()

def seed_demo_data(conn):
    """Carga datos iniciales de prueba si la base está vacía."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM productos")
    if cursor.fetchone()[0] > 0:
        return

    # Usuarios demo
    cursor.executemany(
        "INSERT INTO usuarios (username, nombre, rol, pin) VALUES (?, ?, ?, ?)",
        [
            ("op1", "Carlos Operario", "operario", "1234"),
            ("sup1", "Norma Supervisora", "supervisor", "9999"),
        ]
    )

    # Ubicaciones demo (Prefijo LOC-)
    cursor.executemany(
        "INSERT INTO ubicaciones (codigo_qr, zona, pasillo, nivel, descripcion) VALUES (?, ?, ?, ?, ?)",
        [
            ("LOC-A01-N1", "Zona A", "Pasillo 01", "Nivel 1", "Estantería Alta Rotación"),
            ("LOC-A01-N2", "Zona A", "Pasillo 01", "Nivel 2", "Estantería Media Rotación"),
            ("LOC-REC-01", "Recepción", "Muelle 1", "Piso", "Zona de Descargue"),
            ("LOC-DES-01", "Despacho", "Muelle 2", "Piso", "Zona de Alistamiento Final"),
        ]
    )

    # Productos demo (Códigos de barras comerciales EAN-13 y SKU)
    cursor.executemany(
        "INSERT INTO productos (sku, codigo_barras, nombre, unidad, requiere_lote) VALUES (?, ?, ?, ?, ?)",
        [
            ("SKU-1001", "7702001001015", "Aceite Vegetal 1000ml", "BOT", 1),
            ("SKU-1002", "7702001001022", "Arroz Blanco Premium 5kg", "BOL", 1),
            ("SKU-1003", "7702001001039", "Café Molido Tradicional 500g", "PAQ", 1),
        ]
    )

    # Stock inicial demo
    cursor.executemany(
        "INSERT INTO inventario (sku, ubicacion_qr, lote, fecha_vencimiento, cantidad) VALUES (?, ?, ?, ?, ?)",
        [
            ("SKU-1001", "LOC-A01-N1", "LOT-2026A", "2027-05-30", 50),
            ("SKU-1002", "LOC-A01-N1", "LOT-2026B", "2027-08-15", 80),
            ("SKU-1003", "LOC-A01-N2", "LOT-2026C", "2027-03-10", 35),
        ]
    )

    # Pedido de prueba para Picking (Prefijo PED-)
    cursor.execute(
        "INSERT INTO pedidos (codigo_qr, cliente, estado, operario_asignado, fecha_creacion) VALUES (?, ?, ?, ?, ?)",
        ("PED-2026-001", "Supermercados El Valle", "PENDIENTE", "op1", datetime.now().isoformat())
    )
    cursor.executemany(
        """INSERT INTO pedido_items 
           (pedido_qr, sku, ubicacion_sugerida, lote_sugerido, cantidad_solicitada) 
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("PED-2026-001", "SKU-1001", "LOC-A01-N1", "LOT-2026A", 3),
            ("PED-2026-001", "SKU-1003", "LOC-A01-N2", "LOT-2026C", 2),
        ]
    )

    conn.commit()
