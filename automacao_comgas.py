import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

def carregar_config():
    # Tentar carregar de arquivo .env se existir
    env_file = os.path.join(os.getcwd(), ".env")
    cnpj = os.environ.get("COMGAS_CNPJ", "")
    
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("COMGAS_CNPJ="):
                    cnpj = line.split("=", 1)[1].strip().replace(".", "").replace("/", "").replace("-", "")
                    
    if not cnpj:
        print("⚠️ Variável COMGAS_CNPJ não encontrada no .env. Solicite o preenchimento no arquivo .env.")
        sys.exit(1)
        
    # Carregar medidores de medidores.json ou medidores.example.json
    json_path = os.path.join(os.getcwd(), "medidores.json")
    if not os.path.exists(json_path):
        json_path = os.path.join(os.getcwd(), "medidores.example.json")
        
    if not os.path.exists(json_path):
        print("⚠️ Arquivo medidores.json não encontrado.")
        sys.exit(1)
        
    with open(json_path, "r", encoding="utf-8") as f:
        medidores = json.load(f)
        
    return cnpj, medidores

TARGET_URL = "https://virtual.comgas.com.br/?login-documento-e-codigo-usuario="

async def baixar_fatura(context, cnpj, bloco, codigo, pasta_destino):
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    
    print(f"\n=======================================================")
    print(f"▶ Processando Bloco: {bloco} | Código: {codigo}")
    print(f"=======================================================")
    
    try:
        # 1. Acesso à página de login
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)
        
        # 2. Localização do modal de login
        modal = page.locator("modal-container").first
        await modal.wait_for(state="visible", timeout=20000)
        
        cnpj_input = modal.locator("input#cpfCnpj")
        codigo_input = modal.locator("input#codigoUsuario")
        btn_enviar = modal.locator("#btnEnviar")
        
        # Digitação sequencial para acionar as validações reativas
        await cnpj_input.click()
        await cnpj_input.press_sequentially(cnpj, delay=20)
        await cnpj_input.press("Tab")
        
        await codigo_input.click()
        await codigo_input.press_sequentially(codigo, delay=20)
        await codigo_input.press("Tab")
        
        await page.wait_for_timeout(500)
        await btn_enviar.click()
        
        # 3. Aguardar autenticação e limpar overlay
        await page.wait_for_timeout(5000)
        await page.evaluate("""() => {
            document.querySelectorAll('modal-container, .modal-backdrop, .modal').forEach(m => m.remove());
            document.body.classList.remove('modal-open');
            document.body.style.overflow = 'auto';
        }""")
        
        # Fechar banner de cookies se existir
        try:
            cookie_btn = page.locator("button:has-text('Aceitar Todos'), button:has-text('Permitir todos')").first
            if await cookie_btn.count() > 0 and await cookie_btn.is_visible():
                await cookie_btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass
        
        # 4. Navegar até o Extrato 2ª Via
        print(f"[{bloco}] Acessando Extrato 2ª Via...")
        await page.evaluate("""() => {
            const elements = Array.from(document.querySelectorAll('p, a, span, div, button'));
            const target = elements.find(el => el.innerText && el.innerText.trim() === 'Extrato 2ª Via');
            if (target) {
                target.click();
                if (target.parentElement) target.parentElement.click();
            }
        }""")
        
        # 5. Localizar botão do PDF e capturar o download
        await page.wait_for_timeout(5000)
        btn_pdf = page.locator("button:has-text('PDF da 2ª Via')").first
        await btn_pdf.wait_for(state="visible", timeout=20000)
        
        print(f"[{bloco}] Clicando em 'PDF da 2ª Via'...")
        async with page.expect_download(timeout=25000) as download_info:
            await btn_pdf.click()
        download = await download_info.value
        
        # 6. Salvar com a nomenclatura padrão
        nome_arquivo = f"Fatura_Comgas_{bloco}_{codigo}.pdf"
        caminho_final = os.path.join(pasta_destino, nome_arquivo)
        await download.save_as(caminho_final)
        
        print(f"✅ [{bloco}] Concluído com sucesso! Salvo em: {nome_arquivo}")
        return True, nome_arquivo
        
    except Exception as e:
        print(f"❌ [{bloco}] Erro durante o processo: {e}")
        try:
            await page.screenshot(path=os.path.join(pasta_destino, f"erro_{bloco}_{codigo}.png"))
        except Exception:
            pass
        return False, str(e)
    finally:
        await page.close()

async def executar_todos():
    cnpj, medidores = carregar_config()
    pasta_destino = os.path.join(os.getcwd(), "faturas")
    os.makedirs(pasta_destino, exist_ok=True)
    
    print("==================================================================")
    print("🚀 ComgasCraft: AUTOMAÇÃO DE DOWNLOADS DE 2ª VIA COMGÁS")
    print(f"📁 Pasta de destino: {pasta_destino}")
    print(f"📊 Total de medidores a processar: {len(medidores)}")
    print("==================================================================")
    
    relatorio = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
        )
        
        for idx, item in enumerate(medidores, 1):
            bloco = item["bloco"]
            codigo = item["codigo"]
            
            context = await browser.new_context(
                no_viewport=True,
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            
            print(f"\nProgresso: [{idx}/{len(medidores)}]")
            sucesso, msg = await baixar_fatura(context, cnpj, bloco, codigo, pasta_destino)
            relatorio.append({"bloco": bloco, "codigo": codigo, "sucesso": sucesso, "detalhes": msg})
            
            await context.close()
            await asyncio.sleep(2)
            
        await browser.close()
        
    # Resumo final
    print("\n==================================================================")
    print("📋 RELATÓRIO FINAL DA OPERAÇÃO")
    print("==================================================================")
    total_sucesso = sum(1 for r in relatorio if r["sucesso"])
    print(f"Total processado: {len(relatorio)} | Sucesso: {total_sucesso} | Falhas: {len(relatorio) - total_sucesso}\n")
    for r in relatorio:
        status = "✅ OK" if r["sucesso"] else "❌ FALHA"
        print(f"[{status}] Bloco {r['bloco']} ({r['codigo']}) -> {r['detalhes']}")
    print("==================================================================")

if __name__ == "__main__":
    asyncio.run(executar_todos())
