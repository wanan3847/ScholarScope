"""Conservative explicit constraints checked against actual title/abstract text."""
import re
from datetime import datetime

DEEP = r"deep[- ]learning|deep neural|convolution|\bCNN\b|\bLSTM\b|\bGRU\b|transformer|graph neural|\bGNN\b|\bGCN\b|(?:residual|attention).*(?:network|model|u.net)|\bu[- ]?net\b|autoencoder|深度学习|深度神经|卷积|图神经|长短期记忆|自编码器"
WELL = r"well[- ]?(?:logs?|logging)|borehole[- ]logs?|petrophysical logs?|测井"
PROPERTY = r"porosity|permeability|孔隙度|渗透率"


def year_bounds(query, year_from=0, year_to=0):
    """Resolve explicit periods without treating every mentioned year as a filter."""
    lower,upper=int(year_from or 0),int(year_to or 0)
    period=re.search(r"((?:19|20)\d{2})\s*(?:[-–—~至到]|to)\s*((?:19|20)\d{2})",query,re.I)
    if period:
        if not lower:lower=min(int(period[1]),int(period[2]))
        if not upper:upper=max(int(period[1]),int(period[2]))
    if re.search(r"近(?:三|3)年|past (?:three|3) years",query,re.I):
        if not lower:lower=datetime.now().year-2
        if not upper:upper=datetime.now().year
    if not lower:
        since=re.search(r"(?:since|after|from)\s+((?:19|20)\d{2})|((?:19|20)\d{2})\s*年?\s*(?:以来|之后|起)",query,re.I)
        if since:lower=int(since[1] or since[2])
    return lower,upper


def constraints(query):
    checks = []
    if re.search(r"deep[- ]learning|深度学习", query, re.I): checks.append(("深度学习方法", DEEP))
    if re.search(WELL, query, re.I): checks.append(("测井资料", WELL))
    if re.search(WELL, query, re.I) and re.search(PROPERTY, query, re.I):
        targets=[(label,pattern) for label,pattern in (("孔隙度",r"porosity|孔隙度"),("渗透率",r"permeability|渗透率")) if re.search(pattern,query,re.I)]
        checks.append(("孔隙度或渗透率预测对象",PROPERTY) if len(targets)==2 else (targets[0][0]+"预测对象",targets[0][1]))
    if re.search(r"graph neural|\bGNN\b|图神经", query, re.I): checks.append(("图神经网络方法", r"graph neural|graph convolution|\bGNN\b|图神经|图卷积"))
    return checks


def matches(query, paper):
    title=str(paper.get("title", ""));abstract=str(paper.get("abstract", ""))
    text = title + " " + abstract
    if not all(re.search(pattern, text, re.I) for _, pattern in constraints(query)):return False
    if re.search(WELL,query,re.I) and re.search(PROPERTY,query,re.I):
        # Input/output roles matter: merely mentioning porosity or logs in the
        # background does not make a seismic inversion or log-imputation study
        # a direct well-log-to-property prediction method.
        if re.search(r"missing[- ]well[- ]log|missing well-log|synthetic well[- ]log|rock typing|elastic properties prediction|测井.*补全|岩石.*分类",title,re.I):return False
        if re.search(r"seismic.*(?:porosity|reservoir)|地震",title,re.I) and not re.search(WELL,title,re.I):return False
        if re.search(r"predict\w* .*from seismic|from (?:partial.angle stack )?seismic|seismic.to.porosity|from seismic data",abstract,re.I):return False
        if re.search(r"deep[- ]learning|深度学习",query,re.I) and not re.search(DEEP,title,re.I):
            study_sentences=re.split(r"(?<=[.!?。])\s+",abstract)
            applied=[s for s in study_sentences if re.search(r"this (?:study|research|paper)|we (?:propose|develop|use|train|apply)|proposed|used|applied|employ|integrat|were compared|本研究|本文|采用|提出",s,re.I)]
            if not any(re.search(DEEP,s,re.I) for s in applied):return False
    return True


def scope_notes(query, paper):
    """Explain visible input/target boundaries without inferring missing facts."""
    if not (re.search(WELL,query,re.I) and re.search(PROPERTY,query,re.I)):return []
    title=str(paper.get("title",""));abstract=str(paper.get("abstract",""))
    notes=[]
    if re.search(r"neutron porosity|中子孔隙",title,re.I):
        notes.append("预测目标是中子孔隙度曲线；与岩芯或有效孔隙度目标的区别需在原文核对。")
    if re.search(WELL,title,re.I) and re.search(r"well tests",title,re.I) and re.search(r"seismic",title,re.I):
        notes.append("方法联合使用测井、试井和地震资料，适用于多源资料融合。")
    if re.search(r"this dissertation",abstract,re.I):
        notes.append("来源为学位论文，引用时请核对其与后续出版论文的关系。")
    return notes
