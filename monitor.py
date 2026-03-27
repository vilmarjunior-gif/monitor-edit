import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import google.generativeai as genai

# --- CONFIGURAÇÕES DE IA (GEMINI) ---
gemini_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=gemini_key)
# Usando o modelo 1.5-flash (rápido e gratuito via API)
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
    {
        "nome": "FINEP (Abertas)", 
        "url": "http://www.finep.gov.br/chamadas-publicas/chamadaspublicas?situacao=aberta", 
        "tag": "a", "filtro": "/chamadas-publicas/", "base_url": "http://www.finep.gov.br"
    },
    {
        "nome": "FAPEMAT (Abertos)", 
        "url": "https://www.fapemat.mt.gov.br/aberto", 
        "tag": "a", "filtro": "/editais/", "base_url": ""
    },
    {
        "nome": "CNPq (Chamadas)", 
        "url": "http://memoria2.cnpq.br/web/guest/chamadas-publicas", 
        "tag": "a", "filtro": "id=", "base_url": ""
    },
    {
        "nome": "CAPES (Editais)", 
        "url": "https://www.gov.br/capes/pt-br/assuntos/editais-e-resultados-capes", 
        "tag": "a", "filtro": "editais", "base_url": ""
    },
    {
        "nome": "Clima e Sociedade (iCS)", 
        "url": "https://climaesociedade.org/editais/", 
        "tag": "h3", 
        "filtro": "http", 
        "base_url": ""
    },
    {
        "nome": "EMBRAPII", 
        "url": "https://embrapii.org.br/transparencia/#chamadas", 
        "tag": "a", 
        "filtro": "chamadas-publicas", 
        "base_url": ""
    }
]

DB_FILE = "historico_editais.csv"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/110.0.0.0 Safari/537.36'}

# --- FUNÇÃO DE RESUMO COM IA ---
def gerar_resumo_ia(link):
    try:
        # Visita a página do edital para pegar o texto
        res = requests.get(link, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Extrai o texto e limpa espaços extras
        texto_pagina = ' '.join(soup.get_text().split())
        # Limita a 5000 caracteres para não estourar a API
        texto_curto = texto_pagina[:5000]

        prompt = (
            f"Você é um especialista em editais da Embrapa. Resuma o edital abaixo em no máximo 4 tópicos curtos: "
            f"1. OBJETIVO, 2. PÚBLICO-ALVO, 3. VALOR (se houver), 4. PRAZO FINAL. "
            f"Se não encontrar as informações, diga 'Informação não detalhada na página'. "
            f"Texto: {texto_curto}"
        )

        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Erro ao gerar resumo IA: {e}")
        return "⚠️ Não foi possível gerar o resumo automático para este link."

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Erro no Telegram: {e}")

def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    
    ANOS_ANTIGOS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"]
    if any(ano in texto_min for ano in ANOS_ANTIGOS):
        return False

    DESCARTAR = ["resultado", "finalizado", "encerrado", "preliminar", "homologação", "psicologia", "musica", "saúde bucal", "defesa", "mineral", "aeronáutica", "naval", "semicondutores", "saúde"] 
    if any(desc in texto_min for desc in DESCARTAR):
        return False
        
    return any(palavra.lower() in texto_min for palavra in PALAVRAS_INTERESSE)

def monitorar():
    if os.path.exists(DB_FILE):
        try:
            df_historico = pd.read_csv(DB_FILE)
            vistos = df_historico['link'].tolist()
        except Exception:
            vistos = []
    else:
        vistos = []

    print(f"[{time.strftime('%d/%m/%Y %H:%M:%S')}] Iniciando varredura...")
    novos_encontrados = []

    for site in MAPA_SITES:
        try:
            print(f"Verificando {site['nome']}...")
            res = requests.get(site["url"], headers=HEADERS, timeout=30)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for item in soup.find_all(site["tag"]):
                if item.name == 'h3':
                    link_tag = item.find('a')
                    link = link_tag.get('href', '') if link_tag else ''
                else:
                    link = item.get('href', '')
                
                titulo = item.get_text().strip()
                
                # Garante que o link seja completo
                if link.startswith('/'):
                    link = site["base_url"] + link
                elif not link.startswith('http'):
                    link = site["base_url"] + "/" + link if site["base_url"] else link
                
                if site["filtro"] in link and link not in vistos and len(titulo) > 20:
                    if verificar_palavras_chave(titulo):
                        print(f"Novo edital relevante: {titulo}")
                        
                        # CHAMADA DA IA PARA RESUMO
                        resumo_ia = gerar_resumo_ia(link)
                        
                        msg = (
                            f"🔔 *NOVO EDITAL ({site['nome']})*\n\n"
                            f"📄 *Título:* {titulo}\n\n"
                            f"🤖 *Resumo Inteligente:*\n{resumo_ia}\n\n"
                            f"🔗 [Clique aqui para Acessar]({link})"
                        )
                        
                        enviar_telegram(msg)
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                        
                        # Pequena pausa para não sobrecarregar as APIs
                        time.sleep(2) 
                    else:
                        # Ignorado por palavras-chave, mas marcado como visto
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)

        except Exception as e:
            print(f"Falha ao processar {site['nome']}: {e}")

    if novos_encontrados:
        df_novos = pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link'])
        df_novos.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)
        print(f"Sucesso: {len(novos_encontrados)} itens processados.")
    else:
        print("Fim da varredura. Nada novo.")

if __name__ == "__main__":
    monitorar()
