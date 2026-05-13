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

# Desativa avisos de SSL para sites governamentais instáveis
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURAÇÕES DE IA (GEMINI) ---
gemini_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('models/gemini-1.5-flash')

# --- CONFIGURAÇÕES DE ACESSO ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASS = os.getenv('EMAIL_PASS')
EMAIL_DESTINO = os.getenv('EMAIL_USER')

# --- SUA LISTA COMPLETA DE PALAVRAS-CHAVE (MANTIDA INTEGRALMENTE) ---
PALAVRAS_INTERESSE = [
    "silvicultura", "proinfra", "fundo", "carbono", "sustentável",
    "chamada", "agriculture", "bioinsumos", "pesquisa", "familiar",
    "regenerativa", "inovação", "clima", "edital", "mato grosso", "amazônia", "acesso", "sobre",
    "sustentabilidade", "icts", "universal", "insumos biológicos", "agentes de biocontrole",
    "fungicidas microbiológicos", "bioestimulantes", "inoculantes", "indutores de resistência",
    "microbiota do solo", "solubilizadores de fosfato", "fixação biológica de nitrogênio",
    "metabólitos secundários", "ediçãogênica", "crispr-cas9", "bioeconomia",
    "promotores de crescimento", "doenças emergentes", "manejo sustentável",
    "sustentabilidade", "bioinsumos", "agentes biológicos", "controle biológico",
    "produtos biológicos", "biopesticidas", "biofertilizantes", "bioinseticidas",
    "biofungicidas", "bionematicidas", "antagonistas", "isolados microbianos",
    "prospecção de microrganismos", "microbiologia do solo", "manejo integrado de pragas",
    "biorremediação", "agriculture familiar", "sustentabilidade agrícola", "saúde do solo",
    "economia circular", "agroecologia", "segurançaalimentar", "transição agroecológica",
    "resiliência climática", "descarbonização", "plano de baixa emissão de carbono"
]

# --- MAPA DE SITES (SEM A FINEP — tratada separadamente com paginação) ---
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
        prompt = f"Analise este edital de forma técnica e direta para a Embrapa (Objetivo, Público, Datas, Valores): {texto[:8000]}"
        return model.generate_content(prompt).text
    except:
        return "⚠️ Não foi possível ler o conteúdo automaticamente."


def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass


def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    DESCARTAR = ["resultado", "finalizado", "encerrado", "homologação"]
    if any(desc in texto_min for desc in DESCARTAR):
        return False
    return any(p.lower() in texto_min for p in PALAVRAS_INTERESSE)


def monitorar_finep(vistos, novos_encontrados):
    """
    Percorre todas as páginas de chamadas abertas da FINEP com paginação.
    A FINEP lista os editais em tags <h3><a href='/chamadas-publicas/chamadapublica/ID'>Título</a></h3>
    A paginação usa o parâmetro &start=N (incrementos de 10).
    """
    base = "https://www.finep.gov.br"
    start = 0
    print("Verificando FINEP (com paginação)...")

    while True:
        url = f"{base}/chamadas-publicas/chamadaspublicas?situacao=aberta&start={start}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=30, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')

            # Os editais ficam dentro de <h3><a href="...">Título</a></h3>
            itens = soup.find_all('h3')
            if not itens:
                print(f"  FINEP: nenhum <h3> encontrado na página start={start}, encerrando.")
                break

            encontrou_chamada = False
            for item in itens:
                link_tag = item.find('a')
                if not link_tag:
                    continue

                link = link_tag.get('href', '').strip()
                titulo = link_tag.get_text().strip()

                if not link or not titulo:
                    continue

                # Normaliza para URL absoluta
                if link.startswith('/'):
                    link = base + link
                elif not link.startswith('http'):
                    link = base + '/' + link

                # Só processa links de chamada pública e não duplicados
                if 'chamadapublica' not in link.lower():
                    continue

                encontrou_chamada = True

                if link in vistos:
                    continue

                vistos.append(link)
                novos_encontrados.append(["FINEP", titulo, link])

                if verificar_palavras_chave(titulo):
                    print(f"  🎯 FINEP RELEVANTE: {titulo}")
                    resumo = gerar_resumo_ia(link)
                    msg = (
                        f"🔔 *NOVO EDITAL (FINEP)*\n\n"
                        f"📄 *{titulo}*\n\n"
                        f"🔗 [Acessar Edital]({link})"
                    )
                    enviar_telegram(msg)
                    enviar_email(titulo, resumo, link)
                    time.sleep(2)

            # Verifica se há próxima página pelo link "Próx"
            proximo = soup.find('a', string=lambda t: t and 'Próx' in t)
            if not proximo or not encontrou_chamada:
                print(f"  FINEP: última página processada (start={start}).")
                break

            start += 10
            time.sleep(1)  # Respeita o servidor entre páginas

        except Exception as e:
            print(f"  Erro FINEP (start={start}): {e}")
            break


def monitorar():
    vistos = pd.read_csv(DB_FILE)['link'].tolist() if os.path.exists(DB_FILE) else []
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando monitoramento global...")
    novos_encontrados = []

    # --- FINEP: tratamento especial com paginação ---
    monitorar_finep(vistos, novos_encontrados)

    # --- Demais sites ---
    for site in MAPA_SITES:
        try:
            print(f"Verificando {site['nome']}...")
            res = requests.get(site["url"], headers=HEADERS, timeout=30, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')

            for item in soup.find_all(site["tag"]):
                link_tag = item.find('a') if item.name != 'a' else item
                if not link_tag:
                    continue

                link = link_tag.get('href', '')
                if not link:
                    continue

                titulo = link_tag.get_text().strip()

                # Normaliza links
                if link.startswith('/'):
                    link = site["base_url"] + link
                elif not link.startswith('http') and site["base_url"]:
                    link = (site["base_url"] + "/" + link).replace("//", "/")

                # Filtro de link e duplicidade
                if site["filtro"] in link.lower() and link not in vistos and len(titulo) > 15:
                    if verificar_palavras_chave(titulo):
                        print(f"🎯 RELEVANTE ENCONTRADO: {titulo}")
                        resumo = gerar_resumo_ia(link)

                        msg_telegram = f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🔗 [Acessar Edital]({link})"
                        enviar_telegram(msg_telegram)
                        enviar_email(titulo, resumo, link)

                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                        time.sleep(2)
                    else:
                        # Salva no histórico para não analisar novamente
                        vistos.append(link)
                        novos_encontrados.append([site["nome"], titulo, link])

        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos_encontrados:
        df_novos = pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link'])
        df_novos.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)
        print(f"✅ {len(novos_encontrados)} novos itens processados.")
    else:
        print("ℹ️ Nenhum item novo encontrado nesta execução.")


if __name__ == "__main__":
    monitorar()
