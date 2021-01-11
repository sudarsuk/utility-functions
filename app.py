import json
import logging
import time
import yaml

import flask as x

import models as db
import utils as fn

# Configuration
logging.root.level = logging.INFO

app = x.Flask(__name__, static_folder="site--%s/static" % fn.config["site"])
app.secret_key = fn.config["secret_key"]
app.logger = logging.root
app.jinja_options = {
    "line_comment_prefix": "#:",
    "extensions": ["jinja2.ext.autoescape", "jinja2.ext.with_", "jinja2.ext.loopcontrols"],
}

product_list = fn.config["product_list"]
product_dict = {p["code"]: p for p in product_list}


@app.before_request
def before_request():
    if "order_id" in x.session and not x.session.get("order_id"):
        x.session.pop("order_id")


@app.context_processor
def context_processor():
    return {
        "vendor": fn.config["vendor"],
        "logo_url": fn.config["logo_url"],
        "phone_number": fn.config["phone_number"],
        "account_name": fn.config["account_name"],
        "account_bank": fn.config["account_bank"],
        "account_number": fn.config["account_number"],

        "json": json,
        "fmt_price": fn.fmt_price,
        "product_list": product_list,
        "product_dict": product_dict,

        "relative": fn.relative,
        "order_total": fn.order_total,
        "shipping_is_free": fn.shipping_is_free,
        "get_order_code": fn.get_order_code,
    }


# main
@app.route("/", methods=["GET", "POST"])
def index():
    global product_list

    if "new" in x.request.args:
        x.session.pop("order_id", "")
        return x.redirect("/")

    if "edit" not in x.request.args and "order_id" in x.session:
        return x.redirect("/confirm")

    if x.request.method == "POST":
        data = fn.get_order_data(product_list, x.request.form)
        if not data:
            return x.redirect("/")

        if x.session.get("order_id"):
            order = db.Order.get_by_id(x.session["order_id"])
            order.data_json = json.dumps(data)
            order.status = "CREATED"
            order.save()
        else:
            order = db.Order.create(
                data_json=json.dumps(data),
                status="CREATED",
            )

        x.session["order_id"] = order.id
        return x.redirect("/confirm")

    return x.render_template("index.html", product_list=product_list, **locals())


@app.route("/confirm", methods=["GET", "POST"])
def confirm():
    if not x.session.get("order_id"):
        return x.redirect("/")

    order = db.Order.get_by_id(x.session["order_id"])
    order_data = json.loads(order.data_json)

    if order.status in ["PAID", "FINISHED"]:
        return x.redirect("/?new")

    if order.status == "CONFIRMED" and "edit" not in x.request.args:
        return x.redirect("/thanks")

    if x.request.method == "POST":
        order.name = x.request.form.get("name")
        order.phone = x.request.form.get("phone")
        order.address = x.request.form.get("address")
        order.status = "CONFIRMED"
        order.save()

        return x.redirect("/thanks")

    return x.render_template("confirm.html", **locals())


@app.route("/thanks")
def thanks():
    if not x.session.get("order_id"):
        return x.redirect("/")

    order = db.Order.get_by_id(x.session["order_id"])
    order_data = json.loads(order.data_json)

    if order.status in ["PAID", "FINISHED"]:
        return x.redirect("/?new")

    return x.render_template("thanks.html", **locals())


# admin
@app.route("/admin", methods=["GET", "POST"])
def admin():
    # logout
    if "out" in x.request.args:
        x.session.pop("admin_logged", "")
        return x.redirect("/admin")

    # POST: login
    if x.request.method == "POST" and x.request.form["action"] == "login":
        if x.request.form["password"] == fn.config["admin_password"]:
            x.session["admin_logged"] = int(time.time())
            return x.redirect("/admin")

        return x.render_template("login.html", error=True)
    # endfold

    # check login
    if time.time() - x.session.get("admin_logged", 0) > 24 * 3600:
        return x.render_template("login.html")

    # POST: mark_as_paid
    if x.request.method == "POST" and x.request.form["action"] == "mark_as_paid":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        order.status = "PAID"
        order.save()

        return x.redirect("/admin")

    # POST: mark_as_unpaid
    if x.request.method == "POST" and x.request.form["action"] == "mark_as_unpaid":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        order.status = "CONFIRMED"
        order.save()

        return x.redirect("/admin")
    # endfold

    confirmed_order_list = db.Order.select()\
        .where(db.Order.status == "CONFIRMED")\
        .order_by(db.Order.created_at.desc())

    paid_order_list = db.Order.select()\
        .where(db.Order.status == "PAID")\
        .order_by(db.Order.created_at.desc())

    return x.render_template("admin/admin.html", **locals())


@app.route("/admin/archive", methods=["GET", "POST"])
def admin_archive():
    # check login
    if time.time() - x.session.get("admin_logged", 0) > 24 * 3600:
        return x.redirect("/admin")

    # POST: delete
    if x.request.method == "POST" and x.request.form["action"] == "delete":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        if order.status == "FINISHED":
            order.status = "DELETED"
            order.save()

        return x.redirect("/admin/archive")

    # POST: undelete
    if x.request.method == "POST" and x.request.form["action"] == "undelete":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        if order.status == "DELETED":
            order.status = "FINISHED"
            order.save()

        return x.redirect("/admin/archive?trash")
    # endfold

    if x.request.query_string.decode() == "trash":
        deleted_order_list = db.Order.select()\
            .where(db.Order.status == "DELETED")\
            .order_by(db.Order.created_at.desc())
    elif x.request.query_string.decode() == "inventory":
        finished_order_list = db.Order.select()\
            .where(db.Order.status == "FINISHED")\
            .order_by(db.Order.created_at.desc())
        count_dict = {}
        total_dict = {}
        for o in finished_order_list:
            for e in json.loads(o.data_json):
                count_dict[e["code"]] = count_dict.get(e["code"], 0) + e["count"]
                total_dict[e["code"]] = total_dict.get(e["code"], 0) + e["count"] * e["price"]
    else:
        finished_order_list = db.Order.select()\
            .where(db.Order.status == "FINISHED")\
            .order_by(db.Order.created_at.desc())

        total = sum(fn.order_total(json.loads(o.data_json)) for o in finished_order_list)

    return x.render_template("admin/admin-archive.html", **locals())


# manager
@app.route("/manager", methods=["GET", "POST"])
def manager():
    # GET: ?out
    if "out" in x.request.args:
        x.session.pop("manager_logged", "")
        return x.redirect("/manager")
    # endfold

    # POST: login
    if x.request.method == "POST" and x.request.form["action"] == "login":
        if x.request.form["password"] == "Manager-Tagtaa":
            x.session["manager_logged"] = int(time.time())
            return x.redirect("/manager")

        return x.render_template("login.html", error=True, profile="manager")
    # endfold

    # check login
    if time.time() - x.session.get("manager_logged", 0) > 24 * 3600:
        return x.render_template("login.html", profile="manager")

    # GET: ?export
    if "export" in x.request.args:
        paid_order_list = db.Order.select()\
            .where(db.Order.status == "PAID")\
            .order_by(db.Order.created_at.desc())

        data = []
        for o in paid_order_list:
            data.append([o.name, o.phone, o.address])

        headers = {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": "attachment; filename=order-tagtaa.xlsx",
        }

        return x.make_response(fn.get_xlsx(data), 200, headers)
    # endfold

    # POST: mark_as_finished
    if x.request.method == "POST" and x.request.form["action"] == "mark_as_finished":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        assert order.status == "PAID"
        order.status = "FINISHED"
        order.save()

        return x.redirect("/manager")

    # POST: mark_as_unfinished
    if x.request.method == "POST" and x.request.form["action"] == "mark_as_unfinished":
        order_id = int(x.request.form.get("order_id"))
        order = db.Order.get_by_id(order_id)
        assert order.status == "FINISHED"
        order.status = "PAID"
        order.save()

        return x.redirect("/manager")
    # endfold

    confirmed_order_list = db.Order.select()\
        .where(db.Order.status == "CONFIRMED")\
        .order_by(db.Order.created_at.desc())

    paid_order_list = db.Order.select()\
        .where(db.Order.status == "PAID")\
        .order_by(db.Order.created_at.desc())

    finished_order_list = db.Order.select()\
        .where(db.Order.status == "FINISHED")\
        .order_by(db.Order.created_at.desc())\
        .limit(30)

    return x.render_template("admin/manager.html", **locals())


# static
@app.route("/favicon.ico")
def favicon_ico():
    return x.send_file("%s/static/favicon/favicon.ico" % app.root_path)


@app.route("/favicon.png")
def favicon_png():
    return x.send_file("%s/static/favicon/favicon.png" % app.root_path)


@app.route("/robots.txt")
def robots_txt():
    # debt: allow robots after changed personal bank account
    response = x.make_response("User-agent: * Disallow: /")
    response.headers["Content-Type"] = "text/plain"
    return response
