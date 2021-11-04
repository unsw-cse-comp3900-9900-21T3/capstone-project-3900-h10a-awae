"""
Routes for creating and ending a mock checkout session
"""

from flask import json, redirect, request, render_template, url_for, jsonify, abort
from flask_login import current_user

from server import app, get_db
from .endpoints import user_bp, api_bp
from .forms import UserPurchaseForm, PaymentCardForm, serialize_form, valid_states

from classes.cart import  get_user_cart
from classes.checkout import CheckoutExpired, CheckoutAlreadyCompleted
from classes.cafepass import refresh_cafepass_level, get_cafepass, CafepassInfo
from classes.profile_payment import get_default_payment_info, get_default_billing_info
from classes.profile_payment import set_default_billing_payment_info, set_default_payment_info
from db.checkout_db import checkout_db

import random
import math

# handle checkout on instant buy
@api_bp.route('/transaction/buy', methods=['POST'])
def product_buy():
    form = UserPurchaseForm(meta=dict(csrf=False))

    if not form.validate_on_submit():
        return jsonify(serialize_form(form)), 400
    
    product_id = form.id.data
    quantity = form.quantity.data

    with app.app_context():
        db = get_db()
    product = db.get_entry_by_id("products", product_id)

    if not product_id:
        abort(404)
    
    if quantity > product['stock']:
        return jsonify(dict(error="Out of stock")), 400

    cart_item = {"product_id": product_id, "quantity": quantity}

    # update product stock
    product_old = list(product.values())
    product['stock'] -= quantity
    product_new = list(product.values())
    db.update("products", product_old, product_new)

    # get cafepass discount
    cafepass = get_cafepass()
    if cafepass:
        discount = CafepassInfo(cafepass, db).frac_discount
    else:
        discount = 0

    checkout_id = checkout_db.create_checkout([cart_item], db, discount, current_user.get_id(), is_cart=False)
    return redirect(url_for("user_bp.cart_checkout_billing", checkout_id=checkout_id))

# handle checkout on cart checkout
@user_bp.route("/checkout", methods=["POST", "GET"])
def cart_checkout():

    with app.app_context():
        db = get_db()

    cafepass = get_cafepass()
    if cafepass:
        discount = CafepassInfo(cafepass, db).frac_discount
    else:
        discount = 0

    cart = get_user_cart()
    checkout_id = checkout_db.create_checkout(cart.db_items, db, discount, current_user.get_id(), is_cart=True)
    return redirect(url_for("user_bp.cart_checkout_billing", checkout_id=checkout_id))

# handle checkout billing screen
@user_bp.route("/checkout_billing/<string:checkout_id>", methods=["GET"])
def cart_checkout_billing(checkout_id):
    with app.app_context():
        db = get_db()
        try:
            checkout = checkout_db.get_checkout(checkout_id, db)
        except KeyError as ex:
            abort(404)
        except CheckoutExpired as ex:
            abort(404)
    
    if checkout.user_id != current_user.get_id():
        abort(403)
    
    if checkout.is_completed:
        return redirect(url_for("user_bp.order_page", id=checkout.order_id))
    
    # NOTE: Guest user placeholder for demonstration
    if not current_user.is_authenticated:
        default_billing_info = dict(
            country="Australia",
            address="Guest Address #1",
            state=random.choice(valid_states),
            zip_code="1234"
        )

        default_payment_info = dict(
            cc_name="Guest Name #1",
            cc_number="4242 4242 4242 4242",
            cc_expiry="01 / 26",
            cc_cvc="123" 
        )
    # get registered user default info
    else:
        default_billing_info = get_default_billing_info()
        info = get_default_payment_info()
        default_payment_info = info and dict(
            cc_name=info["name"],
            cc_number=info["number"],
            cc_expiry=info["expiry"],
            cc_cvc=info["cvc"] 
        )

    form = PaymentCardForm()
    data = dict(
        checkout=checkout,
        form=form,
        checkout_id=checkout_id,
        default_billing_info=default_billing_info,
        default_payment_info=default_payment_info,
        valid_states=valid_states
    )


    return render_template("checkout.html", **data)

# payment validation and completion 
@api_bp.route("/checkout_billing/<string:checkout_id>", methods=["POST"])
def cart_checkout_billing(checkout_id):
    form = PaymentCardForm()
    if not form.validate_on_submit():
        return jsonify(serialize_form(form)), 400

    with app.app_context():
        db = get_db()
        try:
            checkout = checkout_db.get_checkout(checkout_id, db)
        except KeyError as ex:
            abort(404)
        except CheckoutExpired as ex:
            abort(404)

    if checkout.user_id != current_user.get_id():
        abort(403)

    # if order already exists
    if checkout.is_completed:
        res =  dict(redirect=url_for("user_bp.order_page", id=checkout.order_id))
        return jsonify(res), 200

    # create order and redirect
    payment = (form.cc_name.data, form.cc_number.data, form.cc_expiry.data, form.cc_cvc.data)
    billing = (form.country.data, form.address.data, form.state.data, form.zip_code.data)
    payment_past_id = db.add("payment_past", payment)
    billing_past_id = db.add("billing_past", billing)

    order = (current_user.get_id(), payment_past_id, billing_past_id, checkout.subtotal, checkout.discount, checkout.total_cost, checkout.total_items)
    order_id = db.add("order2", order)
    for product in checkout.get_products():
        order_item = (order_id, product["id"], product["quantity"])
        db.add("order2_item", order_item)


    # Handle saving of user data for checkout
    if current_user.is_authenticated:
        if form.remember_billing.data:
            set_default_billing_payment_info(
                form.address.data, form.country.data, 
                form.state.data, form.zip_code.data)

        if form.remember_payment.data:
            set_default_payment_info(
                form.cc_name.data, form.cc_number.data,
                form.cc_expiry.data, form.cc_cvc.data)

    checkout.order_id = order_id    

    # increase battlepass here at checkout completion
    cafepass = get_cafepass(current_user.get_id())
    if cafepass:
        with app.app_context():
            db = get_db()
            cafepass_old = list(cafepass.values())
            cafepass['net_xp'] += int(math.floor(checkout.total_cost))
            cafepass['level'] = refresh_cafepass_level(db, cafepass)
            cafepass_new = list(cafepass.values())
            db.update("cafepass", cafepass_old, cafepass_new)
    
    # empty cart if checkout originated from cart
    if checkout.is_cart:
        cart = get_user_cart()
        cart.empty()

    res =  dict(redirect=url_for("user_bp.order_page", id=order_id))
    
    return jsonify(res), 200

