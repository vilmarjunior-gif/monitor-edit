import os
import hashlib
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import google.generativeai as genai
import fitz
import io
import smtplib
import urllib3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Desativa avisos de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURAÇÕES DE IA ---
gemini_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('models/gemini-1.5-flash')

# --- CONFIGURAÇÕES DE ACESSO ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
EMAIL_DESTINO = os.getenv('EMAIL_USER')

# --- PALAVRAS-CHAVE ---
PALAVRAS_INTERESSE = [
    "silvicultura", "proinfra", "fundo", "carbono", "sustentável",
    "chamada", "agricultura", "bioinsumos", "pesquisa", "familiar",
    "regenerativa", "inovação", "clima", "edital", "mato grosso", "amazônia", "acesso",
    "sustentabilidade", "icts", "universal", "insumos biológicos", "agentes de biocontrole",
    "fungicidas microbiológicos", "bioestimulantes", "inoculantes", "indutores de resistência",
    "microbiota do solo", "solubilizadores de fosfato", "fixação biológica de nitrogênio",
    "metabólitos secundários", "ediçãogênica", "crispr-cas9", "bioeconomia",
    "promotores de crescimento", "doenças emergentes", "manejo sustentável",
    "agentes biológicos", "controle biológico", "produtos biológicos", "biopesticidas",
    "biofertilizantes", "bioinseticidas", "biofungicidas", "bionematicidas", "antagonistas",
    "isolados microbianos", "prospecção de microrganismos", "microbiologia do solo",
    "manejo integrado de pragas", "biorremediação", "agricultura familiar",
    "sustentabilidade agrícola", "saúde do solo", "economia circular", "agroecologia",
    "segurançaalimentar", "transição agroecológica", "resiliência climática",
    "descarbonização", "plano de baixa emissão de carbono", "entomologia", "pragas",
    "agroecologia", "sanidade vegetal", "controle biológico"
]

# --- MAPA DE SITES (sem FINEP — tratada separadamente) ---
MAPA_SITES = [
    {
        "nome": "FAPEMAT",
        "url": "https://www.fapemat.mt.gov.br/editais_1",
        "tag": "a",
        "filtro": ["/editais/", "edital"],
        "base_url": "https://www.fapemat.mt.gov.br"
    },
    {
        "nome": "CNPq",
        "url": "https://www.gov.br/cnpq/pt-br/chamadas/abertas-para-submissao",
        "tag": "a",
        "filtro": ["chamada", "chamadas"], 
        "base_url": "https://www.gov.br"
    },
    {
        "nome": "CAPES",
        "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes",
        "tag": "a",
        "filtro": ["editais", "edital"],
        "base_url": "https://www.gov.br"
    },
    {
        "nome": "Clima e Sociedade (iCS)",
        "url": "https://climaesociedade.org/editais/",
        "tag": "h3",
        "filtro": ["http"],
        "base_url": ""
    },
    {
        "nome": "EMBRAPII",
        "url": "https://embrapii.org.br/transparencia/", 
        "tag": "a",
        "filtro": ["chamada", "edital"],
        "base_url": "https://embrapii.org.br"
    },
    {
        "nome": "Hub de Economia e Clima",
        "url": "https://hubdeeconomiaeclima.org.br/editais/",
        "tag": "a",
        "filtro": ["/editais/"],
        "base_url": "https://hubdeeconomiaeclima.org.br",
        "modo": "pagina_unica"
    }
]

DB_FILE = "historico_editais.csv"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


def enviar_email(titulo, resumo, link):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📌 NOVO EDITAL: {titulo[:60]}..."
    
    corpo_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #0056b3;">Novo Edital Encontrado</h2>
        <p style="font-size: 16px;"><b>{titulo}</b></p>
        <hr>
        <h3>🤖 Resumo:</h3>
        <div style="background: #f4f4f4; padding: 12px; border-left: 4px solid #0056b3; white-space: pre-wrap;">
          {resumo}
        </div>
        <br>
        <p style="text-align: center;">
          <a href="{link}" target="_blank" style="background-color: #0056b3; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
            🔗 Acessar Edital Completo
          </a>
        </p>
        <p style="font-size: 12px; color: #777;">Link direto: <a href="{link}">{link}</a></p>
      </body>
    </html>
    """
    msg.attach(MIMEText(corpo_html, 'html'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
            print(f"E-mail enviado para {EMAIL_DESTINO}")
    except Exception as e:
        print(f"Erro e-mail: {e}")


def gerar_resumo_ia(link, titulo_reserva="Edital"):
    try:
        res = requests.get(link, headers=HEADERS, timeout=30, verify=False)
        texto = ""
        if 'pdf' in res.headers.get('Content-Type', '').lower() or link.lower().endswith('.pdf'):
            with fitz.open(stream=io.BytesIO(res.content), filetype="pdf") as doc:
                texto = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            texto = ' '.join(soup.get_text().split())

        if len(texto.strip()) < 100:
            return f"📌 **{titulo_reserva}**\n\n*(Acesse o link direto abaixo para visualizar as informações no portal oficial).* "

        return model.generate_content(
            f"Resuma este edital para a Embrapa em até 4 tópicos curtos (Objetivo, Público, Datas, Valores): {texto[:8000]}"
        ).text
    except Exception as e:
        print(f"Erro na IA para {link}: {e}")
        return f"📌 **{titulo_reserva}**\n\n*(Acesse o edital pelo link abaixo para conferir os detalhes).* "


def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"},
            timeout=10
        )
    except:
        pass


def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    if any(desc in texto_min for desc in ["resultado", "finalizado", "encerrado", "homologação"]):
        return False
    return any(p.lower() in texto_min for p in PALAVRAS_INTERESSE)


def bate_filtro(filtro, *campos):
    if isinstance(filtro, str):
        filtro = [filtro]
    campos_min = [c.lower() for c in campos if c]
    return any(f.lower() in campo for f in filtro for campo in campos_min)


def monitorar_finep(vistos, novos_encontrados):
    print("Verificando FINEP (Nova API)...")
    pagina = 1
    tem_mais_paginas = True

    while tem_mais_paginas:
        url_api = f"https://www.finep.gov.br/o/c/chamadapublicas?sort=dataDePublicacao:desc&search=&page={pagina}&pageSize=250"
        
        try:
            res = requests.get(url_api, headers=HEADERS, timeout=30, verify=False)
            if res.status_code != 200:
                print(f"  FINEP: Falha ao acessar a página {pagina} (Status: {res.status_code}).")
                break
                
            dados = res.json()
            lista_editais = dados.get('items', [])
            
            if not lista_editais:
                break

            for edital in lista_editais:
                titulo = edital.get('titulo') or edital.get('nome') or "Oportunidade FINEP Sem Título"
                id_chamada = edital.get('id')
                
                link_final = f"https://www.finep.gov.br/oportunidades?id={id_chamada}" if id_chamada else "https://www.finep.gov.br/oportunidades"

                if link_final in vistos:
                    continue

                print(f"  Novo edital: {titulo}")
                vistos.append(link_final)

                objetivo = edital.get('objetivo', '')
                condicao = edital.get('condicaoDeFinanciamento', '')
                publico = edital.get('publico', '')
                texto_completo = f"{titulo} {objetivo} {condicao} {publico}"

                novos_encontrados.append(["FINEP", titulo, link_final])

                if verificar_palavras_chave(texto_completo):
                    print(f"  🎯 FINEP RELEVANTE: {titulo}")
                    
                    resumo = model.generate_content(
                        f"Resuma este edital para a Embrapa (Foco: Objetivo, Público, Datas, Valores). Dados: {texto_completo[:8000]}"
                    ).text if texto_completo.strip() else f"Oportunidade FINEP: {titulo}"

                    msg = f"🔔 *NOVO EDITAL (FINEP)*\n\n📄 *{titulo}*\n\n🔗 [Acessar Oportunidade]({link_final})"

                    enviar_telegram(msg)
                    enviar_email(titulo, resumo, link_final)
                    time.sleep(2)

            pagina += 1
            time.sleep(1)

        except Exception as e:
            print(f"  Erro FINEP (página {pagina}): {e}")
            break


def monitorar_pagina_unica(site, vistos, novos_encontrados):
    try:
        res = requests.get(site["url"], headers=HEADERS, timeout=30, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        texto = ' '.join(soup.get_text().split())

        hash_conteudo = hashlib.sha256(texto.encode('utf-8')).hexdigest()
        chave_hash = f"{site['nome']}::hash::{hash_conteudo}"

        if chave_hash in vistos:
            return

        vistos.append(chave_hash)

        titulo_tag = soup.find(['h2', 'h3'])
        titulo = titulo_tag.get_text().strip() if titulo_tag else f"Atualização em {site['nome']}"

        novos_encontrados.append([site["nome"], titulo, site["url"]])

        if verificar_palavras_chave(texto):
            print(f"🎯 RELEVANTE: {titulo} ({site['nome']})")
            resumo = gerar_resumo_ia(site["url"], titulo)
            enviar_telegram(f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🔗 [Acessar Edital]({site['url']})")
            enviar_email(titulo, resumo, site["url"])
            time.sleep(2)

    except Exception as e:
        print(f"Erro em {site['nome']}: {e}")


def monitorar():
    try:
        vistos = pd.read_csv(DB_FILE)['link'].tolist() if os.path.exists(DB_FILE) else []
    except:
        vistos = []

    print(f"[{time.strftime('%H:%M:%S')}] Iniciando monitoramento...")
    novos = []

    # --- FINEP ---
    monitorar_finep(vistos, novos)

    # --- Demais sites ---
    for site in MAPA_SITES:
        try:
            print(f"Verificando {site['nome']}...")

            if site.get("modo") == "pagina_unica":
                monitorar_pagina_unica(site, vistos, novos)
                continue

            res = requests.get(site["url"], headers=HEADERS, timeout=30, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')

            for item in soup.find_all(site["tag"]):
                link_tag = item.find('a') if item.name != 'a' else item
                if not link_tag or not link_tag.get('href'):
                    continue

                link = link_tag['href']
                titulo = link_tag.get_text().strip()

                if link.startswith('/'):
                    link = site["base_url"] + link

                if (bate_filtro(site["filtro"], link, titulo)
                        and link not in vistos
                        and len(titulo) > 15):
                    vistos.append(link)
                    novos.append([site["nome"], titulo, link])
                    
                    if verificar_palavras_chave(titulo):
                        print(f"🎯 RELEVANTE: {titulo}")
                        resumo = gerar_resumo_ia(link, titulo)
                        enviar_telegram(f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🔗 [Acessar Edital]({link})")
                        enviar_email(titulo, resumo, link)
                        time.sleep(2)

        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos:
        pd.DataFrame(novos, columns=['fonte', 'titulo', 'link']).to_csv(
            DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False
        )
        print(f"✅ {len(novos)} novos processados e salvos no CSV.")
    else:
        print("ℹ️ Nenhum edital novo encontrado nesta execução.")


if __name__ == "__main__":
    monitorar()
