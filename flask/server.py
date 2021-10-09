# %%

from flask import Flask
from flask_login import LoginManager
import sqlite3
import pandas as pd
from classes.table import *
from classes.database import *

from flask import g
app = Flask(__name__)
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = Database("db/ecommerce.db")
    return db
    
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db.conn is not None:
        db.conn.close()
        

# Create product DB and fill it with products

# Flask setup
login_manager = LoginManager()
login_manager.init_app(app)
app.secret_key = 'very-secret-123' # must include

#login_manager.login_view = 'login'

# System setup
print("System setup")
# Create table
table_name = "products"

def make_dicts(cursor, row):
    return dict((cursor.description[idx][0], value) for idx, value in enumerate(row))

# db = Database("db/ecommerce.db")# Save db in application context
with app.app_context():
    db = get_db()   # Initialize db
    with app.open_resource('db/ecommerce.sql', mode='r') as f:
        db.tables_create(f)
        print(db.tables)

    #db.fill("Product", "data/awae_products.xlsx")
# table_products = Table("products", table_cols["products"], conn, cur)
# table_accounts = Table("accounts", table_cols["accounts"], conn, cur)

# table_products.drop()
# table_products.create()


# %%