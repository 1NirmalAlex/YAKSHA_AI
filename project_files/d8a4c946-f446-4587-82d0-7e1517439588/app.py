"""
SpendSense
Auto-assembled by YAKSHA AI v2.0 Assembly Engine — do not edit by hand;
regenerate via the agent crew instead.
Dependencies: flask, flask-cors
"""

# --- Frontend markup (embedded verbatim by Assembly Engine) ---
FRONTEND_HTML = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SpendSense</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n</head>\n<body class=\"bg-gray-100 min-h-screen p-4\">\n  <div class=\"max-w-5xl mx-auto bg-white rounded-lg shadow-md p-6\">\n    <h1 class=\"text-2xl font-bold mb-4 text-center\">SpendSense</h1>\n\n    <!-- Expense Form -->\n    <form id=\"expense-form\" class=\"grid grid-cols-1 md:grid-cols-3 gap-4 mb-6\">\n      <div>\n        <label class=\"block text-sm font-medium text-gray-700\">Amount ($)</label>\n        <input type=\"number\" step=\"0.01\" required min=\"0\" name=\"amount\"\n               class=\"mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n      </div>\n      <div>\n        <label class=\"block text-sm font-medium text-gray-700\">Description</label>\n        <input type=\"text\" required name=\"description\"\n               class=\"mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n      </div>\n      <div>\n        <label class=\"block text-sm font-medium text-gray-700\">Date</label>\n        <input type=\"date\" required name=\"date\"\n               class=\"mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n      </div>\n      <div class=\"md:col-span-3 flex justify-end\">\n        <button type=\"submit\"\n                class=\"px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 focus:outline-none\">\n          Add Expense\n        </button>\n      </div>\n    </form>\n\n    <!-- Filters -->\n    <div class=\"flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-4\">\n      <div class=\"flex items-center gap-2\">\n        <label class=\"text-sm font-medium\">From:</label>\n        <input type=\"date\" id=\"filter-start\" class=\"rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n        <label class=\"text-sm font-medium ml-2\">To:</label>\n        <input type=\"date\" id=\"filter-end\" class=\"rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n      </div>\n      <div class=\"flex items-center gap-2\">\n        <label class=\"text-sm font-medium\">Category:</label>\n        <select id=\"filter-category\" class=\"rounded-md border-gray-300 shadow-sm focus:ring-indigo-500 focus:border-indigo-500\">\n          <option value=\"\">All</option>\n        </select>\n        <button id=\"apply-filters\"\n                class=\"px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700\">\n          Apply\n        </button>\n        <button id=\"clear-filters\"\n                class=\"px-3 py-1 bg-gray-300 text-gray-800 rounded hover:bg-gray-400\">\n          Clear\n        </button>\n      </div>\n    </div>\n\n    <!-- Expenses Table -->\n    <div id=\"expenses-section\">\n      <h2 class=\"text-xl font-semibold mb-2\">Expenses</h2>\n      <div id=\"expenses-loading\" class=\"text-gray-600\">Loading expenses...</div>\n      <div id=\"expenses-error\" class=\"text-red-600 hidden\"></div>\n      <table id=\"expenses-table\" class=\"min-w-full table-auto hidden\">\n        <thead class=\"bg-gray-200\">\n          <tr>\n            <th class=\"px-3 py-2 text-left\">Date</th>\n            <th class=\"px-3 py-2 text-left\">Description</th>\n            <th class=\"px-3 py-2 text-left\">Category</th>\n            <th class=\"px-3 py-2 text-right\">Amount ($)</th>\n          </tr>\n        </thead>\n        <tbody class=\"divide-y divide-gray-100\"></tbody>\n      </table>\n    </div>\n\n    <!-- Summary Panel -->\n    <div id=\"summary-section\" class=\"mt-8\">\n      <h2 class=\"text-xl font-semibold mb-2\">Spending Summary</h2>\n      <div id=\"summary-loading\" class=\"text-gray-600\">Loading summary...</div>\n      <div id=\"summary-error\" class=\"text-red-600 hidden\"></div>\n      <div id=\"summary-content\" class=\"hidden\">\n        <ul id=\"summary-list\" class=\"space-y-2\"></ul>\n        <div id=\"summary-chart\" class=\"mt-4 space-y-2\"></div>\n      </div>\n    </div>\n  </div>\n\n  <script>\n    // Utility\n    const qs = (s) => document.querySelector(s);\n    const qsa = (s) => document.querySelectorAll(s);\n    const formatDate = (d) => new Date(d).toLocaleDateString();\n\n    // Initialize default date in form\n    const today = new Date().toISOString().split('T')[0];\n    qs('input[name=\"date\"]').value = today;\n\n    // State\n    let expenses = [];\n    let summary = {};\n\n    // Fetch expenses with optional filters\n    async function loadExpenses() {\n      qs('#expenses-loading').classList.remove('hidden');\n      qs('#expenses-error').classList.add('hidden');\n      qs('#expenses-table').classList.add('hidden');\n\n      const params = new URLSearchParams();\n      const start = qs('#filter-start').value;\n      const end = qs('#filter-end').value;\n      const cat = qs('#filter-category').value;\n      if (start) params.append('start', start);\n      if (end) params.append('end', end);\n      if (cat) params.append('category', cat);\n\n      try {\n        const res = await fetch('/api/expenses?' + params.toString());\n        if (!res.ok) throw new Error('Failed to fetch expenses');\n        expenses = await res.json();\n        renderExpenses();\n        populateCategoryFilter();\n      } catch (e) {\n        qs('#expenses-error').textContent = e.message;\n        qs('#expenses-error').classList.remove('hidden');\n      } finally {\n        qs('#expenses-loading').classList.add('hidden');\n      }\n    }\n\n    // Render expenses table\n    function renderExpenses() {\n      const tbody = qs('#expenses-table tbody');\n      tbody.innerHTML = '';\n      if (expenses.length === 0) {\n        tbody.innerHTML = '<tr><td colspan=\"4\" class=\"px-3 py-2 text-center text-gray-500\">No expenses found.</td></tr>';\n      } else {\n        expenses.forEach(exp => {\n          const tr = document.createElement('tr');\n          tr.innerHTML = `\n            <td class=\"px-3 py-2\">${formatDate(exp.date)}</td>\n            <td class=\"px-3 py-2\">${exp.description}</td>\n            <td class=\"px-3 py-2\">${exp.category || 'Uncategorized'}</td>\n            <td class=\"px-3 py-2 text-right\">${Number(exp.amount).toFixed(2)}</td>\n          `;\n          tbody.appendChild(tr);\n        });\n      }\n      qs('#expenses-table').classList.remove('hidden');\n    }\n\n    // Populate category filter options based on summary categories\n    function populateCategoryFilter() {\n      const select = qs('#filter-category');\n      const selected = select.value;\n      // Clear existing except first (All)\n      select.innerHTML = '<option value=\"\">All</option>';\n      const categories = new Set(expenses.map(e => e.category).filter(Boolean));\n      categories.forEach(cat => {\n        const opt = document.createElement('option');\n        opt.value = cat;\n        opt.textContent = cat;\n        if (cat === selected) opt.selected = true;\n        select.appendChild(opt);\n      });\n    }\n\n    // Load summary\n    async function loadSummary() {\n      qs('#summary-loading').classList.remove('hidden');\n      qs('#summary-error').classList.add('hidden');\n      qs('#summary-content').classList.add('hidden');\n\n      try {\n        const res = await fetch('/api/summary');\n        if (!res.ok) throw new Error('Failed to fetch summary');\n        summary = await res.json(); // Assume format: { category1: total, category2: total, ... }\n        renderSummary();\n      } catch (e) {\n        qs('#summary-error').textContent = e.message;\n        qs('#summary-error').classList.remove('hidden');\n      } finally {\n        qs('#summary-loading').classList.add('hidden');\n      }\n    }\n\n    // Render summary list and simple bar chart\n    function renderSummary() {\n      const list = qs('#summary-list');\n      const chart = qs('#summary-chart');\n      list.innerHTML = '';\n      chart.innerHTML = '';\n\n      const entries = Object.entries(summary);\n      if (entries.length === 0) {\n        list.innerHTML = '<li class=\"text-gray-500\">No summary data.</li>';\n        qs('#summary-content').classList.remove('hidden');\n        return;\n      }\n\n      const maxAmount = Math.max(...entries.map(e => e[1]), 0);\n\n      entries.forEach(([cat, amt]) => {\n        // List item\n        const li = document.createElement('li');\n        li.textContent = `${cat}: $${amt.toFixed(2)}`;\n        list.appendChild(li);\n\n        // Bar chart row\n        const row = document.createElement('div');\n        row.className = 'flex items-center';\n        row.innerHTML = `\n          <span class=\"w-24 text-sm\">${cat}</span>\n          <div class=\"flex-1 bg-gray-200 h-4 rounded\">\n            <div class=\"bg-indigo-600 h-4 rounded\" style=\"width:${(amt / maxAmount) * 100}%\"></div>\n          </div>\n          <span class=\"w-16 text-right text-sm\">$${amt.toFixed(2)}</span>\n        `;\n        chart.appendChild(row);\n      });\n\n      qs('#summary-content').classList.remove('hidden');\n    }\n\n    // Form submission\n    qs('#expense-form').addEventListener('submit', async (e) => {\n      e.preventDefault();\n      const formData = new FormData(e.target);\n      const payload = {\n        amount: parseFloat(formData.get('amount')),\n        description: formData.get('description').trim(),\n        date: formData.get('date')\n      };\n      // Optional: could include category if UI had it; omitted per brief.\n\n      try {\n        const res = await fetch('/api/expenses', {\n          method: 'POST',\n          headers: {'Content-Type': 'application/json'},\n          body: JSON.stringify(payload)\n        });\n        if (!res.ok) throw new Error('Failed to add expense');\n        e.target.reset();\n        qs('input[name=\"date\"]').value = today; // reset date to today\n        await loadExpenses();\n        await loadSummary();\n      } catch (err) {\n        alert(err.message);\n      }\n    });\n\n    // Filter buttons\n    qs('#apply-filters').addEventListener('click', () => loadExpenses());\n    qs('#clear-filters').addEventListener('click', () => {\n      qs('#filter-start').value = '';\n      qs('#filter-end').value = '';\n      qs('#filter-category').value = '';\n      loadExpenses();\n    });\n\n    // Initial load\n    loadExpenses();\n    loadSummary();\n  </script>\n</body>\n</html>"

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime, date

app = Flask(__name__)
CORS(app)

# SQLite configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///expenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Expense model
class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    category = db.Column(db.String(64), nullable=False, default='Other')

db.create_all()

# Keyword to category mapping
KEYWORD_CATEGORY_MAP = {
    'coffee': 'Food',
    'latte': 'Food',
    'tea': 'Food',
    'sandwich': 'Food',
    'uber': 'Transport',
    'lyft': 'Transport',
    'taxi': 'Transport',
    'bus': 'Transport',
    'train': 'Transport',
    'movie': 'Entertainment',
    'cinema': 'Entertainment',
    'concert': 'Entertainment',
    'book': 'Education',
    'course': 'Education',
    'gym': 'Health',
    'pharmacy': 'Health',
    'doctor': 'Health',
    'rent': 'Housing',
    'electricity': 'Housing',
    'water': 'Housing',
    'internet': 'Housing'
}

def determine_category(description: str) -> str:
    desc_lower = description.lower()
    for keyword, cat in KEYWORD_CATEGORY_MAP.items():
        if keyword in desc_lower:
            return cat
    return 'Other'

def parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

def validate_expense_payload(data):
    errors = []
    amount = data.get('amount')
    description = data.get('description')
    date_str = data.get('date')

    if amount is None:
        errors.append('Missing amount.')
    else:
        try:
            amount = float(amount)
            if amount <= 0:
                errors.append('Amount must be positive.')
        except (ValueError, TypeError):
            errors.append('Amount must be a number.')

    if not description or not isinstance(description, str):
        errors.append('Missing or invalid description.')

    expense_date = date.today()
    if date_str:
        parsed = parse_date(date_str)
        if parsed is None:
            errors.append('Invalid date format. Use YYYY-MM-DD.')
        else:
            expense_date = parsed

    return errors, amount, description, expense_date

@app.route('/api/expenses', methods=['POST'])
def create_expense():
    if not request.is_json:
        return jsonify({'error': 'Request body must be JSON.'}), 400
    data = request.get_json()
    errors, amount, description, expense_date = validate_expense_payload(data)
    if errors:
        return jsonify({'error': errors}), 400

    category = determine_category(description)

    expense = Expense(
        amount=amount,
        description=description,
        date=expense_date,
        category=category
    )
    db.session.add(expense)
    db.session.commit()

    return jsonify({
        'id': expense.id,
        'amount': expense.amount,
        'description': expense.description,
        'date': expense.date.isoformat(),
        'category': expense.category
    }), 201

@app.route('/api/expenses', methods=['GET'])
def list_expenses():
    query = Expense.query

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    category = request.args.get('category')

    if start_date_str:
        start_date = parse_date(start_date_str)
        if start_date is None:
            return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD.'}), 400
        query = query.filter(Expense.date >= start_date)

    if end_date_str:
        end_date = parse_date(end_date_str)
        if end_date is None:
            return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD.'}), 400
        query = query.filter(Expense.date <= end_date)

    if category:
        query = query.filter(Expense.category == category)

    expenses = query.order_by(Expense.date.desc()).all()
    result = [{
        'id': e.id,
        'amount': e.amount,
        'description': e.description,
        'date': e.date.isoformat(),
        'category': e.category
    } for e in expenses]

    return jsonify(result), 200

@app.route('/api/summary', methods=['GET'])
def expense_summary():
    query = db.session.query(Expense.category, func.sum(Expense.amount).label('total'))

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if start_date_str:
        start_date = parse_date(start_date_str)
        if start_date is None:
            return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD.'}), 400
        query = query.filter(Expense.date >= start_date)

    if end_date_str:
        end_date = parse_date(end_date_str)
        if end_date is None:
            return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD.'}), 400
        query = query.filter(Expense.date <= end_date)

    query = query.group_by(Expense.category)
    summary = {category: total for category, total in query.all()}

    return jsonify(summary), 200

@app.route('/api/categories', methods=['GET'])
def list_categories():
    # Gather categories from mapping plus "Other"
    categories = set(KEYWORD_CATEGORY_MAP.values())
    categories.add('Other')
    return jsonify(sorted(categories)), 200


# --- Frontend route (injected by Assembly Engine) ---
@app.route("/")
def _yaksha_serve_frontend():
    return FRONTEND_HTML


# --- Entry point (generated by Assembly Engine) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
