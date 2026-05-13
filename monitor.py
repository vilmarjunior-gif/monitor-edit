import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import google.generativeai as genai
import fitz  # Biblioteca PyMuPDF
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
    "sustentabilidade", "bioinsumos", "agentes biológicos", "controle biológico", 
    "produtos biológicos", "biopesticidas", "biofertilizantes", "bioinseticidas", 
    "biofungicidas", "bionematicidas", "antagonistas", "isolados microbianos", 
    "prospecção de microrganismos", "microbiologia do solo", "manejo integrado de pragas",
    "biorremediação", "agricultura familiar", "sustentabilidade agrícola", "saúde do solo", 
    "economia circular", "agroecologia", "segurançaalimentar", "transição agroecológica", 
    "resiliência climática", "descarbonização", "plano de baixa emissão de carbono"
]

MAPA_SITES = [
    {
        "nome": "FINEP (Chamadas)", 
        "url": "https://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta", 
        "tag": "tr", # Mudado para TR para ler a linha da tabela
        "filtro": "chamada", # Filtro mais amplo (pega singular e plural)
        "base_url": "https://www.finep.gov.br"
    },
    {"nome": "FAPEMAT (Abertos)", "url": "https://www.fapemat.mt.gov.br/aberto", "tag": "a", "filtro": "/editais/", "base_url": ""},
    {"nome": "CNPq (Chamadas)", "url": "http://memoria2.cnpq.br/web/guest/chamadas-public-as", "tag": "a", "filtro": "id=", "base_url": ""},
    {"nome": "CAPES (Editais)", "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes", "tag": "a", "filtro": "editais", "base_url": ""},
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

    corpo_html = f"""
    <html>
    <body>
        <h2>Novo Edital Encontrado</h2>
        <p><b>Título:</b> {titulo}</p>
        <hr>
        <h3>🤖 Resumo da Inteligência Artificial:</h3>
        <p style="white-space: pre-wrap; background-color: #f9f9f9; padding: 10px; border-left: 5px solid #2ecc71;">{resumo}</p>
        <hr>
        <p>🔗 <a href="{link}">Clique aqui para acessar o edital completo</a></p>
        <br>
        <small>Monitor de Editais Automático</small>
    </body>
    </html>
    """
    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def gerar_resumo_ia(link):
    try:
        res = requests.get(link, headers=HEADERS, timeout=40, verify=False)
        content_type = res.headers.get('Content-Type', '').lower()
        texto_para_ia = ""

        if 'pdf' in content_type or link.lower().endswith('.pdf'):
            with fitz.open(stream=io.BytesIO(res.content), filetype="pdf") as doc:
                for page in doc[:6]:
                    texto_para_ia += page.get_text()
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            texto_para_ia = ' '.join(soup.get_text().split())

        texto_final = texto_para_ia[:9000]

        if len(texto_final) < 60:
            return "⚠️ O conteúdo do edital não pôde ser lido (página vazia ou protegida)."

        prompt = (
            f"Analise o conteúdo deste edital e extraia as informações de forma técnica e direta: "
            f"1. OBJETIVO (O que é o edital?)\n"
            f"2. PÚBLICO-ALVO (Quem pode participar?)\n"
            f"3. CRONOGRAMA (Datas de inscrição e prazos)\n"
            f"4. VALORES (Valor total ou por projeto)\n\n"
            f"Ao final, adicione uma seção chamada 'CONSIDERAÇÕES' com uma análise breve "
            f"sobre a relevância do tema para a Embrapa.\n"
            f"Seja conciso e use tópicos. Texto: {texto_final}"
        )
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Erro ao processar o conteúdo: {str(e)[:50]}"

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except:
        pass

def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    ANOS_ANTIGOS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"]
    if any(ano in texto_min for ano in ANOS_ANTIGOS): return False
    DESCARTAR = ["resultado", "finalizado", "encerrado", "homologação", "psicologia", "musica", "saúde"] 
    if any(desc in texto_min for desc in DESCARTAR): return False
    return any(palavra.lower() in texto_min for palavra in PALAVRAS_INTERESSE)

def monitorar():
    vistos = pd.read_csv(DB_FILE)['link'].tolist() if os.path.exists(DB_FILE) else []
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando...")
    novos_encontrados = []

    for site in MAPA_SITES:
        try:
            print(f"Verificando {site['nome']}...")
            res = requests.get(site["url"], headers=HEADERS, timeout=30, verify=False)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for item in soup.find_all(site["tag"]):
                # Busca link dentro do item (TR ou Div)
                link_tag = item.find('a') if item.name != 'a' else item
                if not link_tag: continue
                
                link = link_tag.get('href', '')
                
                # Se for FINEP, pegamos o texto da linha inteira para garantir o título
                if "finep.gov.br" in site["url"]:
                    titulo = item.get_text().replace('\n', ' ').strip()
                else:
                    titulo = item.get_text().strip()
                
                if not titulo: titulo = link_tag.get_text().strip()
                
                # Normalização do Link
                if link.startswith('/'): 
                    link = site["base_url"] + link
                elif not link.startswith('http') and site["base_url"]:
                    link = (site["base_url"] + "/" + link).replace("//", "/")
                
                if site["filtro"] in link and link not in vistos and len(titulo) > 15:
                    if verificar_palavras_chave(titulo):
                        print(f"Novo edital relevante encontrado: {titulo}")
                        resumo = gerar_resumo_ia(link)
                        
                        # ENVIO TELEGRAM
                        msg = f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🤖 *Resumo:*\n{resumo}\n\n🔗 [Acessar Edital]({link})"
                        enviar_telegram(msg)
                        
                        # ENVIO E-MAIL
                        enviar_email(titulo, resumo, link)
                        
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                        time.sleep(5) 
                    else:
                        # Adiciona ao histórico mesmo se não for relevante para não ler de novo
                        vistos.append(link)
                        novos_encontrados.append([site["nome"], titulo, link])

        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos_encontrados:
        df_novos = pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link'])
        df_novos.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)

if __name__ == "__main__":
    monitorar()
