import pandas as pd

def load_real_world_excel(file_path, sheet_name=None):
    """
    Scans the Excel file to discover where data actually starts,
    skips empty design headers, and returns a clean DataFrame + Schema metadata.
    """
    workbook = pd.ExcelFile(file_path, engine="openpyxl")
    sheet_names = workbook.sheet_names
    if not sheet_names:
        raise ValueError("The workbook contains no worksheets.")
    selected_sheet = sheet_name or sheet_names[0]
    if selected_sheet not in sheet_names:
        raise ValueError(f"Worksheet '{selected_sheet}' was not found.")

    # 1. Read a small sample chunk to locate the header row
    sample = pd.read_excel(file_path, sheet_name=selected_sheet, header=None, nrows=20, engine='openpyxl')

    populated_counts = sample.notna().sum(axis=1)
    populated_rows = populated_counts[populated_counts > 0].index
    if len(populated_rows) == 0:
        raise ValueError("The provided Excel sheet appears to be empty.")

    # Skip title rows by preferring the first row with multiple populated cells.
    header_rows = populated_counts[populated_counts > 1].index
    start_row_idx = header_rows[0] if len(header_rows) else populated_rows[0]

    # 3. Reload the spreadsheet properly skipping the dead space
    df = pd.read_excel(file_path, sheet_name=selected_sheet, skiprows=start_row_idx, engine='openpyxl')

    # Clean up column names (remove leading/trailing spaces or 'Unnamed' artifacts)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

    # 4. Construct a concise text map for the LLM's system instructions
    schema_context = {
        "columns": list(df.columns),
        "data_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "total_rows": len(df),
        "missing_values": df.isnull().sum().to_dict(),
        "first_3_rows_sample": df.head(3).to_dict(orient='records')
        ,"sheet_names": sheet_names
        ,"selected_sheet": selected_sheet
    }

    return df, schema_context
