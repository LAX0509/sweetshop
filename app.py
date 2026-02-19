import os
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

app = Flask(__name__)
app.secret_key = "v&v_super_secret_key"

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///local.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    stock = Column(Integer, nullable=False, default=0)
    img = Column(String(500), nullable=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    cliente = Column(String(120), nullable=False)
    direccion = Column(String(250), nullable=False)
    telefono = Column(String(30), nullable=False)
    correo = Column(String(200), nullable=False)
    productos = Column(String(2000), nullable=False)
    total = Column(Float, nullable=False, default=0.0)
    status = Column(String(80), nullable=False, default="Pendiente de Envío")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

def init_db_and_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        has_any = db.query(Product).first()
        if not has_any:
            db.add_all(
                [
                    Product(
                        name="Gomitas de Oso",
                        price=5.0,
                        stock=10,
                        img="https://cdn-icons-png.flaticon.com/512/819/819058.png",
                    ),
                    Product(
                        name="Chocolates Premium",
                        price=12.0,
                        stock=5,
                        img="https://cdn-icons-png.flaticon.com/512/2619/2619554.png",
                    ),
                    Product(
                        name="Caramelos Ácidos",
                        price=3.5,
                        stock=20,
                        img="https://cdn-icons-png.flaticon.com/512/1043/1043440.png",
                    ),
                ]
            )
            db.commit()
    finally:
        db.close()

@app.before_first_request
def _startup():
    init_db_and_seed()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            flash("Inicia sesión para acceder.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def luhn_ok(card_digits: str) -> bool:
    total = 0
    rev = card_digits[::-1]
    for i, ch in enumerate(rev):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

@app.route("/")
def index():
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.id.asc()).all()
        return render_template("index.html", products=products)
    finally:
        db.close()

@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    p_id = request.form.get("id")
    qty_raw = request.form.get("quantity", "1")

    try:
        p_id_int = int(p_id)
        qty = int(qty_raw)
    except (TypeError, ValueError):
        flash("Datos inválidos.", "danger")
        return redirect(url_for("index"))

    if qty < 1:
        flash("La cantidad debe ser mayor a 0.", "danger")
        return redirect(url_for("index"))

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == p_id_int).first()
        if not product:
            flash("Producto no encontrado.", "danger")
            return redirect(url_for("index"))

        cart = session.get("cart", {})
        already = int(cart.get(str(p_id_int), 0))
        new_total = already + qty

        if new_total > product.stock:
            flash("Stock insuficiente.", "danger")
            return redirect(url_for("index"))

        cart[str(p_id_int)] = new_total
        session["cart"] = cart
        session.modified = True
        flash(f"¡{product.name} añadido!", "success")
        return redirect(url_for("index"))
    finally:
        db.close()

@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    items = []
    total = 0.0

    if not cart_data:
        return render_template("cart.html", items=[], total=0.0)

    ids = []
    for p_id_str in cart_data.keys():
        try:
            ids.append(int(p_id_str))
        except ValueError:
            pass

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        by_id = {p.id: p for p in products}

        for p_id_str, qty in cart_data.items():
            try:
                p_id_int = int(p_id_str)
                qty_int = int(qty)
            except (TypeError, ValueError):
                continue

            p = by_id.get(p_id_int)
            if not p:
                continue

            subtotal = float(p.price) * qty_int
            total += subtotal
            items.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "price": float(p.price),
                    "qty": qty_int,
                    "subtotal": subtotal,
                    "img": p.img or "",
                }
            )

        return render_template("cart.html", items=items, total=total)
    finally:
        db.close()

@app.route("/remove_item/<p_id>")
def remove_item(p_id):
    cart = session.get("cart", {})
    if p_id in cart:
        cart.pop(p_id)
        session["cart"] = cart
        session.modified = True
        flash("Producto eliminado", "info")
    return redirect(url_for("cart"))

@app.route("/remove_one/<p_id>")
def remove_one(p_id):
    cart = session.get("cart", {})
    if p_id in cart:
        if int(cart[p_id]) > 1:
            cart[p_id] = int(cart[p_id]) - 1
        else:
            cart.pop(p_id)
        session["cart"] = cart
        session.modified = True
        flash("Se quitó una unidad.", "info")
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["POST"])
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("El carrito está vacío. ¡Añade algo antes de pagar!", "danger")
        return redirect(url_for("index"))

    nombre = (request.form.get("nombre") or "").strip()
    direccion = (request.form.get("direccion") or "").strip()
    telefono = only_digits(request.form.get("telefono") or "")
    correo = (request.form.get("correo") or "").strip()
    tarjeta = only_digits(request.form.get("tarjeta") or "")
    cvv = only_digits(request.form.get("cvv") or "")
    exp = (request.form.get("exp") or "").strip()

    if not nombre or not direccion:
        flash("Nombre y dirección son obligatorios.", "danger")
        return redirect(url_for("cart"))

    if not re.fullmatch(r"\d{7,15}", telefono):
        flash("Teléfono inválido. Solo números.", "danger")
        return redirect(url_for("cart"))

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", correo):
        flash("Correo inválido.", "danger")
        return redirect(url_for("cart"))

    if not re.fullmatch(r"\d{16}", tarjeta):
        flash("Número de tarjeta inválido.", "danger")
        return redirect(url_for("cart"))

    if not luhn_ok(tarjeta):
        flash("Tarjeta inválida.", "danger")
        return redirect(url_for("cart"))

    if not re.fullmatch(r"\d{3,4}", cvv):
        flash("CVV inválido.", "danger")
        return redirect(url_for("cart"))

    if not re.fullmatch(r"(0[1-9]|1[0-2])\/\d{2}", exp):
        flash("Expiración inválida. Usa MM/AA.", "danger")
        return redirect(url_for("cart"))

    db = SessionLocal()
    try:
        order_id = None
        total_pedido = 0.0
        items_comprados = []

        for p_id_str, qty in cart_data.items():
            try:
                p_id_int = int(p_id_str)
                qty_int = int(qty)
            except (TypeError, ValueError):
                continue

            p = db.query(Product).filter(Product.id == p_id_int).with_for_update().first()
            if not p:
                continue

            if qty_int > p.stock:
                flash(f"Stock insuficiente para {p.name}.", "danger")
                return redirect(url_for("cart"))

            total_pedido += float(p.price) * qty_int
            items_comprados.append(f"{p.name} (x{qty_int})")
            p.stock -= qty_int

        new_order = Order(
            cliente=nombre,
            direccion=direccion,
            telefono=telefono,
            correo=correo,
            productos=", ".join(items_comprados),
            total=total_pedido,
            status="Pendiente de Envío",
        )
        db.add(new_order)
        db.commit()
        order_id = new_order.id

        session.pop("cart", None)
        flash(f"¡Gracias {nombre}! Tu pedido #{order_id} ha sido procesado.", "success")
        return redirect(url_for("index"))
    finally:
        db.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "admin" and request.form.get("password") == "1234":
            session["user"] = "admin"
            return redirect(url_for("admin_panel"))
        flash("Error de acceso", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

@app.route("/admin")
@login_required
def admin_panel():
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.id.asc()).all()
        orders = db.query(Order).order_by(Order.id.desc()).all()
        return render_template("admin.html", products=products, orders=orders)
    finally:
        db.close()

@app.route("/admin/product/new", methods=["GET", "POST"])
@login_required
def admin_new_product():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        price_raw = (request.form.get("price") or "").strip()
        stock_raw = (request.form.get("stock") or "").strip()
        img = (request.form.get("img") or "").strip()

        if not name:
            flash("Nombre requerido.", "danger")
            return redirect(url_for("admin_new_product"))

        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            flash("Precio o stock inválido.", "danger")
            return redirect(url_for("admin_new_product"))

        if price < 0 or stock < 0:
            flash("Precio y stock deben ser >= 0.", "danger")
            return redirect(url_for("admin_new_product"))

        db = SessionLocal()
        try:
            p = Product(
                name=name,
                price=price,
                stock=stock,
                img=img or "https://cdn-icons-png.flaticon.com/512/3081/3081559.png",
            )
            db.add(p)
            db.commit()
            flash("Producto creado.", "success")
            return redirect(url_for("admin_panel"))
        finally:
            db.close()

    return render_template("admin_product_form.html", mode="new", product=None)

@app.route("/admin/product/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_product(product_id):
    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            flash("Producto no encontrado.", "danger")
            return redirect(url_for("admin_panel"))

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            price_raw = (request.form.get("price") or "").strip()
            stock_raw = (request.form.get("stock") or "").strip()
            img = (request.form.get("img") or "").strip()

            if not name:
                flash("Nombre requerido.", "danger")
                return redirect(url_for("admin_edit_product", product_id=product_id))

            try:
                price = float(price_raw)
                stock = int(stock_raw)
            except ValueError:
                flash("Precio o stock inválido.", "danger")
                return redirect(url_for("admin_edit_product", product_id=product_id))

            if price < 0 or stock < 0:
                flash("Precio y stock deben ser >= 0.", "danger")
                return redirect(url_for("admin_edit_product", product_id=product_id))

            p.name = name
            p.price = price
            p.stock = stock
            p.img = img or p.img

            db.commit()
            flash("Producto actualizado.", "success")
            return redirect(url_for("admin_panel"))

        return render_template("admin_product_form.html", mode="edit", product=p)
    finally:
        db.close()

@app.route("/admin/product/<int:product_id>/delete", methods=["POST"])
@login_required
def admin_delete_product(product_id):
    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            flash("Producto no encontrado.", "danger")
            return redirect(url_for("admin_panel"))

        db.delete(p)
        db.commit()
        flash("Producto eliminado.", "info")
        return redirect(url_for("admin_panel"))
    finally:
        db.close()

@app.route("/admin/product/<int:product_id>/stock", methods=["POST"])
@login_required
def admin_adjust_stock(product_id):
    delta_raw = (request.form.get("delta") or "").strip()
    try:
        delta = int(delta_raw)
    except ValueError:
        flash("Cambio de stock inválido.", "danger")
        return redirect(url_for("admin_panel"))

    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            flash("Producto no encontrado.", "danger")
            return redirect(url_for("admin_panel"))

        new_stock = int(p.stock) + delta
        if new_stock < 0:
            flash("El stock no puede quedar en negativo.", "danger")
            return redirect(url_for("admin_panel"))

        p.stock = new_stock
        db.commit()
        flash("Stock actualizado.", "success")
        return redirect(url_for("admin_panel"))
    finally:
        db.close()

@app.route("/admin/order/<int:order_id>/status", methods=["POST"])
@login_required
def admin_update_order_status(order_id):
    new_status = (request.form.get("status") or "").strip()
    allowed = ["Pendiente de Envío", "En preparación", "Enviado", "Entregado", "Cancelado"]
    if new_status not in allowed:
        flash("Estado inválido.", "danger")
        return redirect(url_for("admin_panel"))

    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        if not o:
            flash("Pedido no encontrado.", "danger")
            return redirect(url_for("admin_panel"))

        o.status = new_status
        db.commit()
        flash("Estado actualizado.", "success")
        return redirect(url_for("admin_panel"))
    finally:
        db.close()

if __name__ == "__main__":
    app.run()

