import os
import re
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

# Padrões de href para busca via BeautifulSoup
PADROES_SUBMISSAO_HREF = [
    '/e/chamada-publica/',
    'cadastro.finep.gov.br',
    'financiamento.finep.gov.br',   # plataforma FAP (chamadas para ICTs/empresas)
    'plataforma.finep',
]

# Padrões de regex para busca no HTML bruto (captura links em JS, texto, atributos, etc.)
PADROES_SUBMISSAO_REGEX = [
    r'https?://(?:www\.)?finep\.gov\.br/e/chamada-publica/[\d/]+',
    r'https?://financiamento\.finep\.gov\.br[^\s"\'<>&]+',
    r'https?://cadastro\.finep\.gov\.br[^\s"\'<>&]+',
    r'https?://plataforma\.finep[^\s"\'<>&]+',
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
            f"Resuma este edital para a Embrapa (Foco: Objetivo, Público, Datas, Valores): {texto[:8000]}"
        ).text
    except:
        return "⚠️ Não foi possível ler o conteúdo automaticamente."


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
    Acessa a página individual do edital da FINEP e extrai:
    - Descrição completa (para verificação de palavras-chave)
    - Link de submissão da plataforma externa

    Estratégia dupla:
    1. Busca via BeautifulSoup em <a href> (links explícitos no HTML)
    2. Busca via regex no HTML bruto (captura links em JS inline, atributos data-*, texto, etc.)
    """
    detalhes = {"descricao": "", "link_submissao": None}
    try:
        res = requests.get(url_edital, headers=HEADERS, timeout=30, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        html_bruto = res.text

        # Texto limpo para palavras-chave
        detalhes["descricao"] = ' '.join(soup.get_text().split())

        # --- TENTATIVA 1: links <a href> normais ---
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if any(p in href for p in PADROES_SUBMISSAO_HREF) and 'chamadaspublicas' not in href:
                detalhes["link_submissao"] = (
                    'https://www.finep.gov.br' + href if href.startswith('/') else href
                )
                print(f"    🔗 Link submissão (href): {detalhes['link_submissao']}")
                break

        # --- TENTATIVA 2: regex no HTML bruto (fallback para links em JS ou atributos) ---
        if not detalhes["link_submissao"]:
            for padrao in PADROES_SUBMISSAO_REGEX:
                match = re.search(padrao, html_bruto)
                if match:
                    detalhes["link_submissao"] = match.group(0).rstrip('.,;)')
                    print(f"    🔗 Link submissão (regex): {detalhes['link_submissao']}")
                    break

        if not detalhes["link_submissao"]:
            print(f"    ⚠️  Nenhum link de submissão encontrado para: {url_edital}")

    except Exception as e:
        print(f"    Erro ao extrair detalhes de {url_edital}: {e}")

    return detalhes


def monitorar_finep(vistos, novos_encontrados):
    """
    Percorre todas as páginas de chamadas abertas da FINEP com paginação.
    Para cada edital novo:
      1. Acessa a página individual para extrair descrição e link de submissão
      2. Verifica palavras-chave na descrição completa (não só no título)
      3. Envia notificação com link do edital + link de submissão quando disponível
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

            encontrados_nesta_pag = 0
            for item in itens:
                link_tag = item.find('a', href=True)
                if not link_tag:
                    continue

                href = link_tag['href'].strip()
                link_listagem = base + href if href.startswith('/') else href
                titulo = link_tag.get_text().strip()

                if not titulo or 'chamadapublica' not in link_listagem.lower():
                    continue

                encontrados_nesta_pag += 1

                if link_listagem in vistos:
                    continue

                print(f"  Novo edital: {titulo}")
                vistos.append(link_listagem)

                # Acessa página do edital para descrição completa + link de submissão
                detalhes = extrair_detalhes_finep(link_listagem)
                time.sleep(1)

                # Texto completo para palavras-chave (título + corpo da página)
                texto_completo = titulo + " " + detalhes["descricao"]

                # Link final: usa submissão se disponível, senão usa listagem
                link_final = detalhes["link_submissao"] if detalhes["link_submissao"] else link_listagem
                novos_encontrados.append(["FINEP", titulo, link_final])

                if verificar_palavras_chave(texto_completo):
                    print(f"  🎯 FINEP RELEVANTE: {titulo}")
                    resumo = gerar_resumo_ia(link_listagem)  # Resumo da página pública (mais completo)

                    # Monta mensagem com ambos os links quando disponível
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
            if not proximo or encontrados_nesta_pag == 0:
                print(f"  FINEP: última página processada (start={start}).")
                break

            start += 10
            time.sleep(1)

        except Exception as e:
            print(f"  Erro FINEP (start={start}): {e}")
            break


def monitorar():
    try:
        vistos = pd.read_csv(DB_FILE)['link'].tolist() if os.path.exists(DB_FILE) else []
    except:
        vistos = []

    print(f"[{time.strftime('%H:%M:%S')}] Iniciando monitoramento...")
    novos = []

    # --- FINEP: tratamento especial ---
    monitorar_finep(vistos, novos)

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
                    novos.append([site["nome"], titulo, link])
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

    if novos:
        pd.DataFrame(novos, columns=['fonte', 'titulo', 'link']).to_csv(
            DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False
        )
        print(f"✅ {len(novos)} novos processados.")
    else:
        print("ℹ️ Nenhum item novo encontrado nesta execução.")


if __name__ == "__main__":
    monitorar()
