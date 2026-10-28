"""
DocuChat AI - Safe & High-Precision Excel & Spreadsheet Analysis Engine
Performs verified metadata inspection, calculations (sum, average, min, max, count),
category grouping, top-N ranking, calendar monthly summaries, duplicate/missing data auditing,
profit margin analysis, and natural language query interpretation using openpyxl and pandas.
Prevents arbitrary code execution and formula injection (CWE-1236).
Integrates with LangChain tool-calling loop, ContextVar conversation document scoping,
and deterministic QA synthesis.
"""

import os
import re
import json
import logging
import math
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

import openpyxl
from openpyxl.utils import get_column_letter
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from backend.config import settings

logger = logging.getLogger("excel_analyzer")

# ContextVar for propagating active document information into tool calls within async task context
active_excel_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("active_excel_context", default=None)


class ExcelAnalysisInput(BaseModel):
    operation: str = Field(
        ...,
        description="Analysis operation: 'metadata', 'sum'/'total', 'average'/'mean', 'max'/'highest', "
                    "'min'/'lowest', 'count', 'groupby', 'top_n'/'ranking', 'monthly_summary', "
                    "'missing_duplicates', 'margins', 'filter', 'summary', or 'query'."
    )
    column: Optional[str] = Field(
        None,
        description="Target column name to calculate or inspect (e.g. 'Sales', 'Target', 'Profit', 'Quantity'). Case-insensitive."
    )
    group_by: Optional[str] = Field(
        None,
        description="Column name to group rows by (e.g. 'Region', 'Product', 'Salesperson', 'Department')."
    )
    filter_column: Optional[str] = Field(
        None,
        description="Column name to filter rows on (e.g. 'Department', 'Region')."
    )
    filter_value: Optional[str] = Field(
        None,
        description="Value to match for the filter (e.g. 'IT', 'North', 'Electronics')."
    )
    sheet_name: Optional[str] = Field(
        None,
        description="Worksheet name if workbook contains multiple sheets (defaults to active sheet)."
    )
    doc_id: Optional[str] = Field(
        None,
        description="Document ID or artifact ID of the spreadsheet. If omitted, automatically resolved from conversation context."
    )
    n: Optional[int] = Field(
        5,
        description="Number of top or bottom records to return for ranking operations (default: 5)."
    )
    sort_ascending: Optional[bool] = Field(
        False,
        description="Sort order: False for highest-to-lowest (descending), True for lowest-to-highest."
    )
    date_column: Optional[str] = Field(
        None,
        description="Column name containing transaction/record dates for monthly summaries (e.g. 'Date')."
    )
    query: Optional[str] = Field(
        None,
        description="Natural language question to analyze against the spreadsheet (e.g. 'What is total revenue?')."
    )


def resolve_spreadsheet_file(doc_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolves the spreadsheet file path and metadata using:
    1. Explicit doc_id argument.
    2. Active conversation ContextVar.
    3. Document store in UPLOAD_DIR.
    4. Generated artifacts in OUTPUT_DIR.
    """
    ctx = active_excel_context.get() or {}
    resolved_id = doc_id or ctx.get("doc_id")

    # If no doc_id was passed and context has a file_path that exists, use it
    if not resolved_id and ctx.get("file_path") and os.path.exists(ctx["file_path"]):
        return {
            "doc_id": ctx.get("doc_id", "active_context"),
            "file_path": ctx["file_path"],
            "filename": ctx.get("filename", Path(ctx["file_path"]).name)
        }

    upload_dir = Path(settings.UPLOAD_DIR)
    output_dir = Path(getattr(settings, "OUTPUT_DIR", "backend/data/output"))

    # Search in UPLOAD_DIR by resolved_id
    if resolved_id:
        candidates = list(upload_dir.glob(f"{resolved_id}_*")) + list(upload_dir.glob(f"{resolved_id}.*"))
        if candidates:
            cand = candidates[0]
            ext = cand.suffix.lower()
            if ext in (".xlsx", ".xls", ".csv"):
                return {
                    "doc_id": resolved_id,
                    "file_path": str(cand),
                    "filename": cand.name.split("_", 1)[-1] if "_" in cand.name else cand.name
                }
            else:
                raise ValueError(f"Document {resolved_id} format '{ext}' is not a supported spreadsheet format.")

        # Search in OUTPUT_DIR by resolved_id (in case an artifact was generated earlier)
        if output_dir.exists():
            art_candidates = list(output_dir.glob(f"*{resolved_id}*"))
            for cand in art_candidates:
                if cand.suffix.lower() in (".xlsx", ".xls", ".csv"):
                    return {
                        "doc_id": resolved_id,
                        "file_path": str(cand),
                        "filename": cand.name
                    }

        if doc_id:
            raise FileNotFoundError(f"Spreadsheet document with ID '{doc_id}' was not found in storage.")

    # Fallback: check context doc_ids list
    doc_ids_list = ctx.get("doc_ids") or []
    for d_id in doc_ids_list:
        candidates = list(upload_dir.glob(f"{d_id}_*"))
        for cand in candidates:
            if cand.suffix.lower() in (".xlsx", ".xls", ".csv"):
                return {
                    "doc_id": d_id,
                    "file_path": str(cand),
                    "filename": cand.name.split("_", 1)[-1] if "_" in cand.name else cand.name
                }

    # Fallback: check if context has filename
    if ctx.get("filename"):
        fn = ctx["filename"]
        for cand in list(upload_dir.glob(f"*{fn}*")) + list(output_dir.glob(f"*{fn}*")):
            if cand.suffix.lower() in (".xlsx", ".xls", ".csv") and cand.is_file():
                return {
                    "doc_id": cand.name.split("_", 1)[0] if "_" in cand.name else "local",
                    "file_path": str(cand),
                    "filename": fn
                }

    # Fallback: discover any ready spreadsheet in UPLOAD_DIR
    for ext in ("*.xlsx", "*.xls", "*.csv"):
        for cand in upload_dir.glob(ext):
            return {
                "doc_id": cand.name.split("_", 1)[0] if "_" in cand.name else "local",
                "file_path": str(cand),
                "filename": cand.name.split("_", 1)[-1] if "_" in cand.name else cand.name
            }

    # Fallback: check OUTPUT_DIR for recently generated workbooks
    if output_dir.exists():
        recent_files = sorted(
            [f for f in output_dir.glob("*.xlsx") if f.is_file()],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if recent_files:
            cand = recent_files[0]
            return {
                "doc_id": cand.stem,
                "file_path": str(cand),
                "filename": cand.name
            }

    raise FileNotFoundError("No active spreadsheet document was found in the current conversation context.")


def _find_column(df: pd.DataFrame, target: Optional[str]) -> Optional[str]:
    """Case-insensitive, symbol-tolerant, and whitespace-tolerant column matching."""
    if not target or not isinstance(target, str):
        return None
    target_clean = re.sub(r"[^\w\s]", "", target).strip().lower()
    for col in df.columns:
        col_clean = re.sub(r"[^\w\s]", "", str(col)).strip().lower()
        if col_clean == target_clean:
            return col
    # Exact lowercase match
    target_raw = target.strip().lower()
    for col in df.columns:
        if str(col).strip().lower() == target_raw:
            return col
    # Partial substring match fallback (e.g. 'sale' matching 'Total Sales')
    for col in df.columns:
        col_str = str(col).strip().lower()
        if target_raw in col_str or col_str in target_raw:
            return col
    return None


def _find_date_column(df: pd.DataFrame, explicit: Optional[str] = None) -> Optional[str]:
    """Identifies date column automatically or verifies explicit date column."""
    if explicit:
        matched = _find_column(df, explicit)
        if matched:
            return matched

    # Heuristic 1: column name contains 'date', 'day', 'time'
    for col in df.columns:
        if re.search(r"\b(date|day|time|period|month)\b", str(col), re.I):
            return col

    # Heuristic 2: test sample values for parseable datetime
    for col in df.columns:
        sample = df[col].dropna().head(5)
        if len(sample) > 0:
            parsed = pd.to_datetime(sample, errors="coerce")
            if parsed.notnull().sum() >= max(1, int(len(sample) * 0.8)):
                return col
    return None


def inspect_formulas_and_cached_values(file_path: str, sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Rigorously inspects formulas in an Excel workbook.
    Compares data_only=False (formula strings) vs data_only=True (cached values).
    Reports formula locations, missing cached values, and formula syntax health.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in (".xlsx", ".xlsm"):
        return {"has_formulas": False, "formula_cells": [], "missing_cache_cells": [], "notes": "Format does not store Excel formula ASTs."}

    try:
        wb_formulas = openpyxl.load_workbook(file_path, read_only=True, data_only=False)
        wb_values = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        target_sheet = sheet_name if sheet_name and sheet_name in wb_formulas.sheetnames else wb_formulas.sheetnames[0]
        ws_f = wb_formulas[target_sheet]
        ws_v = wb_values[target_sheet]

        formula_cells = []
        missing_cache_cells = []

        # Read up to first 200 rows and 50 cols for performance
        rows_f = list(ws_f.iter_rows(values_only=False))
        rows_v = list(ws_v.iter_rows(values_only=False))

        wb_formulas.close()
        wb_values.close()

        for r_idx, (rf_row, rv_row) in enumerate(zip(rows_f[:200], rows_v[:200]), start=1):
            for c_idx, (cf, cv) in enumerate(zip(rf_row[:50], rv_row[:50]), start=1):
                f_val = str(cf.value) if cf.value is not None else ""
                if f_val.startswith("="):
                    cell_ref = f"{get_column_letter(c_idx)}{r_idx}"
                    v_val = cv.value
                    formula_cells.append({
                        "cell": cell_ref,
                        "formula": f_val,
                        "cached_value": v_val
                    })
                    if v_val is None:
                        missing_cache_cells.append(cell_ref)

        return {
            "has_formulas": len(formula_cells) > 0,
            "total_formula_cells": len(formula_cells),
            "formula_samples": formula_cells[:10],
            "missing_cached_values_count": len(missing_cache_cells),
            "missing_cache_cells": missing_cache_cells[:10],
            "all_cached_available": len(missing_cache_cells) == 0,
            "notes": (
                "All formulas have cached calculated values available."
                if len(missing_cache_cells) == 0
                else f"Note: {len(missing_cache_cells)} formula cell(s) have uncalculated/null cached values. Python fallback engine active."
            )
        }
    except Exception as e:
        logger.warning(f"[EXCEL_ANALYZER] Formula inspection failed: {e}")
        return {"has_formulas": False, "error": str(e)}


def _evaluate_cell_formula(formula: Any, cell_lookup: Dict[str, Any], current_row: Optional[int] = None) -> Any:
    """
    Evaluates Excel cell formulas in Python when cached values are uncalculated or None.
    Handles IFERROR, arithmetic expressions (+, -, *, /), cell references (F2, $G$2, etc.),
    and summary aggregations (SUM, AVERAGE, COUNT, COUNTA, MAX, MIN).
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula

    clean = formula.lstrip("=").strip()

    # IFERROR(expr, fallback)
    m_iferr = re.match(r"^IFERROR\s*\(\s*(.*?)\s*,\s*([^)]+)\s*\)$", clean, re.I)
    if m_iferr:
        expr, fallback_str = m_iferr.group(1), m_iferr.group(2)
        try:
            val = _evaluate_cell_formula("=" + expr, cell_lookup, current_row)
            if val is not None and not (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
                return val
            fallback_val = float(fallback_str) if fallback_str.replace(".", "", 1).isdigit() else fallback_str
            return fallback_val
        except Exception:
            try:
                return float(fallback_str)
            except Exception:
                return fallback_str

    # Range aggregations: e.g. SUM(F2:F31), SUM('Sales Data'!H2:H31)
    m_agg = re.match(
        r"^(SUM|AVERAGE|AVG|COUNT|COUNTA|MAX|MIN)\s*\(\s*(?:['\w\s]+!)?\$?([A-Za-z]+)\$?(\d+)\s*:\s*(?:['\w\s]+!)?\$?([A-Za-z]+)\$?(\d+)\s*\)$",
        clean,
        re.I
    )
    if m_agg:
        func = m_agg.group(1).upper()
        col1 = m_agg.group(2).upper()
        r1 = int(m_agg.group(3))
        col2 = m_agg.group(4).upper()
        r2 = int(m_agg.group(5))
        vals = []
        for r in range(r1, r2 + 1):
            key = f"{col1}{r}"
            v = cell_lookup.get(key)
            if v is not None:
                try:
                    clean_v = str(v).replace(",", "").replace("₹", "").replace("$", "").replace("%", "").strip()
                    vals.append(float(clean_v))
                except Exception:
                    pass
        if func == "SUM":
            return float(sum(vals))
        elif func in ("AVERAGE", "AVG"):
            return float(sum(vals) / len(vals)) if vals else 0.0
        elif func in ("COUNT", "COUNTA"):
            return len(vals)
        elif func == "MAX":
            return float(max(vals)) if vals else 0.0
        elif func == "MIN":
            return float(min(vals)) if vals else 0.0

    # Cell references replacement: e.g. F2, $F$2, J2, H2, 'Sales Data'!H2
    def _replace_ref(m):
        t = re.sub(r"[\$']", "", m.group(0))
        if "!" in t:
            t = t.split("!")[-1]
        t = t.upper()
        if t in cell_lookup:
            v = cell_lookup[t]
            if v is None:
                return "0"
            try:
                clean_v = str(v).replace(",", "").replace("₹", "").replace("$", "").replace("%", "").strip()
                float(clean_v)
                return clean_v
            except Exception:
                return "0"
        return "0"

    py_expr = re.sub(r"(?:['\w\s]+!)?\$?[A-Za-z]+\$?\d+", _replace_ref, clean)
    try:
        if re.match(r"^[\d\s\+\-\*\/\(\)\.\%]+$", py_expr):
            res = eval(py_expr, {"__builtins__": {}}, {})
            if isinstance(res, float) and (math.isnan(res) or math.isinf(res)):
                return 0.0
            return res
    except ZeroDivisionError:
        return 0.0
    except Exception:
        pass
    return None


def execute_excel_analysis(
    operation: str,
    column: Optional[str] = None,
    group_by: Optional[str] = None,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    sheet_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    n: Optional[int] = 5,
    sort_ascending: Optional[bool] = False,
    date_column: Optional[str] = None,
    query: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes spreadsheet analysis using openpyxl and pandas.
    Supports operations: metadata, sum, average, max, min, count, groupby,
    top_n (ranking), monthly_summary, missing_duplicates, margins, summary, and query.
    Returns a comprehensive structured dictionary with calculation steps, exact figures, and evidence tables.
    """
    # 1. Resolve spreadsheet file
    try:
        resolved = resolve_spreadsheet_file(doc_id)
    except Exception as e:
        logger.error(f"[EXCEL_ANALYZER] File resolution failed: {e}")
        return {"status": "error", "message": str(e)}

    file_path = resolved["file_path"]
    filename = resolved["filename"]
    ext = Path(file_path).suffix.lower()

    logger.info(f"[EXCEL_ANALYZER] Executing '{operation}' on '{filename}' (ID: {resolved['doc_id']}), col='{column}', grp='{group_by}'")

    try:
        # Load workbook sheets and data
        if ext in (".xlsx", ".xls", ".xlsm"):
            wb_v = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            wb_f = openpyxl.load_workbook(file_path, read_only=True, data_only=False)
            sheet_names = wb_v.sheetnames

            # Intelligently pick tabular data sheet over dashboard/lists/summary if sheet_name not specified
            if not sheet_name:
                data_candidates = [
                    s for s in sheet_names
                    if re.search(r"\b(sales\s*data|data|transactions|records|sheet1|raw)\b", s, re.I)
                ]
                active_sheet = data_candidates[0] if data_candidates else sheet_names[0]
            else:
                active_sheet = sheet_name if sheet_name in sheet_names else sheet_names[0]

            ws_v = wb_v[active_sheet]
            ws_f = wb_f[active_sheet]
            raw_v = list(ws_v.iter_rows(values_only=True))
            raw_f = list(ws_f.iter_rows(values_only=True))
            wb_v.close()
            wb_f.close()

            if not raw_v:
                return {
                    "status": "success",
                    "filename": filename,
                    "sheet_names": sheet_names,
                    "active_sheet": active_sheet,
                    "data_rows": 0,
                    "total_columns": 0,
                    "columns": [],
                    "message": f"Worksheet '{active_sheet}' is empty."
                }

            header = [
                str(c).strip() if c is not None and str(c).strip() != "" else f"Column_{i+1}"
                for i, c in enumerate(raw_v[0])
            ]

            # Build data rows with formula evaluation fallback when cached value is None
            data_rows = []
            grid_lookup: Dict[str, Any] = {}

            for r_idx in range(1, len(raw_v)):
                excel_row = r_idx + 1
                row_v = raw_v[r_idx]
                row_f = raw_f[r_idx] if r_idx < len(raw_f) else [None] * len(row_v)
                curr_row_vals = []

                for c_idx in range(len(header)):
                    col_letter = get_column_letter(c_idx + 1)
                    coord = f"{col_letter}{excel_row}"
                    val_v = row_v[c_idx] if c_idx < len(row_v) else None
                    val_f = row_f[c_idx] if c_idx < len(row_f) else None

                    if val_v is not None and not (isinstance(val_v, str) and val_v.startswith("=")):
                        cell_val = val_v
                    elif isinstance(val_f, str) and val_f.startswith("="):
                        cell_val = _evaluate_cell_formula(val_f, grid_lookup, excel_row)
                    else:
                        cell_val = val_v

                    grid_lookup[coord] = cell_val
                    curr_row_vals.append(cell_val)

                data_rows.append(curr_row_vals)

            total_cols = len(header)
            dims = f"A1:{get_column_letter(total_cols)}{len(data_rows) + 1}"
            df = pd.DataFrame(data_rows, columns=header)

            # If the last row is a summary row (e.g. 'Total Summary' or 'Total'), exclude from calculation DataFrame
            if len(df) > 1:
                first_col = df.columns[0]
                last_val = str(df.iloc[-1][first_col]).strip().lower()
                if "total" in last_val or "summary" in last_val:
                    df = df.iloc[:-1].reset_index(drop=True)
        else:
            # CSV file
            df = pd.read_csv(file_path)
            sheet_names = ["CSV Data"]
            active_sheet = "CSV Data"
            dims = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"

        total_rows = len(df)
        total_columns = len(df.columns)
        columns_list = list(df.columns)

        # Inspect formulas in workbook
        formula_audit = inspect_formulas_and_cached_values(file_path, sheet_name=active_sheet)

        # Clean numeric columns (convert currency/commas/rupee symbols to numbers)
        for col in df.columns:
            if df[col].dtype == object:
                # Strip currency symbols, commas, percent signs
                clean_str = (
                    df[col].astype(str)
                    .str.replace("₹", "", regex=False)
                    .str.replace("$", "", regex=False)
                    .str.replace(",", "", regex=False)
                    .str.replace("%", "", regex=False)
                    .str.strip()
                )
                converted = pd.to_numeric(clean_str, errors="coerce")
                if converted.notnull().sum() >= max(1, int(len(df) * 0.5)):
                    # Check if original was percentage string
                    is_pct = df[col].astype(str).str.contains("%").sum() >= int(len(df) * 0.4)
                    if is_pct:
                        df[col] = converted / 100.0
                    else:
                        df[col] = converted

        op_lower = (operation or "metadata").strip().lower()

        # If natural query interpretation requested
        if op_lower in ("query", "natural_language") and query:
            return _interpret_natural_query(df, query, filename, active_sheet, sheet_names, formula_audit)

        # Operation 1: Metadata & Structure inspection
        if op_lower in ("metadata", "info", "structure", "columns", "sheets"):
            return {
                "status": "success",
                "filename": filename,
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
                "total_sheets": len(sheet_names),
                "data_rows": total_rows,
                "total_columns": total_columns,
                "columns": columns_list,
                "dimensions": dims,
                "formula_audit": formula_audit,
                "summary": (
                    f"Workbook '{filename}' contains {len(sheet_names)} sheet(s): {', '.join(sheet_names)}. "
                    f"Active sheet '{active_sheet}' has {total_rows} data rows and {total_columns} columns: "
                    f"{', '.join(columns_list)}."
                )
            }

        # Apply row filter if specified
        target_df = df
        filter_matched_col = _find_column(df, filter_column)
        if filter_matched_col and filter_value is not None:
            val_clean = str(filter_value).strip().lower()
            target_df = df[df[filter_matched_col].astype(str).str.strip().str.lower() == val_clean]

        target_col = _find_column(target_df, column)

        # Operation 2: Missing values & Duplicate Records Audit
        if op_lower in ("missing_duplicates", "duplicates", "nulls", "audit", "clean"):
            missing_per_col = target_df.isnull().sum().to_dict()
            missing_cols = {str(k): int(v) for k, v in missing_per_col.items() if v > 0}
            total_duplicate_rows = int(target_df.duplicated().sum())

            # Detect ID column
            id_col = _find_column(target_df, "Transaction ID") or _find_column(target_df, "ID") or _find_column(target_df, "Emp ID")
            id_duplicate_count = 0
            if id_col:
                id_duplicate_count = int(target_df[id_col].duplicated().sum())

            return {
                "status": "success",
                "filename": filename,
                "operation": "missing_duplicates",
                "total_rows": len(target_df),
                "missing_values_by_column": missing_cols,
                "has_missing_values": len(missing_cols) > 0,
                "total_duplicate_rows": total_duplicate_rows,
                "id_column": id_col,
                "duplicate_ids_count": id_duplicate_count,
                "is_clean": (len(missing_cols) == 0 and total_duplicate_rows == 0 and id_duplicate_count == 0),
                "summary": (
                    f"Audit for '{filename}': {len(target_df)} rows checked. "
                    f"Duplicate rows: {total_duplicate_rows}. "
                    f"Duplicate IDs ({id_col or 'N/A'}): {id_duplicate_count}. "
                    f"Missing values: {sum(missing_cols.values())} across {len(missing_cols)} column(s)."
                )
            }

        # Operation 3: Top-N / Ranking Analysis
        if op_lower in ("top_n", "top", "ranking", "bottom_n", "bottom", "rank"):
            if not target_col:
                # Look for typical metrics: Profit, Sales, Total Sales, Revenue
                target_col = (
                    _find_column(target_df, "Profit") or
                    _find_column(target_df, "Total Sales") or
                    _find_column(target_df, "Sales") or
                    _find_column(target_df, "Revenue")
                )
                if not target_col:
                    num_cols = target_df.select_dtypes(include=["number"]).columns
                    target_col = num_cols[0] if len(num_cols) > 0 else None

            if not target_col:
                return {"status": "error", "message": "No numeric column found to perform ranking."}

            rank_n = int(n) if n and n > 0 else 5
            ascending = bool(sort_ascending or op_lower in ("bottom_n", "bottom"))

            # Deterministic tie-breaking: sort by target_col then by index or ID column
            id_col = _find_column(target_df, "Transaction ID") or _find_column(target_df, "ID")
            sort_cols = [target_col, id_col] if id_col else [target_col]
            sort_orders = [ascending, True] if id_col else [ascending]

            sorted_df = target_df.sort_values(by=sort_cols, ascending=sort_orders).head(rank_n)
            records = []
            for rank_idx, (_, r) in enumerate(sorted_df.iterrows(), start=1):
                rec = {
                    "rank": rank_idx,
                    str(target_col): float(r[target_col]) if pd.notnull(r[target_col]) else 0.0,
                }
                # Include ID, salesperson, region, product if present
                for key_field in ("Transaction ID", "ID", "Salesperson Name", "Salesperson", "Region", "Product Name", "Product", "Date"):
                    col_found = _find_column(target_df, key_field)
                    if col_found:
                        rec[col_found] = str(r[col_found])
                records.append(rec)

            return {
                "status": "success",
                "filename": filename,
                "operation": "top_n",
                "ranking_column": target_col,
                "n": rank_n,
                "order": "ascending (lowest)" if ascending else "descending (highest)",
                "records": records,
                "summary": f"Top {rank_n} records by {target_col}: " + "; ".join(
                    f"#{r['rank']}: {r.get(id_col or '', '')} {target_col}={r[target_col]:,.2f}" for r in records
                )
            }

        # Operation 4: Monthly Sales & Trend Summary
        if op_lower in ("monthly_summary", "monthly", "trends", "monthly_sales", "timeline"):
            dt_col = _find_date_column(target_df, date_column)
            if not dt_col:
                return {"status": "error", "message": f"Could not locate date column in spreadsheet. Available columns: {columns_list}"}

            sales_col = (
                _find_column(target_df, column) or
                _find_column(target_df, "Total Sales") or
                _find_column(target_df, "Sales") or
                _find_column(target_df, "Revenue")
            )
            profit_col = _find_column(target_df, "Profit")
            qty_col = _find_column(target_df, "Quantity Sold") or _find_column(target_df, "Quantity")

            # Parse dates
            df_dates = target_df.copy()
            df_dates["_parsed_date"] = pd.to_datetime(df_dates[dt_col], errors="coerce")
            valid_dates = df_dates.dropna(subset=["_parsed_date"]).copy()

            if len(valid_dates) == 0:
                return {"status": "error", "message": f"Date column '{dt_col}' contains no parseable dates."}

            valid_dates["_year_month"] = valid_dates["_parsed_date"].dt.to_period("M")
            valid_dates["_month_label"] = valid_dates["_parsed_date"].dt.strftime("%b-%Y")

            agg_dict = {"_parsed_date": "count"}
            if sales_col and sales_col in valid_dates.columns and pd.api.types.is_numeric_dtype(valid_dates[sales_col]):
                agg_dict[sales_col] = "sum"
            if profit_col and profit_col in valid_dates.columns and pd.api.types.is_numeric_dtype(valid_dates[profit_col]):
                agg_dict[profit_col] = "sum"
            if qty_col and qty_col in valid_dates.columns and pd.api.types.is_numeric_dtype(valid_dates[qty_col]):
                agg_dict[qty_col] = "sum"

            grouped_monthly = valid_dates.groupby(["_year_month", "_month_label"]).agg(agg_dict).reset_index()
            grouped_monthly = grouped_monthly.sort_values(by="_year_month")

            monthly_data = []
            for _, mrow in grouped_monthly.iterrows():
                m_info = {
                    "month": str(mrow["_month_label"]),
                    "transactions": int(mrow["_parsed_date"]),
                }
                if sales_col in agg_dict:
                    m_info["total_sales"] = float(mrow[sales_col])
                if profit_col in agg_dict:
                    m_info["total_profit"] = float(mrow[profit_col])
                    if m_info.get("total_sales", 0) > 0:
                        m_info["profit_margin_pct"] = round((m_info["total_profit"] / m_info["total_sales"]) * 100.0, 2)
                if qty_col in agg_dict:
                    m_info["total_units"] = int(mrow[qty_col])
                monthly_data.append(m_info)

            return {
                "status": "success",
                "filename": filename,
                "operation": "monthly_summary",
                "date_column": dt_col,
                "sales_column": sales_col,
                "monthly_breakdown": monthly_data,
                "summary": (
                    f"Monthly summary across {len(monthly_data)} calendar month(s): " +
                    "; ".join(f"{m['month']}: Sales ₹{m.get('total_sales', 0):,.2f} ({m['transactions']} txns)" for m in monthly_data)
                )
            }

        # Operation 5: Group By calculation (e.g. Region vs Sales, Salesperson vs Profit)
        grp_col = _find_column(df, group_by)
        if op_lower in ("groupby", "group_by", "categories", "category_summary") or grp_col is not None:
            if not grp_col:
                grp_col = (
                    _find_column(df, "Region") or
                    _find_column(df, "Product Name") or
                    _find_column(df, "Product") or
                    _find_column(df, "Salesperson Name") or
                    _find_column(df, "Salesperson") or
                    _find_column(df, "Department") or
                    _find_column(df, "Category")
                )
            if not target_col:
                target_col = (
                    _find_column(target_df, "Total Sales") or
                    _find_column(target_df, "Sales") or
                    _find_column(target_df, "Profit") or
                    _find_column(target_df, "Revenue")
                )
                if not target_col:
                    num_cols = target_df.select_dtypes(include=["number"]).columns
                    target_col = num_cols[0] if len(num_cols) > 0 else None

            if grp_col and target_col:
                grouped = target_df.groupby(grp_col)[target_col].agg(["sum", "mean", "min", "max", "count"]).reset_index()
                # Sort descending by sum
                grouped = grouped.sort_values(by="sum", ascending=False)
                res_dict = {}
                for _, row in grouped.iterrows():
                    res_dict[str(row[grp_col])] = {
                        "total": float(row["sum"]),
                        "average": float(round(row["mean"], 2)),
                        "min": float(row["min"]),
                        "max": float(row["max"]),
                        "count": int(row["count"])
                    }
                top_group = grouped.iloc[0][grp_col] if len(grouped) > 0 else "None"
                top_group_val = grouped.iloc[0]["sum"] if len(grouped) > 0 else 0.0

                return {
                    "status": "success",
                    "filename": filename,
                    "operation": "groupby",
                    "group_by_column": grp_col,
                    "target_column": target_col,
                    "top_category": str(top_group),
                    "top_category_value": float(top_group_val),
                    "grouped_results": res_dict,
                    "summary": f"Grouped {target_col} by {grp_col}: " + "; ".join(f"{k}: total {v['total']:,.2f}" for k, v in res_dict.items())
                }

        # Resolve target numeric column for math
        if not target_col and op_lower in ("sum", "total", "average", "mean", "avg", "max", "highest", "min", "lowest"):
            num_cols = target_df.select_dtypes(include=["number"]).columns
            target_col = num_cols[0] if len(num_cols) > 0 else None

        if not target_col and op_lower not in ("summary", "count"):
            return {
                "status": "error",
                "message": f"Column '{column}' was not found in spreadsheet. Available columns: {columns_list}"
            }

        # Operation 6: Count
        if op_lower in ("count", "row_count", "rows"):
            return {
                "status": "success",
                "filename": filename,
                "operation": "count",
                "column": target_col or "All",
                "result": len(target_df),
                "formatted": f"{len(target_df):,}",
                "summary": f"Total transactions/rows: {len(target_df)}"
            }

        # Operation 7: Total / Sum
        if op_lower in ("sum", "total"):
            total_val = float(target_df[target_col].sum())
            return {
                "status": "success",
                "filename": filename,
                "operation": "sum",
                "column": target_col,
                "filter": {filter_matched_col: filter_value} if filter_matched_col else None,
                "result": total_val,
                "formatted": f"{total_val:,.2f}".rstrip("0").rstrip("."),
                "rows_calculated": len(target_df),
                "summary": f"Total {target_col}: {total_val:,.2f} across {len(target_df)} records."
            }

        # Operation 8: Average / Mean
        if op_lower in ("average", "mean", "avg"):
            avg_val = float(target_df[target_col].mean()) if len(target_df) > 0 else 0.0
            return {
                "status": "success",
                "filename": filename,
                "operation": "average",
                "column": target_col,
                "filter": {filter_matched_col: filter_value} if filter_matched_col else None,
                "result": avg_val,
                "formatted": f"{avg_val:,.2f}".rstrip("0").rstrip("."),
                "rows_calculated": len(target_df),
                "summary": f"Average {target_col}: {avg_val:,.2f}."
            }

        # Operation 9: Max / Highest
        if op_lower in ("max", "highest"):
            max_idx = target_df[target_col].idxmax()
            max_val = float(target_df[target_col].max())
            best_row = target_df.loc[max_idx].to_dict() if pd.notnull(max_idx) else {}
            return {
                "status": "success",
                "filename": filename,
                "operation": "max",
                "column": target_col,
                "result": max_val,
                "formatted": f"{max_val:,.2f}".rstrip("0").rstrip("."),
                "row_details": {str(k): v for k, v in best_row.items()},
                "summary": f"Maximum {target_col}: {max_val:,.2f}."
            }

        # Operation 10: Min / Lowest
        if op_lower in ("min", "lowest"):
            min_idx = target_df[target_col].idxmin()
            min_val = float(target_df[target_col].min())
            worst_row = target_df.loc[min_idx].to_dict() if pd.notnull(min_idx) else {}
            return {
                "status": "success",
                "filename": filename,
                "operation": "min",
                "column": target_col,
                "result": min_val,
                "formatted": f"{min_val:,.2f}".rstrip("0").rstrip("."),
                "row_details": {str(k): v for k, v in worst_row.items()},
                "summary": f"Minimum {target_col}: {min_val:,.2f}."
            }

        # Operation 11: Comprehensive Statistical Summary
        numeric_cols = df.select_dtypes(include=["number"]).columns
        num_summary = {}
        for nc in numeric_cols:
            num_summary[nc] = {
                "total": float(df[nc].sum()),
                "average": float(round(df[nc].mean(), 2)),
                "max": float(df[nc].max()),
                "min": float(df[nc].min()),
            }

        return {
            "status": "success",
            "filename": filename,
            "sheet_names": sheet_names,
            "active_sheet": active_sheet,
            "data_rows": total_rows,
            "total_columns": total_columns,
            "columns": columns_list,
            "numeric_metrics": num_summary,
            "summary": f"Comprehensive metrics calculated for {len(numeric_cols)} numeric columns across {total_rows} rows."
        }

    except Exception as e:
        logger.error(f"[EXCEL_ANALYZER] Error executing '{operation}' on '{filename}': {e}", exc_info=True)
        return {"status": "error", "message": f"Spreadsheet analysis failed: {str(e)}"}


def _interpret_natural_query(
    df: pd.DataFrame,
    query: str,
    filename: str,
    active_sheet: str,
    sheet_names: List[str],
    formula_audit: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Interprets natural language queries directly using pandas and domain intelligence.
    Extracts metrics, ranks, groupbys, and summaries, and formats grounded natural language answers.
    """
    q_clean = query.strip().lower()

    # Case 1: Total sales / revenue question
    if re.search(r"\b(total|sum)\s*(sales|revenue|amount|turnover)?\b|\bhow\s+much\s+(total\s+)?(sales|revenue)\b", q_clean):
        target_col = _find_column(df, "Total Sales") or _find_column(df, "Sales") or _find_column(df, "Revenue")
        if target_col:
            val = float(df[target_col].sum())
            return {
                "status": "success",
                "filename": filename,
                "operation": "sum",
                "answer": f"The total sales revenue is **₹{val:,.2f}** calculated across all {len(df)} transactions in '{active_sheet}'.",
                "calculation": f"SUM({target_col}) = ₹{val:,.2f}",
                "result": val,
                "column": target_col,
                "rows_evaluated": len(df)
            }

    # Case 2: Average, min, max sales
    if re.search(r"\b(average|mean|min|minimum|max|maximum)\b.*\b(sales|profit|revenue)\b|\bcalculate\s+average\b", q_clean):
        target_col = (
            _find_column(df, "Total Sales") if "sales" in q_clean or "revenue" in q_clean
            else _find_column(df, "Profit") if "profit" in q_clean
            else _find_column(df, "Sales")
        ) or df.select_dtypes(include=["number"]).columns[0]

        total = float(df[target_col].sum())
        avg = float(df[target_col].mean())
        mini = float(df[target_col].min())
        maxi = float(df[target_col].max())

        return {
            "status": "success",
            "filename": filename,
            "operation": "summary",
            "answer": (
                f"Statistical metrics for **{target_col}** across {len(df)} transactions:\n"
                f"- **Total**: ₹{total:,.2f}\n"
                f"- **Average**: ₹{avg:,.2f}\n"
                f"- **Minimum**: ₹{mini:,.2f}\n"
                f"- **Maximum**: ₹{maxi:,.2f}"
            ),
            "result": {"total": total, "average": avg, "min": mini, "max": maxi},
            "column": target_col
        }

    # Case 3: Which region generated the highest revenue?
    if re.search(r"\b(which|what)\s+region\b.*\b(highest|most|top|max)\b|\bregion\s+generated\s+the\s+highest\b", q_clean):
        reg_col = _find_column(df, "Region")
        sales_col = _find_column(df, "Total Sales") or _find_column(df, "Sales") or _find_column(df, "Revenue")
        if reg_col and sales_col:
            grp = df.groupby(reg_col)[sales_col].sum().sort_values(ascending=False)
            top_reg = grp.index[0]
            top_val = float(grp.iloc[0])
            breakdown_lines = [f"- **{k}**: ₹{v:,.2f} ({round(v/grp.sum()*100, 1)}%)" for k, v in grp.items()]
            return {
                "status": "success",
                "filename": filename,
                "operation": "groupby",
                "answer": (
                    f"The **{top_reg}** region generated the highest revenue with **₹{top_val:,.2f}** "
                    f"({round(top_val/grp.sum()*100, 1)}% of total revenue).\n\n"
                    f"**Regional Breakdown:**\n" + "\n".join(breakdown_lines)
                ),
                "top_region": top_reg,
                "top_value": top_val,
                "breakdown": grp.to_dict()
            }

    # Case 4: Top 5 most profitable transactions
    if re.search(r"\btop\s*(5|five)?\s*(most\s+)?profit(able)?\b|\btop\s*(5|five)\s+transactions\b", q_clean):
        profit_col = _find_column(df, "Profit") or _find_column(df, "Total Sales") or _find_column(df, "Sales")
        id_col = _find_column(df, "Transaction ID") or _find_column(df, "ID")
        salesperson_col = _find_column(df, "Salesperson Name") or _find_column(df, "Salesperson")
        product_col = _find_column(df, "Product Name") or _find_column(df, "Product")

        top_df = df.sort_values(by=[profit_col, id_col] if id_col else [profit_col], ascending=False).head(5)
        table_lines = [f"| Rank | Transaction ID | Salesperson | Product | Profit |"]
        table_lines.append("| --- | --- | --- | --- | --- |")
        for idx, (_, r) in enumerate(top_df.iterrows(), start=1):
            t_id = str(r[id_col]) if id_col else f"Row {idx}"
            sp = str(r[salesperson_col]) if salesperson_col else "N/A"
            prd = str(r[product_col]) if product_col else "N/A"
            prof = float(r[profit_col])
            table_lines.append(f"| #{idx} | {t_id} | {sp} | {prd} | ₹{prof:,.2f} |")

        return {
            "status": "success",
            "filename": filename,
            "operation": "top_n",
            "answer": "Here are the top 5 most profitable transactions:\n\n" + "\n".join(table_lines),
            "records": top_df.to_dict(orient="records")
        }

    # Case 5: Missing values and duplicate records
    if re.search(r"\b(missing\s+values?|duplicates?|nulls?|corrupt)\b", q_clean):
        audit = execute_excel_analysis("missing_duplicates", doc_id=filename)
        return {
            "status": "success",
            "filename": filename,
            "operation": "missing_duplicates",
            "answer": (
                f"Data Quality Audit for **{filename}** ({len(df)} rows):\n"
                f"- **Duplicate Rows**: {audit.get('total_duplicate_rows', 0)}\n"
                f"- **Duplicate Transaction IDs**: {audit.get('duplicate_ids_count', 0)}\n"
                f"- **Missing/Null Values**: " +
                (f"{sum(audit.get('missing_values_by_column', {}).values())} found" if audit.get("has_missing_values") else "None (Dataset is 100% complete)") + "\n"
                f"- **Overall Quality**: {'✅ Clean & Valid' if audit.get('is_clean') else '⚠️ Issues detected'}"
            ),
            "audit_data": audit
        }

    # Case 6: Monthly sales summary / comparison
    if re.search(r"\b(monthly|month|trends?|compare\s+monthly)\b", q_clean):
        res = execute_excel_analysis("monthly_summary", doc_id=filename)
        if res.get("status") == "success":
            breakdown = res.get("monthly_breakdown", [])
            lines = ["| Month | Sales (₹) | Profit (₹) | Margin | Transactions |", "| --- | --- | --- | --- | --- |"]
            for m in breakdown:
                lines.append(
                    f"| {m['month']} | ₹{m.get('total_sales', 0):,.2f} | ₹{m.get('total_profit', 0):,.2f} | "
                    f"{m.get('profit_margin_pct', 0.0)}% | {m['transactions']} |"
                )
            return {
                "status": "success",
                "filename": filename,
                "operation": "monthly_summary",
                "answer": "Monthly sales performance comparison:\n\n" + "\n".join(lines),
                "monthly_breakdown": breakdown
            }

    # Fallback: General metadata and numeric summary
    summary_res = execute_excel_analysis("summary", doc_id=filename)
    return {
        "status": "success",
        "filename": filename,
        "operation": "summary",
        "answer": (
            f"Spreadsheet **{filename}** has {len(df)} data rows and {len(df.columns)} columns: "
            f"{', '.join(df.columns)}.\n"
            f"Formulas present: {formula_audit.get('has_formulas', False)}."
        ),
        "summary_data": summary_res
    }


@tool("excel_analyzer", args_schema=ExcelAnalysisInput)
def excel_analyzer_tool(
    operation: str,
    column: Optional[str] = None,
    group_by: Optional[str] = None,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    sheet_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    n: Optional[int] = 5,
    sort_ascending: Optional[bool] = False,
    date_column: Optional[str] = None,
    query: Optional[str] = None
) -> str:
    """
    Analyzes uploaded Excel workbooks (.xlsx, .xls) and CSV spreadsheets.
    Use this tool whenever questions ask for:
    - Sheet names, row counts, column counts, column names
    - Totals, sums, averages, maximums, minimums on columns (e.g. Sales, Target, Profit)
    - Grouping data by department, region, salesperson, or category
    - Top 5 or ranking transactions / salespeople
    - Monthly trends and date-based sales breakdowns
    - Missing value and duplicate transaction audits
    - Filtering specific departments or records
    - Natural language questions about spreadsheet metrics
    """
    res = execute_excel_analysis(
        operation=operation,
        column=column,
        group_by=group_by,
        filter_column=filter_column,
        filter_value=filter_value,
        sheet_name=sheet_name,
        doc_id=doc_id,
        n=n,
        sort_ascending=sort_ascending,
        date_column=date_column,
        query=query
    )
    return json.dumps(res, default=str)
