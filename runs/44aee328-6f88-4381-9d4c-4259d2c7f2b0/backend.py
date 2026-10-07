from flask import Flask, request, jsonify
import re

app = Flask(__name__)

EMAIL_REGEX = re.compile(r'^[^@]+@[^@]+\.[^@]+$')


@app.route('/contact', methods=['POST'])
def contact():
    if not request.is_json:
        return jsonify({"status": "error", "error": "Request must be JSON"}), 400

    data = request.get_json()
    required_fields = ['name', 'email', 'message']

    for field in required_fields:
        if field not in data:
            return jsonify({"status": "error", "error": f"Missing field: {field}"}), 400
        if not isinstance(data[field], str) or not data[field].strip():
            return jsonify({"status": "error", "error": f"Field '{field}' cannot be empty"}), 400

    email = data['email'].strip()
    if not EMAIL_REGEX.match(email):
        return jsonify({"status": "error", "error": "Invalid email format"}), 400

    # Here you could process the message (e.g., store or send email)
    return jsonify({"status": "success"}), 200