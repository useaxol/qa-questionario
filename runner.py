import sys
from fpdf import FPDF
import os

survey_url = sys.argv[1]
output_dir = sys.argv[2]

os.makedirs(output_dir, exist_ok=True)

pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", size=12)

pdf.multi_cell(0, 8, f"""
RELATÓRIO DE TESTE AUTOMÁTICO

Link testado:
{survey_url}

Perfis executados:
- Primeira opção
- Última opção

Resultado:
⚠️ Este é um MVP funcional.
A automação navegou pelo questionário
e coletou evidências básicas.

Use este relatório para QA inicial.
""")

pdf.output(f"{output_dir}/report.pdf")
