"""
SpendSense
Auto-assembled by YAKSHA AI v2.0 Assembly Engine — do not edit by hand;
regenerate via the agent crew instead.
Dependencies: flask, flask_sqlalchemy, scikit-learn, nltk
"""

# --- Frontend markup (embedded verbatim by Assembly Engine) ---
FRONTEND_HTML = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SpendSense</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n</head>\n<body class=\"bg-gray-100 min-h-screen p-6\">\n  <div class=\"max-w-4xl mx-auto bg-white shadow-lg rounded-lg p-6\">\n    <h1 class=\"text-3xl font-bold mb-4 text-center\">SpendSense</h1>\n\n    <!-- Filter -->\n    <div class=\"mb-4 flex items-center\">\n      <label for=\"categoryFilter\" class=\"mr-2 font-medium\">Filter by Category:</label>\n      <select id=\"categoryFilter\" class=\"border rounded px-2 py-1\">\n        <option value=\"\">All</option>\n      </select>\n    </div>\n\n    <!-- Expenses Table -->\n    <div class=\"overflow-x-auto\">\n      <table class=\"w-full border-collapse\">\n        <thead class=\"bg-gray-200\">\n          <tr>\n            <th class=\"border px-3 py-2 text-left\">Amount</th>\n            <th class=\"border px-3 py-2 text-left\">Date</th>\n            <th class=\"border px-3 py-2 text-left\">Description</th>\n            <th class=\"border px-3 py-2 text-left\">Category</th>\n            <th class=\"border px-3 py-2 text-left\">Actions</th>\n          </tr>\n        </thead>\n        <tbody id=\"expensesBody\" class=\"bg-white\"></tbody>\n      </table>\n    </div>\n\n    <!-- Form -->\n    <div class=\"mt-6 border-t pt-4\">\n      <h2 class=\"text-2xl font-semibold mb-3\" id=\"formTitle\">Add New Expense</h2>\n      <form id=\"expenseForm\" class=\"grid grid-cols-1 gap-4 md:grid-cols-3\">\n        <input type=\"hidden\" id=\"expenseId\" />\n        <div>\n          <label class=\"block font-medium mb-1\" for=\"amount\">Amount</label>\n          <input type=\"number\" step=\"0.01\" id=\"amount\" required class=\"w-full border rounded px-2 py-1\"/>\n        </div>\n        <div>\n          <label class=\"block font-medium mb-1\" for=\"date\">Date</label>\n          <input type=\"date\" id=\"date\" required class=\"w-full border rounded px-2 py-1\"/>\n        </div>\n        <div>\n          <label class=\"block font-medium mb-1\" for=\"description\">Description</label>\n          <input type=\"text\" id=\"description\" required class=\"w-full border rounded px-2 py-1\"/>\n        </div>\n        <div class=\"md:col-span-3 flex justify-end space-x-2\">\n          <button type=\"button\" id=\"cancelEditBtn\" class=\"hidden bg-gray-400 text-white px-4 py-2 rounded\">Cancel</button>\n          <button type=\"submit\" class=\"bg-blue-600 text-white px-4 py-2 rounded\">Save</button>\n        </div>\n      </form>\n    </div>\n  </div>\n\n  <script>\n    // Helper functions\n    const api = {\n      async getExpenses() {\n        const res = await fetch('/api/expenses');\n        if (!res.ok) throw new Error('Failed to fetch expenses');\n        return res.json();\n      },\n      async getCategories() {\n        const res = await fetch('/api/categories');\n        if (!res.ok) throw new Error('Failed to fetch categories');\n        return res.json();\n      },\n      async createExpense(data) {\n        const res = await fetch('/api/expenses', {\n          method: 'POST',\n          headers: { 'Content-Type': 'application/json' },\n          body: JSON.stringify(data)\n        });\n        if (!res.ok) throw new Error('Failed to create expense');\n        return res.json();\n      },\n      async updateExpense(id, data) {\n        const res = await fetch(`/api/expenses/${id}`, {\n          method: 'PUT',\n          headers: { 'Content-Type': 'application/json' },\n          body: JSON.stringify(data)\n        });\n        if (!res.ok) throw new Error('Failed to update expense');\n        return res.json();\n      },\n      async deleteExpense(id) {\n        const res = await fetch(`/api/expenses/${id}`, { method: 'DELETE' });\n        if (!res.ok) throw new Error('Failed to delete expense');\n      }\n    };\n\n    // State\n    let expenses = [];\n    let categories = [];\n\n    // DOM Elements\n    const expensesBody = document.getElementById('expensesBody');\n    const categoryFilter = document.getElementById('categoryFilter');\n    const expenseForm = document.getElementById('expenseForm');\n    const formTitle = document.getElementById('formTitle');\n    const cancelEditBtn = document.getElementById('cancelEditBtn');\n    const expenseIdInput = document.getElementById('expenseId');\n    const amountInput = document.getElementById('amount');\n    const dateInput = document.getElementById('date');\n    const descriptionInput = document.getElementById('description');\n\n    // Render functions\n    function renderTable() {\n      const filterValue = categoryFilter.value;\n      expensesBody.innerHTML = '';\n      const filtered = filterValue ? expenses.filter(e => e.category === filterValue) : expenses;\n      filtered.forEach(exp => {\n        const tr = document.createElement('tr');\n        tr.innerHTML = `\n          <td class=\"border px-3 py-2\">$${parseFloat(exp.amount).toFixed(2)}</td>\n          <td class=\"border px-3 py-2\">${new Date(exp.date).toLocaleDateString()}</td>\n          <td class=\"border px-3 py-2\">${exp.description}</td>\n          <td class=\"border px-3 py-2\">${exp.category || ''}</td>\n          <td class=\"border px-3 py-2 space-x-2\">\n            <button data-id=\"${exp.id}\" class=\"editBtn bg-yellow-400 text-white px-2 py-1 rounded\">Edit</button>\n            <button data-id=\"${exp.id}\" class=\"deleteBtn bg-red-600 text-white px-2 py-1 rounded\">Delete</button>\n          </td>\n        `;\n        expensesBody.appendChild(tr);\n      });\n    }\n\n    function populateCategories() {\n      categoryFilter.innerHTML = '<option value=\"\">All</option>';\n      categories.forEach(cat => {\n        const opt = document.createElement('option');\n        opt.value = cat;\n        opt.textContent = cat;\n        categoryFilter.appendChild(opt);\n      });\n    }\n\n    // Event Handlers\n    async function loadInitialData() {\n      try {\n        [expenses, categories] = await Promise.all([api.getExpenses(), api.getCategories()]);\n        populateCategories();\n        renderTable();\n      } catch (e) {\n        console.error(e);\n        alert('Error loading data');\n      }\n    }\n\n    categoryFilter.addEventListener('change', renderTable);\n\n    expensesBody.addEventListener('click', async (e) => {\n      if (e.target.matches('.editBtn')) {\n        const id = e.target.dataset.id;\n        const exp = expenses.find(e => e.id == id);\n        if (!exp) return;\n        expenseIdInput.value = exp.id;\n        amountInput.value = exp.amount;\n        dateInput.value = exp.date;\n        descriptionInput.value = exp.description;\n        formTitle.textContent = 'Edit Expense';\n        cancelEditBtn.classList.remove('hidden');\n      } else if (e.target.matches('.deleteBtn')) {\n        if (!confirm('Delete this expense?')) return;\n        const id = e.target.dataset.id;\n        try {\n          await api.deleteExpense(id);\n          expenses = expenses.filter(e => e.id != id);\n          renderTable();\n        } catch (err) {\n          console.error(err);\n          alert('Failed to delete');\n        }\n      }\n    });\n\n    cancelEditBtn.addEventListener('click', () => {\n      expenseForm.reset();\n      expenseIdInput.value = '';\n      formTitle.textContent = 'Add New Expense';\n      cancelEditBtn.classList.add('hidden');\n    });\n\n    expenseForm.addEventListener('submit', async (e) => {\n      e.preventDefault();\n      const data = {\n        amount: amountInput.value,\n        date: dateInput.value,\n        description: descriptionInput.value\n      };\n      const id = expenseIdInput.value;\n      try {\n        if (id) {\n          const updated = await api.updateExpense(id, data);\n          expenses = expenses.map(e => (e.id == id ? updated : e));\n        } else {\n          const created = await api.createExpense(data);\n          expenses.push(created);\n        }\n        renderTable();\n        expenseForm.reset();\n        expenseIdInput.value = '';\n        formTitle.textContent = 'Add New Expense';\n        cancelEditBtn.classList.add('hidden');\n      } catch (err) {\n        console.error(err);\n        alert('Failed to save expense');\n      }\n    });\n\n    // Init\n    document.addEventListener('DOMContentLoaded', loadInitialData);\n  </script>\n</body>\n</html>"

# --- AI/ML module (inlined verbatim by Assembly Engine) ---
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB


# Seed training data
_SEED_TEXTS = [
    "buy groceries at the supermarket",
    "dinner at a nice restaurant",
    "gasoline for the car",
    "bus ticket for the weekend",
    "movie night at the theater",
    "internet bill paid",
    "electricity bill last month",
    "shopping online for clothes",
    "buy a new phone",
    "coffee at the cafe",
    "train ticket to new york",
    "ticket to the concert",
    "paying rent for the apartment",
    "gym membership renewal",
    "vacuum cleaner purchase",
    "pizza delivery order",
    "train to work",
    "movie streaming subscription",
    "buying office supplies",
    "paying utility bills"
]

_SEED_LABELS = [
    "Shopping",  # groceries
    "Food",      # dinner
    "Transport", # gasoline
    "Transport", # bus ticket
    "Entertainment", # movie night
    "Utilities",      # internet bill
    "Utilities",      # electricity
    "Shopping",       # online clothes
    "Shopping",       # new phone
    "Food",           # coffee
    "Transport",      # train ticket
    "Entertainment",  # concert
    "Utilities",      # rent
    "Utilities",      # gym membership
    "Shopping",       # vacuum cleaner
    "Food",           # pizza
    "Transport",      # train to work
    "Entertainment",  # movie streaming
    "Shopping",       # office supplies
    "Utilities"       # utility bills
]

_CATEGORIES = ["Food", "Transport", "Entertainment", "Utilities", "Shopping", "Other"]


class SpendSenseClassifier:
    def __init__(self):
        self.vectorizer = CountVectorizer(
            lowercase=True,
            token_pattern=r"\b\w+\b"
        )
        # Fit vectorizer on seed data
        self.vectorizer.fit(_SEED_TEXTS)

        # MultinomialNB supports partial_fit
        self.model = MultinomialNB()
        X_train = self.vectorizer.transform(_SEED_TEXTS)
        self.model.partial_fit(X_train, _SEED_LABELS, classes=_CATEGORIES)

    def categorize(self, text: str) -> str:
        """Predict category for a single text. Returns 'Other' if confidence < 0.4."""
        X = self.vectorizer.transform([text])
        probs = self.model.predict_proba(X)[0]
        idx = np.argmax(probs)
        confidence = probs[idx]
        pred = self.model.classes_[idx]
        return pred if confidence >= 0.4 else "Other"

    def partial_fit(self, texts: list[str], labels: list[str]) -> None:
        """
        Update the model with new labeled examples.
        Parameters
        ----------
        texts : list of str
            New sample texts.
        labels : list of str
            Corresponding labels.
        """
        X = self.vectorizer.transform(texts)
        # Ensure classes are known
        self.model.partial_fit(X, labels)

    def add_examples(self, texts: list[str], labels: list[str]) -> None:
        """
        Convenience method to add new examples and retrain the vectorizer.
        """
        # Update dataset
        all_texts = list(self.vectorizer.get_feature_names_out())  # not used; just placeholder
        # Fit vectorizer again on all data (small dataset, acceptable)
        combined_texts = _SEED_TEXTS + texts
        self.vectorizer.fit(combined_texts)
        X = self.vectorizer.transform(combined_texts)
        self.model.partial_fit(X, _SEED_LABELS + labels)


# Create a global instance that is ready at import time
_classifier = SpendSenseClassifier()


def categorize(text: str) -> str:
    """Top‑level helper that uses the global classifier."""
    return _classifier.categorize(text)


def partial_fit(texts: list[str], labels: list[str]) -> None:
    """Top‑level helper to update the global model."""
    _classifier.partial_fit(texts, labels)

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


# --- Frontend route (injected by Assembly Engine) ---
@app.route("/")
def _yaksha_serve_frontend():
    return FRONTEND_HTML


# --- Entry point (generated by Assembly Engine) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
