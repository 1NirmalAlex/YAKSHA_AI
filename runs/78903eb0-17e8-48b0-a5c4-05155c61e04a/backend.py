from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import threading

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///expenses.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(64), nullable=False)


# Ensure tables are created before first request
with app.app_context():
    db.create_all()


# Simple keyword‑based categorizer (placeholder for an ML model)
_category_keywords = {
    "Food": ["restaurant", "cafe", "meal", "food", "lunch", "dinner", "breakfast", "snack"],
    "Transport": ["uber", "taxi", "bus", "train", "metro", "flight", "gas", "fuel", "ticket"],
    "Entertainment": ["movie", "cinema", "concert", "game", "sports", "theater", "festival"],
    "Shopping": ["store", "mall", "clothing", "shoes", "electronics", "grocery", "amazon"],
    "Bills": ["electricity", "water", "internet", "phone", "rent", "mortgage", "utility"],
}
_default_category = "Other"


def categorize(text: str) -> str:
    lowered = text.lower()
    for cat, keywords in _category_keywords.items():
        if any(k in lowered for k in keywords):
            return cat
    return _default_category


def expense_to_dict(expense: Expense) -> dict:
    return {
        "id": expense.id,
        "amount": expense.amount,
        "date": expense.date.isoformat(),
        "description": expense.description,
        "category": expense.category,
    }


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    expenses = Expense.query.all()
    return jsonify([expense_to_dict(e) for e in expenses])


@app.route("/api/expenses", methods=["POST"])
def create_expense():
    data = request.get_json()
    if not data:
        return make_response(jsonify({"error": "Invalid JSON"}), 400)

    amount = data.get("amount")
    date_str = data.get("date")
    description = data.get("description")

    if amount is None or date_str is None or description is None:
        return make_response(jsonify({"error": "Missing required fields"}), 400)

    try:
        date_obj = datetime.fromisoformat(date_str).date()
    except ValueError:
        return make_response(jsonify({"error": "Invalid date format"}), 400)

    category = categorize(description)

    expense = Expense(
        amount=amount, date=date_obj, description=description, category=category
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify(expense_to_dict(expense)), 201


@app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
def update_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    data = request.get_json()
    if not data:
        return make_response(jsonify({"error": "Invalid JSON"}), 400)

    amount = data.get("amount")
    date_str = data.get("date")
    description = data.get("description")

    if amount is not None:
        expense.amount = amount
    if date_str is not None:
        try:
            expense.date = datetime.fromisoformat(date_str).date()
        except ValueError:
            return make_response(jsonify({"error": "Invalid date format"}), 400)
    if description is not None:
        if description != expense.description:
            expense.category = categorize(description)
        expense.description = description

    db.session.commit()
    return jsonify(expense_to_dict(expense))


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    return "", 204


@app.route("/api/categories", methods=["GET"])
def get_categories():
    categories = db.session.query(Expense.category).distinct().all()
    distinct = [c[0] for c in categories]
    return jsonify(distinct)