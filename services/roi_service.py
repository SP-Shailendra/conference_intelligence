import pandas as pd

def calculate_roi_metrics():
    # Lavo pricing estimates from Section 16
    lavo_cost_matrix = pd.DataFrame([
        {'Conference': 'ASCO Annual Meeting',  'Lavo_Cost_USD': 18500, 'Abstracts_Covered': 5000},
        {'Conference': 'ACR Convergence',      'Lavo_Cost_USD': 16000, 'Abstracts_Covered': 4500},
        {'Conference': 'ESMO Congress',        'Lavo_Cost_USD': 14000, 'Abstracts_Covered': 3800},
        {'Conference': 'EHA Congress',         'Lavo_Cost_USD': 9500,  'Abstracts_Covered': 2200},
        {'Conference': 'ASH Annual Meeting',   'Lavo_Cost_USD': 15500, 'Abstracts_Covered': 4200},
        {'Conference': 'AACR Annual Meeting',  'Lavo_Cost_USD': 12000, 'Abstracts_Covered': 3500},
    ])

    # Token cost constants
    AZURE_IN, AZURE_OUT = 0.005, 0.015
    AVG_IN_TOKENS, AVG_OUT_TOKENS = 600, 120

    def llm_cost(n):
        return round((n * AVG_IN_TOKENS / 1000) * AZURE_IN + (n * AVG_OUT_TOKENS / 1000) * AZURE_OUT, 4)

    # Apply calculations
    lavo_cost_matrix['LLM_Cost_Azure_USD'] = lavo_cost_matrix['Abstracts_Covered'].apply(llm_cost)
    lavo_cost_matrix['Savings_Azure_USD'] = lavo_cost_matrix['Lavo_Cost_USD'] - lavo_cost_matrix['LLM_Cost_Azure_USD']
    lavo_cost_matrix['ROI_Pct_Azure'] = (lavo_cost_matrix['Savings_Azure_USD'] / lavo_cost_matrix['Lavo_Cost_USD'] * 100).round(1)

    total_lavo = lavo_cost_matrix['Lavo_Cost_USD'].sum()
    total_azure = lavo_cost_matrix['LLM_Cost_Azure_USD'].sum()
    savings_azure = lavo_cost_matrix['Savings_Azure_USD'].sum()

    # Extrapolate to 22 conferences
    est22_lavo = (total_lavo / 6) * 22
    est22_azure = (total_azure / 6) * 22
    est22_save = est22_lavo - est22_azure

    return {
        "conferences": lavo_cost_matrix.to_dict(orient='records'),
        "total_lavo": f"{total_lavo:,.0f}",
        "total_azure": f"{total_azure:,.2f}",
        "savings_azure": f"{savings_azure:,.0f}",
        "roi_azure_pct": round((savings_azure/total_lavo)*100, 1),
        "est22_lavo": f"{est22_lavo:,.0f}",
        "est22_save": f"{est22_save:,.0f}"
    }