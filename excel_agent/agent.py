import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from loader import load_real_world_excel
from engine import PythonSandboxREPL

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def run_data_agent(file_path, user_question):
    # 1. Setup Data Frame and Schema Summary Map
    df, schema = load_real_world_excel(file_path)
    repl = PythonSandboxREPL(df)
    
    # 2. Build the System Blueprint to instruct the Agent
    system_prompt = f"""
You are a senior data analyst agent running in a REPL environment. 
You can run code against a pre-loaded Pandas DataFrame named `df`.

Here is the exact data layout extracted from the file (skipping blank leading design rows):
- Available Columns: {schema['columns']}
- Data Types: {json.dumps(schema['data_types'])}
- Total Record Count: {schema['total_rows']}
- Missing Values Per Column: {json.dumps(schema['missing_values'])}
- Sample Rows: {json.dumps(schema['first_3_rows_sample'])}

CRITICAL WORKING FORMAT RULES:
If you need to calculate an answer via Python, reply using this exact multi-line structure:
THOUGHT: State your plan to extract the data.
CODE:
```python
# Write executable Python code here. 
# ALWAYS explicitly use print() statement to expose the answer metrics.
print(df['your_target_column'].mean())
```

Once you receive the execution result text from the environment sandbox, summarize your final findings clearly in standard conversational plain English using:
FINAL ANSWER: Your complete text answer summary here.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question}
    ]
    
    # 3. Execution Loops (Allows up to 3 self-correction retries if errors occur)
    for iteration in range(3):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.1
        )
        
        assistant_reply = response.choices[0].message.content
        print(f"\n--- [Agent Thought Process Loop {iteration+1}] ---\n{assistant_reply}")
        
        if "CODE:" in assistant_reply:
            # Parse out code block
            parts = assistant_reply.split("```python")
            if len(parts) > 1:
                code_block = parts[1].split("```")[0].strip()
                
                # Run extracted code inside our execution sandbox
                execution_result = repl.execute_code(code_block)
                print(f"\n--- [REPL Console Output] ---\n{execution_result}")
                
                # Feed code console logs back into the conversation context
                messages.append({"role": "assistant", "content": assistant_reply})
                messages.append({"role": "user", "content": f"REPL CONSOLE OUTPUT:\n{execution_result}"})
                continue
        
        if "FINAL ANSWER:" in assistant_reply:
            return assistant_reply.split("FINAL ANSWER:")[1].strip()
            
    return "Agent loop timed out without reaching a finalized summary."

# Quick Execution Test Interface
if __name__ == "__main__":
    # Ensure an environment variable file exists with your: OPENAI_API_KEY=sk-...
    FILE_TARGET = "your_complex_file.xlsx" 
    QUESTION = "Which column has the highest number of missing values and what are our top 3 highest revenue metrics?"
    
    if os.path.exists(FILE_TARGET):
        final_summary = run_data_agent(FILE_TARGET, QUESTION)
        print(f"\n============================\n🤖 AGENT SUMMARY RESULT:\n============================\n{final_summary}")
    else:
        print(f"Please drop a target excel spreadsheet named '{FILE_TARGET}' into this folder to test.")
