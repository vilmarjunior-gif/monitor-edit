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

# Desativa avisos de certificado (comum em sites governamentais)
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

# --- SUA LISTA COMPLETA DE PALAVRAS-CHAVE ---
PALAVRAS_INTERESSE = [
    "silvicultura", "proinfra", "fundo", "carbono", "sustentável", 
    "chamada", "agricultura", "bioinsumos", "pesquisa", "familiar",
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
    "biorremediação", "agricultura familiar", "sustentabilidade agrícola", "saúde do solo", 
    "economia circular", "agroecologia", "segurançaalimentar", "transição agroecológica", 
    "resiliência climática", "descarbonização", "plano de baixa emissão de carbono"
]

MAPA_SITES = [
    {
        "nome": "FINEP", 
        "url": "https://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta", 
        "tag": "tr", # Agora busca a linha inteira da tabela
        "filtro": "chamada", 
        "base_url": "https://www.finep.gov.br"
    },
    {"nome": "FAPEMAT", "url": "https://www.fapemat.mt.gov.br/aberto", "tag": "a", "filtro": "/editais/", "base_url": ""},
    {"nome": "CNPq", "url": "http://memoria2.cnpq.br/web/guest/chamadas-public-as", "tag": "a", "filtro": "id=", "base_url": ""},
    {"nome": "CAPES", "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes", "tag": "a", "filtro": "editais", "base_url": ""},
    {"nome": "Clima e Sociedade (iCS)", "url": "https://climaesociedade.org/editais/", "tag": "h3", "filtro": "http", "base_url": ""},
    {"nome": "EMBRAPII", "url": "https://embrapii.org.br/transparencia/#chamadas", "tag": "a", "filtro": "chamadas-publicas", "base_url": ""},
    {"nome": "Hub de Economia e Clima", "url": "https://hubdeeconomiaeclima.org.br/editais/", "tag": "a", "filtro": "/editais/", "base_url": "https://hubdeeconomiaeclima.org.br"}
]

DB_FILE = "historico_editais.csv"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

# ... (Funções enviar_email, gerar_resumo_ia, enviar_telegram permanecem as mesmas) ...
def enviar_email(titulo, resumo, link):
    if not EMAIL_USER or not EMAIL_PASS: return
    msg = MIMEMultipart(); msg['From'] = EMAIL_USER; msg['To'] = EMAIL_DESTINO; msg['Subject'] = f"📌 NOVO EDITAL: {titulo[:60]}..."
    corpo = f"<html><body><h2>Novo Edital</h2><p><b>Título:</b> {titulo}</p><hr><h3>🤖 Resumo:</h3><p>{resumo}</p><hr><p>🔗 <a href='{link}'>Link</a></p></body></html>"
    msg.attach(MIMEText(corpo, 'html'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(EMAIL_USER, EMAIL_PASS); s.send_message(msg)
    except Exception as e: print(f"Erro e-mail: {e}")

def gerar_resumo_ia(link):
    try:
        res = requests.get(link, headers=HEADERS, timeout=40, verify=False)
        texto = ""
        if 'pdf' in res.headers.get('Content-Type', '').lower() or link.lower().endswith('.pdf'):
            with fitz.open(stream=io.BytesIO(res.content), filetype="pdf") as doc:
                for page in doc[:6]: texto += page.get_text()
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            texto = ' '.join(soup.get_text().split())
        prompt = f"Analise de forma técnica para a Embrapa: {texto[:8000]}"
        return model.generate_content(prompt).text
    except: return "⚠️ Conteúdo ilegível."

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    DESCARTAR = ["resultado", "finalizado", "encerrado", "homologação"] 
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
            
            # Na FINEP, cada edital é um <tr> (linha da tabela)
            for item in soup.find_all(site["tag"]):
                link_tag = item.find('a') if item.name != 'a' else item
                if not link_tag: continue
                
                link = link_tag.get('href', '')
                # Pegamos o texto da linha inteira (item.get_text) para não perder o nome do edital
                titulo = item.get_text().replace('\n', ' ').strip()
                
                if link.startswith('/'): link = site["base_url"] + link
                elif not link.startswith('http') and site["base_url"]:
                    link = (site["base_url"] + "/" + link).replace("//", "/")
                
                # Se o link contém 'chamada' (singular ou plural) e não foi visto
                if site["filtro"] in link.lower() and link not in vistos and len(titulo) > 15:
                    if verificar_palavras_chave(titulo):
                        print(f"🎯 NOVO EDITAL: {titulo}")
                        resumo = gerar_resumo_ia(link)
                        enviar_telegram(f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🔗 [Acessar]({link})")
                        enviar_email(titulo, resumo, link)
                        
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                        time.sleep(5)
                    else:
                        # Se não interessa, salvamos para não ler novamente
                        vistos.append(link)
                        novos_encontrados.append([site["nome"], titulo, link])

        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos_encontrados:
        pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link']).to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)

if __name__ == "__main__":
    monitorar()
