import sys
import os
import time
from fpdf import FPDF
from playwright.sync_api import sync_playwright

survey_url = sys.argv[1]
output_dir = sys.argv[2]

os.makedirs(output_dir, exist_ok=True)
shots_dir = os.path.join(output_dir, "screenshots")
os.makedirs(shots_dir, exist_ok=True)

NEXT_TEXTS = ["Next", "Avançar", "Continuar", "Próximo", "Submit", "Enviar"]

def find_next(page):
    # tenta achar botão/link de "Next"
    for t in NEXT_TEXTS:
        for sel in [f"button:has-text('{t}')",
                    f"input[type='submit'][value*='{t}']",
                    f"input[type='button'][value*='{t}']",
                    f"a:has-text('{t}')"]:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    if loc.first.is_visible():
                        return loc.first
                except Exception:
                    pass
    return None

def answer_first_options(page):
    actions = 0

    # Radios: marca o primeiro de cada grupo
    radios = page.locator("input[type='radio']")
    try:
        n = radios.count()
    except Exception:
        n = 0

    if n > 0:
        names = set()
        for i in range(n):
            try:
                nm = radios.nth(i).get_attribute("name")
                if nm:
                    names.add(nm)
            except Exception:
                pass

        for nm in names:
            group = page.locator(f"input[type='radio'][name='{nm}']")
            try:
                gn = group.count()
                if gn == 0:
                    continue
                # escolhe o primeiro visível
                chosen = None
                for j in range(gn):
                    r = group.nth(j)
                    try:
                        if r.is_visible() and r.is_enabled():
                            chosen = r
                            break
                    except Exception:
                        pass
                if chosen:
                    try:
                        if not chosen.is_checked():
                            chosen.click(force=True)
                            actions += 1
                    except Exception:
                        pass
            except Exception:
                pass

    # Checkboxes: marca o primeiro checkbox visível
    cbs = page.locator("input[type='checkbox']")
    try:
        cn = cbs.count()
    except Exception:
        cn = 0

    if cn > 0:
        for i in range(cn):
            cb = cbs.nth(i)
            try:
                if cb.is_visible() and cb.is_enabled() and not cb.is_checked():
                    cb.click(force=True)
                    actions += 1
                    break
            except Exception:
                pass

    # Text inputs: preenche com "teste" se vazio
    inputs = page.locator("input[type='text'], input[type='number'], input[type='email']")
    try:
        tn = inputs.count()
    except Exception:
        tn = 0

    for i in range(tn):
        inp = inputs.nth(i)
        try:
            if inp.is_visible() and inp.is_enabled():
                val = inp.input_value()
                if not val.strip():
                    inp.fill("25" if (inp.get_attribute("type") == "number") else "teste")
                    actions += 1
        except Exception:
            pass

    # Textarea
    tas = page.locator("textarea")
    try:
        ttn = tas.count()
    except Exception:
        ttn = 0
    for i in range(ttn):
        ta = tas.nth(i)
        try:
            if ta.is_visible() and ta.is_enabled():
                val = ta.input_value()
                if not val.strip():
                    ta.fill("teste")
                    actions += 1
        except Exception:
            pass

    return actions

def build_pdf(summary_lines, screenshot_files, pdf_path):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 8, "\n".join(summary_lines))

    pdf.ln(4)
    pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 7, "Screenshots gerados (arquivos):")
    for f in screenshot_files[:40]:
        pdf.multi_cell(0, 6, f"- {f}")

    pdf.output(pdf_path)

def main():
    max_pages = 60
    screenshot_files = []
    summary = [
        "RELATÓRIO DE TESTE AUTOMÁTICO (MVP)",
        "",
        f"Link testado: {survey_url}",
        "",
        "Perfil: sempre primeira opção (quando aplicável).",
        ""
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(survey_url, wait_until="domcontentloaded")
        time.sleep(1)

        stopped_reason = None

        for idx in range(1, max_pages + 1):
            shot_path = os.path.join(shots_dir, f"{idx:03d}.png")
            try:
                page.screenshot(path=shot_path, full_page=True)
                screenshot_files.append(f"screenshots/{idx:03d}.png")
            except Exception:
                pass

            actions = answer_first_options(page)

            nxt = find_next(page)
            if not nxt:
                stopped_reason = f"Parou na etapa {idx}: não encontrou botão de avançar."
                break

            try:
                nxt.click()
            except Exception as e:
                stopped_reason = f"Parou na etapa {idx}: erro ao clicar em avançar ({e})."
                break

            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass

            # Detecta tela de finalização (heurística simples)
            try:
                body = page.locator("body").inner_text().lower()
                if any(k in body for k in ["obrigado", "thank you", "finalizado", "concluído", "completed"]):
                    stopped_reason = f"Finalizou com sucesso na etapa {idx}."
                    break
            except Exception:
                pass

        if not stopped_reason:
            stopped_reason = f"Parou por limite máximo de páginas ({max_pages})."

        summary.append(f"Resultado: {stopped_reason}")
        summary.append("")
        summary.append(f"Total de screenshots: {len(screenshot_files)}")

        pdf_path = os.path.join(output_dir, "report.pdf")
        build_pdf(summary, screenshot_files, pdf_path)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
