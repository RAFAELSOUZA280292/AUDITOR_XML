import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import tempfile, os, io

# ---------- Helpers ----------
def detectar_encoding(path):
    try:
        import chardet
    except ImportError:
        return 'latin-1'
    try:
        with open(path, 'rb') as f:
            raw = f.read(10000)
        enc = chardet.detect(raw).get('encoding') or 'latin-1'
        return enc
    except Exception:
        return 'latin-1'

def extrair_competencia_do_0000(path, enc):
    try:
        with open(path, 'r', encoding=enc, errors='ignore') as f:
            for _ in range(20):
                line = f.readline()
                if not line: break
                if line.startswith('|0000|'):
                    fields = line.strip().split('|')
                    if len(fields) > 4 and len(fields[4]) == 8:
                        dt_ini = fields[4]; return f"{dt_ini[2:4]}/{dt_ini[4:8]}"
        return "Competência Não Encontrada"
    except Exception as e:
        return f"Erro ao extrair competência: {e}"

# ---------- XML NF-e ----------
def parse_xml_nfe(xml_path):
    data = {}
    try:
        tree = ET.parse(xml_path); root = tree.getroot()
        ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
        inf = root.find('.//nfe:infNFe', ns)
        if inf is not None:
            nfe_id = inf.get('Id')
            data['Chave'] = (nfe_id[3:] if (nfe_id and nfe_id.startswith('NFe')) else nfe_id)
        tot = root.find('.//nfe:ICMSTot', ns)
        if tot is not None:
            v = lambda tag: tot.find(f"nfe:{tag}", ns)
            data['Valor ICMS XML'] = float((v('vICMS').text if v('vICMS') is not None and v('vICMS').text else 0) or 0)
            data['Valor IPI XML']  = float((v('vIPI').text  if v('vIPI')  is not None and v('vIPI').text  else 0) or 0)
            data['Valor Produtos XML'] = float((v('vProd').text if v('vProd') is not None and v('vProd').text else 0) or 0)
        emit = root.find('.//nfe:emit', ns)
        if emit is not None:
            data['Emitente XML'] = (emit.find('nfe:xNome', ns).text if emit.find('nfe:xNome', ns) is not None else 'N/A')
            data['CNPJ Emitente XML'] = (emit.find('nfe:CNPJ', ns).text if emit.find('nfe:CNPJ', ns) is not None else 'N/A')
        dest = root.find('.//nfe:dest', ns)
        if dest is not None:
            data['Destinatário XML'] = (dest.find('nfe:xNome', ns).text if dest.find('nfe:xNome', ns) is not None else 'N/A')
            data['CNPJ Destinatário XML'] = (dest.find('nfe:CNPJ', ns).text if dest.find('nfe:CNPJ', ns) is not None else 'N/A')
        return data if data else None
    except Exception:
        return None

# ---------- XML CT-e ----------
def parse_xml_cte(xml_path):
    d = {}
    try:
        tree = ET.parse(xml_path); root = tree.getroot()
        ns = {'cte': 'http://www.portalfiscal.inf.br/cte'}
        inf = root.find('.//cte:infCte', ns)
        if inf is not None:
            cte_id = inf.get('Id'); d['Chave'] = (cte_id[3:] if (cte_id and cte_id.startswith('CTe')) else cte_id)
        vPrest = root.find('.//cte:vPrest', ns)
        if vPrest is not None:
            t = vPrest.find('cte:vTPrest', ns); d['Valor Total Prestação XML'] = float(t.text) if t is not None and t.text else 0.0
        icms_outra = root.find('.//cte:ICMS/cte:ICMSOutraUF', ns)
        if icms_outra is not None:
            v = lambda tag: icms_outra.find(f'cte:{tag}', ns)
            d['BC ICMS XML'] = float(v('vBCOutraUF').text) if v('vBCOutraUF') is not None and v('vBCOutraUF').text else 0.0
            d['Valor ICMS XML'] = float(v('vICMSOutraUF').text) if v('vICMSOutraUF') is not None and v('vICMSOutraUF').text else 0.0
            d['Alíquota ICMS XML'] = float(v('pICMSOutraUF').text) if v('pICMSOutraUF') is not None and v('pICMSOutraUF').text else 0.0
            cst = icms_outra.find('cte:CST', ns); d['CST XML'] = cst.text if cst is not None else 'N/A'
        else:
            for kind in ['ICMS00','ICMS90','ICMS20','ICMS40','ICMS51','ICMS60','ICMS70','ICMSPart','ICMSST','ICMSCons','ICMSUFDest']:
                node = root.find(f'.//cte:ICMS/cte:{kind}', ns)
                if node is not None:
                    v = lambda tag: node.find(f'cte:{tag}', ns)
                    d['BC ICMS XML'] = float(v('vBC').text) if v('vBC') is not None and v('vBC').text else 0.0
                    d['Valor ICMS XML'] = float(v('vICMS').text) if v('vICMS') is not None and v('vICMS').text else 0.0
                    d['Alíquota ICMS XML'] = float(v('pICMS').text) if v('pICMS') is not None and v('pICMS').text else 0.0
                    cst = node.find('cte:CST', ns); d['CST XML'] = cst.text if cst is not None else 'N/A'
                    break
        # Tomador (toma3 simples)
        toma = root.find('.//cte:toma3/cte:toma', ns)
        toma_v = toma.text if toma is not None else ''
        tipo = "Não Identificado"; nome = "N/A"
        if toma_v == '0':
            rem = root.find('.//cte:rem', ns); x = rem.find('cte:xNome', ns) if rem is not None else None; nome = x.text if x is not None else 'N/A'; tipo="Remetente"
        elif toma_v == '1':
            ex = root.find('.//cte:exped', ns); x = ex.find('cte:xNome', ns) if ex is not None else None; nome = x.text if x is not None else 'N/A'; tipo="Expedidor"
        elif toma_v == '2':
            rc = root.find('.//cte:receb', ns); x = rc.find('cte:xNome', ns) if rc is not None else None; nome = x.text if x is not None else 'N/A'; tipo="Recebedor"
        elif toma_v == '3':
            de = root.find('.//cte:dest', ns); x = de.find('cte:xNome', ns) if de is not None else None; nome = x.text if x is not None else 'N/A'; tipo="Destinatário"
        d['Tipo Tomador XML'] = tipo; d['Nome Tomador XML'] = nome
        # Emit/Dest
        emit = root.find('.//cte:emit', ns)
        if emit is not None:
            xn = emit.find('cte:xNome', ns); c = emit.find('cte:CNPJ', ns)
            d['Emitente XML'] = xn.text if xn is not None else 'N/A'; d['CNPJ Emitente XML'] = c.text if c is not None else 'N/A'
        dest = root.find('.//cte:dest', ns)
        if dest is not None:
            xn = dest.find('cte:xNome', ns); c = dest.find('cte:CNPJ', ns)
            d['Destinatário XML'] = xn.text if xn is not None else 'N/A'; d['CNPJ Destinatário XML'] = c.text if c is not None else 'N/A'
        return d if d else None
    except Exception:
        return None

# ---------- Processadores (mesma regra do seu script) ----------
def processar_sped_nfe(sped_path, xml_map):
    recs, warns = [], []
    enc = detectar_encoding(sped_path)
    comp = extrair_competencia_do_0000(sped_path, enc)
    if comp == "Competência Não Encontrada": warns.append(f"Aviso: Competência não encontrada em {os.path.basename(sped_path)}."); comp = "Desconhecida"
    current, cfops = None, set()
    try:
        with open(sped_path,'r',encoding=enc,errors='ignore') as f:
            for line_num, line in enumerate(f,1):
                fields = line.strip().split('|')
                if len(fields)<2: continue
                t = fields[1]
                if t=="C100":
                    if current is not None:
                        current['CFOP']=", ".join(sorted(cfops)) if cfops else ""
                        icms = float(current.get("Valor ICMS SPED","0").replace(",",".")) if current.get("Valor ICMS SPED") else 0.0
                        ipi  = float(current.get("Valor IPI SPED","0").replace(",","."))  if current.get("Valor IPI SPED")  else 0.0
                        has_entry = any(c.startswith(("1","2","3")) for c in cfops)
                        if (icms>0 or ipi>0) and has_entry:
                            chave = current.get("Chave")
                            if chave and chave in xml_map:
                                x = xml_map[chave]
                                current.update({
                                    "Valor ICMS XML": x.get("Valor ICMS XML",0.0),
                                    "Valor IPI XML": x.get("Valor IPI XML",0.0),
                                    "Valor Produtos XML": x.get("Valor Produtos XML",0.0),
                                    "Emitente XML": x.get("Emitente XML","N/A"),
                                    "CNPJ Emitente XML": x.get("CNPJ Emitente XML","N/A"),
                                    "Destinatário XML": x.get("Destinatário XML","N/A"),
                                    "CNPJ Destinatário XML": x.get("CNPJ Destinatário XML","N/A"),
                                    "XML Encontrado":"Sim"
                                })
                                diff_icms = icms - current["Valor ICMS XML"]
                                diff_ipi  = ipi  - current["Valor IPI XML"]
                                current["Diferença ICMS (SPED - XML)"]=diff_icms
                                current["Diferença IPI (SPED - XML)"]=diff_ipi
                                icms_div=abs(diff_icms)>=0.01; ipi_div=abs(diff_ipi)>=0.01
                                current["Status Auditoria"]="OK" if not icms_div and not ipi_div else \
                                    "Divergência: " + ", ".join(
                                        (["Crédito a Maior"] if diff_icms>0 and icms_div else []) +
                                        (["Crédito a Menor"] if diff_icms<0 and icms_div else []) +
                                        (["Divergência IPI (a Maior)"] if diff_ipi>0 and ipi_div else []) +
                                        (["Divergência IPI (a Menor)"] if diff_ipi<0 and ipi_div else [])
                                    ) or "Divergência Geral"
                            else:
                                current.update({
                                    "Valor ICMS XML":0.0,"Valor IPI XML":0.0,"Valor Produtos XML":0.0,
                                    "Emitente XML":"N/A","CNPJ Emitente XML":"N/A","Destinatário XML":"N/A","CNPJ Destinatário XML":"N/A",
                                    "XML Encontrado":"Não","Diferença ICMS (SPED - XML)":icms,"Diferença IPI (SPED - XML)":ipi,"Status Auditoria":"XML Não Encontrado"
                                })
                            recs.append(current)
                    try:
                        current={
                            "Competência": comp,
                            "Série da nota": fields[7].strip(),
                            "Número da nota": fields[8].strip(),
                            "Chave": fields[9].strip(),
                            "Data de emissão": fields[10].strip(),
                            "Valor Total SPED": fields[12].replace(",",".").strip(),
                            "BC ICMS SPED": fields[21].replace(",",".").strip(),
                            "Valor ICMS SPED": fields[22].replace(",",".").strip(),
                            "Valor IPI SPED": fields[25].replace(",",".").strip()
                        }
                    except IndexError:
                        warns.append(f"Aviso: C100 malformado em {os.path.basename(sped_path)} linha {line_num}.")
                        current=None
                    cfops=set()
                elif t=="C170" and current is not None and len(fields)>11:
                    cf = fields[11].strip()
                    if cf: cfops.add(cf)
        if current is not None:
            # repete fechamento (igual acima)
            current['CFOP']=", ".join(sorted(cfops)) if cfops else ""
            icms=float(current.get("Valor ICMS SPED","0").replace(",",".")) if current.get("Valor ICMS SPED") else 0.0
            ipi=float(current.get("Valor IPI SPED","0").replace(",",".")) if current.get("Valor IPI SPED") else 0.0
            has_entry = any(c.startswith(("1","2","3")) for c in cfops)
            if (icms>0 or ipi>0) and has_entry:
                chave=current.get("Chave")
                # … (mesma lógica do bloco anterior)
                if chave and chave in xml_map:
                    x=xml_map[chave]
                    current.update({
                        "Valor ICMS XML": x.get("Valor ICMS XML",0.0),
                        "Valor IPI XML": x.get("Valor IPI XML",0.0),
                        "Valor Produtos XML": x.get("Valor Produtos XML",0.0),
                        "Emitente XML": x.get("Emitente XML","N/A"),
                        "CNPJ Emitente XML": x.get("CNPJ Emitente XML","N/A"),
                        "Destinatário XML": x.get("Destinatário XML","N/A"),
                        "CNPJ Destinatário XML": x.get("CNPJ Destinatário XML","N/A"),
                        "XML Encontrado":"Sim"
                    })
                    diff_icms=icms-current["Valor ICMS XML"]; diff_ipi=ipi-current["Valor IPI XML"]
                    current["Diferença ICMS (SPED - XML)"]=diff_icms; current["Diferença IPI (SPED - XML)"]=diff_ipi
                    icms_div=abs(diff_icms)>=0.01; ipi_div=abs(diff_ipi)>=0.01
                    current["Status Auditoria"]="OK" if not icms_div and not ipi_div else "Divergência: " + ", ".join(
                        (["Crédito a Maior"] if diff_icms>0 and icms_div else [])+
                        (["Crédito a Menor"] if diff_icms<0 and icms_div else [])+
                        (["Divergência IPI (a Maior)"] if diff_ipi>0 and ipi_div else [])+
                        (["Divergência IPI (a Menor)"] if diff_ipi<0 and ipi_div else [])
                    ) or "Divergência Geral"
                else:
                    current.update({
                        "Valor ICMS XML":0.0,"Valor IPI XML":0.0,"Valor Produtos XML":0.0,
                        "Emitente XML":"N/A","CNPJ Emitente XML":"N/A","Destinatário XML":"N/A","CNPJ Destinatário XML":"N/A",
                        "XML Encontrado":"Não","Diferença ICMS (SPED - XML)":icms,"Diferença IPI (SPED - XML)":ipi,"Status Auditoria":"XML Não Encontrado"
                    })
                recs.append(current)
    except Exception as e:
        warns.append(f"Erro inesperado em {os.path.basename(sped_path)}: {e}")
    return recs, warns

def processar_sped_cte(sped_path, xml_map):
    recs, warns = [], []
    enc = detectar_encoding(sped_path)
    comp = extrair_competencia_do_0000(sped_path, enc)
    if comp == "Competência Não Encontrada": warns.append(f"Aviso: Competência não encontrada em {os.path.basename(sped_path)}."); comp="Desconhecida"
    current, cfops, aliquotas = None, set(), set()
    try:
        with open(sped_path,'r',encoding=enc,errors='ignore') as f:
            for line_num, line in enumerate(f,1):
                fields = line.strip().split('|')
                if len(fields)<2: continue
                t=fields[1]
                if t=="D100":
                    if current is not None:
                        current['CFOPs SPED']=", ".join(sorted(cfops)) if cfops else ""
                        current['Alíquotas ICMS SPED']=", ".join(sorted(aliquotas)) if aliquotas else ""
                        bc=float(current.get("BC ICMS SPED","0").replace(",",".")) if current.get("BC ICMS SPED") else 0.0
                        icms=float(current.get("Valor ICMS SPED","0").replace(",",".")) if current.get("Valor ICMS SPED") else 0.0
                        if icms>0:
                            chave=current.get("Chave CT-e")
                            if chave and chave in xml_map:
                                x=xml_map[chave]
                                current.update({
                                    "Valor Total Prestação XML":x.get("Valor Total Prestação XML",0.0),
                                    "BC ICMS XML":x.get("BC ICMS XML",0.0),
                                    "Valor ICMS XML":x.get("Valor ICMS XML",0.0),
                                    "Alíquota ICMS XML":x.get("Alíquota ICMS XML",0.0),
                                    "CST XML":x.get("CST XML","N/A"),
                                    "Tipo Tomador XML":x.get("Tipo Tomador XML","Não Identificado"),
                                    "Nome Tomador XML":x.get("Nome Tomador XML","N/A"),
                                    "Emitente XML":x.get("Emitente XML","N/A"),
                                    "CNPJ Emitente XML":x.get("CNPJ Emitente XML","N/A"),
                                    "Destinatário XML":x.get("Destinatário XML","N/A"),
                                    "CNPJ Destinatário XML":x.get("CNPJ Destinatário XML","N/A"),
                                    "XML Encontrado":"Sim"
                                })
                                diff_bc=bc-current["BC ICMS XML"]; diff_icms=icms-current["Valor ICMS XML"]
                                current["Diferença BC ICMS (SPED - XML)"]=diff_bc; current["Diferença ICMS (SPED - XML)"]=diff_icms
                                icms_div=abs(diff_icms)>=0.01; bc_div=abs(diff_bc)>=0.01
                                current["Status Auditoria"]="OK" if not icms_div and not bc_div else "Divergência: " + ", ".join(
                                    (["Crédito a Maior"] if diff_icms>0 and icms_div else [])+
                                    (["Crédito a Menor"] if diff_icms<0 and icms_div else [])+
                                    (["Divergência BC ICMS (a Maior)"] if diff_bc>0 and bc_div else [])+
                                    (["Divergência BC ICMS (a Menor)"] if diff_bc<0 and bc_div else [])
                                ) or "Divergência Geral"
                            else:
                                current.update({
                                    "Valor Total Prestação XML":0.0,"BC ICMS XML":0.0,"Valor ICMS XML":0.0,"Alíquota ICMS XML":0.0,"CST XML":"N/A",
                                    "Tipo Tomador XML":"Não Identificado","Nome Tomador XML":"N/A","Emitente XML":"N/A","CNPJ Emitente XML":"N/A",
                                    "Destinatário XML":"N/A","CNPJ Destinatário XML":"N/A","XML Encontrado":"Não",
                                    "Diferença BC ICMS (SPED - XML)":bc,"Diferença ICMS (SPED - XML)":icms,"Status Auditoria":"XML Não Encontrado"
                                })
                            recs.append(current)
                    try:
                        current={
                            "Competência":comp,
                            "Série CT-e":fields[7].strip(),
                            "Número CT-e":fields[9].strip(),
                            "Chave CT-e":fields[10].strip(),
                            "Data de Emissão SPED":fields[11].strip(),
                            "Valor Total Prestação SPED":fields[13].replace(",",".").strip(),
                            "BC ICMS SPED":fields[19].replace(",",".").strip(),
                            "Valor ICMS SPED":fields[20].replace(",",".").strip()
                        }
                    except IndexError:
                        warns.append(f"Aviso: D100 malformado em {os.path.basename(sped_path)} linha {line_num}.")
                        current=None
                    cfops, aliquotas = set(), set()
                elif t=="D190" and current is not None and len(fields)>4:
                    if fields[3].strip(): cfops.add(fields[3].strip())
                    if fields[4].strip(): aliquotas.add(fields[4].strip())
        if current is not None:
            # fechar último
            current['CFOPs SPED']=", ".join(sorted(cfops)) if cfops else ""
            current['Alíquotas ICMS SPED']=", ".join(sorted(aliquotas)) if aliquotas else ""
            bc=float(current.get("BC ICMS SPED","0").replace(",",".")) if current.get("BC ICMS SPED") else 0.0
            icms=float(current.get("Valor ICMS SPED","0").replace(",",".")) if current.get("Valor ICMS SPED") else 0.0
            if icms>0:
                chave=current.get("Chave CT-e")
                if chave and chave in xml_map:
                    x=xml_map[chave]
                    current.update({
                        "Valor Total Prestação XML":x.get("Valor Total Prestação XML",0.0),
                        "BC ICMS XML":x.get("BC ICMS XML",0.0),
                        "Valor ICMS XML":x.get("Valor ICMS XML",0.0),
                        "Alíquota ICMS XML":x.get("Alíquota ICMS XML",0.0),
                        "CST XML":x.get("CST XML","N/A"),
                        "Tipo Tomador XML":x.get("Tipo Tomador XML","Não Identificado"),
                        "Nome Tomador XML":x.get("Nome Tomador XML","N/A"),
                        "Emitente XML":x.get("Emitente XML","N/A"),
                        "CNPJ Emitente XML":x.get("CNPJ Emitente XML","N/A"),
                        "Destinatário XML":x.get("Destinatário XML","N/A"),
                        "CNPJ Destinatário XML":x.get("CNPJ Destinatário XML","N/A"),
                        "XML Encontrado":"Sim"
                    })
                    diff_bc=bc-current["BC ICMS XML"]; diff_icms=icms-current["Valor ICMS XML"]
                    current["Diferença BC ICMS (SPED - XML)"]=diff_bc; current["Diferença ICMS (SPED - XML)"]=diff_icms
                    icms_div=abs(diff_icms)>=0.01; bc_div=abs(diff_bc)>=0.01
                    current["Status Auditoria"]="OK" if not icms_div and not bc_div else "Divergência: " + ", ".join(
                        (["Crédito a Maior"] if diff_icms>0 and icms_div else [])+
                        (["Crédito a Menor"] if diff_icms<0 and icms_div else [])+
                        (["Divergência BC ICMS (a Maior)"] if diff_bc>0 and bc_div else [])+
                        (["Divergência BC ICMS (a Menor)"] if diff_bc<0 and bc_div else [])
                    ) or "Divergência Geral"
                else:
                    current.update({
                        "Valor Total Prestação XML":0.0,"BC ICMS XML":0.0,"Valor ICMS XML":0.0,"Alíquota ICMS XML":0.0,"CST XML":"N/A",
                        "Tipo Tomador XML":"Não Identificado","Nome Tomador XML":"N/A","Emitente XML":"N/A","CNPJ Emitente XML":"N/A",
                        "Destinatário XML":"N/A","CNPJ Destinatário XML":"N/A","XML Encontrado":"Não",
                        "Diferença BC ICMS (SPED - XML)":bc,"Diferença ICMS (SPED - XML)":icms,"Status Auditoria":"XML Não Encontrado"
                    })
                recs.append(current)
    except Exception as e:
        warns.append(f"Erro inesperado em {os.path.basename(sped_path)}: {e}")
    return recs, warns

# ---------- Excel helpers ----------
def montar_excel(df, avisos, nome_aba):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=nome_aba)
        if avisos:
            pd.DataFrame({"Avisos": avisos}).to_excel(w, index=False, sheet_name="Avisos")
    buf.seek(0); return buf

# ---------- UI ----------
st.set_page_config(page_title="Auditor SPED (Web)", layout="wide")
st.title("Auditor SPED – NF-e e CT-e (Web)")

tab1, tab2 = st.tabs(["NF-e (C100/C170)", "CT-e (D100/D190)"])

with tab1:
    st.subheader("NF-e com cruzamento dos XMLs")
    sped_files = st.file_uploader("SPED(s) .txt", type=["txt"], accept_multiple_files=True)
    xml_files  = st.file_uploader("XML(s) .xml ou .txt", type=["xml","txt"], accept_multiple_files=True)
    if st.button("Processar NF-e"):
        if not sped_files: st.warning("Envie ao menos um SPED."); st.stop()
        # salvar uploads
        tmp_speds, tmp_xmls = [], []
        for f in sped_files:
            t = tempfile.NamedTemporaryFile(delete=False, suffix=".txt"); t.write(f.read()); t.close(); tmp_speds.append(t.name)
        for f in xml_files:
            suf = ".xml" if f.name.lower().endswith(".xml") else ".txt"
            t = tempfile.NamedTemporaryFile(delete=False, suffix=suf); t.write(f.read()); t.close(); tmp_xmls.append(t.name)
        # mapa de XML
        xml_map, xml_warns = {}, []
        for p in tmp_xmls:
            d = parse_xml_nfe(p)
            if d and 'Chave' in d: xml_map[d['Chave']] = d
            else: xml_warns.append(f"XML NF-e inválido ou sem chave: {os.path.basename(p)}")
        # processa
        all_rows, all_warns = [], []
        for p in tmp_speds:
            r, w = processar_sped_nfe(p, xml_map); all_rows += r; all_warns += w
        if not all_rows:
            st.info("Nenhuma nota com ICMS/IPI > 0 e CFOP de entrada, pelos critérios."); st.stop()
        cols = ["Competência","Série da nota","Número da nota","Chave","Data de emissão","Valor Total SPED","BC ICMS SPED","Valor ICMS SPED","Valor IPI SPED","CFOP","XML Encontrado","Emitente XML","CNPJ Emitente XML","Destinatário XML","CNPJ Destinatário XML","Valor Produtos XML","Valor ICMS XML","Valor IPI XML","Diferença ICMS (SPED - XML)","Diferença IPI (SPED - XML)","Status Auditoria"]
        df = pd.DataFrame(all_rows)
        for c in cols:
            if c not in df.columns: df[c]=None
        df=df[cols]
        for c in ["Valor Total SPED","BC ICMS SPED","Valor ICMS SPED","Valor IPI SPED","Valor Produtos XML","Valor ICMS XML","Valor IPI XML","Diferença ICMS (SPED - XML)","Diferença IPI (SPED - XML)"]:
            df[c]=pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        st.dataframe(df, use_container_width=True)
        xls = montar_excel(df, xml_warns+all_warns, "NF-e")
        st.download_button("⬇️ Baixar Excel (NF-e)", data=xls, file_name="auditoria_sped_xml_nfe.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.subheader("CT-e com cruzamento dos XMLs")
    sped_files = st.file_uploader("SPED(s) .txt", type=["txt"], accept_multiple_files=True, key="sped_cte")
    xml_files  = st.file_uploader("XML(s) de CT-e .xml ou .txt", type=["xml","txt"], accept_multiple_files=True, key="xml_cte")
    if st.button("Processar CT-e"):
        if not sped_files: st.warning("Envie ao menos um SPED."); st.stop()
        tmp_speds, tmp_xmls = [], []
        for f in sped_files:
            t=tempfile.NamedTemporaryFile(delete=False, suffix=".txt"); t.write(f.read()); t.close(); tmp_speds.append(t.name)
        for f in xml_files:
            suf=".xml" if f.name.lower().endswith(".xml") else ".txt"
            t=tempfile.NamedTemporaryFile(delete=False, suffix=suf); t.write(f.read()); t.close(); tmp_xmls.append(t.name)
        xml_map, xml_warns = {}, []
        for p in tmp_xmls:
            d = parse_xml_cte(p)
            if d and 'Chave' in d: xml_map[d['Chave']] = d
            else: xml_warns.append(f"XML CT-e inválido ou sem chave: {os.path.basename(p)}")
        all_rows, all_warns = [], []
        for p in tmp_speds:
            r,w = processar_sped_cte(p, xml_map); all_rows += r; all_warns += w
        if not all_rows:
            st.info("Nenhum CT-e com ICMS > 0 pelos critérios."); st.stop()
        cols = ["Competência","Série CT-e","Número CT-e","Chave CT-e","Tipo Tomador XML","Nome Tomador XML","Data de Emissão SPED","Valor Total Prestação SPED","BC ICMS SPED","Valor ICMS SPED","CFOPs SPED","Alíquotas ICMS SPED","XML Encontrado","Emitente XML","CNPJ Emitente XML","Destinatário XML","CNPJ Destinatário XML","Valor Total Prestação XML","BC ICMS XML","Valor ICMS XML","Alíquota ICMS XML","CST XML","Diferença BC ICMS (SPED - XML)","Diferença ICMS (SPED - XML)","Status Auditoria"]
        df = pd.DataFrame(all_rows)
        for c in cols:
            if c not in df.columns: df[c]=None
        df=df[cols]
        for c in ["Valor Total Prestação SPED","BC ICMS SPED","Valor ICMS SPED","Valor Total Prestação XML","BC ICMS XML","Valor ICMS XML","Alíquota ICMS XML","Diferença BC ICMS (SPED - XML)","Diferença ICMS (SPED - XML)"]:
            df[c]=pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        st.dataframe(df, use_container_width=True)
        xls = montar_excel(df, xml_warns+all_warns, "CT-e")
        st.download_button("⬇️ Baixar Excel (CT-e)", data=xls, file_name="auditoria_sped_xml_cte.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
