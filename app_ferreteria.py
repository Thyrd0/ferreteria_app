import streamlit as st
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fpdf import FPDF
import json

# Configuración de la página
st.set_page_config(
    page_title="Sistema Gestión Ferretería",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Conexión a PostgreSQL
@st.cache_resource
def init_connection():
    try:
        conn = psycopg2.connect(
            host=st.secrets["DB_HOST"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASSWORD"],
            port=st.secrets["DB_PORT"]
        )
        return conn
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None

conn = init_connection()

# Función para ejecutar consultas
def ejecutar_consulta(query, params=None):
    try:
        cur = conn.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        result = cur.fetchall()
        conn.commit()
        cur.close()
        return result
    except Exception as e:
        st.error(f"Error en consulta: {e}")
        return None

# Función para ejecutar procedimientos almacenados
def ejecutar_sp(sp_name, params=None):
    try:
        cur = conn.cursor()
        if params:
            cur.callproc(sp_name, params)
        else:
            cur.callproc(sp_name)
        result = cur.fetchall()
        conn.commit()
        cur.close()
        return result
    except Exception as e:
        st.error(f"Error ejecutando SP: {e}")
        return None

# Autenticación
def login():
    st.sidebar.title("🔐 Sistema de Ferretería")
    st.sidebar.markdown("---")

    username = st.sidebar.text_input("Usuario", value="admin")
    password = st.sidebar.text_input("Contraseña", type="password", value="admin123")

    if st.sidebar.button("🚀 Ingresar", use_container_width=True):
        user_data = ejecutar_consulta(
            """
            SELECT username, nombre, rol
            FROM usuarios
            WHERE username = %s AND password = %s AND activo = true
            """,
            (username, password)
        )
        if user_data:
            st.session_state.logged_in = True
            st.session_state.user = {
                "username": user_data[0][0],
                "nombre": user_data[0][1],
                "rol": user_data[0][2]
            }
            st.rerun()
        else:
            st.sidebar.error("❌ Usuario o contraseña incorrectos o inactivo")

# Dashboard principal
def dashboard():
    st.title("🏪 Dashboard - Sistema de Gestión de Ferretería")

    # Métricas del día
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        ventas_hoy = ejecutar_consulta("SELECT COALESCE(SUM(total), 0) FROM ventas WHERE fecha_venta::date = CURRENT_DATE")
        st.metric("💰 Ventas Hoy", f"${ventas_hoy[0][0]:,.2f}" if ventas_hoy else "$0")

    with col2:
        productos_total = ejecutar_consulta("SELECT COUNT(*) FROM productos WHERE activo = true")
        st.metric("📦 Productos", productos_total[0][0] if productos_total else 0)

    with col3:
        stock_bajo = ejecutar_sp("sp_productos_stock_bajo")
        st.metric("⚠️ Stock Bajo", len(stock_bajo) if stock_bajo else 0)

    with col4:
        clientes_total = ejecutar_consulta("SELECT COUNT(*) FROM clientes")
        st.metric("👥 Clientes", clientes_total[0][0] if clientes_total else 0)

    st.markdown("---")

    # Gráficos
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Productos por Categoría")
        cat_data = ejecutar_consulta("""
            SELECT c.nombre, COUNT(p.id)
            FROM categorias c
            LEFT JOIN productos p ON c.id = p.categoria_id
            GROUP BY c.nombre
        """)
        if cat_data:
            df_cat = pd.DataFrame(cat_data, columns=['Categoría', 'Cantidad'])
            fig = px.pie(df_cat, values='Cantidad', names='Categoría')
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📈 Ventas Últimos 7 Días")
        ventas_data = ejecutar_consulta("""
            SELECT fecha_venta::date as fecha, SUM(total) as total
            FROM ventas
            WHERE fecha_venta >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY fecha_venta::date
            ORDER BY fecha
        """)
        if ventas_data:
            df_ventas = pd.DataFrame(ventas_data, columns=['Fecha', 'Total'])
            fig = px.line(df_ventas, x='Fecha', y='Total', title='Ventas Diarias')
            st.plotly_chart(fig, use_container_width=True)

    # Productos con stock bajo
    st.subheader("⚠️ Productos con Stock Bajo")
    stock_bajo_data = ejecutar_sp("sp_productos_stock_bajo")
    if stock_bajo_data:
        df_stock = pd.DataFrame(stock_bajo_data, columns=['ID', 'Producto', 'Stock Actual', 'Stock Mínimo'])
        st.dataframe(df_stock, use_container_width=True)

# Módulo generar ticket venta
def generar_ticket(venta_id):
    # Obtener cabecera
    venta = ejecutar_consulta("""
        SELECT v.id, v.numero_factura, v.fecha_venta, v.total, 
               COALESCE(c.nombre,'Consumidor Final') as cliente, v.metodo_pago
        FROM ventas v
        LEFT JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = %s
    """, (venta_id,))

    # Obtener detalles
    detalles = ejecutar_consulta("""
        SELECT p.nombre, vd.cantidad, vd.precio
        FROM venta_detalles vd
        JOIN productos p ON vd.producto_id = p.id
        WHERE vd.venta_id = %s
    """, (venta_id,))

    # Crear PDF
    pdf = FPDF("P", "mm", (80, 200))  # ancho tipo ticket
    pdf.add_page()
    pdf.set_font("Courier", "B", 12)

    # Encabezado
    pdf.cell(60, 5, "FERRETERIA 'COMPRA Y PAGA'", ln=True, align="C")
    pdf.set_font("Courier", "", 10)
    pdf.cell(60, 5, "Av. Principal 123", ln=True, align="C")
    pdf.cell(60, 5, "RUC: 123456789", ln=True, align="C")
    pdf.ln(5)

    # Datos factura
    pdf.set_font("Courier", "", 9)
    pdf.cell(60, 5, f"Factura: {venta[0][1]}", ln=True)
    pdf.cell(60, 5, f"Fecha: {venta[0][2].strftime('%d/%m/%Y %H:%M')}", ln=True)
    pdf.cell(60, 5, f"Cliente: {venta[0][4]}", ln=True)
    pdf.cell(60, 5, f"Metodo: {venta[0][5]}", ln=True)
    pdf.ln(3)

    # Línea divisoria
    pdf.cell(60, 5, "-"*32, ln=True, align="C")

    # Detalles productos
    pdf.set_font("Courier", "B", 9)
    pdf.cell(25, 5, "Producto", border=0)
    pdf.cell(10, 5, "Cant", border=0, align="R")
    pdf.cell(15, 5, "Precio", border=0, align="R")
    pdf.cell(15, 5, "Total", border=0, align="R")
    pdf.ln(5)

    pdf.set_font("Courier", "", 9)
    for d in detalles:
        nombre, cant, precio = d
        subtotal = cant * precio
        pdf.cell(25, 5, nombre[:12], border=0)  # cortar nombre largo
        pdf.cell(10, 5, str(cant), border=0, align="R")
        pdf.cell(15, 5, f"{precio:.2f}", border=0, align="R")
        pdf.cell(15, 5, f"{subtotal:.2f}", border=0, align="R")
        pdf.ln(5)

    # Línea divisoria
    pdf.cell(60, 5, "-"*32, ln=True, align="C")

    # Total
    pdf.set_font("Courier", "B", 10)
    pdf.cell(50, 5, "TOTAL", border=0, align="R")
    pdf.cell(15, 5, f"{venta[0][3]:.2f}", border=0, align="R")
    pdf.ln(10)

    # Mensaje final
    pdf.set_font("Courier", "", 9)
    pdf.cell(60, 5, "Gracias por su compra!", ln=True, align="C")
    pdf.cell(60, 5, "Vuelva pronto", ln=True, align="C")

    return pdf.output(dest="S").encode("latin-1")

# Módulo de productos
def modulo_productos():
    st.title("📦 Gestión de Productos")

    if "mensaje_exito" in st.session_state:
      st.success(st.session_state.mensaje_exito)
      del st.session_state.mensaje_exito

    tab1, tab2, tab3 = st.tabs(["Lista de Productos", "Agregar Producto", "Inventario"])

    with tab1:
        st.subheader("Lista de Productos")
        productos = ejecutar_sp("sp_obtener_productos")
        if productos:
            df = pd.DataFrame(productos, columns=['ID', 'Código', 'Nombre', 'Categoría', 'Precio', 'Stock'])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No hay productos registrados")

    with tab2:
        st.subheader("Agregar Nuevo Producto")

        with st.form("form_producto"):
            col1, col2 = st.columns(2)

            with col1:
                nombre = st.text_input("Nombre del Producto*")
                descripcion = st.text_area("Descripción")
                categorias = ejecutar_consulta("SELECT id, nombre FROM categorias")
                categoria_opts = {cat[1]: cat[0] for cat in categorias} if categorias else {}
                categoria = st.selectbox("Categoría", options=list(categoria_opts.keys()))

            with col2:
                marca = st.text_input("Marca")
                precio_compra = st.number_input("Precio Compra", min_value=0.0, step=0.1)
                precio_venta = st.number_input("Precio Venta*", min_value=0.0, step=0.1)
                stock = st.number_input("Stock Inicial", min_value=0, value=0)
                stock_minimo = st.number_input("Stock Mínimo", min_value=1, value=5)

            if st.form_submit_button("💾 Guardar Producto"):
                if nombre and precio_venta > 0:
                    categoria_id = categoria_opts.get(categoria)
                    ejecutar_consulta("""
                        INSERT INTO productos (nombre, descripcion, categoria_id, marca,
                                             precio_compra, precio_venta, stock_actual, stock_minimo)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (nombre, descripcion, categoria_id, marca, precio_compra, precio_venta, stock, stock_minimo))
                    #st.success("✅ Producto creado exitosamente")
                    st.session_state.mensaje_exito = "✅ Producto creado exitosamente"
                    st.rerun()
                else:
                    st.error("❌ Nombre y precio de venta son obligatorios")

    #with tab3:
        #st.subheader("Control de Inventario")
        # Aquí puedes agregar funcionalidad para ajustes de inventario

# Módulo de ventas
def modulo_ventas():
    st.title("💰 Módulo de Ventas")

    if "mensaje_exito" in st.session_state:
      st.success(st.session_state.mensaje_exito)
      del st.session_state.mensaje_exito  # se borra después de mostrarlo

    if "carrito" not in st.session_state:
        st.session_state.carrito = []

    # Obtener productos activos
    productos = ejecutar_consulta("""
        SELECT id, nombre, precio_venta, stock_actual
        FROM productos
        WHERE activo = true AND stock_actual > 0
        ORDER BY nombre
    """)

    if not productos:
        st.warning("No hay productos disponibles para la venta")
        return

    col1, col2 = st.columns(2)
    with col1:
        producto_sel = st.selectbox(
            "Seleccionar Producto",
            [f"{p[0]} - {p[1]} - ${p[2]} (Stock: {p[3]})" for p in productos]
        )
    with col2:
        cantidad = st.number_input("Cantidad", min_value=1, value=1)

    if st.button("➕ Agregar al Carrito"):
        prod_id = int(producto_sel.split('-')[0].strip())
        nombre = producto_sel.split('-')[1].strip()
        precio = float(producto_sel.split('$')[1].split(' ')[0])
        st.session_state.carrito.append({
            "producto_id": prod_id,
            "nombre": nombre,
            "precio": precio,
            "cantidad": cantidad
        })
        st.success(f"{nombre} agregado al carrito")

    if st.session_state.carrito:
        df_carrito = pd.DataFrame(st.session_state.carrito)
        df_carrito['Subtotal'] = df_carrito['precio'] * df_carrito['cantidad']
        st.dataframe(df_carrito, use_container_width=True)
        total = df_carrito['Subtotal'].sum()
        st.metric("Total", f"${total:,.2f}")

        metodo_pago = st.selectbox("Método de Pago", ["Efectivo", "Tarjeta", "Transferencia"])
        cliente_id = st.number_input("ID Cliente", min_value=1, value=1)

        if st.button("💳 Procesar Venta"):
            try:
                detalles_json = json.dumps(st.session_state.carrito)
                resultado = ejecutar_sp("sp_registrar_venta", (detalles_json, cliente_id, 1, metodo_pago))
                if resultado:
                    venta_id = resultado[0][0]
                    total_venta = resultado[0][2]
                    st.success(f"✅ Venta procesada! Total: ${total_venta:,.2f}")

                    pdf_data = generar_ticket(venta_id)
                    st.download_button("📥 Descargar Ticket", pdf_data, "ticket.pdf", "application/pdf")

                    st.session_state.carrito = []
                else:
                    st.error("❌ No se pudo registrar la venta")
            except Exception as e:
                st.error(f"Ocurrió un error: {e}")



# Celda: Módulo de Gestión de Clientes (agregar al archivo app_ferreteria.py)
def modulo_clientes():
    st.title("👥 Gestión de Clientes")

    tab1, tab2, tab3, tab4 = st.tabs(["Lista de Clientes", "Agregar Cliente", "Editar Cliente", "Historial de Compras"])

    with tab1:
        st.subheader("📋 Lista de Clientes Registrados")

        # Búsqueda y filtros
        col1, col2 = st.columns([2, 1])
        with col1:
            buscar_cliente = st.text_input("🔍 Buscar cliente por nombre o cédula")
        with col2:
            ordenar_por = st.selectbox("Ordenar por", ["Nombre", "Fecha Registro", "Compras Recientes"])

        # Obtener clientes con filtros
        query = """
            SELECT id, cedula, nombre, telefono, email,
                   direccion, fecha_registro,
                   (SELECT COUNT(*) FROM ventas WHERE cliente_id = clientes.id) as total_compras,
                   (SELECT COALESCE(SUM(total), 0) FROM ventas WHERE cliente_id = clientes.id) as monto_total
            FROM clientes
            WHERE 1=1
        """
        params = []

        if buscar_cliente:
            query += " AND (nombre ILIKE %s OR cedula ILIKE %s)"
            params.extend([f"%{buscar_cliente}%", f"%{buscar_cliente}%"])

        if ordenar_por == "Nombre":
            query += " ORDER BY nombre"
        elif ordenar_por == "Fecha Registro":
            query += " ORDER BY fecha_registro DESC"
        else:
            query += " ORDER BY (SELECT MAX(fecha_venta) FROM ventas WHERE cliente_id = clientes.id) DESC NULLS LAST"

        clientes = ejecutar_consulta(query, params) if params else ejecutar_consulta(query)

        if clientes:
            df_clientes = pd.DataFrame(clientes, columns=[
                'ID', 'Cédula', 'Nombre', 'Teléfono', 'Email',
                'Dirección', 'Fecha Registro', 'Total Compras', 'Monto Total'
            ])

            # Formatear fechas
            df_clientes['Fecha Registro'] = pd.to_datetime(df_clientes['Fecha Registro']).dt.strftime('%Y-%m-%d %H:%M')

            # Mostrar dataframe con estilo
            st.dataframe(
                df_clientes,
                column_config={
                    "Monto Total": st.column_config.NumberColumn(
                        "Monto Total",
                        format="$%.2f",
                    ),
                    "Total Compras": st.column_config.NumberColumn(
                        "Total Compras",
                        format="%d compras",
                    )
                },
                use_container_width=True,
                hide_index=True
            )

            # Estadísticas rápidas
            st.subheader("📊 Estadísticas de Clientes")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Clientes", len(clientes))
            with col2:
                clientes_compras = sum(1 for c in clientes if c[7] > 0)
                st.metric("Clientes con Compras", clientes_compras)
            with col3:
                promedio_compras = df_clientes['Monto Total'].mean() if not df_clientes.empty else 0
                st.metric("Promedio por Cliente", f"${promedio_compras:,.2f}")

        else:
            st.info("No hay clientes registrados")

    with tab2:
        st.subheader("➕ Agregar Nuevo Cliente")

        with st.form("form_cliente_nuevo"):
            col1, col2 = st.columns(2)

            with col1:
                cedula = st.text_input("Cédula/RUC*", max_chars=13)
                nombre = st.text_input("Nombre Completo*", max_chars=100)
                telefono = st.text_input("Teléfono", max_chars=15)

            with col2:
                email = st.text_input("Email", max_chars=100)
                direccion = st.text_area("Dirección", max_chars=200)

            if st.form_submit_button("💾 Guardar Cliente", use_container_width=True):
                if cedula and nombre:
                    # Verificar si la cédula ya existe
                    existe = ejecutar_consulta("SELECT id FROM clientes WHERE cedula = %s", (cedula,))
                    if existe:
                        st.error("❌ Ya existe un cliente con esta cédula")
                    else:
                        ejecutar_consulta("""
                            INSERT INTO clientes (cedula, nombre, telefono, email, direccion)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (cedula, nombre, telefono, email, direccion))
                        st.success("✅ Cliente registrado exitosamente")
                        st.rerun()
                else:
                    st.error("❌ Cédula y Nombre son obligatorios")

    with tab3:
        st.subheader("✏️ Editar Información de Cliente")

        # Seleccionar cliente a editar
        clientes_lista = ejecutar_consulta("SELECT id, cedula, nombre FROM clientes ORDER BY nombre")
        if clientes_lista:
            cliente_opts = {f"{c[1]} - {c[2]}": c[0] for c in clientes_lista}
            cliente_seleccionado = st.selectbox("Seleccionar Cliente", options=list(cliente_opts.keys()))

            if cliente_seleccionado:
                cliente_id = cliente_opts[cliente_seleccionado]
                cliente_data = ejecutar_consulta("SELECT * FROM clientes WHERE id = %s", (cliente_id,))

                if cliente_data:
                    with st.form("form_editar_cliente"):
                        col1, col2 = st.columns(2)

                        with col1:
                            cedula_edit = st.text_input("Cédula", value=cliente_data[0][1], max_chars=13)
                            nombre_edit = st.text_input("Nombre", value=cliente_data[0][2], max_chars=100)
                            telefono_edit = st.text_input("Teléfono", value=cliente_data[0][3] or "", max_chars=15)

                        with col2:
                            email_edit = st.text_input("Email", value=cliente_data[0][4] or "", max_chars=100)
                            direccion_edit = st.text_area("Dirección", value=cliente_data[0][5] or "", max_chars=200)

                        if st.form_submit_button("💾 Actualizar Cliente", use_container_width=True):
                            ejecutar_consulta("""
                                UPDATE clientes
                                SET cedula = %s, nombre = %s, telefono = %s,
                                    email = %s, direccion = %s
                                WHERE id = %s
                            """, (cedula_edit, nombre_edit, telefono_edit, email_edit, direccion_edit, cliente_id))
                            st.success("✅ Cliente actualizado exitosamente")
                            st.rerun()
        else:
            st.info("No hay clientes registrados para editar")

    with tab4:
        st.subheader("📋 Historial de Compras por Cliente")

        clientes_compras = ejecutar_consulta("""
            SELECT id, cedula, nombre FROM clientes
            WHERE id IN (SELECT DISTINCT cliente_id FROM ventas WHERE cliente_id IS NOT NULL)
            ORDER BY nombre
        """)

        if clientes_compras:
            cliente_hist_opts = {f"{c[1]} - {c[2]}": c[0] for c in clientes_compras}
            cliente_hist = st.selectbox("Seleccionar Cliente para ver historial", options=list(cliente_hist_opts.keys()))

            if cliente_hist:
                cliente_id_hist = cliente_hist_opts[cliente_hist]

                # Obtener historial de compras
                compras = ejecutar_consulta("""
                    SELECT v.id, v.numero_factura, v.fecha_venta, v.total, v.metodo_pago,
                           COUNT(vd.id) as items,
                           STRING_AGG(p.nombre, ', ') as productos
                    FROM ventas v
                    LEFT JOIN venta_detalles vd ON v.id = vd.venta_id
                    LEFT JOIN productos p ON vd.producto_id = p.id
                    WHERE v.cliente_id = %s
                    GROUP BY v.id, v.numero_factura, v.fecha_venta, v.total, v.metodo_pago
                    ORDER BY v.fecha_venta DESC
                """, (cliente_id_hist,))

                if compras:
                    df_compras = pd.DataFrame(compras, columns=[
                        'ID', 'Factura', 'Fecha', 'Total', 'Método Pago', 'Items', 'Productos'
                    ])
                    df_compras['Fecha'] = pd.to_datetime(df_compras['Fecha']).dt.strftime('%Y-%m-%d %H:%M')

                    # Estadísticas del cliente
                    total_gastado = df_compras['Total'].sum()
                    total_compras = len(compras)
                    promedio_compra = total_gastado / total_compras if total_compras > 0 else 0

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total Gastado", f"${total_gastado:,.2f}")
                    col2.metric("Total Compras", total_compras)
                    col3.metric("Promedio por Compra", f"${promedio_compra:,.2f}")

                    st.dataframe(
                        df_compras,
                        column_config={
                            "Total": st.column_config.NumberColumn(format="$%.2f"),
                            "Productos": st.column_config.TextColumn(width="large")
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    # Gráfico de compras por mes
                    st.subheader("📈 Compras por Mes")
                    compras_mes = ejecutar_consulta("""
                        SELECT DATE_TRUNC('month', fecha_venta) as mes,
                               COUNT(*) as num_compras,
                               SUM(total) as total_mes
                        FROM ventas
                        WHERE cliente_id = %s
                        GROUP BY DATE_TRUNC('month', fecha_venta)
                        ORDER BY mes
                    """, (cliente_id_hist,))

                    if compras_mes:
                        df_mes = pd.DataFrame(compras_mes, columns=['Mes', 'Número Compras', 'Total Mes'])
                        df_mes['Mes'] = pd.to_datetime(df_mes['Mes']).dt.strftime('%Y-%m')

                        fig = make_subplots(specs=[[{"secondary_y": True}]])
                        fig.add_trace(
                            go.Bar(x=df_mes['Mes'], y=df_mes['Número Compras'], name="Número de Compras"),
                            secondary_y=False,
                        )
                        fig.add_trace(
                            go.Scatter(x=df_mes['Mes'], y=df_mes['Total Mes'], name="Total Gastado", mode='lines+markers'),
                            secondary_y=True,
                        )
                        fig.update_layout(title_text="Evolución de Compras")
                        fig.update_xaxes(title_text="Mes")
                        fig.update_yaxes(title_text="Número de Compras", secondary_y=False)
                        fig.update_yaxes(title_text="Total Gastado ($)", secondary_y=True)

                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Este cliente no tiene compras registradas")
        else:
            st.info("No hay clientes con historial de compras")

# Celda: Módulo de Reportes (agregar al archivo app_ferreteria.py)
def modulo_reportes():
    st.title("📊 Reportes Avanzados")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Dashboard Ejecutivo",
        "💰 Ventas",
        "📦 Inventario",
        "👥 Clientes",
        "📋 Personalizados"
    ])

    with tab1:
        st.subheader("📈 Dashboard Ejecutivo")

        # Selector de rango de fechas
        col1, col2 = st.columns(2)
        with col1:
            fecha_inicio = st.date_input("Fecha Inicio", value=pd.to_datetime("today") - pd.DateOffset(months=1))
        with col2:
            fecha_fin = st.date_input("Fecha Fin", value=pd.to_datetime("today"))

        if st.button("🔄 Generar Reporte", use_container_width=True):
            # Métricas principales
            metricas = ejecutar_consulta("""
                SELECT
                    COUNT(*) as total_ventas,
                    COALESCE(SUM(total), 0) as total_ingresos,
                    COALESCE(AVG(total), 0) as promedio_venta,
                    COUNT(DISTINCT cliente_id) as clientes_activos
                FROM ventas
                WHERE fecha_venta::date BETWEEN %s AND %s
            """, (fecha_inicio, fecha_fin))

            if metricas:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Ventas", metricas[0][0])
                col2.metric("Ingresos Totales", f"${metricas[0][1]:,.2f}")
                col3.metric("Promedio por Venta", f"${metricas[0][2]:,.2f}")
                col4.metric("Clientes Activos", metricas[0][3])

            # Gráfico de ventas por día
            ventas_dia = ejecutar_consulta("""
                SELECT fecha_venta::date as fecha, SUM(total) as total_dia
                FROM ventas
                WHERE fecha_venta::date BETWEEN %s AND %s
                GROUP BY fecha_venta::date
                ORDER BY fecha
            """, (fecha_inicio, fecha_fin))

            if ventas_dia:
                df_ventas_dia = pd.DataFrame(ventas_dia, columns=['Fecha', 'Total'])
                fig = px.line(df_ventas_dia, x='Fecha', y='Total', title='Ventas Diarias')
                st.plotly_chart(fig, use_container_width=True)

            # Top 5 productos más vendidos
            top_productos = ejecutar_consulta("""
                SELECT p.nombre, SUM(vd.cantidad) as total_vendido, SUM(vd.cantidad * vd.precio) as ingresos
                FROM venta_detalles vd
                JOIN productos p ON vd.producto_id = p.id
                JOIN ventas v ON vd.venta_id = v.id
                WHERE v.fecha_venta::date BETWEEN %s AND %s
                GROUP BY p.nombre
                ORDER BY total_vendido DESC
                LIMIT 5
            """, (fecha_inicio, fecha_fin))

            if top_productos:
                st.subheader("🏆 Top 5 Productos Más Vendidos")
                df_top = pd.DataFrame(top_productos, columns=['Producto', 'Cantidad', 'Ingresos'])
                fig = px.bar(df_top, x='Producto', y='Cantidad', title='Cantidad Vendida por Producto')
                st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("💰 Reportes de Ventas")

        reporte_tipo = st.radio("Tipo de Reporte", [
            "Ventas por Período",
            "Ventas por Método de Pago",
            "Ventas por Vendedor"
        ])

        col1, col2 = st.columns(2)
        with col1:
            fecha_inicio_ventas = st.date_input("Fecha Inicio Ventas", value=pd.to_datetime("today") - pd.DateOffset(months=1))
        with col2:
            fecha_fin_ventas = st.date_input("Fecha Fin Ventas", value=pd.to_datetime("today"))

        if st.button("📊 Generar Reporte Ventas", use_container_width=True):
            if reporte_tipo == "Ventas por Período":
                datos = ejecutar_consulta("""
                    SELECT fecha_venta::date as fecha,
                           COUNT(*) as numero_ventas,
                           SUM(total) as total_ventas,
                           AVG(total) as promedio_venta
                    FROM ventas
                    WHERE fecha_venta::date BETWEEN %s AND %s
                    GROUP BY fecha_venta::date
                    ORDER BY fecha
                """, (fecha_inicio_ventas, fecha_fin_ventas))

                if datos:
                    df = pd.DataFrame(datos, columns=['Fecha', 'Número Ventas', 'Total Ventas', 'Promedio Venta'])
                    st.dataframe(df, use_container_width=True)

                    # Exportar a CSV
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "📥 Descargar CSV",
                        csv,
                        "reporte_ventas_periodo.csv",
                        "text/csv",
                        use_container_width=True
                    )

            elif reporte_tipo == "Ventas por Método de Pago":
                datos = ejecutar_consulta("""
                    SELECT metodo_pago,
                           COUNT(*) as numero_ventas,
                           SUM(total) as total_ventas
                    FROM ventas
                    WHERE fecha_venta::date BETWEEN %s AND %s
                    GROUP BY metodo_pago
                    ORDER BY total_ventas DESC
                """, (fecha_inicio_ventas, fecha_fin_ventas))

                if datos:
                    df = pd.DataFrame(datos, columns=['Método Pago', 'Número Ventas', 'Total Ventas'])
                    fig = px.pie(df, values='Total Ventas', names='Método Pago', title='Distribución por Método de Pago')
                    st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("📦 Reportes de Inventario")

        st.subheader("Valorización de Inventario")
        inventario_valor = ejecutar_consulta("""
            SELECT
                SUM(stock_actual * precio_compra) as valor_costo,
                SUM(stock_actual * precio_venta) as valor_venta,
                COUNT(*) as total_productos,
                SUM(CASE WHEN stock_actual <= stock_minimo THEN 1 ELSE 0 END) as productos_stock_bajo
            FROM productos
            WHERE activo = true
        """)

        if inventario_valor:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Valor al Costo", f"${inventario_valor[0][0]:,.2f}")
            col2.metric("Valor al Precio Venta", f"${inventario_valor[0][1]:,.2f}")
            col3.metric("Total Productos", inventario_valor[0][2])
            col4.metric("Productos Stock Bajo", inventario_valor[0][3])

        st.subheader("Rotación de Productos")
        rotacion = ejecutar_consulta("""
            SELECT p.nombre,
                   p.stock_actual,
                   COALESCE(SUM(vd.cantidad), 0) as vendidos_30dias,
                   CASE WHEN p.stock_actual > 0
                        THEN COALESCE(SUM(vd.cantidad), 0) / p.stock_actual
                        ELSE 0 END as indice_rotacion
            FROM productos p
            LEFT JOIN venta_detalles vd ON p.id = vd.producto_id
            LEFT JOIN ventas v ON vd.venta_id = v.id AND v.fecha_venta >= NOW() - INTERVAL '30 days'
            WHERE p.activo = true
            GROUP BY p.id, p.nombre, p.stock_actual
            ORDER BY indice_rotacion DESC
            LIMIT 10
        """)

        if rotacion:
            df_rotacion = pd.DataFrame(rotacion, columns=['Producto', 'Stock', 'Vendidos 30d', 'Índice Rotación'])
            st.dataframe(df_rotacion, use_container_width=True)

    with tab4:
        st.subheader("👥 Reportes de Clientes")

        # Clientes más valiosos
        clientes_top = ejecutar_consulta("""
            SELECT c.nombre, c.cedula, c.telefono,
                   COUNT(v.id) as total_compras,
                   SUM(v.total) as total_gastado,
                   MAX(v.fecha_venta) as ultima_compra
            FROM clientes c
            JOIN ventas v ON c.id = v.cliente_id
            GROUP BY c.id, c.nombre, c.cedula, c.telefono
            ORDER BY total_gastado DESC
            LIMIT 10
        """)

        if clientes_top:
            st.subheader("🏆 Top 10 Clientes Más Valiosos")
            df_clientes_top = pd.DataFrame(clientes_top, columns=[
                'Nombre', 'Cédula', 'Teléfono', 'Total Compras', 'Total Gastado', 'Última Compra'
            ])
            st.dataframe(df_clientes_top, use_container_width=True)

        # Frecuencia de compra
        st.subheader("📅 Frecuencia de Compra por Cliente")
        frecuencia = ejecutar_consulta("""
            SELECT c.nombre,
                   COUNT(v.id) as total_compras,
                   MIN(v.fecha_venta) as primera_compra,
                   MAX(v.fecha_venta) as ultima_compra,
                   (MAX(v.fecha_venta) - MIN(v.fecha_venta)) / COUNT(v.id) as frecuencia_promedio
            FROM clientes c
            JOIN ventas v ON c.id = v.cliente_id
            GROUP BY c.id, c.nombre
            HAVING COUNT(v.id) > 1
            ORDER BY frecuencia_promedio
            LIMIT 10
        """)

        if frecuencia:
            df_frecuencia = pd.DataFrame(frecuencia, columns=[
                'Nombre', 'Total Compras', 'Primera Compra', 'Última Compra', 'Frecuencia Promedio'
            ])
            st.dataframe(df_frecuencia, use_container_width=True)

    with tab5:
        st.subheader("📋 Reportes Personalizados")

        st.info("""
        **Genera reportes personalizados ejecutando consultas SQL directamente.**
        ⚠️ Solo para usuarios administradores con conocimiento de la estructura de la base de datos.
        """)

        if st.session_state.user['rol'] == 'admin':
            query_personalizada = st.text_area("Escribe tu consulta SQL:", height=100,
                                              placeholder="SELECT * FROM ventas WHERE fecha_venta >= CURRENT_DATE - INTERVAL '7 days'")

            if st.button("▶️ Ejecutar Consulta", use_container_width=True):
                if query_personalizada:
                    try:
                        resultado = ejecutar_consulta(query_personalizada)
                        if resultado:
                            df_resultado = pd.DataFrame(resultado)
                            st.dataframe(df_resultado, use_container_width=True)

                            # Opciones de exportación
                            col1, col2 = st.columns(2)
                            with col1:
                                csv = df_resultado.to_csv(index=False)
                                st.download_button(
                                    "📥 Descargar CSV",
                                    csv,
                                    "reporte_personalizado.csv",
                                    "text/csv",
                                    use_container_width=True
                                )
                            with col2:
                                excel_buffer = io.BytesIO()
                                df_resultado.to_excel(excel_buffer, index=False)
                                st.download_button(
                                    "📊 Descargar Excel",
                                    excel_buffer.getvalue(),
                                    "reporte_personalizado.xlsx",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    use_container_width=True
                                )
                        else:
                            st.info("La consulta no devolvió resultados")
                    except Exception as e:
                        st.error(f"Error en la consulta: {e}")
                else:
                    st.warning("Por favor, escribe una consulta SQL")
        else:
            st.warning("❌ Solo los administradores pueden ejecutar consultas personalizadas")

# Modulo perfil de usuario
def perfil_usuario():
    st.title("👤 Mi Perfil")
    user = st.session_state.user

    st.subheader("Información del Usuario")
    st.write(f"**Usuario:** {user['username']}")
    st.write(f"**Nombre:** {user['nombre']}")
    st.write(f"**Rol:** {user['rol']}")

    with st.form("form_editar_perfil"):
        nuevo_nombre = st.text_input("Nombre", value=user['nombre'])
        nuevo_email = st.text_input("Email", value=user.get('email', ""))
        nueva_password = st.text_input("Nueva Contraseña", type="password")

        if st.form_submit_button("💾 Actualizar Perfil"):
            ejecutar_consulta("""
                UPDATE usuarios
                SET nombre = %s, email = %s, password = COALESCE(NULLIF(%s,''), password)
                WHERE username = %s
            """, (nuevo_nombre, nuevo_email, nueva_password, user['username']))
            st.success("✅ Perfil actualizado exitosamente")
            st.session_state.user['nombre'] = nuevo_nombre
            st.session_state.user['email'] = nuevo_email

# Navegación principal con roles
def main():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        login()
    else:
        st.sidebar.title(f"👋 Hola, {st.session_state.user['nombre']}")
        st.sidebar.markdown(f"**Rol:** {st.session_state.user['rol']}")
        st.sidebar.markdown("---")

        rol = st.session_state.user['rol']

        # Menú dinámico según rol
        if rol == "admin":
            menu = st.sidebar.selectbox(
                "📋 Navegación",
                ["Dashboard", "Productos", "Ventas", "Clientes", "Reportes", "Perfil"]
            )
        elif rol == "vendedor":
            menu = st.sidebar.selectbox(
                "📋 Navegación",
                ["Ventas", "Clientes", "Perfil"]
            )
        elif rol == "inventarista":
            menu = st.sidebar.selectbox(
                "📋 Navegación",
                ["Productos", "Perfil"]
            )
        else:
            st.error("🚫 Rol no reconocido")
            return

        # Cargar módulos según menú y permisos
        if menu == "Dashboard":
            if rol == "admin":
                dashboard()
            else:
                st.error("🚫 No tienes permiso para acceder al Dashboard")

        elif menu == "Productos":
            if rol in ["admin", "inventarista"]:
                modulo_productos()
            else:
                st.error("🚫 No tienes permiso para gestionar productos")

        elif menu == "Ventas":
            if rol in ["admin", "vendedor"]:
                modulo_ventas()
            else:
                st.error("🚫 No tienes permiso para procesar ventas")

        elif menu == "Clientes":
            if rol in ["admin", "vendedor"]:
                modulo_clientes()
            else:
                st.error("🚫 No tienes permiso para gestionar clientes")

        elif menu == "Reportes":
            if rol == "admin":
                modulo_reportes()
            else:
                st.error("🚫 Solo el administrador puede ver reportes")

        elif menu == "Perfil":
            perfil_usuario()

        st.sidebar.markdown("---")
        if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state.logged_in = False
            st.rerun()

if __name__ == "__main__":
    main()
