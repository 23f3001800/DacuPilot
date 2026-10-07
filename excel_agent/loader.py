import pandas as pd

def load_real_world_excel(file_path):
    """
    Scans the Excel file to discover where data actually starts,
    skips empty design headers, and returns a clean DataFrame + Schema metadata.
    """
    # 1. Read a small sample chunk to locate the header row
    sample = pd.read_excel(file_path, header=None, nrows=20, engine='openpyxl')
    
    # 2. Find rows that are NOT completely empty (NaN)
    valid_rows = sample.dropna(how='all').index
    
    if len(valid_rows) == 0:
        raise ValueError("The provided Excel sheet appears to be empty.")
    
    # The actual data table starts at the first non-empty layout row index
    start_row_idx = valid_rows[0]
    
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
