import os
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
    "descarbonização", "plano de baixa emissão de carbono"
]

# --- MAPA DE SITES (sem FINEP — tratada separadamente) ---
MAPA_SITES = [
    {"nome": "FAPEMAT", "url": "https://www.fapemat.mt.gov.br/aberto", "tag": "a", "filtro": "/editais/", "base_url": ""},
    {"nome": "CNPq", "url": "http://memoria2.cnpq.br/web/guest/chamadas-public-as", "tag": "a", "filtro": "id=", "base_url": ""},
    {"nome": "CAPES", "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes", "tag": "a", "filtro": "editais", "base_url": ""},
    {"nome": "Clima e Sociedade (iCS)", "url": "https://climaesociedade.org/editais/", "tag": "h3", "filtro": "http", "base_url": ""},
    {"nome": "EMBRAPII", "url": "https://embrapii.org.br/transparencia/#chamadas", "tag": "a", "filtro": "chamadas-publicas", "base_url": ""},
    {"nome": "Hub de Economia e Clima", "url": "https://hubdeeconomiaeclima.org.br/editais/", "tag": "a", "filtro": "/editais/", "base_url": "https://hubdeeconomiaeclima.org.br"}
]

DB_FILE = "historico_editais.csv"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

# Padrões de URL que indicam plataforma de submissão da FINEP
PADROES_SUBMISSAO = [
    '/e/chamada-publica/',
    'cadastro.finep.gov.br',
    'plataforma.finep',
    'chamada-publica',
]


def enviar_email(titulo, resumo, link):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📌 NOVO EDITAL: {titulo[:60]}..."
    corpo_html = (
        f"<html><body>"
        f"<h2>Novo Edital Encontrado</h2>"
        f"<p><b>{titulo}</b></p>"
        f"<hr><h3>🤖 Resumo:</h3>"
        f"<p style='white-space: pre-wrap;'>{resumo}</p>"
        f"<hr><a href='{link}'>Acessar Edital Completo</a>"
        f"</body></html>"
    )
    msg.attach(MIMEText(corpo_html, 'html'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Erro e-mail: {e}")


def gerar_resumo_ia(link):
    try:
        res = requests.get(link, headers=HEADERS, timeout=40, verify=False)
        if 'pdf' in res.headers.get('Content-Type', '').lower() or link.lower().endswith('.pdf'):
            with fitz.open(stream=io.BytesIO(res.content), filetype="pdf") as doc:
                texto = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            texto = ' '.join(soup.get_text().split())
        return model.generate_content(
            f"Analise este edital de forma técnica e direta para a Embrapa (Objetivo, Público, Datas, Valores): {texto[:8000]}"
        ).text
    except:
        return "⚠️ Erro ao processar resumo."


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


def extrair_detalhes_finep(url_edital):
    """
    Acessa a página individual de um edital da FINEP e extrai:
    - Descrição completa (para palavras-chave mais ricas que só o título)
    - Link de submissão da plataforma externa (/e/chamada-publica/XXXXX/YYYYY)

    Retorna dict com 'descricao' e 'link_submissao'.
    """
    detalhes = {
        "descricao": "",
        "link_submissao": None,
    }
    try:
        res = requests.get(url_edital, headers=HEADERS, timeout=30, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')

        # Texto completo da página para enriquecer a busca por palavras-chave
        detalhes["descricao"] = ' '.join(soup.get_text().split())

        # Varre todos os links da página em busca do link de submissão externo
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if any(padrao in href for padrao in PADROES_SUBMISSAO):
                # Ignora links que são a própria página da listagem
                if 'chamadaspublicas' in href:
                    continue
                # Normaliza para URL absoluta se necessário
                if href.startswith('/'):
                    href = 'https://www.finep.gov.br' + href
                detalhes["link_submissao"] = href
                print(f"    🔗 Link de submissão: {href}")
                break  # Primeiro encontrado é o principal

    except Exception as e:
        print(f"    Erro ao extrair detalhes de {url_edital}: {e}")

    return detalhes


def monitorar_finep(vistos, novos_encontrados):
    """
    Percorre todas as páginas de chamadas abertas da FINEP com paginação.
    Para cada edital novo, acessa a página individual para:
      1. Verificar palavras-chave na descrição completa (mais rico que só título)
      2. Extrair o link real de submissão da plataforma externa
    Notifica com ambos os links: página do edital + link de submissão.
    """
    base = "https://www.finep.gov.br"
    start = 0
    print("Verificando FINEP (paginação + extração de links de submissão)...")

    while True:
        url = f"{base}/chamadas-publicas/chamadaspublicas?situacao=aberta&start={start}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')

            itens = soup.find_all(['h3', 'h4'])
            if not itens:
                print(f"  FINEP: sem itens na página start={start}, encerrando.")
                break

            chamadas_na_pagina = 0
            for item in itens:
                link_tag = item.find('a', href=True)
                if not link_tag:
                    continue

                link_listagem = link_tag['href'].strip()
                titulo = link_tag.get_text().strip()

                if not link_listagem or not titulo:
                    continue

                if link_listagem.startswith('/'):
                    link_listagem = base + link_listagem

                # Só processa links de chamada pública individual
                if 'chamadapublica' not in link_listagem.lower():
                    continue

                chamadas_na_pagina += 1

                # Controle de duplicidade pelo link da listagem
                if link_listagem in vistos:
                    continue

                vistos.append(link_listagem)
                print(f"  Novo edital encontrado: {titulo}")

                # Acessa página do edital para extrair detalhes e link de submissão
                detalhes = extrair_detalhes_finep(link_listagem)
                time.sleep(1)

                # Texto completo para verificação de palavras-chave
                texto_completo = titulo + " " + detalhes["descricao"]

                # Link para salvar no histórico e enviar ao usuário:
                # Preferência para o link de submissão externo quando disponível
                link_final = detalhes["link_submissao"] if detalhes["link_submissao"] else link_listagem
                novos_encontrados.append(["FINEP", titulo, link_final])

                if verificar_palavras_chave(texto_completo):
                    print(f"  🎯 FINEP RELEVANTE: {titulo}")
                    resumo = gerar_resumo_ia(link_listagem)  # Resumo sempre da página do edital (mais completo)

                    # Notificação com link de submissão quando disponível
                    if detalhes["link_submissao"]:
                        msg = (
                            f"🔔 *NOVO EDITAL (FINEP)*\n\n"
                            f"📄 *{titulo}*\n\n"
                            f"📋 [Ver Edital]({link_listagem})\n"
                            f"📝 [Submeter Proposta]({detalhes['link_submissao']})"
                        )
                    else:
                        msg = (
                            f"🔔 *NOVO EDITAL (FINEP)*\n\n"
                            f"📄 *{titulo}*\n\n"
                            f"🔗 [Acessar Edital]({link_listagem})"
                        )

                    enviar_telegram(msg)
                    enviar_email(titulo, resumo, link_listagem)
                    time.sleep(2)

            # Verifica paginação
            proximo = soup.find('a', string=lambda t: t and 'Próx' in t)
            if not proximo or chamadas_na_pagina == 0:
                print(f"  FINEP: última página processada (start={start}).")
                break

            start += 10
            time.sleep(1)

        except Exception as e:
            print(f"  Erro FINEP (start={start}): {e}")
            break


def monitorar():
    vistos = pd.read_csv(DB_FILE)['link'].tolist() if os.path.exists(DB_FILE) else []
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando monitoramento global...")
    novos_encontrados = []

    # --- FINEP: tratamento especial com paginação e extração de links ---
    monitorar_finep(vistos, novos_encontrados)

    # --- Demais sites ---
    for site in MAPA_SITES:
        try:
            print(f"Verificando {site['nome']}...")
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

                if site["filtro"] in link.lower() and link not in vistos and len(titulo) > 15:
                    vistos.append(link)
                    novos_encontrados.append([site["nome"], titulo, link])
                    if verificar_palavras_chave(titulo):
                        print(f"🎯 RELEVANTE: {titulo}")
                        resumo = gerar_resumo_ia(link)
                        enviar_telegram(
                            f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🔗 [Link]({link})"
                        )
                        enviar_email(titulo, resumo, link)
                        time.sleep(2)

        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos_encontrados:
        pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link']).to_csv(
            DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False
        )
        print(f"✅ {len(novos_encontrados)} processados.")
    else:
        print("ℹ️ Nenhum item novo encontrado nesta execução.")


if __name__ == "__main__":
    monitorar()
