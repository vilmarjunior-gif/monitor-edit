import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import google.generativeai as genai
import fitz  # Biblioteca PyMuPDF (Adicione PyMuPDF no requirements.txt)
import io

# --- CONFIGURAÇÕES DE IA (GEMINI) ---
gemini_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- CONFIGURAÇÕES DE ACESSO ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- PALAVRAS-CHAVE ---
PALAVRAS_INTERESSE = [
    "silvicultura", "proinfra", "fundo", "carbono", "sustentável", 
    "chamada", "agricultura", "bioinsumos", "pesquisa", "familiar",
    "regenerativa", "inovação", "clima", "edital", "mato grosso", "amazônia", "acesso", "sobre",
    "sustentabilidade", "ICTs", "universal"
]

MAPA_SITES = [
    {"nome": "FINEP (Abertas)", "url": "http://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta", "tag": "a", "filtro": "/chamadas-publicas/", "base_url": "http://www.finep.gov.br"},
    {"nome": "FAPEMAT (Abertos)", "url": "https://www.fapemat.mt.gov.br/aberto", "tag": "a", "filtro": "/editais/", "base_url": ""},
    {"nome": "CNPq (Chamadas)", "url": "http://memoria2.cnpq.br/web/guest/chamadas-publicas", "tag": "a", "filtro": "id=", "base_url": ""},
    {"nome": "CAPES (Editais)", "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes", "tag": "a", "filtro": "editais", "base_url": ""},
    {"nome": "Clima e Sociedade (iCS)", "url": "https://climaesociedade.org/editais/", "tag": "h3", "filtro": "http", "base_url": ""},
    {"nome": "EMBRAPII", "url": "https://embrapii.org.br/transparencia/#chamadas", "tag": "a", "filtro": "chamadas-publicas", "base_url": ""}
]

DB_FILE = "historico_editais.csv"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def gerar_resumo_ia(link):
    try:
        # 1. Faz o download com timeout maior para PDFs pesados
        res = requests.get(link, headers=HEADERS, timeout=40, verify=False)
        content_type = res.headers.get('Content-Type', '').lower()
        texto_para_ia = ""

        # 2. Se for PDF (pelo cabeçalho ou pela extensão)
        if 'pdf' in content_type or link.lower().endswith('.pdf'):
            with fitz.open(stream=io.BytesIO(res.content), filetype="pdf") as doc:
                # Pega as primeiras 6 páginas (geralmente onde estão os dados cruciais)
                for page in doc[:6]:
                    texto_para_ia += page.get_text()
        else:
            # 3. Se for página HTML
            soup = BeautifulSoup(res.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            texto_para_ia = ' '.join(soup.get_text().split())

        texto_final = texto_para_ia[:9000] # Limite seguro para a IA

        if len(texto_final) < 60:
            return "⚠️ O conteúdo do edital não pôde ser lido (página vazia ou protegida)."

        prompt = (
            f"Você é um analista sênior da Embrapa. Com base no texto abaixo, extraia:\n"
            f"1. OBJETIVO (O que é o edital?)\n"
            f"2. PÚBLICO-ALVO (Quem pode participar?)\n"
            f"3. CRONOGRAMA (Datas de inscrição e resultados)\n"
            f"4. VALORES (Valor total ou por projeto)\n\n"
            f"Texto: {texto_final}"
        )

        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Erro ao processar o conteúdo: {str(e)[:50]}"

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    requests.post(url, data=payload, timeout=10)

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
            res = requests.get(site["url"], headers=HEADERS, timeout=30)
            soup = BeautifulSoup(res.text, 'html.parser')
            for item in soup.find_all(site["tag"]):
                link_tag = item.find('a') if item.name == 'h3' else item
                link = link_tag.get('href', '') if link_tag else ''
                titulo = item.get_text().strip()
                
                if link.startswith('/'): link = site["base_url"] + link
                elif not link.startswith('http'): link = (site["base_url"] + "/" + link).replace("//", "/") if site["base_url"] else link
                
                if site["filtro"] in link and link not in vistos and len(titulo) > 20:
                    if verificar_palavras_chave(titulo):
                        resumo = gerar_resumo_ia(link)
                        msg = f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 *{titulo}*\n\n🤖 *Resumo:*\n{resumo}\n\n🔗 [Acessar Edital]({link})"
                        enviar_telegram(msg)
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                        time.sleep(3) # Pausa para evitar bloqueio
                    else:
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
        except Exception as e:
            print(f"Erro em {site['nome']}: {e}")

    if novos_encontrados:
        pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link']).to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)

if __name__ == "__main__":
    monitorar()
