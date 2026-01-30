import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

# --- CONFIGURAÇÕES DE ACESSO ---
TELEGRAM_TOKEN = os.getenv('8459605238:AAGtQn2-NGZDZOI3Pdb5w2dM07soLZM4wgA')
TELEGRAM_CHAT_ID = os.getenv('-1003869932591') 

# --- PALAVRAS-CHAVE ---
PALAVRAS_INTERESSE = [
    "silvicultura", "proinfra", "fundo", "carbono", "sustentável", 
    "chamada", "agricultura", "bioinsumos", "pesquisa", "familiar",
    "regenerativa", "inovação", "grant", "edital", "mato grosso", "amazônia", "acesso", "sobre"
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
        "nome": "FOOD TANK", 
        "url": "https://foodtank.com/news/category/regenerative-agriculture/", 
        "tag": "a", "filtro": "", "base_url": ""
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

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Erro no Telegram: {e}")

def verificar_palavras_chave(texto):
    texto_min = texto.lower()
    
    # 1. Lista de anos "proibidos" (adicionar o quanto eu quiser- nao esquecer)
    ANOS_ANTIGOS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024"]
    if any(ano in texto_min for ano in ANOS_ANTIGOS):
        return False

    # 2. Palavras de descarte (adicionar o quanto eu quiser - nao esquecer)
    DESCARTAR = ["resultado", "finalizado", "encerrado", "preliminar", "homologação", "psicologia", "musica", "saude bucal"] 
    if any(desc in texto_min for desc in DESCARTAR):
        return False
        
    # 3. Verifica se tem editais abertos com palavras de interesse
    return any(palavra.lower() in texto_min for palavra in PALAVRAS_INTERESSE)
def monitorar():
    # Carrega histórico ou cria um DataFrame vazio se não existir
    if os.path.exists(DB_FILE):
        try:
            df_historico = pd.read_csv(DB_FILE)
            vistos = df_historico['link'].tolist()
        except Exception:
            # Se o arquivo estiver corrompido, reseta a lista
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
                link = item.get('href', '')
                titulo = item.get_text().strip()
                
                # Garante que o link seja completo
                if link.startswith('/'):
                    link = site["base_url"] + link
                
                if site["filtro"] in link and link not in vistos and len(titulo) > 20:
                    if verificar_palavras_chave(titulo):
                        msg = f"🔔 *NOVO EDITAL ({site['nome']})*\n\n📄 {titulo}\n\n🔗 [Acessar]({link})"
                        enviar_telegram(msg)
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)
                    else:
                        # Adiciona aos vistos mesmo sem palavra-chave para não processar de novo
                        novos_encontrados.append([site["nome"], titulo, link])
                        vistos.append(link)

        except Exception as e:
            print(f"Falha ao processar {site['nome']}: {e}")

    # Salva os novos registros no CSV
    if novos_encontrados:
        df_novos = pd.DataFrame(novos_encontrados, columns=['fonte', 'titulo', 'link'])
        # 'a' (append) adiciona ao final do arquivo; 'header=False' evita repetir o cabeçalho
        df_novos.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)
        print(f"Sucesso: {len(novos_encontrados)} itens processados.")
    else:
        print("Fim da varredura. Nada novo.")

if __name__ == "__main__":
    monitorar()