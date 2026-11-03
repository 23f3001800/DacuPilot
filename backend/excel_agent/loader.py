import re

import pandas as pd

MAX_WORKBOOK_ROWS = 250_000
MAX_WORKBOOK_COLUMNS = 500
MAX_WORKBOOK_CELLS = 5_000_000


def _stable_column_names(columns):
    """Keep every source column addressable, including blank/duplicate headers."""
    used = set()
    names = []
    for index, value in enumerate(columns, start=1):
        base = str(value).strip() if value is not None and str(value).strip() else f"Column {index}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} ({suffix})"
            suffix += 1
        used.add(candidate)
        names.append(candidate)
    return names


def _header_values(sheet, header_row: int, column_count: int) -> list[object]:
    values = [sheet.cell(row=header_row, column=index).value for index in range(1, column_count + 1)]
    for merged in sheet.merged_cells.ranges:
        if merged.min_row <= header_row <= merged.max_row:
            title = sheet.cell(row=merged.min_row, column=merged.min_col).value
            start = max(1, merged.min_col)
            end = min(column_count, merged.max_col)
            for column in range(start, end + 1):
                values[column - 1] = title
    return values


def _semantic_type(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    values = series.dropna().astype(str).head(500)
    if values.empty:
        return "empty"

    has_currency = values.str.contains(r"[$€£₹¥]", regex=True).any()
    numeric_text = values.str.replace(r"[\s,$€£₹¥]", "", regex=True)
    numeric_ratio = pd.to_numeric(numeric_text, errors="coerce").notna().mean()
    if numeric_ratio >= 0.8:
        return "currency" if has_currency else "numeric text"

    date_values = pd.to_datetime(values, errors="coerce", format="mixed")
    if date_values.notna().mean() >= 0.8:
        return "date text"
    if series.nunique(dropna=True) <= min(50, max(10, len(series) // 5)):
        return "category"
    return "text"


def load_real_world_excel(file_path, sheet_name=None):
    """Load a selected worksheet and return normalized columns plus safe metadata."""
    try:
        workbook = pd.ExcelFile(file_path, engine="openpyxl")
    except Exception as error:
        raise ValueError("The uploaded file is not a readable Excel workbook.") from error
    try:
        sheet_names = workbook.sheet_names
        if not sheet_names:
            raise ValueError("The workbook contains no worksheets.")
        hidden_sheets = [sheet.title for sheet in workbook.book.worksheets if sheet.sheet_state != "visible"]
        visible_sheets = [sheet.title for sheet in workbook.book.worksheets if sheet.sheet_state == "visible"]
        selected_sheet = sheet_name or (visible_sheets[0] if visible_sheets else sheet_names[0])
        if selected_sheet not in sheet_names:
            raise ValueError(f"Worksheet '{selected_sheet}' was not found.")

        sample = pd.read_excel(file_path, sheet_name=selected_sheet, header=None, nrows=20, engine="openpyxl")
        populated_counts = sample.notna().sum(axis=1)
        populated_rows = populated_counts[populated_counts > 0].index
        if len(populated_rows) == 0:
            raise ValueError(f"Worksheet '{selected_sheet}' is empty.")

        header_candidates = populated_counts[populated_counts > 1].index
        header_row_index = int(header_candidates[0] if len(header_candidates) else populated_rows[0])
        header_row = header_row_index + 1
        sheet = workbook.book[selected_sheet]
        column_count = int(sample.shape[1])
        if column_count > MAX_WORKBOOK_COLUMNS:
            raise ValueError(
                f"Worksheet '{selected_sheet}' exceeds the {MAX_WORKBOOK_COLUMNS}-column analysis limit. "
                "Remove unused columns and upload the relevant data."
            )
        source_headers = _header_values(sheet, header_row, column_count)
        row_limit = min(
            MAX_WORKBOOK_ROWS,
            max(1, MAX_WORKBOOK_CELLS // max(column_count, 1)),
        )

        frame = pd.read_excel(
            file_path,
            sheet_name=selected_sheet,
            skiprows=header_row,
            header=None,
            nrows=row_limit + 1,
            engine="openpyxl",
        )
        if len(frame) > row_limit and row_limit < MAX_WORKBOOK_ROWS:
            raise ValueError(
                f"Worksheet '{selected_sheet}' exceeds the {MAX_WORKBOOK_CELLS:,}-cell analysis limit. "
                "Split the workbook or select a smaller relevant worksheet."
            )
        if len(frame) > MAX_WORKBOOK_ROWS:
            raise ValueError(
                f"Worksheet '{selected_sheet}' exceeds the {MAX_WORKBOOK_ROWS:,}-row analysis limit. "
                "Split the workbook into smaller files and upload the relevant section."
            )

        width = max(len(frame.columns), len(source_headers))
        if width > MAX_WORKBOOK_COLUMNS:
            raise ValueError(
                f"Worksheet '{selected_sheet}' exceeds the {MAX_WORKBOOK_COLUMNS}-column analysis limit. "
                "Remove unused columns and upload the relevant data."
            )
        if len(frame) * width > MAX_WORKBOOK_CELLS:
            raise ValueError(
                f"Worksheet '{selected_sheet}' exceeds the {MAX_WORKBOOK_CELLS:,}-cell analysis limit. "
                "Split the workbook or select a smaller relevant worksheet."
            )
        if len(frame.columns) < width:
            for column in range(len(frame.columns), width):
                frame[column] = pd.NA
        names = _stable_column_names(source_headers[:width])
        frame = frame.iloc[:, :width]
        frame.columns = names
        frame = frame.dropna(how="all").reset_index(drop=True)

        data_types = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
        schema_context = {
            "columns": list(frame.columns),
            "data_types": data_types,
            "semantic_types": {str(column): _semantic_type(frame[column]) for column in frame.columns},
            "total_rows": len(frame),
            "missing_values": {str(column): int(value) for column, value in frame.isna().sum().items()},
            "empty_columns": [str(column) for column in frame.columns if frame[column].isna().all()],
            "first_3_rows_sample": frame.head(3).where(frame.head(3).notna(), None).to_dict(orient="records"),
            "sheet_names": sheet_names,
            "hidden_sheets": hidden_sheets,
            "selected_sheet": selected_sheet,
            "header_row": header_row,
            "merged_headers": any(merged.min_row <= header_row <= merged.max_row for merged in sheet.merged_cells.ranges),
            "row_limit": MAX_WORKBOOK_ROWS,
            "column_limit": MAX_WORKBOOK_COLUMNS,
            "cell_limit": MAX_WORKBOOK_CELLS,
            "effective_row_limit": row_limit,
        }
        return frame, schema_context
    finally:
        workbook.close()
