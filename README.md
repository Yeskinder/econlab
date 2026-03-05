# EconLab Bot

**EconLab Bot** is a Telegram bot for tracking personal finances and generating actionable financial insights. Built with Python and SQLite, it demonstrates my programming, data analysis, and problem-solving skills applied to practical finance and business scenarios.

---

## Features

- **Track Income & Expenses** – Add transactions with categories and descriptions  
- **Quick Add** – Send `+100 Salary` or `-50 Coffee` for fast entry  
- **Balance Summary** – View your current balance and monthly overview  
- **Transaction History** – Browse your recent transactions  
- **Financial Reports** – Get weekly, monthly, or yearly reports  
- **Category Breakdown** – See spending patterns by category  
- **SQLite Database** – All data stored locally  

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and see welcome message |
| `/help` | Show all available commands |
| `/income` | Add new income |
| `/expense` | Add new expense |
| `/balance` | View balance summary |
| `/history` | View recent transactions |
| `/history 20` | View last 20 transactions |
| `/report` | Monthly financial report |
| `/report week` | Weekly report |
| `/report year` | Yearly report |
| `/categories` | View available categories |
| `/expenses_by_category` | Expense breakdown |
| `/income_by_category` | Income breakdown |
| `/delete` | Delete a transaction |
| `/cancel` | Cancel current operation |

---

## Quick Add

You can quickly add transactions by sending messages in this format:  

- `+1000 Monthly salary` – Adds $1000 income  
- `-50 Lunch with friends` – Adds $50 expense  
- `+500` – Adds $500 income (no description)  

---

## Default Categories

**Expenses:**  
- 🍔 Food  
- 🚗 Transport  
- 🏠 Housing  
- 🎬 Entertainment  
- 🛒 Shopping  
- 💊 Health  
- 📚 Education  
- 💡 Utilities  
- 📝 Other  

**Income:**  
- 💼 Salary  
- 💰 Freelance  
- 📈 Investment  
- 🎁 Gift  
- 📝 Other  

---

## Data Storage

All data is stored in a local SQLite database (`finance.db`). The database is created automatically when you first run the bot.

---

## Project Structure

telegram-finance-bot/
├── bot.py           # Main bot application
├── database.py      # Database operations
├── requirements.txt # Python dependencies
├── .env.example     # Environment template
├── .env             # Your configuration (create this)
├── finance.db       # SQLite database (auto-created)
└── README.md        # This file

---

## Technologies Used

- Python  
- SQLite  
- pandas  
- matplotlib  
- Telegram Bot API  

---

## GitHub Repository

The project code is available at: []
