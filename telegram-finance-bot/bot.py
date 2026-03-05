import os
import logging
from datetime import datetime, date, timedelta
import html
from typing import Optional
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from database import Database

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
db = Database()

# Conversation states
AMOUNT, CATEGORY, DESCRIPTION = range(3)

# Default categories
DEFAULT_EXPENSE_CATEGORIES = [
    ("🍔 Food", "Food"),
    ("🚗 Transport", "Transport"),
    ("🏠 Housing", "Housing"),
    ("🎬 Entertainment", "Entertainment"),
    ("🛒 Shopping", "Shopping"),
    ("💊 Health", "Health"),
    ("📚 Education", "Education"),
    ("💡 Utilities", "Utilities"),
    ("📝 Other", "Other"),
]

DEFAULT_INCOME_CATEGORIES = [
    ("💼 Salary", "Salary"),
    ("💰 Freelance", "Freelance"),
    ("📈 Investment", "Investment"),
    ("🎁 Gift", "Gift"),
    ("📝 Other", "Other"),
]

INFLATION_RATES = {
    "KZ": 0.123,   # Kazakhstan (default)
    "US": 0.027,   # United States
    "EU": 0.023,   # Eurozone (rough proxy)
    "RU": 0.056,   # Russia (rough proxy)
}

INFLATION_COUNTRIES = [
    ("🇰🇿 Kazakhstan", "KZ"),
    ("🇺🇸 USA", "US"),
    ("🇪🇺 Eurozone", "EU"),
    ("🇷🇺 Russia", "RU"),
]


def format_money(amount: float) -> str:
    """Format money with proper separators."""
    return f"${amount:,.2f}"


def escape_html(text: Optional[str]) -> str:
    """Escape user-provided text for parse_mode='HTML'."""
    return html.escape(text or "")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and register user."""
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)

    safe_first_name = escape_html(user.first_name or "there")
    welcome_text = (
        f"👋 Welcome to EconLab Bot, {safe_first_name}!\n\n"
        "I'll help you track your income and expenses. Here's what I can do:\n\n"
        "<b>💰 Add Transactions</b>\n"
        "/income - Add income\n"
        "/expense - Add expense\n\n"
        "<b>📊 View & Analyze</b>\n"
        "/balance - View current balance\n"
        "/history - View recent transactions\n"
        "/report - Get detailed report\n"
        "/inflation_report - Inflation-adjusted balance\n"
        "/insights - Month-to-month insights\n\n"
        "<b>⚙️ Manage</b>\n"
        "/categories - View your categories\n"
        "/delete - Delete a transaction\n"
        "/set_goal - Set a savings goal\n"
        "/goal_status - View savings goal progress\n"
        "/help - Show all commands\n\n"
        "Let's get started! Try adding your first transaction."
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    help_text = (
        "📖 <b>EconLab Bot Commands</b>\n\n"
        "<b>Adding Transactions:</b>\n"
        "/income - Record new income\n"
        "/expense - Record new expense\n\n"
        "<b>Viewing Data:</b>\n"
        "/balance - Current balance summary\n"
        "/history - Last 10 transactions\n"
        "/history 20 - Last 20 transactions\n"
        "/report - Monthly financial report\n"
        "/report week - Weekly report\n"
        "/report year - Yearly report\n"
        "/inflation_report - Inflation-adjusted balance\n"
        "/insights - Month-to-month insights\n\n"
        "<b>Categories:</b>\n"
        "/categories - View all categories\n"
        "/expenses_by_category - Expense breakdown\n"
        "/income_by_category - Income breakdown\n\n"
        "<b>Savings Goals:</b>\n"
        "/goals - List all goals\n"
        "<code>/set_goal &lt;amount&gt; &lt;YYYY-MM-DD&gt; [name]</code> - Create goal\n"
        "Example: <code>/set_goal 5000 2026-12-31 Vacation</code>\n"
        "<code>/goal_status &lt;goal_id&gt;</code> - Goal status\n"
        "<code>/save &lt;goal_id&gt; &lt;amount&gt;</code> - Add to goal wallet\n"
        "<code>/unsave &lt;goal_id&gt; &lt;amount&gt;</code> - Remove from goal wallet\n"
        "<code>/delete_goal &lt;goal_id&gt;</code> - Delete goal\n\n"
        "<b>Management:</b>\n"
        "/delete - Delete a transaction\n"
        "\n"
        "<b>Quick Add (without menus):</b>\n"
        "Send: <code>+1000 Salary bonus</code> for income\n"
        "Send: <code>-50 Lunch</code> for expense"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

def _parse_amount(text: str) -> float:
    return float(text.replace(",", "").replace("$", ""))


def _parse_due_date(text: str) -> date:
    """Parse YYYY-MM-DD or DD.MM.YYYY."""
    t = text.strip()
    if "." in t:
        # DD.MM.YYYY
        d, m, y = t.split(".")
        return date(int(y), int(m), int(d))
    # YYYY-MM-DD
    y, m, d = t.split("-")
    return date(int(y), int(m), int(d))


def _month_range(d: date):
    start = datetime(d.year, d.month, 1)
    if d.month == 12:
        end = datetime(d.year + 1, 1, 1)
    else:
        end = datetime(d.year, d.month + 1, 1)
    return start, end


def _months_left(today: date, due: date) -> int:
    """Approximate months remaining, minimum 1 if due is today/future."""
    if due < today:
        return 0
    months = (due.year - today.year) * 12 + (due.month - today.month)
    if due.day >= today.day:
        months += 1
    return max(1, months)


async def inflation_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show nominal vs inflation-adjusted balance."""
    user_id = update.effective_user.id

    # If user provided country code/name, use it; otherwise ask via buttons.
    if not context.args:
        keyboard = []
        row = []
        for label, code in INFLATION_COUNTRIES:
            row.append(InlineKeyboardButton(label, callback_data=f"infl_{code}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("✅ Use default (Kazakhstan)", callback_data="infl_KZ")])
        await update.message.reply_text(
            "📉 <b>Inflation Report</b>\n\nSelect a country (default: Kazakhstan):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return

    arg = " ".join(context.args).strip().upper()
    code = None
    if arg in INFLATION_RATES:
        code = arg
    else:
        # Try match by country label
        for label, c in INFLATION_COUNTRIES:
            if arg in label.upper():
                code = c
                break
    code = code or "KZ"

    nominal = db.get_summary(user_id)["balance"]
    rate = INFLATION_RATES.get(code, INFLATION_RATES["KZ"])
    real = nominal / (1 + rate) if (1 + rate) != 0 else nominal

    country_name = next((lbl for lbl, c in INFLATION_COUNTRIES if c == code), "🇰🇿 Kazakhstan")
    text = (
        "📉 <b>Inflation Report</b>\n\n"
        f"🌍 Country: <b>{escape_html(country_name)}</b>\n"
        f"📌 Inflation rate (fixed): <b>{rate * 100:.1f}%</b>\n\n"
        f"💰 Nominal balance: <b>{format_money(nominal)}</b>\n"
        f"🧮 Inflation-adjusted balance: <b>{format_money(real)}</b>\n\n"
        "Formula: <code>Real = Nominal / (1 + inflation_rate)</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def inflation_report_country_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inflation country selection via inline keyboard."""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("infl_", "").upper()
    if code not in INFLATION_RATES:
        code = "KZ"

    user_id = update.effective_user.id
    nominal = db.get_summary(user_id)["balance"]
    rate = INFLATION_RATES[code]
    real = nominal / (1 + rate) if (1 + rate) != 0 else nominal
    country_name = next((lbl for lbl, c in INFLATION_COUNTRIES if c == code), "🇰🇿 Kazakhstan")

    text = (
        "📉 <b>Inflation Report</b>\n\n"
        f"🌍 Country: <b>{escape_html(country_name)}</b>\n"
        f"📌 Inflation rate (fixed): <b>{rate * 100:.1f}%</b>\n\n"
        f"💰 Nominal balance: <b>{format_money(nominal)}</b>\n"
        f"🧮 Inflation-adjusted balance: <b>{format_money(real)}</b>\n\n"
        "Formula: <code>Real = Nominal / (1 + inflation_rate)</code>"
    )
    await query.edit_message_text(text, parse_mode="HTML")


async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create savings goal: /set_goal <amount> <YYYY-MM-DD> [name]."""
    user_id = update.effective_user.id

    if len(context.args) < 2:
        await update.message.reply_text(
            "🎯 <b>Create a Savings Goal</b>\n\n"
            "Usage: <code>/set_goal &lt;amount&gt; &lt;YYYY-MM-DD&gt; [name]</code>\n"
            "Example: <code>/set_goal 5000 2026-12-31 Vacation</code>\n"
            "Also supports date like <code>31.12.2026</code>.",
            parse_mode="HTML",
        )
        return

    try:
        amount = _parse_amount(context.args[0])
        if amount <= 0:
            raise ValueError("amount")
        due = _parse_due_date(context.args[1])
    except Exception:
        await update.message.reply_text(
            "❌ Couldn't parse that.\n\n"
            "Usage: <code>/set_goal &lt;amount&gt; &lt;YYYY-MM-DD&gt; [name]</code>\n"
            "Example: <code>/set_goal 5000 2026-12-31 Vacation</code>",
            parse_mode="HTML",
        )
        return

    name = " ".join(context.args[2:]).strip() or None
    goal_id = db.create_goal(user_id, amount, due.isoformat(), name)

    label = f"<b>{escape_html(name)}</b>" if name else "<b>Savings Goal</b>"
    await update.message.reply_text(
        "✅ Goal saved!\n\n"
        f"🎯 Goal: {label}\n"
        f"🔖 ID: <code>#{goal_id}</code>\n"
        f"💰 Target: <b>{format_money(amount)}</b>\n"
        f"📅 Due: <b>{due.strftime('%Y-%m-%d')}</b>\n\n"
        f"Check progress: <code>/goal_status {goal_id}</code>\n"
        f"Add savings: <code>/save {goal_id} 100</code>",
        parse_mode="HTML",
    )

async def goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all goals for the user."""
    user_id = update.effective_user.id
    goals_list = db.list_goals(user_id)
    if not goals_list:
        await update.message.reply_text(
            "🎯 You don't have any goals yet.\n\nCreate one with <code>/set_goal 5000 2026-12-31 Vacation</code>.",
            parse_mode="HTML",
        )
        return

    total_saved = db.get_total_saved(user_id)
    nominal_balance = db.get_summary(user_id)["balance"]
    available = nominal_balance - total_saved

    text = "🎯 <b>Your Goals</b>\n\n"
    for g in goals_list[:30]:
        gid = g["id"]
        name = g.get("name") or "Savings Goal"
        target = float(g["target_amount"])
        saved = float(g["saved_amount"])
        pct = (saved / target * 100) if target > 0 else 0
        pct = max(0.0, min(999.0, pct))
        text += (
            f"• <code>#{gid}</code> <b>{escape_html(name)}</b>\n"
            f"  Saved: {format_money(saved)} / {format_money(target)} ({pct:.1f}%)\n"
            f"  Due: {escape_html(str(g['due_date']))}\n\n"
        )

    text += (
        f"🏦 Total savings (all goals): <b>{format_money(total_saved)}</b>\n"
        f"💳 Available balance: <b>{format_money(available)}</b>\n\n"
        "Tip: <code>/goal_status &lt;id&gt;</code>, <code>/save &lt;id&gt; &lt;amount&gt;</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def goal_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show status for one goal: /goal_status <id>."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/goal_status &lt;goal_id&gt;</code>\nExample: <code>/goal_status 1</code>",
            parse_mode="HTML",
        )
        return

    try:
        goal_id = int(context.args[0].replace("#", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid goal id.", parse_mode="HTML")
        return

    goal = db.get_goal(user_id, goal_id)
    if not goal:
        await update.message.reply_text("❌ Goal not found.", parse_mode="HTML")
        return

    try:
        due = date.fromisoformat(goal["due_date"])
    except Exception:
        due = datetime.fromisoformat(goal["due_date"]).date()

    target = float(goal["target_amount"])
    saved = float(goal["saved_amount"])
    name = goal.get("name") or "Savings Goal"
    remaining = max(0.0, target - saved)

    today = datetime.now().date()
    days_left = (due - today).days
    months_left = _months_left(today, due)

    if days_left < 0:
        status_line = f"⏰ <b>Overdue by {abs(days_left)} days</b>"
        monthly_needed = remaining
    else:
        status_line = f"📅 Time left: <b>{days_left} days</b> (~{months_left} month(s))"
        monthly_needed = (remaining / months_left) if months_left > 0 else remaining

    pct = (saved / target * 100) if target > 0 else 0
    pct = max(0.0, min(100.0, pct))
    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))

    total_saved = db.get_total_saved(user_id)
    nominal_balance = db.get_summary(user_id)["balance"]
    available = nominal_balance - total_saved

    text = (
        f"🎯 <b>{escape_html(name)}</b> (<code>#{goal_id}</code>)\n\n"
        f"💰 Target: <b>{format_money(target)}</b>\n"
        f"🏦 Saved (goal wallet): <b>{format_money(saved)}</b>\n"
        f"🧾 Remaining: <b>{format_money(remaining)}</b>\n"
        f"{status_line}\n\n"
        f"{bar} <b>{pct:.1f}%</b>\n\n"
        f"📌 Required monthly savings: <b>{format_money(monthly_needed)}</b>\n\n"
        f"💳 Available balance (after all goals): <b>{format_money(available)}</b>\n"
        f"Add: <code>/save {goal_id} 100</code>  Remove: <code>/unsave {goal_id} 50</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def save_to_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/save <goal_id> <amount> - move money from available balance into goal wallet."""
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: <code>/save &lt;goal_id&gt; &lt;amount&gt;</code>\nExample: <code>/save 1 100</code>",
            parse_mode="HTML",
        )
        return

    try:
        goal_id = int(context.args[0].replace("#", ""))
        amount = _parse_amount(context.args[1])
        if amount <= 0:
            raise ValueError("amount")
    except Exception:
        await update.message.reply_text("❌ Invalid input.", parse_mode="HTML")
        return

    goal = db.get_goal(user_id, goal_id)
    if not goal:
        await update.message.reply_text("❌ Goal not found.", parse_mode="HTML")
        return

    nominal_balance = db.get_summary(user_id)["balance"]
    total_saved = db.get_total_saved(user_id)
    available = nominal_balance - total_saved
    if available < amount:
        await update.message.reply_text(
            f"❌ Not enough available balance.\n\nAvailable: <b>{format_money(available)}</b>",
            parse_mode="HTML",
        )
        return

    if not db.adjust_goal_saved_amount(user_id, goal_id, amount):
        await update.message.reply_text("❌ Could not save to goal.", parse_mode="HTML")
        return

    await update.message.reply_text(
        f"✅ Saved <b>{format_money(amount)}</b> to goal <code>#{goal_id}</code>.",
        parse_mode="HTML",
    )


async def unsave_from_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unsave <goal_id> <amount> - move money from goal wallet back to available balance."""
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: <code>/unsave &lt;goal_id&gt; &lt;amount&gt;</code>\nExample: <code>/unsave 1 50</code>",
            parse_mode="HTML",
        )
        return

    try:
        goal_id = int(context.args[0].replace("#", ""))
        amount = _parse_amount(context.args[1])
        if amount <= 0:
            raise ValueError("amount")
    except Exception:
        await update.message.reply_text("❌ Invalid input.", parse_mode="HTML")
        return

    goal = db.get_goal(user_id, goal_id)
    if not goal:
        await update.message.reply_text("❌ Goal not found.", parse_mode="HTML")
        return

    if not db.adjust_goal_saved_amount(user_id, goal_id, -amount):
        await update.message.reply_text("❌ Not enough saved in that goal.", parse_mode="HTML")
        return

    await update.message.reply_text(
        f"✅ Removed <b>{format_money(amount)}</b> from goal <code>#{goal_id}</code>.",
        parse_mode="HTML",
    )


async def delete_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delete_goal <goal_id> - delete a goal."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/delete_goal &lt;goal_id&gt;</code>\nExample: <code>/delete_goal 1</code>",
            parse_mode="HTML",
        )
        return

    try:
        goal_id = int(context.args[0].replace("#", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid goal id.", parse_mode="HTML")
        return

    if db.delete_goal(user_id, goal_id):
        await update.message.reply_text(f"✅ Goal <code>#{goal_id}</code> deleted.", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Goal not found.", parse_mode="HTML")


async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Month-over-month insights for income/expenses/savings rate and category spikes."""
    user_id = update.effective_user.id
    today = datetime.now().date()
    cur_start, cur_end = _month_range(today)

    prev_month_day = (cur_start - timedelta(days=1)).date()
    prev_start, prev_end = _month_range(prev_month_day)

    cur = db.get_summary_range(user_id, cur_start, cur_end)
    prev = db.get_summary_range(user_id, prev_start, prev_end)

    def pct_change(current: float, previous: float):
        if previous == 0:
            return None
        return (current - previous) / previous * 100

    cur_income, cur_exp, cur_bal = cur["income"], cur["expense"], cur["balance"]
    prev_income, prev_exp, prev_bal = prev["income"], prev["expense"], prev["balance"]

    cur_savings_rate = (cur_bal / cur_income * 100) if cur_income > 0 else 0.0
    prev_savings_rate = (prev_bal / prev_income * 100) if prev_income > 0 else 0.0

    # Category increases (expenses)
    cur_cats = {i["category"]: i["total"] for i in db.get_category_breakdown_range(user_id, "expense", cur_start, cur_end)}
    prev_cats = {i["category"]: i["total"] for i in db.get_category_breakdown_range(user_id, "expense", prev_start, prev_end)}

    deltas = []
    for cat, cur_total in cur_cats.items():
        prev_total = prev_cats.get(cat, 0.0)
        delta = cur_total - prev_total
        if delta > 0:
            deltas.append((cat, prev_total, cur_total, delta))
    deltas.sort(key=lambda x: x[3], reverse=True)
    top = deltas[:3]

    lines = []
    lines.append("📊 <b>Insights (This Month vs Last Month)</b>\n")
    lines.append(f"📅 This month: <b>{escape_html(cur_start.strftime('%Y-%m'))}</b>")
    lines.append(f"📅 Last month: <b>{escape_html(prev_start.strftime('%Y-%m'))}</b>\n")

    # Totals with change
    inc_chg = pct_change(cur_income, prev_income)
    exp_chg = pct_change(cur_exp, prev_exp)
    sr_chg = (cur_savings_rate - prev_savings_rate)

    def fmt_chg(v):
        return "—" if v is None else f"{v:+.1f}%"

    lines.append("<b>Totals:</b>")
    lines.append(f"💵 Income: {format_money(cur_income)} ({fmt_chg(inc_chg)})")
    lines.append(f"💸 Expenses: {format_money(cur_exp)} ({fmt_chg(exp_chg)})")
    lines.append(f"💰 Net: {format_money(cur_bal)} ({fmt_chg(pct_change(cur_bal, prev_bal))})")
    lines.append(f"📈 Savings rate: <b>{cur_savings_rate:.1f}%</b> ({sr_chg:+.1f}pp)\n")

    if top:
        lines.append("<b>Biggest expense increases:</b>")
        for cat, p, c, d in top:
            safe_cat = escape_html(cat)
            if p > 0:
                pchg = (c - p) / p * 100
                lines.append(f"- <b>{safe_cat}</b>: {format_money(c)} ({pchg:+.1f}%, +{format_money(d)})")
            else:
                lines.append(f"- <b>{safe_cat}</b>: {format_money(c)} (new, +{format_money(d)})")
        lines.append("")

    # Recommendations (simple)
    recs = []
    if exp_chg is not None and exp_chg > 10:
        recs.append(f"Expenses increased by <b>{exp_chg:.1f}%</b> — review the categories above.")
    elif exp_chg is None and cur_exp > 0 and prev_exp == 0:
        recs.append("You had <b>new expenses</b> this month — consider setting a budget category limit.")

    if inc_chg is not None and inc_chg < -10:
        recs.append(f"Income decreased by <b>{abs(inc_chg):.1f}%</b> — be conservative with discretionary spending.")

    if cur_savings_rate < 10 and cur_income > 0:
        recs.append("Savings rate is below <b>10%</b> — try to reduce one discretionary category or increase income.")
    elif cur_income == 0 and cur_exp > 0:
        recs.append("No income recorded this month — add income entries to get accurate savings rate insights.")

    if recs:
        lines.append("<b>Recommendations:</b>")
        for r in recs[:3]:
            lines.append(f"- {r}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start income addition flow."""
    context.user_data["transaction_type"] = "income"
    await update.message.reply_text(
        "💵 Enter the income amount (numbers only):\n\nExample: <code>1500</code> or <code>1500.50</code>",
        parse_mode="HTML"
    )
    return AMOUNT


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start expense addition flow."""
    context.user_data["transaction_type"] = "expense"
    await update.message.reply_text(
        "💸 Enter the expense amount (numbers only):\n\nExample: <code>50</code> or <code>29.99</code>",
        parse_mode="HTML"
    )
    return AMOUNT


async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the amount and ask for category."""
    try:
        amount = _parse_amount(update.message.text)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        context.user_data["amount"] = amount
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid positive number.\n\nExample: <code>100</code> or <code>50.99</code>",
            parse_mode="HTML"
        )
        return AMOUNT

    trans_type = context.user_data["transaction_type"]
    categories = DEFAULT_INCOME_CATEGORIES if trans_type == "income" else DEFAULT_EXPENSE_CATEGORIES

    keyboard = []
    row = []
    for emoji_name, name in categories:
        row.append(InlineKeyboardButton(emoji_name, callback_data=f"cat_{name}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⏭️ Skip Category", callback_data="cat_skip")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📁 Select a category for your {trans_type}:",
        reply_markup=reply_markup
    )
    return CATEGORY


async def receive_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process category selection."""
    query = update.callback_query
    await query.answer()

    category_data = query.data.replace("cat_", "")
    if category_data == "skip":
        context.user_data["category"] = None
    else:
        context.user_data["category"] = category_data

    await query.edit_message_text(
        "📝 Add a description (or send /skip to skip):\n\nExample: <code>Monthly salary</code> or <code>Coffee at Starbucks</code>",
        parse_mode="HTML"
    )
    return DESCRIPTION


async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process description and save transaction."""
    description = update.message.text if update.message.text != "/skip" else None
    return await save_transaction(update, context, description)


async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip description and save transaction."""
    return await save_transaction(update, context, None)


async def save_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE, description: str):
    """Save the transaction to database."""
    user_id = update.effective_user.id
    amount = context.user_data["amount"]
    trans_type = context.user_data["transaction_type"]
    category = context.user_data.get("category")

    trans_id = db.add_transaction(user_id, amount, trans_type, category, description)

    emoji = "💵" if trans_type == "income" else "💸"
    category_text = f"\n📁 Category: {escape_html(category)}" if category else ""
    desc_text = f"\n📝 Description: {escape_html(description)}" if description else ""

    await update.message.reply_text(
        f"{emoji} <b>{escape_html(trans_type.capitalize())} Added!</b>\n\n"
        f"💰 Amount: <b>{format_money(amount)}</b>{category_text}{desc_text}\n"
        f"🔖 ID: <code>#{trans_id}</code>",
        parse_mode="HTML"
    )

    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show balance summary."""
    user_id = update.effective_user.id

    # Get overall summary
    total = db.get_summary(user_id)
    monthly = db.get_summary(user_id, days=30)

    total_saved = db.get_total_saved(user_id)
    available = total["balance"] - total_saved

    balance_text = (
        "📊 <b>Your Balance Summary</b>\n\n"
        "<b>All Time:</b>\n"
        f"💵 Income: {format_money(total['income'])}\n"
        f"💸 Expenses: {format_money(total['expense'])}\n"
        f"💰 Balance (nominal): {format_money(total['balance'])}\n"
        f"🏦 Total savings (all goals): {format_money(total_saved)}\n"
        f"💳 Available balance: <b>{format_money(available)}</b>\n\n"
        "<b>This Month (30 days):</b>\n"
        f"💵 Income: {format_money(monthly['income'])}\n"
        f"💸 Expenses: {format_money(monthly['expense'])}\n"
        f"💰 Balance: {format_money(monthly['balance'])}"
    )
    await update.message.reply_text(balance_text, parse_mode="HTML")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show transaction history."""
    user_id = update.effective_user.id

    # Get limit from args
    limit = 10
    if context.args:
        try:
            limit = min(int(context.args[0]), 50)
        except ValueError:
            pass

    transactions = db.get_transactions(user_id, limit=limit)

    if not transactions:
        await update.message.reply_text("📭 No transactions found. Start by adding /income or /expense!")
        return

    history_text = f"📜 <b>Last {len(transactions)} Transactions</b>\n\n"

    for t in transactions:
        emoji = "💵" if t["type"] == "income" else "💸"
        sign = "+" if t["type"] == "income" else "-"
        date = datetime.fromisoformat(t["created_at"]).strftime("%m/%d %H:%M")
        category = f" [{escape_html(t['category'])}]" if t["category"] else ""
        desc = f" - {escape_html(t['description'])}" if t["description"] else ""

        history_text += f"{emoji} <code>#{t['id']}</code> {sign}{format_money(t['amount'])}{category}{desc}\n   📅 {date}\n\n"

    await update.message.reply_text(history_text, parse_mode="HTML")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate financial report."""
    user_id = update.effective_user.id

    # Parse period
    period = "month"
    days = 30
    if context.args:
        arg = context.args[0].lower()
        if arg == "week":
            period = "week"
            days = 7
        elif arg == "year":
            period = "year"
            days = 365

    summary = db.get_summary(user_id, days=days)
    expense_breakdown = db.get_category_breakdown(user_id, "expense", days=days)
    income_breakdown = db.get_category_breakdown(user_id, "income", days=days)

    report_text = (
        f"📈 <b>Financial Report - Last {escape_html(period.capitalize())}</b>\n\n"
        "<b>Summary:</b>\n"
        f"💵 Total Income: {format_money(summary['income'])}\n"
        f"💸 Total Expenses: {format_money(summary['expense'])}\n"
        f"💰 Net Balance: {format_money(summary['balance'])}\n"
    )

    if expense_breakdown:
        report_text += "\n<b>💸 Expenses by Category:</b>\n"
        for item in expense_breakdown[:5]:
            pct = (item["total"] / summary["expense"] * 100) if summary["expense"] > 0 else 0
            report_text += f"  • {escape_html(item['category'])}: {format_money(item['total'])} ({pct:.1f}%)\n"

    if income_breakdown:
        report_text += "\n<b>💵 Income by Category:</b>\n"
        for item in income_breakdown[:5]:
            pct = (item["total"] / summary["income"] * 100) if summary["income"] > 0 else 0
            report_text += f"  • {escape_html(item['category'])}: {format_money(item['total'])} ({pct:.1f}%)\n"

    await update.message.reply_text(report_text, parse_mode="HTML")


async def expenses_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show expense breakdown by category."""
    user_id = update.effective_user.id
    breakdown = db.get_category_breakdown(user_id, "expense", days=30)

    if not breakdown:
        await update.message.reply_text("📭 No expenses recorded this month.")
        return

    total = sum(item["total"] for item in breakdown)
    text = "💸 <b>Expenses by Category (Last 30 Days)</b>\n\n"

    for item in breakdown:
        pct = (item["total"] / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        text += f"<b>{escape_html(item['category'])}</b>\n{bar} {format_money(item['total'])} ({pct:.1f}%)\n\n"

    text += f"<b>Total:</b> {format_money(total)}"
    await update.message.reply_text(text, parse_mode="HTML")


async def income_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show income breakdown by category."""
    user_id = update.effective_user.id
    breakdown = db.get_category_breakdown(user_id, "income", days=30)

    if not breakdown:
        await update.message.reply_text("📭 No income recorded this month.")
        return

    total = sum(item["total"] for item in breakdown)
    text = "💵 <b>Income by Category (Last 30 Days)</b>\n\n"

    for item in breakdown:
        pct = (item["total"] / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        text += f"<b>{escape_html(item['category'])}</b>\n{bar} {format_money(item['total'])} ({pct:.1f}%)\n\n"

    text += f"<b>Total:</b> {format_money(total)}"
    await update.message.reply_text(text, parse_mode="HTML")


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available categories."""
    text = "📁 <b>Available Categories</b>\n\n"

    text += "<b>💸 Expense Categories:</b>\n"
    for emoji_name, _ in DEFAULT_EXPENSE_CATEGORIES:
        text += f"  • {emoji_name}\n"

    text += "\n<b>💵 Income Categories:</b>\n"
    for emoji_name, _ in DEFAULT_INCOME_CATEGORIES:
        text += f"  • {emoji_name}\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def delete_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a transaction by ID."""
    user_id = update.effective_user.id

    if not context.args:
        # Show recent transactions to help user pick
        transactions = db.get_transactions(user_id, limit=5)
        if not transactions:
            await update.message.reply_text("📭 No transactions to delete.")
            return

        text = "🗑️ <b>Delete a Transaction</b>\n\nUsage: <code>/delete &lt;id&gt;</code>\n\nRecent transactions:\n\n"
        for t in transactions:
            emoji = "💵" if t["type"] == "income" else "💸"
            text += f"{emoji} <code>#{t['id']}</code> - {format_money(t['amount'])}"
            if t["category"]:
                text += f" [{escape_html(t['category'])}]"
            text += "\n"

        await update.message.reply_text(text, parse_mode="HTML")
        return

    try:
        trans_id = int(context.args[0].replace("#", ""))
        if db.delete_transaction(user_id, trans_id):
            await update.message.reply_text(f"✅ Transaction #{trans_id} deleted successfully!")
        else:
            await update.message.reply_text(f"❌ Transaction #{trans_id} not found.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid transaction ID.\n\nUsage: <code>/delete 123</code>", parse_mode="HTML")


async def quick_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick add transaction from message like '+100 Salary' or '-50 Coffee'."""
    text = update.message.text.strip()

    if not text or text[0] not in ["+", "-"]:
        return

    parts = text.split(maxsplit=1)
    if not parts:
        return

    try:
        amount_str = parts[0]
        sign = amount_str[0]
        amount = float(amount_str[1:].replace(",", ""))

        if amount <= 0:
            return

        trans_type = "income" if sign == "+" else "expense"
        description = parts[1] if len(parts) > 1 else None

        user_id = update.effective_user.id
        trans_id = db.add_transaction(user_id, amount, trans_type, None, description)

        emoji = "💵" if trans_type == "income" else "💸"
        desc_text = f"\n📝 {escape_html(description)}" if description else ""

        await update.message.reply_text(
            f"{emoji} <b>Quick {escape_html(trans_type)} added!</b>\n\n"
            f"💰 Amount: <b>{format_money(amount)}</b>{desc_text}\n"
            f"🔖 ID: <code>#{trans_id}</code>",
            parse_mode="HTML"
        )
    except (ValueError, IndexError):
        pass  # Not a valid quick add format, ignore


def main():
    """Run the bot."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN not found in environment variables!")
        logger.error("Please create a .env file with your BOT_TOKEN")
        return

    # Build application
    application = Application.builder().token(token).build()

    # Conversation handler for adding transactions
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("income", add_income),
            CommandHandler("expense", add_expense),
        ],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            CATEGORY: [CallbackQueryHandler(receive_category, pattern="^cat_")],
            DESCRIPTION: [
                CommandHandler("skip", skip_description),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
            ],
        },
        fallbacks=[],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("categories", categories))
    application.add_handler(CommandHandler("expenses_by_category", expenses_by_category))
    application.add_handler(CommandHandler("income_by_category", income_by_category))
    application.add_handler(CommandHandler("delete", delete_transaction))
    application.add_handler(CommandHandler("inflation_report", inflation_report))
    application.add_handler(CallbackQueryHandler(inflation_report_country_chosen, pattern="^infl_"))
    application.add_handler(CommandHandler("set_goal", set_goal))
    application.add_handler(CommandHandler("goal_status", goal_status))
    application.add_handler(CommandHandler("goals", goals))
    application.add_handler(CommandHandler("delete_goal", delete_goal))
    application.add_handler(CommandHandler("save", save_to_goal))
    application.add_handler(CommandHandler("unsave", unsave_from_goal))
    application.add_handler(CommandHandler("insights", insights))

    # Quick add handler (for messages starting with + or -)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^[+-]"),
        quick_add
    ))

    # Start the bot
    logger.info("Starting Finance Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
