"""Tkinter budget manager derived from HTML prototype features."""

from __future__ import annotations

import argparse
import csv
import json
import locale
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from uuid import uuid4

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:  # Charts are optional
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB = True
except Exception:  # pragma: no cover - optional dependency
    MATPLOTLIB = False
    FigureCanvasTkAgg = Figure = None


DATA_FILE = Path("DATA/budget_state.json")
DATE_FORMATS: Sequence[str] = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")

def _ensure_locale() -> None:
    try:
        locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
    except Exception:  # pragma: no cover
        pass


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("Date invalide (utiliser AAAA-MM-JJ).")


def format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def format_currency(amount: float) -> str:
    _ensure_locale()
    try:
        return locale.currency(amount, grouping=True)
    except Exception:  # pragma: no cover
        return f"{amount:,.2f} €".replace(",", " ")


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def month_label(key: str) -> str:
    dt = datetime.strptime(key, "%Y-%m")
    return dt.strftime("%B %Y").capitalize()


@dataclass
class Transaction:
    id: str
    date: date
    description: str
    category: str
    type: str  # "income" or "expense"
    amount: float
    notes: str = ""

    @property
    def signed(self) -> float:
        return self.amount if self.type == "income" else -abs(self.amount)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Transaction":
        return cls(
            id=str(data.get("id")),
            date=parse_date(str(data["date"])),
            description=str(data.get("description", "")),
            category=str(data.get("category", "Autre")),
            type=str(data.get("type", "expense")),
            amount=float(data.get("amount", 0.0)),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["date"] = format_date(self.date)
        return payload


@dataclass
class Budget:
    id: str
    category: str
    monthly_limit: float

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Budget":
        return cls(
            id=str(data.get("id")),
            category=str(data.get("category", "Autre")),
            monthly_limit=float(data.get("monthly_limit", data.get("limit", 0.0))),
        )

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class BudgetState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.transactions: List[Transaction] = []
        self.budgets: List[Budget] = []

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.transactions = [Transaction.from_dict(t) for t in raw.get("transactions", [])]
        self.budgets = [Budget.from_dict(b) for b in raw.get("budgets", [])]

    def save(self) -> None:
        payload = {
            "transactions": [t.to_dict() for t in self.transactions],
            "budgets": [b.to_dict() for b in self.budgets],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def months(self) -> List[str]:
        keys = sorted({month_key(t.date) for t in self.transactions})
        return keys

    def transactions_for_month(self, key: Optional[str]) -> List[Transaction]:
        if not key:
            return list(self.transactions)
        return [t for t in self.transactions if month_key(t.date) == key]

    def totals_for_month(self, key: Optional[str]) -> Dict[str, float]:
        selected = self.transactions_for_month(key)
        incomes = sum(t.amount for t in selected if t.type == "income")
        expenses = sum(t.amount for t in selected if t.type == "expense")
        net = sum(t.signed for t in selected)
        return {"income": incomes, "expense": expenses, "net": net}

    def budgets_usage(self, key: Optional[str]) -> List[Dict[str, float]]:
        txs = self.transactions_for_month(key)
        groups: Dict[str, float] = {}
        for tx in txs:
            if tx.type != "expense":
                continue
            groups[tx.category] = groups.get(tx.category, 0.0) + tx.amount
        rows: List[Dict[str, float]] = []
        for budget in self.budgets:
            used = groups.get(budget.category, 0.0)
            rows.append(
                {
                    "category": budget.category,
                    "limit": budget.monthly_limit,
                    "used": used,
                    "remaining": budget.monthly_limit - used,
                }
            )
        for category, used in groups.items():
            if not any(b.category == category for b in self.budgets):
                rows.append({"category": category, "limit": 0.0, "used": used, "remaining": -used})
        rows.sort(key=lambda r: r["category"].lower())
        return rows

    def monthly_series(self, limit: int = 6) -> List[Dict[str, float]]:
        months = sorted({month_key(t.date) for t in self.transactions})[-limit:]
        series: List[Dict[str, float]] = []
        for key in months:
            totals = self.totals_for_month(key)
            series.append({"month": key, **totals})
        return series


# ----------------------------------------------------------------------
# Dialogs
# ----------------------------------------------------------------------
class TransactionDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, title: str, transaction: Optional[Transaction] = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: Optional[Transaction] = None
        self._original_id = transaction.id if transaction else None

        self.var_date = tk.StringVar(value=format_date(transaction.date) if transaction else "")
        self.var_desc = tk.StringVar(value=transaction.description if transaction else "")
        self.var_category = tk.StringVar(value=transaction.category if transaction else "Autre")
        self.var_amount = tk.StringVar(value=f"{transaction.amount:.2f}" if transaction else "")
        self.var_type = tk.StringVar(value=transaction.type if transaction else "expense")
        self.var_notes = tk.StringVar(value=transaction.notes if transaction else "")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        def row(label: str, widget: tk.Widget, r: int) -> None:
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=4)
            widget.grid(row=r, column=1, sticky="ew", pady=4)

        entry_date = ttk.Entry(body, textvariable=self.var_date)
        row("Date (AAAA-MM-JJ)", entry_date, 0)

        entry_desc = ttk.Entry(body, textvariable=self.var_desc)
        row("Description", entry_desc, 1)

        entry_cat = ttk.Entry(body, textvariable=self.var_category)
        row("Catégorie", entry_cat, 2)

        combo_type = ttk.Combobox(body, textvariable=self.var_type, values=("income", "expense"), state="readonly")
        row("Type", combo_type, 3)

        entry_amount = ttk.Entry(body, textvariable=self.var_amount)
        row("Montant", entry_amount, 4)

        entry_notes = ttk.Entry(body, textvariable=self.var_notes)
        row("Notes", entry_notes, 5)

        body.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Annuler", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(button_frame, text="Enregistrer", command=self._submit).pack(side="right", padx=4)

        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.grab_set()
        entry_date.focus_set()

    def _submit(self) -> None:
        try:
            tx_date = parse_date(self.var_date.get())
            amount = float(self.var_amount.get().replace(",", "."))
        except ValueError as exc:
            messagebox.showerror("Erreur", str(exc), parent=self)
            return
        self.result = Transaction(
            id=self._original_id or uuid4().hex,
            date=tx_date,
            description=self.var_desc.get().strip(),
            category=self.var_category.get().strip() or "Autre",
            type=self.var_type.get(),
            amount=abs(amount),
            notes=self.var_notes.get().strip(),
        )
        self.destroy()


class BudgetDialog(tk.Toplevel):
    def __init__(self, parent: tk.Widget, title: str, budget: Optional[Budget] = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: Optional[Budget] = None
        self._original_id = budget.id if budget else None

        self.var_category = tk.StringVar(value=budget.category if budget else "Autre")
        self.var_limit = tk.StringVar(value=f"{budget.monthly_limit:.2f}" if budget else "")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Catégorie").grid(row=0, column=0, sticky="w", pady=4)
        entry_category = ttk.Entry(body, textvariable=self.var_category)
        entry_category.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="Plafond mensuel").grid(row=1, column=0, sticky="w", pady=4)
        entry_limit = ttk.Entry(body, textvariable=self.var_limit)
        entry_limit.grid(row=1, column=1, sticky="ew", pady=4)

        body.columnconfigure(1, weight=1)

        button_frame = ttk.Frame(self, padding=(16, 0, 16, 16))
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Annuler", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(button_frame, text="Enregistrer", command=self._submit).pack(side="right", padx=4)

        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.grab_set()
        entry_category.focus_set()

    def _submit(self) -> None:
        try:
            limit = float(self.var_limit.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Erreur", "Montant invalide", parent=self)
            return
        self.result = Budget(
            id=self._original_id or uuid4().hex,
            category=self.var_category.get().strip() or "Autre",
            monthly_limit=abs(limit),
        )
        self.destroy()


# ----------------------------------------------------------------------
# GUI Application
# ----------------------------------------------------------------------
class BudgetManagerApp:
    def __init__(self, root: tk.Tk, state: BudgetState) -> None:
        self.root = root
        self.state = state
        self.state.load()

        self.root.title("Gestionnaire de budget")
        self.root.geometry("960x720")

        self.month_var = tk.StringVar(value="")
        self._month_labels: Dict[str, Optional[str]] = {}
        toolbar = ttk.Frame(root, padding=12)
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="Période :").pack(side="left")
        self.month_combo = ttk.Combobox(toolbar, textvariable=self.month_var, state="readonly")
        self.month_combo.pack(side="left", padx=8)
        self.month_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_all())

        ttk.Button(toolbar, text="Tout", command=lambda: self._set_month(None)).pack(side="left")
        ttk.Button(toolbar, text="Sauvegarder", command=self._save).pack(side="right")
        ttk.Button(toolbar, text="Importer CSV", command=self.import_transactions).pack(side="right", padx=8)
        ttk.Button(toolbar, text="Exporter CSV", command=self.export_transactions).pack(side="right")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.dashboard_tab = ttk.Frame(self.notebook, padding=20)
        self.transactions_tab = ttk.Frame(self.notebook, padding=12)
        self.budgets_tab = ttk.Frame(self.notebook, padding=12)
        self.analytics_tab = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.dashboard_tab, text="Tableau de bord")
        self.notebook.add(self.transactions_tab, text="Transactions")
        self.notebook.add(self.budgets_tab, text="Budgets")
        self.notebook.add(self.analytics_tab, text="Analyses")

        self._build_dashboard()
        self._build_transactions()
        self._build_budgets()
        self._build_analytics()

        self.refresh_months()
        self.refresh_all()

    # ------------------------------------------------------------------
    # Building UI sections
    # ------------------------------------------------------------------
    def _build_dashboard(self) -> None:
        self.label_income = ttk.Label(self.dashboard_tab, font=("TkDefaultFont", 16, "bold"))
        self.label_expense = ttk.Label(self.dashboard_tab, font=("TkDefaultFont", 16, "bold"))
        self.label_net = ttk.Label(self.dashboard_tab, font=("TkDefaultFont", 18, "bold"))

        self.label_income.pack(anchor="w", pady=8)
        self.label_expense.pack(anchor="w", pady=8)
        self.label_net.pack(anchor="w", pady=8)

        ttk.Label(self.dashboard_tab, text="Suivi des budgets", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(24, 8))

        columns = ("category", "limit", "used", "remaining")
        self.dashboard_tree = ttk.Treeview(self.dashboard_tab, columns=columns, show="headings", height=12)
        headings = {
            "category": "Catégorie",
            "limit": "Plafond",
            "used": "Dépensé",
            "remaining": "Reste",
        }
        for cid, text in headings.items():
            self.dashboard_tree.heading(cid, text=text)
            self.dashboard_tree.column(cid, width=160, anchor="center")
        self.dashboard_tree.pack(fill="both", expand=True)

    def _build_transactions(self) -> None:
        button_frame = ttk.Frame(self.transactions_tab)
        button_frame.pack(fill="x", pady=(0, 8))

        ttk.Button(button_frame, text="Ajouter", command=self.add_transaction).pack(side="left")
        ttk.Button(button_frame, text="Modifier", command=self.edit_transaction).pack(side="left", padx=6)
        ttk.Button(button_frame, text="Supprimer", command=self.delete_transaction).pack(side="left")

        columns = ("date", "description", "category", "type", "amount", "notes")
        self.transactions_tree = ttk.Treeview(self.transactions_tab, columns=columns, show="headings")
        headings = {
            "date": "Date",
            "description": "Description",
            "category": "Catégorie",
            "type": "Type",
            "amount": "Montant",
            "notes": "Notes",
        }
        for cid, text in headings.items():
            self.transactions_tree.heading(cid, text=text)
            self.transactions_tree.column(cid, width=130, anchor="center")
        self.transactions_tree.column("description", width=220, anchor="w")
        self.transactions_tree.column("notes", width=220, anchor="w")

        self.transactions_tree.pack(fill="both", expand=True)

    def _build_budgets(self) -> None:
        button_frame = ttk.Frame(self.budgets_tab)
        button_frame.pack(fill="x", pady=(0, 8))

        ttk.Button(button_frame, text="Ajouter", command=self.add_budget).pack(side="left")
        ttk.Button(button_frame, text="Modifier", command=self.edit_budget).pack(side="left", padx=6)
        ttk.Button(button_frame, text="Supprimer", command=self.delete_budget).pack(side="left")
        ttk.Button(button_frame, text="Exporter", command=self.export_budgets).pack(side="right")

        columns = ("category", "limit")
        self.budgets_tree = ttk.Treeview(self.budgets_tab, columns=columns, show="headings")
        self.budgets_tree.heading("category", text="Catégorie")
        self.budgets_tree.heading("limit", text="Plafond mensuel")
        self.budgets_tree.column("category", width=240, anchor="w")
        self.budgets_tree.column("limit", width=180, anchor="center")
        self.budgets_tree.pack(fill="both", expand=True)

    def _build_analytics(self) -> None:
        if MATPLOTLIB:
            self.figure = Figure(figsize=(6, 4), dpi=100)
            self.chart_axes = self.figure.add_subplot(111)
            self.chart_canvas = FigureCanvasTkAgg(self.figure, master=self.analytics_tab)
            self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
        else:
            ttk.Label(
                self.analytics_tab,
                text="Installez matplotlib pour afficher les graphiques.",
                foreground="gray",
            ).pack(expand=True)

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------
    def refresh_months(self) -> None:
        months = self.state.months()
        labels = ["Toutes"] + [month_label(m) for m in months]
        mapping: Dict[str, Optional[str]] = {"Toutes": None}
        for label, key in zip(labels[1:], months):
            mapping[label] = key
        self._month_labels = mapping
        self.month_combo.configure(values=list(mapping.keys()))
        current = self.month_var.get()
        if current not in mapping:
            if months:
                self.month_var.set(month_label(months[-1]))
            else:
                self.month_var.set("Toutes")

    def _current_month_key(self) -> Optional[str]:
        label = self.month_var.get()
        if label in self._month_labels:
            return self._month_labels[label]
        if self._month_labels:
            return next(reversed(self._month_labels.values()))
        return None

    def refresh_all(self) -> None:
        key = self._current_month_key()
        totals = self.state.totals_for_month(key)
        self.label_income.configure(text=f"Revenus : {format_currency(totals['income'])}")
        self.label_expense.configure(text=f"Dépenses : {format_currency(totals['expense'])}")
        net_text = format_currency(totals["net"])
        self.label_net.configure(text=f"Solde : {net_text}", foreground="green" if totals["net"] >= 0 else "red")

        for item in self.dashboard_tree.get_children():
            self.dashboard_tree.delete(item)
        for row in self.state.budgets_usage(key):
            self.dashboard_tree.insert(
                "",
                "end",
                values=(
                    row["category"],
                    format_currency(row["limit"]),
                    format_currency(row["used"]),
                    format_currency(row["remaining"]),
                ),
            )

        for item in self.transactions_tree.get_children():
            self.transactions_tree.delete(item)
        for tx in sorted(self.state.transactions_for_month(key), key=lambda t: t.date):
            self.transactions_tree.insert(
                "",
                "end",
                iid=tx.id,
                values=(
                    format_date(tx.date),
                    tx.description,
                    tx.category,
                    "Revenu" if tx.type == "income" else "Dépense",
                    format_currency(tx.amount),
                    tx.notes,
                ),
            )

        for item in self.budgets_tree.get_children():
            self.budgets_tree.delete(item)
        for budget in sorted(self.state.budgets, key=lambda b: b.category.lower()):
            self.budgets_tree.insert(
                "",
                "end",
                iid=budget.id,
                values=(budget.category, format_currency(budget.monthly_limit)),
            )

        self._refresh_chart()

    def _refresh_chart(self) -> None:
        if not MATPLOTLIB:
            return
        series = self.state.monthly_series(6)
        self.chart_axes.clear()
        if not series:
            self.chart_axes.text(0.5, 0.5, "Aucune donnée", ha="center", va="center")
        else:
            months = [month_label(s["month"]) for s in series]
            incomes = [s["income"] for s in series]
            expenses = [s["expense"] for s in series]
            self.chart_axes.plot(months, incomes, marker="o", label="Revenus")
            self.chart_axes.plot(months, expenses, marker="o", label="Dépenses")
            self.chart_axes.set_title("Évolution mensuelle")
            self.chart_axes.legend()
            self.chart_axes.grid(True, axis="y", linestyle="--", alpha=0.4)
            self.chart_axes.tick_params(axis="x", rotation=30)
        self.chart_canvas.draw_idle()

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def _set_month(self, key: Optional[str]) -> None:
        if not self._month_labels:
            self.refresh_months()
        if key is None:
            self.month_var.set("Toutes")
        else:
            label = month_label(key)
            if label not in self._month_labels:
                self._month_labels[label] = key
                self.month_combo.configure(values=list(self._month_labels.keys()))
            self.month_var.set(label)
        self.refresh_all()

    def _save(self) -> None:
        self.state.save()
        messagebox.showinfo("Sauvegarde", "Données enregistrées.", parent=self.root)

    # ------------------------------------------------------------------
    # Transaction actions
    # ------------------------------------------------------------------
    def _selected_transaction(self) -> Optional[Transaction]:
        selected = self.transactions_tree.focus()
        if not selected:
            return None
        for tx in self.state.transactions:
            if tx.id == selected:
                return tx
        return None

    def add_transaction(self) -> None:
        dialog = TransactionDialog(self.root, "Nouvelle transaction")
        self.root.wait_window(dialog)
        if dialog.result:
            self.state.transactions.append(dialog.result)
            self.state.transactions.sort(key=lambda t: t.date)
            self.state.save()
            self.refresh_months()
            self.refresh_all()

    def edit_transaction(self) -> None:
        tx = self._selected_transaction()
        if not tx:
            messagebox.showwarning("Modifier", "Sélectionnez une transaction.", parent=self.root)
            return
        dialog = TransactionDialog(self.root, "Modifier", tx)
        self.root.wait_window(dialog)
        if dialog.result:
            for idx, existing in enumerate(self.state.transactions):
                if existing.id == tx.id:
                    self.state.transactions[idx] = dialog.result
                    break
            self.state.transactions.sort(key=lambda t: t.date)
            self.state.save()
            self.refresh_all()

    def delete_transaction(self) -> None:
        tx = self._selected_transaction()
        if not tx:
            messagebox.showwarning("Supprimer", "Sélectionnez une transaction.", parent=self.root)
            return
        if not messagebox.askyesno("Confirmer", "Supprimer cette transaction ?", parent=self.root):
            return
        self.state.transactions = [t for t in self.state.transactions if t.id != tx.id]
        self.state.save()
        self.refresh_months()
        self.refresh_all()

    def import_transactions(self) -> None:
        path = filedialog.askopenfilename(
            title="Importer CSV", filetypes=[("CSV", "*.csv"), ("Tous", "*.*")]
        )
        if not path:
            return
        imported = 0
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    tx = Transaction(
                        id=uuid4().hex,
                        date=parse_date((row.get("date") or "").strip()),
                        description=(row.get("description") or "").strip(),
                        category=(row.get("category") or "Autre").strip() or "Autre",
                        type=(row.get("type") or "expense").strip() or "expense",
                        amount=abs(float((row.get("amount") or 0.0))),
                        notes=(row.get("notes") or "").strip(),
                    )
                except Exception:
                    continue
                self.state.transactions.append(tx)
                imported += 1
        if imported:
            self.state.transactions.sort(key=lambda t: t.date)
            self.state.save()
            self.refresh_months()
            self.refresh_all()
            messagebox.showinfo("Import", f"{imported} transactions importées.", parent=self.root)
        else:
            messagebox.showwarning("Import", "Aucune transaction importée.", parent=self.root)

    def export_transactions(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Exporter transactions",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "description", "category", "type", "amount", "notes"])
            writer.writeheader()
            for tx in self.state.transactions:
                writer.writerow(
                    {
                        "date": format_date(tx.date),
                        "description": tx.description,
                        "category": tx.category,
                        "type": tx.type,
                        "amount": f"{tx.amount:.2f}",
                        "notes": tx.notes,
                    }
                )
        messagebox.showinfo("Export", "Transactions exportées.", parent=self.root)

    # ------------------------------------------------------------------
    # Budget actions
    # ------------------------------------------------------------------
    def _selected_budget(self) -> Optional[Budget]:
        selected = self.budgets_tree.focus()
        if not selected:
            return None
        for budget in self.state.budgets:
            if budget.id == selected:
                return budget
        return None

    def add_budget(self) -> None:
        dialog = BudgetDialog(self.root, "Nouveau budget")
        self.root.wait_window(dialog)
        if dialog.result:
            self.state.budgets.append(dialog.result)
            self.state.save()
            self.refresh_all()

    def edit_budget(self) -> None:
        budget = self._selected_budget()
        if not budget:
            messagebox.showwarning("Modifier", "Sélectionnez un budget.", parent=self.root)
            return
        dialog = BudgetDialog(self.root, "Modifier budget", budget)
        self.root.wait_window(dialog)
        if dialog.result:
            for idx, existing in enumerate(self.state.budgets):
                if existing.id == budget.id:
                    self.state.budgets[idx] = dialog.result
                    break
            self.state.save()
            self.refresh_all()

    def delete_budget(self) -> None:
        budget = self._selected_budget()
        if not budget:
            messagebox.showwarning("Supprimer", "Sélectionnez un budget.", parent=self.root)
            return
        if not messagebox.askyesno("Confirmer", "Supprimer ce budget ?", parent=self.root):
            return
        self.state.budgets = [b for b in self.state.budgets if b.id != budget.id]
        self.state.save()
        self.refresh_all()

    def export_budgets(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Exporter budgets",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous", "*.*")],
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["category", "monthly_limit"])
            writer.writeheader()
            for budget in self.state.budgets:
                writer.writerow({"category": budget.category, "monthly_limit": f"{budget.monthly_limit:.2f}"})
        messagebox.showinfo("Export", "Budgets exportés.", parent=self.root)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def run_app() -> None:
    root = tk.Tk()
    state = BudgetState(DATA_FILE)
    BudgetManagerApp(root, state)
    root.mainloop()


def run_self_test() -> None:
    path = Path("/tmp/test_budget.json")
    state = BudgetState(path)
    state.transactions = [
        Transaction(id="1", date=parse_date("2024-01-05"), description="Salaire", category="Revenus", type="income", amount=3200),
        Transaction(id="2", date=parse_date("2024-01-09"), description="Courses", category="Courses", type="expense", amount=180),
        Transaction(id="3", date=parse_date("2024-01-18"), description="Loyer", category="Logement", type="expense", amount=820),
        Transaction(id="4", date=parse_date("2024-02-03"), description="Restaurant", category="Sorties", type="expense", amount=65),
    ]
    state.budgets = [
        Budget(id="b1", category="Courses", monthly_limit=250),
        Budget(id="b2", category="Logement", monthly_limit=900),
    ]
    state.save()
    other = BudgetState(path)
    other.load()
    assert len(other.transactions) == 4
    assert other.transactions[0].description == "Salaire"
    totals = other.totals_for_month("2024-01")
    assert round(totals["income"], 2) == 3200
    assert round(totals["expense"], 2) == 1000
    usage = other.budgets_usage("2024-01")
    assert any(row["category"] == "Logement" and round(row["used"], 2) == 820 for row in usage)
    path.unlink(missing_ok=True)
    print("Self-test réussi")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Gestionnaire de budget Tkinter")
    parser.add_argument("--self-test", action="store_true", help="exécute un test du cœur logique")
    args = parser.parse_args(argv)
    if args.self_test:
        run_self_test()
    else:
        run_app()


if __name__ == "__main__":  # pragma: no cover
    main()
