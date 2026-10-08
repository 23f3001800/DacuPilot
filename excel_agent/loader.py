import pandas as pd

def load_real_world_excel(file_path):
    """
    Scans the Excel file to discover where data actually starts,
    skips empty design headers, and returns a clean DataFrame + Schema metadata.
    """
    # 1. Read a small sample chunk to locate the header row
    sample = pd.read_excel(file_path, header=None, nrows=20, engine='openpyxl')

    populated_counts = sample.notna().sum(axis=1)
    populated_rows = populated_counts[populated_counts > 0].index
    if len(populated_rows) == 0:
        raise ValueError("The provided Excel sheet appears to be empty.")

    # Skip title rows by preferring the first row with multiple populated cells.
    header_rows = populated_counts[populated_counts > 1].index
    start_row_idx = header_rows[0] if len(header_rows) else populated_rows[0]

    # 3. Reload the spreadsheet properly skipping the dead space
    df = pd.read_excel(file_path, skiprows=start_row_idx, engine='openpyxl')

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
    }

    return df, schema_context
