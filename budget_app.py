"""Budget manager desktop application in Python.

This module provides a Tkinter based interface that mirrors the
capabilities of the HTML prototype (Budget_simple_python_V_04.4_graphique_EXCELLENT.html).
It supports transaction management, budget tracking, data import/export
and interactive charts.  A small CLI self-test is available so automated
checks can exercise the data layer without opening the graphical
interface.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import tkinter as tk
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


# Optional import of matplotlib: charts tab becomes inactive if unavailable.
try:  # pragma: no cover - availability depends on the environment
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path
    MATPLOTLIB_AVAILABLE = False
    FigureCanvasTkAgg = None
    Figure = None


DATA_FILE = Path("DATA/budget_state.json")


def parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD or DD/MM/YYYY string into a :class:`date`.

    Args:
        value: The textual representation of the date.

    Raises:
        ValueError: If the text cannot be parsed.
    """

    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Date invalide : {value!r}. Utilisez AAAA-MM-JJ.")


def format_currency(amount: float) -> str:
    """Format a number as currency with two decimals and thousands separators."""

    sign = "+" if amount >= 0 else "-"
    return f"{sign}{abs(amount):,.2f} €".replace(",", " ")


def month_key(value: date) -> str:
    """Return a key usable for grouping by month (YYYY-MM)."""

    return value.strftime("%Y-%m")


def month_label(value: str) -> str:
    """Return a human readable label for a YYYY-MM key."""

    dt = datetime.strptime(value, "%Y-%m")
    return dt.strftime("%B %Y").capitalize()


def first_day_of_month(dt: date) -> date:
    return date(dt.year, dt.month, 1)


def current_month() -> date:
    today = date.today()
    return first_day_of_month(today)


@dataclass
class Transaction:
    id: str
    date: date
    description: str
    category: str
    amount: float
    type: str  # "income" or "expense"
    notes: str = ""

    @property
    def signed_amount(self) -> float:
        return self.amount if self.type == "income" else -abs(self.amount)

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Transaction":
        return Transaction(
            id=str(data.get("id") or uuid4()),
            date=parse_date(str(data["date"])),
            description=str(data.get("description", "")),
            category=str(data.get("category", "Autre")),
            amount=float(data.get("amount", 0.0)),
            type=str(data.get("type", "expense")),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "description": self.description,
            "category": self.category,
            "amount": round(float(self.amount), 2),
            "type": self.type,
            "notes": self.notes,
        }


@dataclass
class Budget:
    id: str
    category: str
    monthly_limit: float

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Budget":
        return Budget(
            id=str(data.get("id") or uuid4()),
            category=str(data.get("category", "Autre")),
            monthly_limit=float(data.get("monthly_limit", data.get("limit", 0.0))),
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "category": self.category,
            "monthly_limit": round(float(self.monthly_limit), 2),
        }


@dataclass
class BudgetData:
    """In-memory representation of the budget state with persistence helpers."""

    storage_path: Path
    transactions: List[Transaction] = field(default_factory=list)
    budgets: List[Budget] = field(default_factory=list)

    def load(self) -> None:
        if not self.storage_path.exists():
            return
        raw = json.loads(self.storage_path.read_text(encoding="utf8"))
        self.transactions = [Transaction.from_dict(t) for t in raw.get("transactions", [])]
        self.budgets = [Budget.from_dict(b) for b in raw.get("budgets", [])]

    def save(self) -> None:
        payload = {
            "transactions": [t.to_dict() for t in self.transactions],
            "budgets": [b.to_dict() for b in self.budgets],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def add_transaction(self, *, date_value: date, description: str, category: str,
                         amount: float, type_: str, notes: str = "") -> Transaction:
        trx = Transaction(id=str(uuid4()), date=date_value, description=description,
                          category=category or "Autre", amount=abs(float(amount)),
                          type=type_, notes=notes)
        self.transactions.append(trx)
        self.transactions.sort(key=lambda t: (t.date, t.description))
        return trx

    def update_transaction(self, trx_id: str, **updates: object) -> None:
        trx = self.get_transaction(trx_id)
        if not trx:
            raise KeyError(f"Transaction {trx_id} introuvable")
        if "date" in updates or "date_value" in updates:
            value = updates.get("date") or updates.get("date_value")
            if isinstance(value, date):
                trx.date = value
            else:
                trx.date = parse_date(str(value))
        if "description" in updates:
            trx.description = str(updates["description"])
        if "category" in updates:
            trx.category = str(updates["category"])
        if "amount" in updates:
            trx.amount = abs(float(updates["amount"]))
        if "type" in updates or "type_" in updates:
            trx.type = str(updates.get("type") or updates.get("type_"))
        if "notes" in updates:
            trx.notes = str(updates["notes"])

    def delete_transaction(self, trx_id: str) -> None:
        self.transactions = [t for t in self.transactions if t.id != trx_id]

    def get_transaction(self, trx_id: str) -> Optional[Transaction]:
        for trx in self.transactions:
            if trx.id == trx_id:
                return trx
        return None

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------
    def add_budget(self, *, category: str, monthly_limit: float) -> Budget:
        budget = Budget(id=str(uuid4()), category=category or "Autre",
                        monthly_limit=abs(float(monthly_limit)))
        self.budgets.append(budget)
        self.budgets.sort(key=lambda b: b.category.lower())
        return budget

    def update_budget(self, budget_id: str, *, category: Optional[str] = None,
                      monthly_limit: Optional[float] = None) -> None:
        budget = self.get_budget(budget_id)
        if not budget:
            raise KeyError(f"Budget {budget_id} introuvable")
        if category is not None:
            budget.category = category
        if monthly_limit is not None:
            budget.monthly_limit = abs(float(monthly_limit))

    def delete_budget(self, budget_id: str) -> None:
        self.budgets = [b for b in self.budgets if b.id != budget_id]

    def get_budget(self, budget_id: str) -> Optional[Budget]:
        for budget in self.budgets:
            if budget.id == budget_id:
                return budget
        return None

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------
    def transactions_for_month(self, month: Optional[str]) -> List[Transaction]:
        if not month:
            return list(self.transactions)
        return [t for t in self.transactions if month_key(t.date) == month]

    def monthly_summary(self, month: Optional[str]) -> Dict[str, float]:
        items = self.transactions_for_month(month)
        incomes = sum(t.amount for t in items if t.type == "income")
        expenses = sum(t.amount for t in items if t.type == "expense")
        balance = sum(t.signed_amount for t in items)
        return {"incomes": incomes, "expenses": expenses, "balance": balance}

    def category_totals(self, month: Optional[str], *, for_expenses: bool = True) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        for trx in self.transactions_for_month(month):
            if for_expenses and trx.type != "expense":
                continue
            if not for_expenses and trx.type != "income":
                continue
            totals[trx.category] = totals.get(trx.category, 0.0) + abs(trx.signed_amount)
        return totals

    def monthly_balances(self) -> List[Tuple[str, float]]:
        buckets: Dict[str, float] = {}
        for trx in self.transactions:
            buckets.setdefault(month_key(trx.date), 0.0)
            buckets[month_key(trx.date)] += trx.signed_amount
        return sorted(buckets.items())

    def budget_analysis(self, month: Optional[str]) -> List[Dict[str, object]]:
        totals = self.category_totals(month, for_expenses=True)
        analysis = []
        for budget in self.budgets:
            spent = totals.get(budget.category, 0.0)
            remaining = budget.monthly_limit - spent
            pct = 0.0 if budget.monthly_limit == 0 else min(1.0, spent / budget.monthly_limit)
            analysis.append({
                "budget": budget,
                "spent": spent,
                "remaining": remaining,
                "ratio": pct,
            })
        analysis.sort(key=lambda item: item["budget"].category.lower())
        return analysis

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------
    def import_csv(self, path: Path) -> int:
        added = 0
        with path.open("r", encoding="utf8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    trx_date = parse_date(row.get("Date", row.get("date", "")))
                    description = row.get("Description", row.get("description", ""))
                    category = row.get("Catégorie", row.get("category", "Autre"))
                    amount = float(row.get("Montant", row.get("amount", 0)))
                except Exception as exc:  # pragma: no cover - depends on data
                    print(f"Ligne ignorée ({exc}): {row}")
                    continue
                type_ = row.get("Type", row.get("type", "expense")).lower()
                if not description:
                    description = "(sans libellé)"
                if type_ not in {"income", "expense"}:
                    type_ = "income" if amount >= 0 else "expense"
                self.add_transaction(
                    date_value=trx_date,
                    description=description,
                    category=category,
                    amount=abs(amount),
                    type_=type_,
                )
                added += 1
        return added

    def export_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["Date", "Description", "Catégorie", "Montant", "Type", "Notes"],
            )
            writer.writeheader()
            for trx in self.transactions:
                writer.writerow({
                    "Date": trx.date.strftime("%Y-%m-%d"),
                    "Description": trx.description,
                    "Catégorie": trx.category,
                    "Montant": trx.signed_amount,
                    "Type": "income" if trx.type == "income" else "expense",
                    "Notes": trx.notes,
                })

    def import_json(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf8"))
        transactions = [Transaction.from_dict(t) for t in raw.get("transactions", [])]
        budgets = [Budget.from_dict(b) for b in raw.get("budgets", [])]
        self.transactions.extend(transactions)
        self.budgets.extend(budgets)
        self.transactions.sort(key=lambda t: (t.date, t.description))
        self.budgets.sort(key=lambda b: b.category.lower())

    def export_json(self, path: Path) -> None:
        payload = {
            "transactions": [t.to_dict() for t in self.transactions],
            "budgets": [b.to_dict() for b in self.budgets],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")


class TransactionDialog(tk.Toplevel):
    """Modal dialog used to create or edit a transaction."""

    def __init__(self, master: tk.Widget, *, title: str, initial: Optional[Transaction] = None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.result: Optional[Dict[str, object]] = None

        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Date (AAAA-MM-JJ)").grid(row=0, column=0, sticky="w", padx=8, pady=(10, 4))
        self.date_var = tk.StringVar(value=initial.date.isoformat() if initial else date.today().isoformat())
        ttk.Entry(self, textvariable=self.date_var, width=18).grid(row=0, column=1, sticky="ew", padx=8, pady=(10, 4))

        ttk.Label(self, text="Description").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.description_var = tk.StringVar(value=initial.description if initial else "")
        ttk.Entry(self, textvariable=self.description_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(self, text="Catégorie").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.category_var = tk.StringVar(value=initial.category if initial else "Autre")
        ttk.Entry(self, textvariable=self.category_var).grid(row=2, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(self, text="Type").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        self.type_var = tk.StringVar(value=initial.type if initial else "expense")
        ttk.Combobox(self, textvariable=self.type_var, state="readonly",
                     values=["income", "expense"]).grid(row=3, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(self, text="Montant").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        self.amount_var = tk.StringVar(value=f"{initial.amount:.2f}" if initial else "0.00")
        ttk.Entry(self, textvariable=self.amount_var).grid(row=4, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(self, text="Notes").grid(row=5, column=0, sticky="nw", padx=8, pady=4)
        self.notes_var = tk.Text(self, height=4, width=40)
        if initial:
            self.notes_var.insert("1.0", initial.notes)
        self.notes_var.grid(row=5, column=1, sticky="ew", padx=8, pady=4)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)

        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Enregistrer", command=self._save).pack(side=tk.RIGHT, padx=4)

        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.wait_visibility()
        self.focus()

    def _save(self) -> None:
        try:
            trx_date = parse_date(self.date_var.get())
            amount = float(self.amount_var.get().replace(",", "."))
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc), parent=self)
            return
        self.result = {
            "date": trx_date,
            "description": self.description_var.get().strip() or "(sans libellé)",
            "category": self.category_var.get().strip() or "Autre",
            "type": self.type_var.get(),
            "amount": abs(amount),
            "notes": self.notes_var.get("1.0", tk.END).strip(),
        }
        self.destroy()


class BudgetDialog(tk.Toplevel):
    def __init__(self, master: tk.Widget, *, title: str, initial: Optional[Budget] = None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result: Optional[Dict[str, object]] = None

        ttk.Label(self, text="Catégorie").grid(row=0, column=0, sticky="w", padx=8, pady=(12, 4))
        self.category_var = tk.StringVar(value=initial.category if initial else "Autre")
        ttk.Entry(self, textvariable=self.category_var, width=30).grid(row=0, column=1, padx=8, pady=(12, 4))

        ttk.Label(self, text="Plafond mensuel (€)").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.limit_var = tk.StringVar(value=f"{initial.monthly_limit:.2f}" if initial else "0.00")
        ttk.Entry(self, textvariable=self.limit_var, width=15).grid(row=1, column=1, padx=8, pady=4)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="Enregistrer", command=self._save).pack(side=tk.RIGHT, padx=4)

        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.wait_visibility()
        self.focus()

    def _save(self) -> None:
        try:
            limit = float(self.limit_var.get().replace(",", "."))
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc), parent=self)
            return
        self.result = {
            "category": self.category_var.get().strip() or "Autre",
            "monthly_limit": abs(limit),
        }
        self.destroy()


class BudgetApp(tk.Tk):
    """Main Tkinter application."""

    def __init__(self, storage_path: Path = DATA_FILE):
        super().__init__()
        self.title("Gestionnaire de budget — Édition Python")
        self.geometry("1200x720")

        self.data = BudgetData(storage_path)
        self.data.load()

        self.selected_month: Optional[str] = None

        self._build_menu()
        self._build_layout()
        self.refresh_all()

    # ------------------------------------------------------------------
    # UI creation helpers
    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Enregistrer", command=self._save_state)
        file_menu.add_command(label="Exporter en CSV", command=self._export_csv)
        file_menu.add_command(label="Exporter en JSON", command=self._export_json)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.destroy)
        menu_bar.add_cascade(label="Fichier", menu=file_menu)

        data_menu = tk.Menu(menu_bar, tearoff=False)
        data_menu.add_command(label="Importer CSV", command=self._import_csv)
        data_menu.add_command(label="Importer JSON", command=self._import_json)
        data_menu.add_separator()
        data_menu.add_command(label="Instantané (enregistrer sous)", command=self._snapshot)
        data_menu.add_command(label="Charger un instantané", command=self._load_snapshot)
        menu_bar.add_cascade(label="Données", menu=data_menu)

        self.config(menu=menu_bar)

    def _build_layout(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self.month_var = tk.StringVar(value="(Tout)")
        months_frame = ttk.Frame(container)
        months_frame.pack(fill=tk.X, padx=12, pady=8)
        ttk.Label(months_frame, text="Période analysée :").pack(side=tk.LEFT)
        self.month_combo = ttk.Combobox(months_frame, textvariable=self.month_var, width=30, state="readonly")
        self.month_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_month_change())
        self.month_combo.pack(side=tk.LEFT, padx=8)
        ttk.Button(months_frame, text="Mois courant", command=self._reset_month).pack(side=tk.LEFT)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.dashboard_frame = ttk.Frame(self.notebook, padding=12)
        self.transactions_frame = ttk.Frame(self.notebook, padding=12)
        self.budgets_frame = ttk.Frame(self.notebook, padding=12)
        self.charts_frame = ttk.Frame(self.notebook, padding=12)
        self.import_frame = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.dashboard_frame, text="Tableau de bord")
        self.notebook.add(self.transactions_frame, text="Transactions")
        self.notebook.add(self.budgets_frame, text="Budgets")
        if MATPLOTLIB_AVAILABLE:
            self.notebook.add(self.charts_frame, text="Graphiques")
        else:
            label = ttk.Label(self.charts_frame, text="Matplotlib est indisponible. Les graphiques sont désactivés.")
            label.pack()
            self.notebook.add(self.charts_frame, text="Graphiques (indispo)")
        self.notebook.add(self.import_frame, text="Import / Export")

        self._build_dashboard_tab()
        self._build_transactions_tab()
        self._build_budgets_tab()
        self._build_charts_tab()
        self._build_import_tab()

    def _build_dashboard_tab(self) -> None:
        cards = ttk.Frame(self.dashboard_frame)
        cards.pack(fill=tk.X, pady=6)

        self.income_label = ttk.Label(cards, text="Revenus : 0 €", font=("Segoe UI", 14, "bold"))
        self.expense_label = ttk.Label(cards, text="Dépenses : 0 €", font=("Segoe UI", 14, "bold"))
        self.balance_label = ttk.Label(cards, text="Solde : 0 €", font=("Segoe UI", 14, "bold"))

        self.income_label.pack(anchor="w", pady=4)
        self.expense_label.pack(anchor="w", pady=4)
        self.balance_label.pack(anchor="w", pady=4)

        self.budget_list = ttk.Treeview(self.dashboard_frame, columns=("cat", "limit", "spent", "remaining"), show="headings")
        self.budget_list.heading("cat", text="Catégorie")
        self.budget_list.heading("limit", text="Budget")
        self.budget_list.heading("spent", text="Dépensé")
        self.budget_list.heading("remaining", text="Reste")
        self.budget_list.column("cat", width=200)
        self.budget_list.pack(fill=tk.BOTH, expand=True, pady=8)

    def _build_transactions_tab(self) -> None:
        filter_frame = ttk.Frame(self.transactions_frame)
        filter_frame.pack(fill=tk.X)

        ttk.Label(filter_frame, text="Recherche").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=40)
        search_entry.pack(side=tk.LEFT, padx=8)
        search_entry.bind("<KeyRelease>", lambda _event: self.refresh_transactions())

        ttk.Label(filter_frame, text="Type").pack(side=tk.LEFT)
        self.type_filter_var = tk.StringVar(value="all")
        type_combo = ttk.Combobox(filter_frame, textvariable=self.type_filter_var,
                                  values=["all", "income", "expense"], width=10, state="readonly")
        type_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_transactions())
        type_combo.pack(side=tk.LEFT, padx=8)

        columns = ("date", "description", "category", "type", "amount")
        self.transactions_tree = ttk.Treeview(self.transactions_frame, columns=columns, show="headings")
        for col, title in zip(columns, ["Date", "Description", "Catégorie", "Type", "Montant"]):
            self.transactions_tree.heading(col, text=title)
            anchor = tk.E if col == "amount" else tk.W
            width = 120 if col in {"date", "type"} else 200
            self.transactions_tree.column(col, width=width, anchor=anchor)
        self.transactions_tree.pack(fill=tk.BOTH, expand=True, pady=8)

        btn_frame = ttk.Frame(self.transactions_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Ajouter", command=self._add_transaction).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Modifier", command=self._edit_transaction).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Supprimer", command=self._delete_transaction).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Dupliquer", command=self._duplicate_transaction).pack(side=tk.LEFT, padx=4, pady=4)

    def _build_budgets_tab(self) -> None:
        columns = ("category", "limit", "spent", "remaining")
        self.budgets_tree = ttk.Treeview(self.budgets_frame, columns=columns, show="headings")
        for col, title in zip(columns, ["Catégorie", "Budget", "Dépensé", "Reste"]):
            anchor = tk.E if col in {"limit", "spent", "remaining"} else tk.W
            width = 160 if col == "category" else 100
            self.budgets_tree.heading(col, text=title)
            self.budgets_tree.column(col, anchor=anchor, width=width)
        self.budgets_tree.pack(fill=tk.BOTH, expand=True, pady=8)

        btn_frame = ttk.Frame(self.budgets_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Ajouter un budget", command=self._add_budget).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Modifier", command=self._edit_budget).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btn_frame, text="Supprimer", command=self._delete_budget).pack(side=tk.LEFT, padx=4, pady=4)

    def _build_charts_tab(self) -> None:
        if not MATPLOTLIB_AVAILABLE:
            return
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.charts_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_import_tab(self) -> None:
        ttk.Label(self.import_frame,
                  text="Importez ou exportez vos données au format CSV/JSON."
                  ).pack(anchor="w")

        ttk.Button(self.import_frame, text="Importer CSV", command=self._import_csv).pack(anchor="w", pady=6)
        ttk.Button(self.import_frame, text="Importer JSON", command=self._import_json).pack(anchor="w", pady=6)
        ttk.Button(self.import_frame, text="Exporter CSV", command=self._export_csv).pack(anchor="w", pady=6)
        ttk.Button(self.import_frame, text="Exporter JSON", command=self._export_json).pack(anchor="w", pady=6)
        ttk.Button(self.import_frame, text="Sauvegarder", command=self._save_state).pack(anchor="w", pady=6)

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------
    def refresh_all(self) -> None:
        self._update_month_choices()
        self.refresh_dashboard()
        self.refresh_transactions()
        self.refresh_budgets()
        self.refresh_charts()

    def _update_month_choices(self) -> None:
        months = sorted({month_key(trx.date) for trx in self.data.transactions})
        values = ["(Tout)"] + [month_label(m) for m in months]
        self.month_combo["values"] = values
        if self.selected_month:
            label = month_label(self.selected_month)
            if label in values:
                self.month_var.set(label)
            else:
                self.month_var.set("(Tout)")
                self.selected_month = None
        else:
            self.month_var.set("(Tout)")

    def _month_from_label(self, label: str) -> Optional[str]:
        if label == "(Tout)":
            return None
        for trx in self.data.transactions:
            if month_label(month_key(trx.date)) == label:
                return month_key(trx.date)
        # fallback: parse again
        try:
            dt = datetime.strptime(label, "%B %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return None

    def refresh_dashboard(self) -> None:
        summary = self.data.monthly_summary(self.selected_month)
        self.income_label.config(text=f"Revenus : {format_currency(summary['incomes'])}")
        self.expense_label.config(text=f"Dépenses : {format_currency(-summary['expenses'])}")
        self.balance_label.config(text=f"Solde : {format_currency(summary['balance'])}")

        for item in self.budget_list.get_children():
            self.budget_list.delete(item)
        for entry in self.data.budget_analysis(self.selected_month):
            budget = entry["budget"]
            spent = entry["spent"]
            remaining = entry["remaining"]
            self.budget_list.insert("", tk.END, values=(
                budget.category,
                format_currency(budget.monthly_limit),
                format_currency(-spent),
                format_currency(remaining),
            ))

    def refresh_transactions(self) -> None:
        search = self.search_var.get().strip().lower()
        type_filter = self.type_filter_var.get()
        for item in self.transactions_tree.get_children():
            self.transactions_tree.delete(item)
        for trx in self.data.transactions_for_month(self.selected_month):
            if search and search not in trx.description.lower() and search not in trx.category.lower():
                continue
            if type_filter != "all" and trx.type != type_filter:
                continue
            self.transactions_tree.insert(
                "", tk.END, iid=trx.id, values=(
                    trx.date.strftime("%Y-%m-%d"),
                    trx.description,
                    trx.category,
                    "Revenu" if trx.type == "income" else "Dépense",
                    format_currency(trx.signed_amount),
                ))

    def refresh_budgets(self) -> None:
        for item in self.budgets_tree.get_children():
            self.budgets_tree.delete(item)
        analysis = self.data.budget_analysis(self.selected_month)
        for entry in analysis:
            budget = entry["budget"]
            spent = entry["spent"]
            remaining = entry["remaining"]
            self.budgets_tree.insert("", tk.END, iid=budget.id, values=(
                budget.category,
                format_currency(budget.monthly_limit),
                format_currency(-spent),
                format_currency(remaining),
            ))

    def refresh_charts(self) -> None:
        if not MATPLOTLIB_AVAILABLE:
            return
        self.figure.clf()
        totals = self.data.category_totals(self.selected_month, for_expenses=True)
        if totals:
            ax1 = self.figure.add_subplot(121)
            labels = list(totals.keys())
            values = list(totals.values())
            ax1.pie(values, labels=labels, autopct="%1.1f%%", startangle=140)
            ax1.set_title("Répartition des dépenses")
        balances = self.data.monthly_balances()
        if balances:
            ax2 = self.figure.add_subplot(122)
            months, values = zip(*balances)
            ax2.plot(range(len(months)), values, marker="o")
            ax2.set_xticks(range(len(months)))
            ax2.set_xticklabels([month_label(m) for m in months], rotation=45, ha="right")
            ax2.set_title("Solde par mois")
            ax2.grid(True, alpha=0.3)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_month_change(self) -> None:
        self.selected_month = self._month_from_label(self.month_var.get())
        self.refresh_all()

    def _reset_month(self) -> None:
        self.selected_month = month_key(current_month())
        self.refresh_all()

    def _get_selected_transaction_id(self) -> Optional[str]:
        selection = self.transactions_tree.selection()
        return selection[0] if selection else None

    def _add_transaction(self) -> None:
        dialog = TransactionDialog(self, title="Nouvelle transaction")
        self.wait_window(dialog)
        if not dialog.result:
            return
        self.data.add_transaction(
            date_value=dialog.result["date"],
            description=dialog.result["description"],
            category=dialog.result["category"],
            amount=float(dialog.result["amount"]),
            type_=dialog.result["type"],
            notes=str(dialog.result["notes"]),
        )
        self._after_data_change()

    def _edit_transaction(self) -> None:
        trx_id = self._get_selected_transaction_id()
        if not trx_id:
            messagebox.showinfo("Modification", "Sélectionnez une transaction.", parent=self)
            return
        trx = self.data.get_transaction(trx_id)
        if not trx:
            return
        dialog = TransactionDialog(self, title="Modifier la transaction", initial=trx)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self.data.update_transaction(
            trx_id,
            date=dialog.result["date"],
            description=dialog.result["description"],
            category=dialog.result["category"],
            amount=float(dialog.result["amount"]),
            type=dialog.result["type"],
            notes=str(dialog.result["notes"]),
        )
        self._after_data_change()

    def _duplicate_transaction(self) -> None:
        trx_id = self._get_selected_transaction_id()
        if not trx_id:
            messagebox.showinfo("Duplication", "Sélectionnez une transaction.", parent=self)
            return
        trx = self.data.get_transaction(trx_id)
        if not trx:
            return
        copy = self.data.add_transaction(
            date_value=trx.date,
            description=trx.description,
            category=trx.category,
            amount=trx.amount,
            type_=trx.type,
            notes=trx.notes,
        )
        self.selected_month = month_key(copy.date)
        self._after_data_change()

    def _delete_transaction(self) -> None:
        trx_id = self._get_selected_transaction_id()
        if not trx_id:
            messagebox.showinfo("Suppression", "Sélectionnez une transaction.", parent=self)
            return
        if not messagebox.askyesno("Confirmation", "Supprimer la transaction sélectionnée ?", parent=self):
            return
        self.data.delete_transaction(trx_id)
        self._after_data_change()

    def _get_selected_budget_id(self) -> Optional[str]:
        selection = self.budgets_tree.selection()
        return selection[0] if selection else None

    def _add_budget(self) -> None:
        dialog = BudgetDialog(self, title="Nouveau budget")
        self.wait_window(dialog)
        if not dialog.result:
            return
        self.data.add_budget(
            category=dialog.result["category"],
            monthly_limit=float(dialog.result["monthly_limit"]),
        )
        self._after_data_change()

    def _edit_budget(self) -> None:
        budget_id = self._get_selected_budget_id()
        if not budget_id:
            messagebox.showinfo("Modification", "Sélectionnez un budget.", parent=self)
            return
        budget = self.data.get_budget(budget_id)
        if not budget:
            return
        dialog = BudgetDialog(self, title="Modifier le budget", initial=budget)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self.data.update_budget(budget_id,
                                category=dialog.result["category"],
                                monthly_limit=float(dialog.result["monthly_limit"]))
        self._after_data_change()

    def _delete_budget(self) -> None:
        budget_id = self._get_selected_budget_id()
        if not budget_id:
            messagebox.showinfo("Suppression", "Sélectionnez un budget.", parent=self)
            return
        if not messagebox.askyesno("Confirmation", "Supprimer le budget sélectionné ?", parent=self):
            return
        self.data.delete_budget(budget_id)
        self._after_data_change()

    def _after_data_change(self) -> None:
        self.data.save()
        self.refresh_all()

    # ------------------------------------------------------------------
    # File operations (dialogs)
    # ------------------------------------------------------------------
    def _save_state(self) -> None:
        self.data.save()
        messagebox.showinfo("Sauvegarde", "Les données ont été enregistrées.", parent=self)

    def _snapshot(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.data.export_json(Path(path))
        messagebox.showinfo("Instantané", "Instantané enregistré.", parent=self)

    def _load_snapshot(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf8"))
        except Exception as exc:
            messagebox.showerror("Erreur", f"Impossible de lire le fichier : {exc}", parent=self)
            return
        self.data.transactions = [Transaction.from_dict(t) for t in raw.get("transactions", [])]
        self.data.budgets = [Budget.from_dict(b) for b in raw.get("budgets", [])]
        self._after_data_change()

    def _import_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("CSV", "*.csv"), ("Tous", "*.*")])
        if not path:
            return
        added = self.data.import_csv(Path(path))
        self._after_data_change()
        messagebox.showinfo("Import CSV", f"{added} transaction(s) importée(s).", parent=self)

    def _import_json(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("JSON", "*.json"), ("Tous", "*.*")])
        if not path:
            return
        self.data.import_json(Path(path))
        self._after_data_change()
        messagebox.showinfo("Import JSON", "Import terminé.", parent=self)

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        self.data.export_csv(Path(path))
        messagebox.showinfo("Export CSV", "Fichier exporté.", parent=self)

    def _export_json(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.data.export_json(Path(path))
        messagebox.showinfo("Export JSON", "Fichier exporté.", parent=self)

    # ------------------------------------------------------------------
    # CLI helpers
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.mainloop()


def run_self_test(storage_path: Path) -> None:
    """Exercise the data layer so automated checks can run without GUI."""

    data = BudgetData(storage_path)
    data.transactions.clear()
    data.budgets.clear()

    data.add_transaction(date_value=date(2024, 12, 1), description="Salaire", category="Revenus",
                          amount=3200, type_="income")
    data.add_transaction(date_value=date(2024, 12, 5), description="Loyer", category="Logement",
                          amount=900, type_="expense")
    data.add_transaction(date_value=date(2024, 12, 12), description="Courses", category="Alimentation",
                          amount=220.5, type_="expense")
    data.add_budget(category="Logement", monthly_limit=950)
    data.add_budget(category="Alimentation", monthly_limit=350)

    summary = data.monthly_summary("2024-12")
    assert math.isclose(summary["incomes"], 3200)
    assert math.isclose(summary["expenses"], 1120.5)
    assert math.isclose(summary["balance"], 2079.5)

    analysis = data.budget_analysis("2024-12")
    assert len(analysis) == 2
    assert any(abs(item["spent"] - 900) < 1e-6 for item in analysis)

    tmp = storage_path.with_suffix(".tmp.json")
    data.export_json(tmp)
    clone = BudgetData(storage_path)
    clone.import_json(tmp)
    assert len(clone.transactions) >= 3
    tmp.unlink(missing_ok=True)

    print("Self-test terminé avec succès.")


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Gestionnaire de budget graphique en Python")
    parser.add_argument("--self-test", action="store_true", help="Exécuter les tests internes sans interface graphique")
    parser.add_argument("--storage", type=Path, default=DATA_FILE, help="Chemin du fichier de données")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        run_self_test(args.storage)
        return

    app = BudgetApp(storage_path=args.storage)
    app.run()


if __name__ == "__main__":
    main()

