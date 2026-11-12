import os
import sqlite3
from datetime import date

from flask import Flask, jsonify, render_template, request, send_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

app = Flask(__name__)

DATABASE = os.path.join(os.path.dirname(__file__), "expenses.db")
CHART_FILE = os.path.join(os.path.dirname(__file__), "chart.png")
CATEGORIES = ["Food", "Travel", "Bills", "Shopping", "Entertainment", "Other"]
DAILY_CHART_LIMIT = 100_000


def get_connection():
    """Open a database connection and return rows by column name."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    """Create the expenses table the first time the app runs."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL DEFAULT CURRENT_DATE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS income_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                description TEXT NOT NULL,
                date TEXT NOT NULL DEFAULT CURRENT_DATE
            )
            """
        )


def expense_as_dict(row):
    return {
        "id": row["id"],
        "amount": row["amount"],
        "description": row["description"],
        "category": row["category"],
        "date": row["date"],
    }


def income_as_dict(row):
    return {
        "id": row["id"],
        "amount": row["amount"],
        "description": row["description"],
        "date": row["date"],
    }


initialize_database()


@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)


@app.route("/expenses", methods=["POST"])
def add_expense():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    amount = data.get("amount")
    description = data.get("description")
    category = data.get("category")

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400
    if not isinstance(description, str) or not description.strip():
        return jsonify({"error": "Description is required."}), 400
    if category not in CATEGORIES:
        return jsonify({"error": "Choose a valid category."}), 400

    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO expenses (amount, description, category) VALUES (?, ?, ?)",
            (amount, description.strip(), category),
        )
        row = connection.execute(
            "SELECT * FROM expenses WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return jsonify(expense_as_dict(row)), 201


@app.route("/expenses", methods=["GET"])
def list_expenses():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM expenses ORDER BY date DESC, id DESC"
        ).fetchall()
    return jsonify([expense_as_dict(row) for row in rows])


@app.route("/expenses/<int:expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    if cursor.rowcount == 0:
        return jsonify({"error": "Expense not found."}), 404
    return jsonify({"message": "Expense deleted."})


@app.route("/income", methods=["POST"])
def add_income():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    amount = data.get("amount")
    description = data.get("description")

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero."}), 400
    if not isinstance(description, str) or not description.strip():
        return jsonify({"error": "Source or description is required."}), 400

    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO income_entries (amount, description) VALUES (?, ?)",
            (amount, description.strip()),
        )
        row = connection.execute(
            "SELECT * FROM income_entries WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return jsonify(income_as_dict(row)), 201


@app.route("/income", methods=["GET"])
def list_income():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM income_entries ORDER BY date DESC, id DESC"
        ).fetchall()
    return jsonify([income_as_dict(row) for row in rows])


@app.route("/income/<int:income_id>", methods=["DELETE"])
def delete_income(income_id):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM income_entries WHERE id = ?", (income_id,)
        )
    if cursor.rowcount == 0:
        return jsonify({"error": "Income entry not found."}), 404
    return jsonify({"message": "Income entry deleted."})


@app.route("/summary", methods=["GET"])
def summary():
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE date >= ? AND date < date(?, '+1 month')
            GROUP BY category
            ORDER BY category
            """,
            (month_start, month_start),
        ).fetchall()
    return jsonify({row["category"]: round(row["total"], 2) for row in rows})


@app.route("/income/summary", methods=["GET"])
def income_summary():
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM income_entries
            WHERE date >= ? AND date < date(?, '+1 month')
            """,
            (month_start, month_start),
        ).fetchone()
    return jsonify({"total": round(row["total"], 2)})


@app.route("/chart", methods=["GET"])
def chart():
    # Use the current month's category totals for the pie chart.
    totals = summary().get_json()
    categories = list(totals.keys())
    amounts = list(totals.values())

    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with get_connection() as connection:
        daily_rows = connection.execute(
            """
            SELECT date, SUM(amount) AS total
            FROM expenses
            WHERE date >= ? AND date < date(?, '+1 month')
            GROUP BY date
            ORDER BY date
            """,
            (month_start, month_start),
        ).fetchall()

    figure, (pie_axis, line_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    if amounts and sum(amounts) > 0:
        pie_axis.pie(
            amounts,
            labels=categories,
            autopct="%1.0f%%",
            startangle=90,
            colors=["#75b798", "#8ab4e8", "#f3c969", "#e99583", "#b49ae0", "#9da9a1"],
        )
    else:
        pie_axis.text(0.5, 0.5, "No spending yet", ha="center", va="center")
    pie_axis.set_title("Spending distribution")

    totals_by_day = {
        int(row["date"].split("-")[2]): row["total"] for row in daily_rows
    }
    # Include days with no expenses so a single purchase still appears as a
    # continuous line that returns to zero on the other days.
    days = list(range(1, today.day + 1))
    daily_amounts = [totals_by_day.get(day, 0) for day in days]
    chart_amounts = [min(amount, DAILY_CHART_LIMIT) for amount in daily_amounts]
    line_axis.plot(days, chart_amounts, color="#287653", marker="o", linewidth=2)
    line_axis.fill_between(days, chart_amounts, color="#75b798", alpha=0.16)
    for day, amount in zip(days, daily_amounts):
        if amount > 0:
            over_limit = amount > DAILY_CHART_LIMIT
            line_axis.annotate(
                (
                    f"+₹{amount - DAILY_CHART_LIMIT:,.0f} over limit"
                    if over_limit
                    else f"₹{amount:,.0f}"
                ),
                (day, min(amount, DAILY_CHART_LIMIT)),
                textcoords="offset points",
                xytext=(0, -18 if over_limit else 7),
                ha="center",
                fontsize=8,
                color="#286346",
            )
    line_axis.axhline(
        DAILY_CHART_LIMIT,
        color="#cf8b48",
        linestyle="--",
        linewidth=1.2,
        label="₹1,00,000 chart limit",
    )
    line_axis.set_title("Daily spending flow (no-spend days = ₹0)")
    line_axis.set_xlabel("Day of month")
    line_axis.set_ylabel("Amount (₹)")
    line_axis.grid(True, alpha=0.25)
    line_axis.set_ylim(0, DAILY_CHART_LIMIT)
    line_axis.set_yticks(
        [0, 25_000, 50_000, 75_000, DAILY_CHART_LIMIT],
        ["₹0", "₹25k", "₹50k", "₹75k", "₹1L"],
    )
    line_axis.legend(loc="upper left", frameon=False, fontsize=8)
    line_axis.set_xlim(1, max(today.day, 2))
    figure.tight_layout()
    figure.savefig(CHART_FILE)
    plt.close(figure)
    return send_file(CHART_FILE, mimetype="image/png")


if __name__ == "__main__":
    app.run(debug=True)
