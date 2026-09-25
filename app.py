from flask import Flask, send_from_directory, request, jsonify, abort
import os
import ast
import operator

app = Flask(__name__, static_folder='static', static_url_path='/static')

# Helper to evaluate arithmetic expressions safely
# Supports +, -, *, /, parentheses, and unary +/-
operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def eval_expr(node):
    if isinstance(node, ast.Num):  # <number>
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in operators:
        left = eval_expr(node.left)
        right = eval_expr(node.right)
        try:
            return operators[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ValueError('Division by zero')
    if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
        operand = eval_expr(node.operand)
        return operators[type(node.op)](operand)
    if isinstance(node, ast.Expression):
        return eval_expr(node.body)
    raise ValueError('Unsupported expression')

@app.route('/')
def index():
    # Serve the main HTML page
    return send_from_directory('static', 'index.html')

# Serve other static files (css, js) automatically via static_folder
# Flask already handles /static/<path:filename>

@app.route('/api/calculate', methods=['POST'])
def calculate():
    if not request.is_json:
        return jsonify({'error': 'JSON payload required'}), 400
    data = request.get_json()
    expr = data.get('expression')
    if not isinstance(expr, str):
        return jsonify({'error': 'Expression must be a string'}), 400
    # Remove any whitespace
    expr = expr.replace(' ', '')
    # Basic validation: allow only digits, operators, parentheses, decimal point
    if not all(c.isdigit() or c in '+-*/().' for c in expr):
        return jsonify({'error': 'Invalid characters in expression'}), 400
    try:
        # Parse expression safely
        node = ast.parse(expr, mode='eval')
        result = eval_expr(node)
        # Round result to a reasonable precision to avoid floating point noise
        if isinstance(result, float):
            result = round(result, 10)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    # Use host 0.0.0.0 for container compatibility, debug can be toggled via env
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5000, debug=debug)
